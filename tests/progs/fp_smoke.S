#include "common.S"

/* Minimal floating-point probe. Enables the FPU, does a few double-precision
 * ops, then MOVES every result into an integer register (fmv.x.d) and reads
 * fflags into an integer register. That way the observable state lands in the
 * integer file, which every model's commit log reports identically -- so a
 * divergence is a real FP disagreement, not a commit-log formatting quirk. */

  .section .text.init
  .globl _start
_start:
  TRAP_SETUP
  li    t0, (3 << 13)        /* mstatus.FS = Dirty: turn the FPU on */
  csrs  mstatus, t0
  csrw  fflags, x0           /* start from a known-zero exception state */
  la    x31, scratch

  li    t1, 0x400921fb54442d18   /* pi (double) */
  sd    t1, 0(x31)
  li    t1, 0x3ff0000000000000   /* 1.0 */
  sd    t1, 8(x31)
  li    t1, 0x4008000000000000   /* 3.0 */
  sd    t1, 16(x31)

  fld   f1, 0(x31)
  fld   f2, 8(x31)
  fld   f3, 16(x31)

  fadd.d f4, f1, f2
  fmul.d f5, f1, f3
  fdiv.d f6, f2, f3
  fsqrt.d f7, f3
  fmadd.d f8, f1, f2, f3

  fmv.x.d x5, f4
  fmv.x.d x6, f5
  fmv.x.d x7, f6
  fmv.x.d x8, f7
  fmv.x.d x9, f8
  csrr    x10, fflags

  TEST_PASS
