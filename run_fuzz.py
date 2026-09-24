"""Constrained-random fuzzing campaign vs. unmutated BOOM + Spike + Dromajo."""
import os, json, time
from chia_loop import fuzz, models, triangulate
OUT = "tests/progs/fuzz"; os.makedirs(OUT, exist_ok=True)
BASE = "reports/seedstudy/bin/baseline.sim"
N = int(os.environ.get("FUZZ_N", "200"))
t0 = time.time()
counts = {}; candidates = []; ran = 0
for s in range(1, N + 1):
    pid, src = fuzz.program(s, n=120)
    path = os.path.join(OUT, f"{pid}.S"); open(path, "w").write(src)
    elf = os.path.join("build", "progs", f"{pid}.elf")
    if not models.build_elf(path, elf).ok:
        continue
    try:
        sp, _ = models.spike_trace(elf)
        dr, _ = models.dromajo_trace(elf)
        bm, _ = models.boom_trace(elf, sim_path=BASE, max_cycles=200000, timeout=120)
    except Exception as e:
        counts["RUN_ERROR"] = counts.get("RUN_ERROR", 0) + 1
        continue
    v = triangulate.triangulate(bm, sp, dr, start_pc=0x80000000).verdict
    counts[v] = counts.get(v, 0) + 1
    ran += 1
    if v == "RTL_DEFECT":
        candidates.append(pid)
        print(f"*** RTL_DEFECT CANDIDATE: {pid} ***", flush=True)
    if s % 20 == 0:
        print(f"...{s}/{N} ran={ran} counts={counts} ({time.time()-t0:.0f}s)", flush=True)
rec = {"programs": N, "ran": ran, "verdict_counts": counts,
       "rtl_defect_candidates": candidates, "seconds": round(time.time() - t0)}
json.dump(rec, open("reports/fuzz.json", "w"), indent=2)
print(f"\nDONE {ran} programs in {time.time()-t0:.0f}s. counts={counts}")
print(f"organic RTL_DEFECT candidates: {candidates or 'none'}")
