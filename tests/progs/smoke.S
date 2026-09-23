/* Smallest program that produces a non-trivial commit trace: a handful of
   register writes with data dependencies, then halt. Used to validate that the
   trace parsers agree with real tool output before anything harder runs. */
#include "exit.S"

  .section .text.init
  .globl _start
_start:
  li    t0, 1
  li    t1, 2
  add   t2, t0, t1
  slli  t3, t2, 4
  xor   t4, t3, t0
  addi  t5, t4, -7
  TEST_PASS
