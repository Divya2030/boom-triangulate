"""Constrained-random RISC-V program fuzzer.

A step toward the fuzzing approach of DIFUZZRTL / SimFuzz: instead of a few
model-written tests, emit many random-but-legal RV64IM programs and run each
through the triangulation vote against BOOM and the two reference models.

Design constraints that keep every program legal, terminating, and trap-free so
a divergence means a real disagreement, not a crash we caused:
  - x31 is a fixed base pointing at ``scratch``; it is never a destination.
  - a working pool of registers (x5..x30) is used for operands and results.
  - loads/stores address x31 + an aligned offset inside the 256-byte buffer.
  - only RV64I + M ops; div/rem are defined for all inputs in RISC-V, so no traps.
  - no branches or jumps: fixed-length straight-line code, then a clean exit.
Dependencies arise naturally between instructions, which is what stresses the
out-of-order machinery (rename, bypass, load/store queues).
"""
from __future__ import annotations

import random

POOL = list(range(5, 31))          # x5..x30 usable as operands/destinations
BASE = 31                          # x31 = scratch base, never written

RR = ["add", "sub", "and", "or", "xor", "sll", "srl", "sra", "slt", "sltu",
      "mul", "mulh", "mulhu", "mulhsu", "div", "divu", "rem", "remu",
      "addw", "subw", "sllw", "srlw", "sraw", "mulw", "divw", "remw"]
RI = ["addi", "andi", "ori", "xori", "slti", "sltiu", "addiw"]
SH = ["slli", "srli", "srai", "slliw", "srliw", "sraiw"]
LOADS = [("lb", 1), ("lbu", 1), ("lh", 2), ("lhu", 2), ("lw", 4), ("lwu", 4), ("ld", 8)]
STORES = [("sb", 1), ("sh", 2), ("sw", 4), ("sd", 8)]


def _rd(rng):
    return rng.choice(POOL)


def _rs(rng):
    return rng.choice(POOL + [0])          # x0 allowed as a source


def gen_body(rng: random.Random, n: int) -> list[str]:
    out = []
    for _ in range(n):
        k = rng.random()
        if k < 0.42:                                  # register-register
            op = rng.choice(RR)
            out.append(f"  {op} x{_rd(rng)}, x{_rs(rng)}, x{_rs(rng)}")
        elif k < 0.62:                                # register-immediate
            op = rng.choice(RI)
            out.append(f"  {op} x{_rd(rng)}, x{_rs(rng)}, {rng.randint(-2048, 2047)}")
        elif k < 0.74:                                # shift-immediate
            op = rng.choice(SH)
            amt = rng.randint(0, 31 if op.endswith('w') else 63)
            out.append(f"  {op} x{_rd(rng)}, x{_rs(rng)}, {amt}")
        elif k < 0.82:                                # lui / auipc (upper imm)
            op = rng.choice(["lui", "auipc"])
            out.append(f"  {op} x{_rd(rng)}, {rng.randint(0, 1048575)}")
        elif k < 0.91:                                # load (aligned, in-buffer)
            op, w = rng.choice(LOADS)
            off = rng.randrange(0, 256 - 8, w)        # aligned to width, in range
            out.append(f"  {op} x{_rd(rng)}, {off}(x{BASE})")
        else:                                         # store (aligned, in-buffer)
            op, w = rng.choice(STORES)
            off = rng.randrange(0, 256 - 8, w)
            out.append(f"  {op} x{_rs(rng)}, {off}(x{BASE})")
    return out


def render(rng: random.Random, n: int) -> str:
    lines = ['#include "common.S"', "", "  .section .text.init",
             "  .globl _start", "_start:", "  TRAP_SETUP",
             f"  la x{BASE}, scratch"]
    lines.append(f"  li x{POOL[0]}, 0x0123456789abcdef")
    lines.append(f"  sd x{POOL[0]}, 0(x{BASE})")
    lines.append(f"  li x{POOL[1]}, 0xfedcba9876543210")
    lines.append(f"  sd x{POOL[1]}, 8(x{BASE})")
    for r in POOL:
        lines.append(f"  li x{r}, {rng.randint(-2048, 2047)}")
    lines += gen_body(rng, n)
    lines.append("  TEST_PASS")
    return "\n".join(lines) + "\n"


def program(seed: int, n: int = 120) -> tuple[str, str]:
    rng = random.Random(seed)
    return f"fuzz_{seed:06d}", render(rng, n)
