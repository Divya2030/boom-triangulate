/* Demonstrates reference-model-bug detection: correct models agree on MUL,
   the seeded-buggy Spike is off by one. */
#include "common.S"
  .section .text.init
  .globl _start
_start:
  li    s2, 6
  li    s3, 7
  mul   s4, s2, s3          /* correct = 42 */
  li    s5, 12345
  li    s6, 100
  mul   s7, s5, s6          /* correct = 1234500 */
  TEST_PASS
