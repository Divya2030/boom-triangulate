#!/usr/bin/env bash
# Chipyard setup: the long pole, and the only thing standing between us and a
# BOOM commit trace.
#
# Two things this has to work around:
#   1. Chipyard's build-setup.sh calls `conda info --base` and sources
#      etc/profile.d/conda.sh, which micromamba does not provide. So a real
#      (sudo-free) Miniforge goes in tools/conda first.
#   2. We already have riscv64-unknown-elf-gcc and a pinned Spike, so step 3
#      (toolchain collateral) is skipped -- it would rebuild both and cost
#      hours we do not have before the compute window opens.
#
# --use-lean-conda drops FireSim and FireMarshal, which this project never uses.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$REPO/tools"
CONDA_DIR="$TOOLS/conda"
CY="$TOOLS/src/chipyard"
JOBS="${JOBS:-$(nproc)}"

# --- real conda (sudo-free) ------------------------------------------------
if [ ! -x "$CONDA_DIR/bin/conda" ]; then
  echo ">>> installing Miniforge3 to $CONDA_DIR"
  curl -Ls --max-time 900 \
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh" \
    -o /tmp/miniforge.sh
  bash /tmp/miniforge.sh -b -p "$CONDA_DIR"
fi
echo ">>> conda $("$CONDA_DIR/bin/conda" --version)"

# shellcheck disable=SC1091
source "$CONDA_DIR/etc/profile.d/conda.sh"
export CONDA_EXE="$CONDA_DIR/bin/conda"

# --- chipyard --------------------------------------------------------------
if [ ! -d "$CY" ]; then
  echo "error: $CY missing; clone chipyard first" >&2
  exit 1
fi
cd "$CY"

if [ -d "$CY/.conda-env" ]; then
  echo ">>> chipyard conda env already present, nothing to do"
  exit 0
fi

echo ">>> running chipyard build-setup (lean, no ctags, no toolchain rebuild)"
echo ">>> this is the multi-hour step; -j$JOBS"
MAKEFLAGS="-j$JOBS" ./build-setup.sh --use-lean-conda --skip-ctags --skip-toolchain
