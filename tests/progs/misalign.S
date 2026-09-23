/* Reproduction attempt for riscv-boom issue #698:
 * a misaligned load should trap, but BOOM v3 computes corrupted data from the
 * aligned address and writes it to the register file. We store a known pattern,
 * then do misaligned loads and capture the results in callee-saved regs. */
#include "common.S"

  .section .text.init
  .globl _start
_start:
  TRAP_SETUP                 /* handler records mcause into s2, steps over faults */
  la    t0, scratch
  li    t1, 0xdeadbee0
  li    t2, 0xcafe
  slli  t2, t2, 32
  or    t1, t1, t2           /* t1 = 0x0000cafe_deadbee0 */
  sd    t1, 0(t0)            /* aligned 8-byte store */
  fence
  lw    s4, 1(t0)           /* misaligned word load @ +1 */
  lh    s5, 1(t0)           /* misaligned half load  @ +1 */
  ld    s6, 1(t0)           /* misaligned dword load @ +1 */
  lw    s7, 3(t0)           /* misaligned word load  @ +3 */
  lhu   s8, 2(t0)           /* aligned control (should always agree) */
  TEST_PASS
