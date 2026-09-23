"""Command-line entry point for the loop blocks."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import (campaign, diff, formal, generate, hypothesize, models,
               report, seedstudy, trace, triage, triangulate)
from .agent import Agent
from .tools import have


REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _seeds(text: str) -> list[int]:
    return [int(s) for s in text.split(",") if s.strip()]


def _ops(text: str) -> list[str] | None:
    """Operator-name prefixes, e.g. 'SIG_SWAP,COND' to focus on structure."""
    parts = [s.strip() for s in text.split(",") if s.strip()]
    return parts or None


def cmd_status(args) -> int:
    rows = [("iverilog", "dynamic execution"), ("vvp", "dynamic execution"),
            ("yosys", "formal"), ("sby", "formal"),
            ("verilator", "optional, faster dynamic runs")]
    print("tool        status   used for")
    for tool, use in rows:
        print(f"{tool:<11} {'ok' if have(tool) else 'MISSING':<8} {use}")
    agent = Agent()
    print(f"\nagent       {agent.provenance}")
    if not agent.online:
        print("            set GEMINI_API_KEY to enable model-backed triage")
    return 0


def cmd_sim(args) -> int:
    result = campaign.golden_check(_seeds(args.seeds) if args.seeds else None,
                                   args.cycles)
    print(json.dumps(result, indent=2))
    if not result["compiled"]:
        print("\ngolden RTL did not compile", file=sys.stderr)
        return 2
    print("\ngolden RTL: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


def cmd_mutate(args) -> int:
    gold = campaign.golden_check(_seeds(args.seeds) if args.seeds else None,
                                 args.cycles)
    if not (gold["compiled"] and gold["passed"]):
        print("refusing to score mutants: the property set does not pass on the "
              "unmutated design", file=sys.stderr)
        print(json.dumps(gold, indent=2), file=sys.stderr)
        return 2

    record = campaign.run_campaign(
        limit=args.limit,
        seeds=_seeds(args.seeds) if args.seeds else None,
        cycles=args.cycles,
        jobs=args.jobs,
        triage=args.triage,
        ops=_ops(args.ops),
    )
    record["golden"] = gold

    jpath = report.write_json(record, "mutation.json")
    mpath = report.write_markdown(report.mutation_markdown(record), "mutation.md")

    s = record["summary"]
    print(f"scored {s['scored']} mutants: {s['killed']} killed, "
          f"{s['survived']} survived, {s['uncompilable']} uncompilable")
    print(f"kill rate: {s['kill_rate_pct']:.1f}%")
    print(f"reports: {jpath}\n         {mpath}")
    return 0


def cmd_formal(args) -> int:
    v = formal.run_task(args.task, backend=args.backend, timeout=args.timeout)
    print(json.dumps(v.to_dict(), indent=2))
    if v.status == "SKIPPED":
        return 3
    return 0 if v.proved else 1


def cmd_verify(args) -> int:
    """Everything the current machine can run, in one record."""
    seeds = _seeds(args.seeds) if args.seeds else None

    gold = campaign.golden_check(seeds, args.cycles)
    print(f"golden RTL:  {'PASS' if gold['passed'] else 'FAIL'}")

    mut = campaign.run_campaign(seeds=seeds, cycles=2000, triage=args.triage,
                                ops=_ops(args.ops))
    s = mut["summary"]
    print(f"mutation:    {s['killed']}/{s['scored']} killed "
          f"({s['kill_rate_pct']:.1f}% kill rate)")

    formal_results = {}
    for task in formal.TASKS:
        v = formal.run_task(task, backend=args.backend, timeout=args.timeout)
        formal_results[task] = v.to_dict()
        extra = ""
        if task == "prove" and v.induction_length is not None:
            extra = f" (induction length {v.induction_length})"
        if task == "cover" and v.covers:
            reach = sum(1 for c in v.covers if c["status"] == "REACHABLE")
            extra = f" ({reach}/{len(v.covers)} reachable)"
        print(f"formal {task:<6}{v.status}{extra}")

    record = {"generated": report.stamp(), "golden": gold,
              "mutation": mut, "formal": formal_results}
    jpath = report.write_json(record, "verification.json")
    mpath = report.write_markdown(report.verification_markdown(record),
                                  "verification.md")
    print(f"\nreports: {jpath}\n         {mpath}")

    ok = (gold["passed"]
          and formal_results["prove"]["status"] == "PASS"
          and formal_results["bmc"]["status"] == "PASS"
          and formal_results["cover"]["status"] == "PASS")
    return 0 if ok else 1


def cmd_cosim(args) -> int:
    """Build one test program, run it on every available model, diff them."""
    absent = models.TC.missing()
    if absent:
        print(f"missing tools: {', '.join(absent)}. Run setup/00-toolchain.sh "
              f"and setup/01-spike.sh.", file=sys.stderr)
        return 3

    import os
    name = os.path.splitext(os.path.basename(args.prog))[0]
    elf = os.path.join(models.REPO, "build", "progs", f"{name}.elf")

    build = models.build_elf(args.prog, elf)
    if not build.ok:
        print(f"build failed:\n{build.output}", file=sys.stderr)
        return 2

    ref, res = models.spike_trace(elf, truncate=not args.no_truncate)
    if not res.ok:
        print(f"oracle run failed:\n{res.output[-2000:]}", file=sys.stderr)
        return 2
    print(f"oracle (spike): {len(ref)} committed instructions")

    try:
        dut, dres = models.boom_trace(elf, truncate=not args.no_truncate,
                                      config=args.boom_config)
        print(f"implementation (boom): {len(dut)} committed instructions")
        if not dut:
            print("\nBOOM produced no parseable commit events. Raw tail:",
                  file=sys.stderr)
            print(dres.output[-1500:], file=sys.stderr)
            return 2
    except (FileNotFoundError, NotImplementedError) as exc:
        print(f"\nimplementation (boom): unavailable -- {exc}")
        print("\noracle trace (post-sync):")
        start = next((i for i, e in enumerate(ref) if e.pc == args.start_pc), 0)
        for e in ref[start:start + args.show]:
            print("   ", e.describe())
        return 3

    result = diff.compare(ref, dut, start_pc=args.start_pc)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.clean else 1


def cmd_hypothesize(args) -> int:
    """Scan the RTL for seams and propose divergence hypotheses."""
    from collections import Counter

    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None
    seams = hypothesize.scan_seams(args.root, categories=cats,
                                   max_per_marker=args.max_per_marker)
    if not seams:
        print(f"no seams found under {args.root}", file=sys.stderr)
        return 2

    agent = Agent()
    hyps = hypothesize.propose(seams, agent=agent, root=args.root,
                               per_category=args.per_category)

    record = {
        "generated": report.stamp(),
        "provenance": agent.provenance,
        "root": args.root,
        "seam_count": len(seams),
        "seams_by_category": dict(Counter(s.category for s in seams)),
        "hypotheses": [h.to_dict() for h in hyps],
        "seams": [s.to_dict() for s in seams] if args.include_seams else [],
    }
    jpath = report.write_json(record, "hypotheses.json")
    mpath = report.write_markdown(report.hypotheses_markdown(record),
                                  "hypotheses.md")

    print(f"{len(seams)} seams -> {len(hyps)} hypotheses "
          f"(provenance: {agent.provenance})")
    for cat, n in sorted(record["seams_by_category"].items(), key=lambda kv: -kv[1]):
        print(f"  {cat:<22} {n} seams")
    print(f"\nreports: {jpath}\n         {mpath}")
    if not agent.online:
        print("\nnote: offline heuristics only. Set GEMINI_API_KEY for "
              "model-backed hypotheses.")
    return 0


def cmd_generate(args) -> int:
    """Hypothesize, then synthesize and validate a test program for each."""
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None
    seams = hypothesize.scan_seams(args.root, categories=cats)
    if not seams:
        print(f"no seams found under {args.root}", file=sys.stderr)
        return 2

    agent = Agent()
    hyps = hypothesize.propose(seams, agent=agent, root=args.root,
                               per_category=args.per_category)
    results = generate.generate_suite(hyps, agent=agent,
                                      min_events=args.min_events)

    programs = []
    for prog, v in results:
        programs.append({
            "id": prog.id, "hypothesis_id": prog.hypothesis_id,
            "category": prog.category, "path": os.path.relpath(prog.path, REPO_DIR),
            "provenance": prog.provenance, "validation": v.to_dict(),
        })
        mark = "accept" if v.ok else "REJECT"
        print(f"  {mark:<7} {prog.id:<26} retired={v.events:<5} {v.reason}")

    accepted = sum(1 for _, v in results if v.ok)
    record = {
        "generated": report.stamp(),
        "provenance": agent.provenance,
        "summary": {
            "total": len(results),
            "accepted": accepted,
            "not_assembling": sum(1 for _, v in results if not v.assembles),
            "not_terminating": sum(1 for _, v in results
                                   if v.assembles and not v.terminates),
            "too_short": sum(1 for _, v in results
                             if v.terminates and not v.ok),
        },
        "programs": programs,
    }
    jpath = report.write_json(record, "generation.json")
    mpath = report.write_markdown(report.generation_markdown(record),
                                  "generation.md")
    print(f"\n{accepted}/{len(results)} accepted")
    print(f"reports: {jpath}\n         {mpath}")
    return 0 if accepted else 1


def cmd_hunt(args) -> int:
    """The whole loop: hypothesize, generate, compare, triage, feed back."""
    from collections import Counter

    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None
    agent = Agent()

    seams = hypothesize.scan_seams(args.root, categories=cats)
    hyps = hypothesize.propose(seams, agent=agent, root=args.root,
                               per_category=args.per_category)
    by_id = {h.id: h for h in hyps}
    print(f"{len(seams)} seams -> {len(hyps)} hypotheses")

    suite = generate.generate_suite(hyps, agent=agent,
                                    min_events=args.min_events)
    accepted = [(p, v) for p, v in suite if v.ok]
    print(f"{len(accepted)}/{len(suite)} programs accepted by the gate\n")

    findings, clean = [], 0
    for prog, _v in accepted:
        elf = os.path.join(REPO_DIR, "build", "progs", f"{prog.id}.elf")
        ref, _ = models.spike_trace(elf)
        dut, _ = models.boom_trace(elf, config=args.boom_config)
        res = diff.compare(ref, dut, start_pc=args.start_pc,
                           elide_trap_markers=not args.no_elide_traps)
        if res.clean:
            clean += 1
            extra = (f"  ({len(res.trap_artifacts)} trap artifacts elided)"
                     if res.trap_artifacts else "")
            print(f"  {prog.id:<26} CLEAN  matched={res.matched}{extra}")
            continue

        f = triage.triage(prog, res.divergence, elf,
                          hypothesis=by_id.get(prog.hypothesis_id), agent=agent,
                          check_reproducible=not args.no_reproduce,
                          boom_config=args.boom_config,
                          ref_total=res.ref_total, dut_total=res.dut_total)
        findings.append(f)
        print(f"  {prog.id:<26} {res.divergence.kind:<13} -> "
              f"{f.classification} ({f.confidence})")

    record = {
        "generated": report.stamp(),
        "provenance": agent.provenance,
        "summary": {
            "programs": len(accepted), "clean": clean,
            "divergences": len(findings),
            "by_classification": dict(Counter(f.classification for f in findings)),
        },
        "findings": [f.to_dict() for f in findings],
        "feedback_for_next_round": triage.feedback_context(findings),
    }
    jpath = report.write_json(record, "findings.json")
    mpath = report.write_markdown(report.findings_markdown(record),
                                  "findings.md")

    actionable = [f for f in findings if f.actionable]
    print(f"\n{clean} clean, {len(findings)} divergences, "
          f"{len(actionable)} actionable")
    print(f"reports: {jpath}\n         {mpath}")
    if not agent.online:
        print("\nnote: offline. Divergences with no mechanical rule are left "
              "INCONCLUSIVE rather than guessed.")
    return 0


def cmd_seedstudy(args) -> int:
    """Seeded-defect recall study. --dry-run validates without building."""
    from .seeds import SEEDS, BOOM_REL
    ids = [i.strip() for i in args.seeds.split(",") if i.strip()] or None

    if args.dry_run:
        print("validating seed catalog (no builds)...")
        allok = True
        for sd in SEEDS:
            if ids and sd.id not in ids:
                continue
            path = os.path.join(REPO_DIR, BOOM_REL, sd.file)
            try:
                n = open(path).read().count(sd.find)
            except OSError:
                n = -1
            ok = (n == 1)
            allok &= ok
            print(f"  {'OK ' if ok else '!! '}{sd.id:<24} anchor {n}x  ({sd.file})")
        # confirm apply/revert round-trips cleanly on a copy in memory
        for sd in SEEDS:
            if ids and sd.id not in ids:
                continue
            path = os.path.join(REPO_DIR, BOOM_REL, sd.file)
            txt = open(path).read()
            patched = txt.replace(sd.find, sd.replace, 1)
            if patched == txt or patched.replace(sd.replace, sd.find, 1) != txt:
                print(f"  !! {sd.id}: patch/revert not clean")
                allok = False
        print("\nsuite programs available:",
              len(seedstudy._suite_elfs()))
        print("baseline binary present:", os.path.exists(seedstudy.BASELINE_SIM),
              "| working sim present:", models.boom_simulator() is not None)
        print("\nCATALOG VALID -- ready to run on funded compute" if allok
              else "\nFIX CATALOG before running")
        return 0 if allok else 2

    print("running seeded-defect study (each seed rebuilds BOOM, ~40-50 min)...")
    result = seedstudy.run_study(seed_ids=ids, jobs=args.jobs, agent=Agent())
    jpath = report.write_json(result, "seedstudy.json")
    mpath = report.write_markdown(report.seedstudy_markdown(result),
                                  "seedstudy.md")
    r = result["recall_over_observable"]
    print(f"\nbuilt {result['built']}/{result['evaluated']}  "
          f"observable {result['observable']}  caught {result['caught']}")
    print("recall over observable: "
          + ("n/a" if r is None else f"{100*r:.0f}%"))
    print(f"reports: {jpath}\n         {mpath}")
    return 0


def cmd_triangulate(args) -> int:
    """Run a program on BOOM + two oracles (Spike, Dromajo) and vote."""
    import os
    if not models.have_dromajo():
        print("Dromajo not installed (micromamba install -c ucb-bar dromajo)",
              file=sys.stderr)
        return 3
    name = os.path.splitext(os.path.basename(args.prog))[0]
    elf = os.path.join(models.REPO, "build", "progs", f"{name}.elf")
    if not os.path.exists(elf):
        build = models.build_elf(args.prog, elf)
        if not build.ok:
            print(build.output[-1500:], file=sys.stderr)
            return 2

    spike, _ = models.spike_trace(elf)
    dromajo, _ = models.dromajo_trace(elf)
    boom, _ = models.boom_trace(elf, sim_path=args.boom_sim or None)
    print(f"spike={len(spike)}  dromajo={len(dromajo)}  boom={len(boom)} events")

    t = triangulate.triangulate(boom, spike, dromajo, start_pc=args.start_pc)
    print(json.dumps(t.to_dict(), indent=2))
    return 0 if t.verdict == "CLEAN" else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="chia_loop",
                                description="Agentic verification loop for RTL")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="show tool and agent availability")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("sim", help="run the property set on the golden RTL")
    s.add_argument("--seeds", default="")
    s.add_argument("--cycles", type=int, default=3000)
    s.set_defaults(func=cmd_sim)

    s = sub.add_parser("mutate", help="score the property set by mutation testing")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--seeds", default="")
    s.add_argument("--cycles", type=int, default=2000)
    s.add_argument("--jobs", type=int, default=None)
    s.add_argument("--triage", action="store_true",
                   help="ask the agent to explain each surviving mutant")
    s.add_argument("--ops", default="",
                   help="restrict to operator-name prefixes, e.g. SIG_SWAP,COND")
    s.set_defaults(func=cmd_mutate)

    s = sub.add_parser("formal", help="run a formal task")
    s.add_argument("--task", default="prove", choices=formal.TASKS)
    s.add_argument("--backend", default="yosys", choices=("yosys", "sby"))
    s.add_argument("--timeout", type=int, default=1800)
    s.set_defaults(func=cmd_formal)

    s = sub.add_parser("verify", help="sim + mutation + all formal tasks")
    s.add_argument("--seeds", default="")
    s.add_argument("--cycles", type=int, default=3000)
    s.add_argument("--backend", default="yosys", choices=("yosys", "sby"))
    s.add_argument("--timeout", type=int, default=1800)
    s.add_argument("--triage", action="store_true")
    s.add_argument("--ops", default="")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("cosim", help="build a program and compare models on it")
    s.add_argument("--prog", default="tests/progs/smoke.S")
    s.add_argument("--start-pc", type=lambda x: int(x, 0), default=0x80000000,
                   help="sync PC; the models disagree before the program starts")
    s.add_argument("--show", type=int, default=20)
    s.add_argument("--no-truncate", action="store_true",
                   help="keep the post-exit halt loop in the trace")
    s.add_argument("--boom-config", default=models.DEFAULT_BOOM_CONFIG)
    s.set_defaults(func=cmd_cosim)

    s = sub.add_parser("hypothesize",
                       help="scan RTL for seams and propose divergences")
    s.add_argument("--root", default=hypothesize.BOOM_V3)
    s.add_argument("--categories", default="",
                   help="comma-separated subset, e.g. MEMORY_ORDERING,QUEUE_POINTER")
    s.add_argument("--per-category", type=int, default=3)
    s.add_argument("--max-per-marker", type=int, default=None,
                   help="cap seams per marker to keep prompts small")
    s.add_argument("--include-seams", action="store_true",
                   help="write every seam into the JSON record")
    s.set_defaults(func=cmd_hypothesize)

    s = sub.add_parser("generate",
                       help="synthesize and validate test programs")
    s.add_argument("--root", default=hypothesize.BOOM_V3)
    s.add_argument("--categories", default="")
    s.add_argument("--per-category", type=int, default=1)
    s.add_argument("--min-events", type=int, default=8,
                   help="minimum instructions retired after sync to be accepted")
    s.set_defaults(func=cmd_generate)

    s = sub.add_parser("hunt", help="run the whole loop end to end")
    s.add_argument("--root", default=hypothesize.BOOM_V3)
    s.add_argument("--categories", default="")
    s.add_argument("--per-category", type=int, default=1)
    s.add_argument("--min-events", type=int, default=8)
    s.add_argument("--start-pc", type=lambda x: int(x, 0), default=0x80000000)
    s.add_argument("--boom-config", default=models.DEFAULT_BOOM_CONFIG)
    s.add_argument("--no-elide-traps", action="store_true",
                   help="report trap-log artifacts as divergences")
    s.add_argument("--no-reproduce", action="store_true",
                   help="skip the reproducibility re-run (faster, weaker)")
    s.set_defaults(func=cmd_hunt)

    s = sub.add_parser("seedstudy",
                       help="seeded-defect recall study (needs BOOM rebuilds)")
    s.add_argument("--dry-run", action="store_true",
                   help="validate the catalog and setup without building")
    s.add_argument("--seeds", default="",
                   help="comma-separated seed ids to restrict to")
    s.add_argument("--jobs", type=int, default=None)
    s.set_defaults(func=cmd_seedstudy)

    s = sub.add_parser("triangulate",
                       help="BOOM vs two oracles (Spike + Dromajo), mechanical vote")
    s.add_argument("--prog", default="tests/progs/smoke.S")
    s.add_argument("--start-pc", type=lambda x: int(x, 0), default=0x80000000)
    s.add_argument("--boom-sim", default="",
                   help="path to a specific BOOM simulator binary")
    s.set_defaults(func=cmd_triangulate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
