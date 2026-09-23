#!/usr/bin/env bash
# Build a merged $RISCV prefix.
#
# Chipyard's Verilator harness compiles against $RISCV/include/fesvr/*.h and
# links $RISCV/lib/libfesvr.a. Those normally come from build-setup step 3,
# which we skip. Our two prefixes each hold half of what is needed:
#
#   riscv-tools (conda)  bin/riscv64-unknown-elf-*     the cross compiler
#   spike (built here)   include/fesvr, lib/libfesvr   the frontend server
#
# So this overlays them into one tree of symlinks. Symlinks rather than copies
# so that rebuilding spike is picked up without re-running this.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RT="$REPO/tools/mamba/envs/chia/riscv-tools"
SPIKE="$REPO/tools/spike"
DEST="$REPO/tools/riscv-prefix"

for d in "$RT" "$SPIKE"; do
  [ -d "$d" ] || { echo "error: missing $d; run setup/00 and setup/01 first" >&2; exit 1; }
done

rm -rf "$DEST"
mkdir -p "$DEST"

# Merge the three directories the build actually reaches into, entry by entry.
# Spike is overlaid second so its fesvr headers win any name collision.
for sub in bin include lib; do
  mkdir -p "$DEST/$sub"
  for src in "$RT/$sub" "$SPIKE/$sub"; do
    [ -d "$src" ] || continue
    for entry in "$src"/*; do
      [ -e "$entry" ] || continue
      ln -sfn "$entry" "$DEST/$sub/$(basename "$entry")"
    done
  done
done

# Everything else from the compiler prefix passes through untouched.
for entry in "$RT"/*; do
  name="$(basename "$entry")"
  case "$name" in bin|include|lib) continue ;; esac
  ln -sfn "$entry" "$DEST/$name"
done

# Chipyard's conda activate hook forces $RISCV to its own
# .conda-env/riscv-tools, and Verilator bakes that path into the generated
# makefile at verilation time -- so overriding RISCV on the make command line
# afterwards is too late. Overlay fesvr into the path Chipyard actually uses.
CY_RT="$REPO/tools/src/chipyard/.conda-env/riscv-tools"
if [ -d "$CY_RT" ]; then
  for sub in include lib; do
    mkdir -p "$CY_RT/$sub"
    for entry in "$SPIKE/$sub"/*; do
      [ -e "$entry" ] || continue
      target="$CY_RT/$sub/$(basename "$entry")"
      [ -e "$target" ] && [ ! -L "$target" ] && continue   # never shadow a real file
      ln -sfn "$entry" "$target"
    done
  done
  echo ">>> overlaid fesvr into $CY_RT"
fi

echo ">>> merged prefix at $DEST"
for probe in bin/riscv64-unknown-elf-gcc bin/spike include/fesvr/htif.h \
             include/fesvr/tsi.h lib/libfesvr.a; do
  printf '  %-34s %s\n' "$probe" \
    "$([ -e "$DEST/$probe" ] && echo present || echo MISSING)"
done
if [ -d "$CY_RT" ]; then
  echo ">>> chipyard-visible fesvr:"
  for probe in include/fesvr/htif.h include/fesvr/tsi.h include/fesvr/memif.h \
               lib/libfesvr.a; do
    printf '  %-34s %s\n' "$probe" \
      "$([ -e "$CY_RT/$probe" ] && echo present || echo MISSING)"
  done
fi
