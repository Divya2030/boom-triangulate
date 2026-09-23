/* Shared harness for generated test programs.
 *
 * Every program ends by writing tohost, because without it the simulator never
 * terminates and the run is a timeout rather than a result.
 *
 * TRAP_SETUP installs a handler that records mcause and skips the faulting
 * instruction. This is not optional for exception tests: without a handler the
 * two models diverge on trap behaviour itself and the comparison reports a
 * control-flow split that says nothing about the seam under test. Recording
 * mcause into a register also puts the trap cause into the committed trace,
 * which is exactly the state we want to compare.
 */

  .macro TEST_PASS
  la    t0, tohost
  li    t1, 1
  sd    t1, 0(t0)
1:j     1b
  .endm

/* Install the trap handler. Clobbers t0. */
  .macro TRAP_SETUP
  la    t0, __trap_handler
  csrw  mtvec, t0
  .endm

/* Handler: capture the cause, then step over the faulting instruction.
 * The instruction length is decoded from its low two bits -- a compressed
 * instruction advances mepc by 2, a full one by 4. Getting this wrong re-executes
 * the faulting instruction forever. */
  .section .text, "ax", @progbits
  .align 4
  .globl __trap_handler
__trap_handler:
  csrr  s2, mcause
  csrr  s3, mepc
  lhu   s4, 0(s3)
  andi  s5, s4, 3
  li    s6, 3
  beq   s5, s6, 1f
  addi  s3, s3, 2
  j     2f
1:
  addi  s3, s3, 4
2:
  csrw  mepc, s3
  mret

  .section .tohost, "aw", @progbits
  .align 6
  .globl tohost
tohost:   .dword 0
  .align 6
  .globl fromhost
fromhost: .dword 0

  .section .bss
  .align 8
  .globl scratch
scratch:  .zero 256
