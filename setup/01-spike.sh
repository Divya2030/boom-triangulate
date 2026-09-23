#!/usr/bin/env bash
# Build Spike (riscv-isa-sim) from source.
#
# Not on either conda channel, so it is built here. The upstream repo has only
# two release tags and the newest (v1.1.0, 2022) does not compile against GCC 13
# -- fesvr/device.cc references members its own header does not declare. So we
# track master, but pin the exact commit into setup/spike.lock on first build
# and re-fetch that commit on every later run. The oracle's version is part of
# every result this loop produces; "whatever master was that day" is not a
# reproducible claim.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$REPO/tools"
PREFIX="$TOOLS/spike"
SRC="$TOOLS/src/riscv-isa-sim"
LOCK="$REPO/setup/spike.lock"
URL="https://github.com/riscv-software-src/riscv-isa-sim.git"
JOBS="${JOBS:-$(nproc)}"

export PATH="$TOOLS/mamba/envs/chia/bin:$PATH"   # dtc lives here

if [ -x "$PREFIX/bin/spike" ]; then
  echo ">>> spike already built"
  "$PREFIX/bin/spike" --help 2>&1 | head -1
  exit 0
fi

mkdir -p "$TOOLS/src"
if [ ! -d "$SRC/.git" ]; then
  if [ -f "$LOCK" ]; then
    SHA="$(cat "$LOCK")"
    echo ">>> fetching pinned spike commit $SHA"
    mkdir -p "$SRC"; cd "$SRC"
    git init -q .
    git remote add origin "$URL" 2>/dev/null || true
    git fetch -q --depth 1 origin "$SHA"
    git checkout -q FETCH_HEAD
  else
    echo ">>> cloning riscv-isa-sim master (no usable release tag)"
    git clone -q --depth 1 "$URL" "$SRC"
    cd "$SRC"
    git rev-parse HEAD > "$LOCK"
    echo ">>> pinned to $(cat "$LOCK")"
  fi
fi

cd "$SRC"
echo ">>> building spike @ $(git rev-parse --short HEAD) with -j$JOBS"
mkdir -p build && cd build
../configure --prefix="$PREFIX" >/dev/null
make -j"$JOBS"
make install

echo ">>> installed: $("$PREFIX/bin/spike" --help 2>&1 | head -1)"
