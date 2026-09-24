"""Organic bug hunt: many diverse model-written programs vs. UNMUTATED BOOM."""
import os, json, time
from chia_loop import hypothesize, generate, models, triangulate
from chia_loop.agent import Agent
from chia_loop.generate import validate

OUT = "tests/progs/organic"
BASE = "reports/seedstudy/bin/baseline.sim"   # unmutated baseline BOOM
os.makedirs(OUT, exist_ok=True)
agent = Agent()
print(f"agent: {agent.provenance}", flush=True)

seams = hypothesize.scan_seams()
hyps = hypothesize.propose(seams, agent=agent, per_category=4)   # ~20 diverse ideas
print(f"{len(hyps)} hypotheses across {len(set(h.category for h in hyps))} categories", flush=True)

results = []
counts = {}
candidates = []
for i, h in enumerate(hyps):
    prog = generate.synthesize(h, agent=agent, index=i + 1)
    prog.write(OUT)
    v = validate(prog)
    if not v.ok:
        results.append({"id": prog.id, "verdict": "REJECTED_GATE", "reason": v.reason})
        print(f"  {prog.id:26} rejected: {v.reason[:40]}", flush=True)
        continue
    elf = os.path.join("build", "progs", f"{prog.id}.elf")
    try:
        spike, _ = models.spike_trace(elf)
        dromajo, _ = models.dromajo_trace(elf)
        boom, _ = models.boom_trace(elf, sim_path=BASE, max_cycles=200000, timeout=300)
    except Exception as e:
        results.append({"id": prog.id, "verdict": "RUN_ERROR", "reason": str(e)[:80]})
        continue
    t = triangulate.triangulate(boom, spike, dromajo, start_pc=0x80000000)
    counts[t.verdict] = counts.get(t.verdict, 0) + 1
    results.append({"id": prog.id, "category": h.category, "title": h.title,
                    "verdict": t.verdict, "provenance": prog.provenance})
    tag = "  <-- CANDIDATE BUG" if t.verdict == "RTL_DEFECT" else ""
    if t.verdict == "RTL_DEFECT":
        candidates.append(prog.id)
    print(f"  {prog.id:26} {t.verdict}{tag}", flush=True)

rec = {"generated": time.strftime("%Y-%m-%d %H:%M"), "provenance": agent.provenance,
       "programs": len(results), "verdict_counts": counts,
       "rtl_defect_candidates": candidates, "results": results}
json.dump(rec, open("reports/organic.json", "w"), indent=2)
print(f"\nDONE. verdicts: {counts}")
print(f"organic RTL_DEFECT candidates (unmutated BOOM): {candidates or 'none'}")
