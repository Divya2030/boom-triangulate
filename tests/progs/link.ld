/* Bare-metal layout matching the riscv-tests environment: entry at 0x80000000
   and a .tohost section, which is how Spike's HTIF knows the program finished.
   Without tohost the simulator never terminates and every run is a timeout. */
OUTPUT_ARCH("riscv")
ENTRY(_start)
SECTIONS
{
  . = 0x80000000;
  .text.init : { *(.text.init) }
  .text      : { *(.text) }
  .rodata    : { *(.rodata*) }
  .data      : { *(.data) }
  .bss       : { *(.bss) *(COMMON) }
  . = ALIGN(0x1000);
  .tohost    : { *(.tohost) }
}
