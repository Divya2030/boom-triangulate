"""Constrained-random floating-point program fuzzer.

The RV64IM fuzzer (``fuzz.py``) never exercises the FPU. Floating point is where
implementations disagree most: NaN-boxing of single-precision values, min/max
with a NaN operand, saturating float->int conversion, signed zero, sNaN
canonicalisation, and the five rounding modes. This generator targets exactly
those seams.

Robustness of the vote rests on one design choice: FP results are never compared
in the float register file (BOOM, Spike, and Dromajo format float writes in
their commit logs differently). Instead every observable is forced into the
*integer* file -- ``fmv.x.d``/``fmv.x.w`` of each result, ``csrr`` of the
accumulated ``fflags`` -- and comparison/classification write integer registers
directly. All three models report the integer file identically, so a divergence
is a real FP disagreement, not a log-formatting artifact. ``fflags`` is cleared
before the run so the comparison starts from a defined exception state.
"""
from __future__ import annotations

import random

BASE = 31                       # x31 = scratch base, never written
# Integer landing registers for results/flags. Avoid x5,x6 (t0,t1 used by
# TEST_PASS) and x18..x22 (s2..s6 used by the trap handler).
INT_POOL = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 23, 24, 25, 26, 27, 28, 29, 30]
FREGS = list(range(0, 24))      # f0..f23 as the working float pool

# Interesting IEEE-754 double bit patterns, laid out in scratch memory.
DOUBLES = [
    0x0000000000000000,  # +0.0
    0x8000000000000000,  # -0.0
    0x3ff0000000000000,  # 1.0
    0xbff0000000000000,  # -1.0
    0x4008000000000000,  # 3.0
    0x7ff0000000000000,  # +inf
    0xfff0000000000000,  # -inf
    0x7ff8000000000000,  # qNaN
    0x7ff0000000000001,  # sNaN
    0x0000000000000001,  # smallest positive subnormal
    0x000fffffffffffff,  # largest subnormal
    0x0010000000000000,  # smallest positive normal
    0x7fefffffffffffff,  # largest finite (near overflow)
    0x400921fb54442d18,  # pi
    0x43e0000000000000,  # 2^63 (out of range for signed 64-bit int)
    0xc3e0000000000000,  # -2^63
]

RM = ["rne", "rtz", "rdn", "rup", "rmm", "dyn"]     # rounding modes

FP_RR = ["fadd.d", "fsub.d", "fmul.d", "fdiv.d",
         "fadd.s", "fsub.s", "fmul.s", "fdiv.s"]
FP_MINMAX = ["fmin.d", "fmax.d", "fmin.s", "fmax.s"]        # NaN handling
FP_SGNJ = ["fsgnj.d", "fsgnjn.d", "fsgnjx.d",
           "fsgnj.s", "fsgnjn.s", "fsgnjx.s"]
FP_FMA = ["fmadd.d", "fmsub.d", "fnmadd.d", "fnmsub.d"]
FP_UN = ["fsqrt.d", "fsqrt.s"]
FP_CVT_NARROW = ["fcvt.s.d"]        # narrowing: takes a rounding mode
FP_CVT_WIDEN = ["fcvt.d.s"]         # widening: exact, no rounding mode
FP_CVT_FI = ["fcvt.w.d", "fcvt.wu.d", "fcvt.l.d", "fcvt.lu.d",
             "fcvt.w.s", "fcvt.l.s"]                        # saturation seam
FP_CMP = ["feq.d", "flt.d", "fle.d", "feq.s", "flt.s", "fle.s"]
FP_CLASS = ["fclass.d", "fclass.s"]


def _f(rng):
    return rng.choice(FREGS)


def _i(rng):
    return rng.choice(INT_POOL)


def _rm(rng):
    return rng.choice(RM)


def gen_body(rng: random.Random, n: int) -> list[str]:
    out = []
    for _ in range(n):
        k = rng.random()
        if k < 0.28:                                   # arithmetic w/ rounding
            op = rng.choice(FP_RR)
            out.append(f"  {op} f{_f(rng)}, f{_f(rng)}, f{_f(rng)}, {_rm(rng)}")
        elif k < 0.42:                                 # min/max (NaN handling)
            out.append(f"  {rng.choice(FP_MINMAX)} f{_f(rng)}, f{_f(rng)}, f{_f(rng)}")
        elif k < 0.52:                                 # fused multiply-add
            op = rng.choice(FP_FMA)
            out.append(f"  {op} f{_f(rng)}, f{_f(rng)}, f{_f(rng)}, f{_f(rng)}, {_rm(rng)}")
        elif k < 0.60:                                 # sign injection
            out.append(f"  {rng.choice(FP_SGNJ)} f{_f(rng)}, f{_f(rng)}, f{_f(rng)}")
        elif k < 0.68:                                 # sqrt
            out.append(f"  {rng.choice(FP_UN)} f{_f(rng)}, f{_f(rng)}, {_rm(rng)}")
        elif k < 0.76:                                 # format conversion (boxing)
            if rng.random() < 0.5:
                out.append(f"  {rng.choice(FP_CVT_NARROW)} f{_f(rng)}, f{_f(rng)}, {_rm(rng)}")
            else:
                out.append(f"  {rng.choice(FP_CVT_WIDEN)} f{_f(rng)}, f{_f(rng)}")
        elif k < 0.86:                                 # float->int (saturation)
            op = rng.choice(FP_CVT_FI)
            out.append(f"  {op} x{_i(rng)}, f{_f(rng)}, {_rm(rng)}")
        elif k < 0.94:                                 # compare -> int reg
            out.append(f"  {rng.choice(FP_CMP)} x{_i(rng)}, f{_f(rng)}, f{_f(rng)}")
        else:                                          # classify -> int reg
            out.append(f"  {rng.choice(FP_CLASS)} x{_i(rng)}, f{_f(rng)}")
    return out


def render(rng: random.Random, n: int) -> str:
    lines = ['#include "common.S"', "",
             "  .section .text.init", "  .globl _start", "_start:",
             "  TRAP_SETUP",
             "  li t0, (3 << 13)", "  csrs mstatus, t0",   # FPU on
             # Clear the WHOLE fcsr: both the accumulated flags and the rounding
             # mode. frm in particular must be defined, or a `dyn`-rounded op
             # uses the machine's reset rounding mode -- which differs between
             # BOOM and the oracles and shows up as a phantom one-ULP divergence.
             "  csrw fcsr, x0",
             f"  la x{BASE}, scratch"]
    # Lay the interesting patterns into memory, then load them into the pool.
    for i, bits in enumerate(DOUBLES):
        lines.append(f"  li t1, 0x{bits:016x}")
        lines.append(f"  sd t1, {i*8}(x{BASE})")
    for i, fr in enumerate(FREGS):
        src = (i % len(DOUBLES)) * 8
        lines.append(f"  fld f{fr}, {src}(x{BASE})")
    lines += gen_body(rng, n)
    # Snapshot: move every float result into the integer file, then fflags.
    for i, fr in enumerate(FREGS):
        lines.append(f"  fmv.x.d x{INT_POOL[i % len(INT_POOL)]}, f{fr}")
    lines.append(f"  csrr x{INT_POOL[0]}, fflags")
    lines.append("  TEST_PASS")
    return "\n".join(lines) + "\n"


def program(seed: int, n: int = 100) -> tuple[str, str]:
    rng = random.Random(seed)
    return f"fpfuzz_{seed:06d}", render(rng, n)
