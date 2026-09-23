#!/usr/bin/env bash
# Build a BOOM Verilator simulator.
#
# CONFIG defaults to the plain MediumBoomV3Config rather than a *CosimConfig:
# the cosim harness links against Chipyard's own libriscv, which comes from
# build-setup step 3 -- the step we skip because we already have a toolchain.
# Get a plain simulator producing traces first; wire cosim in afterwards.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CY="$REPO/tools/src/chipyard"
CONFIG="${CONFIG:-MediumBoomV3Config}"
JOBS="${JOBS:-$(nproc)}"

# We skipped Chipyard's toolchain step, so point RISCV at the merged prefix
# built by setup/02b -- the compiler from conda plus fesvr from our own Spike,
# which is what the Verilator harness links against.
# This must be set BEFORE sourcing env.sh: the conda env's activate hook reads
# $RISCV unconditionally and dies under `set -u` if it is unset.
MERGED_RISCV="$REPO/tools/riscv-prefix"
export RISCV="$MERGED_RISCV"
[ -e "$MERGED_RISCV/include/fesvr/htif.h" ] || {
  echo "error: run setup/02b-riscv-prefix.sh first" >&2; exit 1; }
export PATH="$REPO/tools/conda/bin:$PATH"

# Third-party init scripts are not written against `set -euo pipefail`.
set +u
# shellcheck disable=SC1091
source "$REPO/tools/conda/etc/profile.d/conda.sh"
# shellcheck disable=SC1091
source "$CY/env.sh"
set -u

# Chipyard's conda activate hook rewrites $RISCV while env.sh is sourced, so
# keep our own copy under a name it will not touch and force it back afterwards.
# It is also passed on the make command line, where it overrides the
# environment unconditionally -- sims/common-sim-flags.mk uses -I$(RISCV)/include
# to find fesvr, and getting it wrong is what made the harness fail to compile.
export RISCV="$MERGED_RISCV"
export PATH="$RISCV/bin:$REPO/tools/spike/bin:$PATH"

echo ">>> building $CONFIG with -j$JOBS (Chisel elaboration then Verilator)"
cd "$CY/sims/verilator"
make -j"$JOBS" CONFIG="$CONFIG" RISCV="$MERGED_RISCV"

echo ">>> simulator binaries:"
ls -la "$CY/sims/verilator"/simulator-* 2>/dev/null || echo "none found"
