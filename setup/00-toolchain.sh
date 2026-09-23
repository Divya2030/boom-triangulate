#!/usr/bin/env bash
# Toolchain bootstrap for the Spike<->BOOM divergence loop.
#
# Deliberately sudo-free and self-contained: everything lands under tools/ in
# the repo so this replays unchanged on the fresh GCP account we get on Sep 21.
# Re-running is safe; each step is skipped if its output already exists.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$REPO/tools"
export MAMBA_ROOT_PREFIX="$TOOLS/mamba"
MM="$TOOLS/micromamba/micromamba"
ENV_NAME="chia"

mkdir -p "$TOOLS"

# --- micromamba ------------------------------------------------------------
if [ ! -x "$MM" ]; then
  echo ">>> fetching micromamba"
  curl -Ls --max-time 300 https://micro.mamba.pm/api/micromamba/linux-64/latest \
    -o /tmp/micromamba.tar.bz2
  mkdir -p "$TOOLS/micromamba"
  tar -xjf /tmp/micromamba.tar.bz2 -C "$TOOLS/micromamba" \
      --strip-components=1 bin/micromamba
fi
echo ">>> micromamba $("$MM" --version)"

# --- environment -----------------------------------------------------------
# ucb-bar::riscv-tools is Chipyard's bundle: it carries both the bare-metal
# riscv64-unknown-elf GCC and spike, which is the pair the loop needs.
if [ ! -d "$MAMBA_ROOT_PREFIX/envs/$ENV_NAME" ]; then
  echo ">>> creating env '$ENV_NAME' (this is the long step)"
  "$MM" create -y -n "$ENV_NAME" \
    -c ucb-bar -c conda-forge \
    "ucb-bar::riscv-tools" \
    verilator dtc make cmake bison flex git python=3.12
else
  echo ">>> env '$ENV_NAME' already present"
fi

# --- report ----------------------------------------------------------------
BIN="$MAMBA_ROOT_PREFIX/envs/$ENV_NAME/bin"
echo
echo ">>> installed:"
for t in spike riscv64-unknown-elf-gcc riscv64-unknown-elf-objdump verilator dtc; do
  if [ -x "$BIN/$t" ]; then
    printf '  %-32s %s\n' "$t" "$("$BIN/$t" --version 2>&1 | head -1)"
  else
    printf '  %-32s MISSING\n' "$t"
  fi
done
echo
echo "activate with:  source setup/activate.sh"
