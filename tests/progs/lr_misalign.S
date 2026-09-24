/* Reproduction attempt for riscv-boom issue #504:
 * a misaligned LR should not set a reservation, but BOOM reportedly does.
 * We do a misaligned LR, then an aligned SC, and capture the SC success flag. */
#include "common.S"
  .section .text.init
  .globl _start
_start:
  TRAP_SETUP
  la    x31, scratch
  li    t0, 0x1122334455667788
  sd    t0, 0(x31)
  addi  t1, x31, 1            /* misaligned address */
  lr.d  s2, (t1)              /* misaligned LR -> should NOT set reservation */
  li    t2, 0x00000000deadbeef
  sc.d  s3, t2, (x31)         /* s3 = 0 if SC succeeds, 1 if it fails */
  lr.d  s4, (x31)             /* aligned control LR */
  li    t3, 0x99
  sc.d  s5, t3, (x31)         /* s5 = control SC result */
  ld    s6, 0(x31)            /* final memory value */
  TEST_PASS
