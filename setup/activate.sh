# Source this to put the whole toolchain on PATH.
_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MAMBA_ROOT_PREFIX="$_REPO/tools/mamba"
export CHIA_ENV="$MAMBA_ROOT_PREFIX/envs/chia"
# riscv-tools installs under its own prefix rather than the env bin/.
export RISCV="$CHIA_ENV/riscv-tools"
export PATH="$_REPO/tools/spike/bin:$RISCV/bin:$CHIA_ENV/bin:$PATH"
