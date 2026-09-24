"""Floating-point constrained-random campaign vs. BOOM + Spike + Dromajo.

Same triangulation vote as the integer campaign, but the programs exercise the
FPU edge cases (NaN-boxing, min/max with NaN, saturating float->int, signed
zero, all rounding modes). For every RTL_DEFECT candidate it records the exact
divergent instruction and the oracle-vs-BOOM values, so a hit can be judged
immediately rather than re-run.
"""
import os, json, time
from chia_loop import fpfuzz, models, triangulate, diff

OUT = "tests/progs/fpfuzz"; os.makedirs(OUT, exist_ok=True)
os.makedirs("reports", exist_ok=True)
N = int(os.environ.get("FPFUZZ_N", "80"))
BODY = int(os.environ.get("FPFUZZ_BODY", "100"))
t0 = time.time()
counts = {}; candidates = []; ran = 0

for s in range(1, N + 1):
    pid, src = fpfuzz.program(s, n=BODY)
    path = os.path.join(OUT, f"{pid}.S"); open(path, "w").write(src)
    elf = os.path.join("build", "progs", f"{pid}.elf")
    if not models.build_elf(path, elf).ok:
        counts["BUILD_FAIL"] = counts.get("BUILD_FAIL", 0) + 1
        continue
    try:
        sp, _ = models.spike_trace(elf)
        dr, _ = models.dromajo_trace(elf)
        bm, _ = models.boom_trace(elf, max_cycles=300000, timeout=180)
    except Exception as e:
        counts["RUN_ERROR"] = counts.get("RUN_ERROR", 0) + 1
        continue
    t = triangulate.triangulate(bm, sp, dr, start_pc=0x80000000)
    counts[t.verdict] = counts.get(t.verdict, 0) + 1
    ran += 1
    if t.verdict == "RTL_DEFECT":
        r = diff.compare(sp, bm, start_pc=0x80000000)
        dv = r.divergence
        info = {"pid": pid, "kind": dv.kind if dv else None,
                "detail": dv.detail if dv else None}
        candidates.append(info)
        print(f"*** RTL_DEFECT CANDIDATE {pid}: {info['detail']} ***", flush=True)
    if s % 10 == 0:
        print(f"...{s}/{N} ran={ran} counts={counts} ({time.time()-t0:.0f}s)", flush=True)

rec = {"programs": N, "body": BODY, "ran": ran, "verdict_counts": counts,
       "rtl_defect_candidates": candidates, "seconds": round(time.time() - t0)}
json.dump(rec, open("reports/fpfuzz.json", "w"), indent=2)
print(f"\nDONE {ran} programs in {time.time()-t0:.0f}s. counts={counts}")
print(f"organic RTL_DEFECT candidates: {[c['pid'] for c in candidates] or 'none'}")
