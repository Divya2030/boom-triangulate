"""Aggregation block: turn per-block results into a JSON record and a summary."""
from __future__ import annotations

import json
import os
import time
from typing import Any

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(REPO, "reports")


def write_json(record: dict[str, Any], name: str) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, name)
    with open(path, "w") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
    return path


def mutation_markdown(record: dict[str, Any]) -> str:
    s = record["summary"]
    lines = [
        "# Mutation campaign",
        "",
        f"- generated: {record['generated']}",
        f"- mutants scored: {s['scored']} "
        f"(excluded, would not compile: {s['uncompilable']})",
        f"- killed: {s['killed']}",
        f"- survived: {s['survived']}",
        f"- **kill rate: {s['kill_rate_pct']:.1f}%**",
        "",
    ]

    survivors = [m for m in record["mutants"] if m["verdict"] == "SURVIVED"]
    if survivors:
        lines += [
            "## Survivors -- property-set holes",
            "",
            "Each survivor is a defect no property detected. These are the loop's",
            "next work items: the agent is asked to synthesize a property that",
            "would kill them.",
            "",
            "| mutant | line | source |",
            "| --- | --- | --- |",
        ]
        for m in survivors:
            src = m["source"].replace("|", "\\|")
            lines.append(f"| `{m['id']}` | {m['line']} | `{src}` |")
        lines.append("")

    killers: dict[str, int] = {}
    for m in record["mutants"]:
        for prop, n in m.get("failing_props", {}).items():
            killers[prop] = killers.get(prop, 0) + 1
    if killers:
        lines += ["## Kills by property", "", "| property | mutants killed |",
                  "| --- | --- |"]
        for prop, n in sorted(killers.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{prop}` | {n} |")
        lines.append("")

    return "\n".join(lines)


def write_markdown(text: str, name: str) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, name)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def verification_markdown(record: dict[str, Any]) -> str:
    """One-page status across the dynamic and formal paths."""
    gold = record["golden"]
    mut = record["mutation"]["summary"]
    fm = record["formal"]

    lines = [
        "# Verification status",
        "",
        f"generated: {record['generated']}",
        "",
        "| check | result |",
        "| --- | --- |",
        f"| golden simulation | {'PASS' if gold['passed'] else 'FAIL'} "
        f"({len(gold['seeds'])} seeds, {gold['cycles_total']} cycles) |",
        f"| mutation kill rate | {mut['kill_rate_pct']:.1f}% "
        f"({mut['killed']}/{mut['scored']}) |",
        f"| bounded model check | {fm['bmc']['status']} ({fm['bmc'].get('note','')}) |",
        f"| unbounded proof | {fm['prove']['status']}"
        + (f", induction length {fm['prove']['induction_length']}"
           if fm["prove"].get("induction_length") is not None else "")
        + " |",
        f"| cover reachability | {fm['cover']['status']} "
        f"({fm['cover'].get('note','')}) |",
        "",
    ]

    if fm["cover"].get("covers"):
        lines += ["## Cover points", "",
                  "An unreachable cover means the assumptions have "
                  "over-constrained the environment.", "",
                  "| point | status | description |", "| --- | --- | --- |"]
        for c in fm["cover"]["covers"]:
            lines.append(f"| `{c['id']}` | {c['status']} | {c['description']} |")
        lines.append("")

    ce = fm["prove"].get("counterexample_initial_state")
    if ce:
        lines += ["## Induction counterexample (initial state)", "",
                  "The state the solver had to invent to break the property. "
                  "Its shape is usually the shape of the missing invariant.", "",
                  "| signal | value |", "| --- | --- |"]
        for k, v in sorted(ce.items()):
            lines.append(f"| `{k}` | {v} |")
        lines.append("")

    survivors = [m for m in record["mutation"]["mutants"]
                 if m["verdict"] == "SURVIVED"]
    if survivors:
        lines += ["## Surviving mutants", "", "| mutant | line | source |",
                  "| --- | --- | --- |"]
        for m in survivors:
            lines.append(f"| `{m['id']}` | {m['line']} | "
                         f"`{m['source'].replace('|', chr(92) + '|')}` |")
        lines.append("")

    return "\n".join(lines)


def hypotheses_markdown(record: dict[str, Any]) -> str:
    """Hypotheses with their RTL citations, so each claim can be traced back."""
    lines = [
        "# Divergence hypotheses",
        "",
        f"generated: {record['generated']}",
        f"provenance: `{record['provenance']}`",
        f"seams scanned: {record['seam_count']} across "
        f"{len(record['seams_by_category'])} categories",
        "",
        "| category | seams |",
        "| --- | --- |",
    ]
    for cat, n in sorted(record["seams_by_category"].items(),
                         key=lambda kv: -kv[1]):
        lines.append(f"| {cat} | {n} |")
    lines.append("")

    for h in record["hypotheses"]:
        lines += [
            f"## {h['id']} — {h['title']}",
            "",
            f"**category** {h['category']} · **confidence** {h['confidence']}",
            "",
            h["rationale"],
            "",
            f"- **preconditions** {h['preconditions']}",
            f"- **stimulus** {h['stimulus_sketch']}",
            f"- **expected divergence** {h['expected_divergence']}",
            "- **evidence** " + ", ".join(f"`{e}`" for e in h["evidence"]),
            "",
        ]
    return "\n".join(lines)


def generation_markdown(record: dict[str, Any]) -> str:
    """Generated programs and, importantly, what the validation gate rejected."""
    s = record["summary"]
    lines = [
        "# Generated test programs",
        "",
        f"generated: {record['generated']}",
        f"provenance: `{record['provenance']}`",
        "",
        f"- synthesized: {s['total']}",
        f"- **accepted: {s['accepted']}**",
        f"- rejected, would not assemble: {s['not_assembling']}",
        f"- rejected, did not terminate: {s['not_terminating']}",
        f"- rejected, retired too little: {s['too_short']}",
        "",
        "A rejected program is the gate working, not the loop failing: a program",
        "that does nothing produces a clean comparison and proves nothing.",
        "",
        "| program | hypothesis | verdict | retired | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in record["programs"]:
        v = "accepted" if p["validation"]["ok"] else "rejected"
        lines.append(f"| `{p['id']}` | {p['hypothesis_id']} | {v} | "
                     f"{p['validation']['events']} | {p['validation']['reason']} |")
    lines.append("")
    return "\n".join(lines)


def findings_markdown(record: dict[str, Any]) -> str:
    """Triaged findings, most actionable first."""
    s = record["summary"]
    lines = [
        "# Triaged findings",
        "",
        f"generated: {record['generated']}",
        f"provenance: `{record['provenance']}`",
        "",
        f"- programs run: {s['programs']}",
        f"- clean comparisons: {s['clean']}",
        f"- divergences triaged: {s['divergences']}",
        "",
        "| classification | count |",
        "| --- | --- |",
    ]
    for cls, n in sorted(s["by_classification"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {cls} | {n} |")
    lines += ["", "Only RTL_DEFECT and MODEL_DEFECT are actionable. Artifacts and",
              "legal differences are recorded but not fed back into the next",
              "hypothesis round, since doing so would steer it toward more noise.",
              ""]

    order = {c: n for n, c in enumerate(
        ["RTL_DEFECT", "MODEL_DEFECT", "INCONCLUSIVE",
         "LEGAL_NONDETERMINISM", "HARNESS_ARTIFACT"])}
    for f in sorted(record["findings"], key=lambda x: order.get(
            x["classification"], 99)):
        lines += [
            f"## {f['id']} — {f['classification']}",
            "",
            f"**confidence** {f['confidence']} · **reproducible** "
            f"{f['reproducible']} · **provenance** `{f['provenance']}`",
            "",
            f"{f['divergence'].get('kind', '')}: {f['divergence'].get('detail', '')}",
            "",
            f["rationale"],
            "",
        ]
        if f.get("recommended_action"):
            lines += [f"**action** {f['recommended_action']}", ""]
        dis = f["evidence"].get("implementation_disassembly") or \
            f["evidence"].get("oracle_disassembly")
        if dis:
            lines += ["```", *dis, "```", ""]
    return "\n".join(lines)


def seedstudy_markdown(score: dict) -> str:
    """Recall / precision table for the seeded-defect control set."""
    r = score.get("recall_over_observable")
    rp = "n/a" if r is None else f"{100*r:.0f}%"
    lines = [
        "# Seeded-defect recall study",
        "",
        f"generated: {stamp()}",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| seeds in catalog | {score['seeds_total']} |",
        f"| evaluated | {score['evaluated']} |",
        f"| built successfully | {score['built']} |",
        f"| observable in committed state | {score['observable']} |",
        f"| caught (triaged RTL_DEFECT) | {score['caught']} |",
        f"| architecturally silent | {score['not_observable']} |",
        f"| **recall over observable seeds** | **{rp}** |",
        f"| total RTL_DEFECT calls | {score['rtl_defect_calls']} |",
        "",
        "Recall's denominator is observable seeds only: a defect that never "
        "changes committed state under bare-metal stimulus cannot be caught by "
        "any differential test, and is reported as such rather than counted as "
        "a miss.",
        "",
        "| seed | category | status | detector |",
        "| --- | --- | --- | --- |",
    ]
    for sid, res in sorted(score["results"].items()):
        lines.append(f"| `{sid}` | {res['category']} | {res['status']} | "
                     f"{res.get('detector_program','') or '—'} |")
    lines.append("")
    return "\n".join(lines)
