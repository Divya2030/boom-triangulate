#!/usr/bin/env bash
# Reproduce the reference-model-bug demonstration (paper Finding 5).
#
# Seeds an off-by-one bug into Spike's MUL, rebuilds a *separate* buggy Spike
# (the correct installed Spike is left untouched), then runs the triangulation
# vote on a multiply test:
#   BOOM + correct Spike + Dromajo  -> CLEAN
#   BOOM + BUGGY  Spike + Dromajo   -> MODEL_DEFECT, outlier = spike
# i.e. the vote pinpoints which reference model is wrong -- something a
# single-golden-model flow cannot do.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPIKE_SRC="$REPO/tools/src/riscv-isa-sim"
MUL="$SPIKE_SRC/riscv/insns/mul.h"
export PATH="$REPO/tools/mamba/envs/chia/bin:$PATH"

cp "$MUL" "$MUL.orig"
trap 'cp "$MUL.orig" "$MUL"; rm -f "$MUL.orig"' EXIT   # always restore correct source
cat > "$MUL" <<'MULEOF'
require_either_extension('M', EXT_ZMMUL);
WRITE_RD(sext_xlen(RS1 * RS2 + 1));   // seeded reference-model bug: MUL off by one
MULEOF

echo ">>> rebuilding buggy Spike (incremental)"
( cd "$SPIKE_SRC/build" && make spike >/dev/null 2>&1 && cp spike "$REPO/tools/spike-buggy" )
echo ">>> buggy Spike at tools/spike-buggy; correct Spike untouched"

python3 - <<'PY'
import os
from chia_loop import models, triangulate
from chia_loop.trace import parse_commit_log, truncate_at_halt
from chia_loop.tools import run
elf="build/progs/mul_demo.elf"
models.build_elf("tests/progs/mul_demo.S", elf)
env=models.TC.env()
def spk(b): 
    r=run([b,"--isa=rv64gc","--log-commits",os.path.abspath(elf)],env=env,timeout=120)
    return truncate_at_halt(parse_commit_log(r.output))
good=spk("tools/spike/bin/spike"); buggy=spk("tools/spike-buggy")
dr,_=models.dromajo_trace(elf)
bm,_=models.boom_trace(elf, sim_path="reports/seedstudy/bin/baseline.sim", max_cycles=200000, timeout=200)
print("correct Spike:", triangulate.triangulate(bm,good,dr,start_pc=0x80000000).verdict)
t=triangulate.triangulate(bm,buggy,dr,start_pc=0x80000000)
print("buggy   Spike:", t.verdict, "-> outlier:", t.outlier)
PY
