/* Shared epilogue: signal success to HTIF and halt. */
  .macro TEST_PASS
  la    t0, tohost
  li    t1, 1
  sd    t1, 0(t0)
1:j     1b
  .endm

  .section .tohost, "aw", @progbits
  .align 6
  .globl tohost
tohost:   .dword 0
  .align 6
  .globl fromhost
fromhost: .dword 0
