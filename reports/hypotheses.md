# Divergence hypotheses

generated: 2026-09-21 14:08:38
provenance: `gemini:gemini-pro-latest`
seams scanned: 423 across 5 categories

| category | seams |
| --- | --- |
| BYPASS_FORWARD | 151 |
| MEMORY_ORDERING | 118 |
| ACKNOWLEDGED_GAP | 92 |
| QUEUE_POINTER | 45 |
| EXCEPTION_PRIORITY | 17 |

## ACKNOWLEDGED_GAP-1 — RV32 Floating-Point Data Truncation

**category** ACKNOWLEDGED_GAP · **confidence** high

BOOM explicitly disables FPU support for RV32 configurations via a require statement. If bypassed, the datapath likely assumes 64-bit integer registers for 64-bit FP operations (like fld/fsd or fmv.x.d), which is false in RV32. This would lead to incorrect data movement between memory/GPRs and FPRs.

- **preconditions** BOOM configured with xLen=32 and usingFPU=true (bypassing the require statement).
- **stimulus** Execute an `fld` instruction to load a 64-bit floating-point value from memory into an FPR, followed by an `fsd` to store it back to a different memory location.
- **expected divergence** BOOM will truncate the 64-bit value to 32 bits during the load or store, resulting in incorrect memory contents compared to Spike.
- **evidence** `common/parameters.scala:198`

## ACKNOWLEDGED_GAP-2 — Commit Map Table Corruption on Exception

**category** ACKNOWLEDGED_GAP · **confidence** high

The commit map table feature is marked as broken and disabled. If enabled, it likely fails to maintain the correct architectural-to-physical register mapping. When an exception occurs and the pipeline flushes, the frontend will restore this corrupted map table, leading to incorrect register reads.

- **preconditions** BOOM configured with enableCommitMapTable=true (bypassing the require statement).
- **stimulus** Execute a sequence of instructions that rename a register (e.g., `addi x5, x0, 42`), immediately followed by an instruction that triggers a synchronous exception (e.g., `ecall`). In the trap handler, read the value of `x5`.
- **expected divergence** BOOM will read a stale or uninitialized value for `x5` in the trap handler due to the corrupted commit map table, whereas Spike will read the correct committed value (42).
- **evidence** `common/parameters.scala:264`

## ACKNOWLEDGED_GAP-3 — Structural Hazard in Shared Mem/IFPU Execution Unit

**category** ACKNOWLEDGED_GAP · **confidence** high

The RTL forbids an execution unit from having both Memory and IFPU (Integer-to-FP) capabilities. If bypassed, the unit likely lacks the necessary scheduling logic or writeback port arbitration to handle both instruction types simultaneously, leading to a structural hazard.

- **preconditions** BOOM configured with an execution unit where hasMem=true and hasIfpu=true (bypassing the require statement).
- **stimulus** Issue a memory load (`ld`) and an integer-to-float conversion (`fcvt.d.l`) back-to-back such that they are scheduled to the same execution unit and their latencies cause them to attempt writeback in the same cycle.
- **expected divergence** BOOM will drop one of the writebacks, leaving the destination register with a stale value, whereas Spike will correctly update both destination registers.
- **evidence** `exu/execution-units/execution-unit.scala:239`

## ACKNOWLEDGED_GAP-4 — Predicated FP Instruction FFlags Leakage

**category** ACKNOWLEDGED_GAP · **confidence** medium

The ExeUnitResp bundle includes a `predicated` bit and an `fflags` valid interface with a 'TODO: Do this better' comment. If an FP instruction is predicated off (e.g., via Short Forward Branch optimization) but still executes in the FPU, it might incorrectly write its exception flags to the ROB, which then commits them to the FCSR.

- **preconditions** BOOM configured with FPU and SFB (Short Forward Branch) optimization enabled.
- **stimulus** Execute an FP instruction that generates an inexact or overflow flag (e.g., dividing by a small number), but predicate it off using a conditional branch that is optimized into a predicated execution (SFB). Read the `fcsr` afterwards.
- **expected divergence** BOOM will incorrectly update the `fcsr` with the flags from the predicated-off instruction, whereas Spike will leave the `fcsr` unmodified.
- **evidence** `exu/execution-units/execution-unit.scala:42`

## ACKNOWLEDGED_GAP-5 — CFLUSH.D.L1 Fault on Scratchpad-Only Configuration

**category** ACKNOWLEDGED_GAP · **confidence** medium

The RTL requires a data cache for the CFLUSH.D.L1 instruction and forbids it on scratchpad-only configurations. If bypassed, the custom flush instruction will be sent to the scratchpad memory controller, which likely does not support cache management operations.

- **preconditions** BOOM configured with a scratchpad (no D-Cache) and haveCFlush=true (bypassing the require statement).
- **stimulus** Execute the `CFLUSH.D.L1` instruction targeting a valid address within the scratchpad memory region.
- **expected divergence** BOOM will either hang (causing a timeout/PC divergence) or raise an illegal access fault, whereas Spike (if configured to support the custom instruction) will treat it as a valid operation.
- **evidence** `lsu/dcache.scala:405`

## BYPASS_FORWARD-1 — Cross-register-file RAW bypass corruption for integer sources in float renamer

**category** BYPASS_FORWARD · **confidence** high

The `BypassAllocations` function checks if `r.ldst === uop.lrs1` without verifying that `uop.lrs1_rtype` matches the rename stage's register type. If an instruction like `fcvt.s.w` (which reads an integer register and writes a float register) is processed in the float rename stage, its `lrs1` (an integer register index) might accidentally match the `ldst` of an older float instruction in the same rename group. This would cause the float rename stage to bypass a float physical register into `prs1`, corrupting the integer source physical register mapping.

- **preconditions** Superscalar dispatch where a float instruction and a subsequent float-destination conversion instruction are in the same rename group.
- **stimulus** fadd.s f1, f2, f3
fcvt.s.w f4, x1  // x1 has index 1, matching f1. Float renamer bypasses f1's pdst to x1's prs1.
- **expected divergence** `fcvt.s.w` reads the result of `fadd.s` instead of `x1`, leading to an incorrect float value in `f4`.
- **evidence** `exu/rename/rename-stage.scala:177`, `exu/rename/rename-stage.scala:194`

## BYPASS_FORWARD-2 — Cross-register-file RAW bypass corruption for float sources in integer renamer

**category** BYPASS_FORWARD · **confidence** high

Similar to the first hypothesis, if a floating-point store (`fsw`) is processed in the integer rename stage for address calculation, its `lrs2` field represents a floating-point register. If an older integer instruction in the same rename group writes to an integer register with the same index, `BypassAllocations` will incorrectly match `r.ldst === uop.lrs2` and bypass the integer physical register to `prs2`, causing the store to write integer data instead of float data.

- **preconditions** An integer instruction and a subsequent floating-point store are in the same rename group.
- **stimulus** addi x2, x0, 42   // writes x2 (index 2)
fsw f2, 0(x1)     // reads f2 (index 2) as rs2. Integer renamer bypasses x2's pdst to f2's prs2.
- **expected divergence** Memory at `0(x1)` contains the value of `x2` (42) instead of the value of `f2`.
- **evidence** `exu/rename/rename-stage.scala:178`, `exu/rename/rename-stage.scala:195`

## BYPASS_FORWARD-3 — Intra-group bypass to x0 ignores hardwired zero semantics

**category** BYPASS_FORWARD · **confidence** medium

If the decode stage does not clear `alloc_reqs` for instructions writing to `x0`, the rename stage will allocate a physical register for `x0`. If a younger instruction in the same rename group reads `x0`, `BypassAllocations` will bypass this newly allocated physical register instead of mapping it to the zero register. This causes the younger instruction to read the non-zero result of the older instruction.

- **preconditions** An instruction writing `x0` and a younger instruction reading `x0` in the same rename group, assuming `alloc_reqs` is not forced false for `x0`.
- **stimulus** addi x0, x1, 1
add x2, x0, x3
- **expected divergence** `x2` gets `x1 + 1 + x3` instead of `x3`.
- **evidence** `exu/rename/rename-stage.scala:177`, `exu/rename/rename-stage.scala:194`

## BYPASS_FORWARD-4 — Cross-register-file WAW bypass corrupts free list via stale_pdst

**category** BYPASS_FORWARD · **confidence** medium

If `alloc_reqs` is not strictly filtered by `rtype` before being passed to `BypassAllocations`, an instruction that allocates an integer register (e.g., `fcvt.w.s x1, f1`) might appear to allocate a register in the float rename stage. A younger float instruction writing to `f1` would see `ldst === uop.ldst` (both are 1) and incorrectly bypass the garbage `pdst` from `fcvt.w.s` as its `stale_pdst`. When the younger instruction commits, it will free a garbage physical register, corrupting the float free list.

- **preconditions** An instruction writing an integer register and reading a float register, followed by a float instruction writing a float register with the same index, in the same rename group.
- **stimulus** fcvt.w.s x1, f1
fadd.s f1, f2, f3 // fadd.s takes fcvt's garbage pdst as its stale_pdst
- **expected divergence** Free list corruption leads to a deadlock or incorrect data in subsequent float instructions due to physical register aliasing.
- **evidence** `exu/rename/rename-stage.scala:180`, `exu/rename/rename-stage.scala:197`

## EXCEPTION_PRIORITY-offline-1 — Simultaneous exceptions may be prioritised differently

**category** EXCEPTION_PRIORITY · **confidence** low

[model call failed: The read operation timed out] When one instruction raises more than one exception condition in the same cycle, the oracle applies the architectural priority order. The implementation selects a cause through its own mux tree, and any disagreement appears as a different mcause/mtval and a different handler entry.

- **preconditions** An instruction that is simultaneously misaligned and page-faulting, or an illegal instruction inside a misaligned fetch.
- **stimulus** Trap on an instruction that satisfies two exception conditions at once; read mcause and mepc in the handler.
- **expected divergence** Different mcause value written, hence different register state after the handler returns.
- **evidence** `ifu/frontend.scala:535`, `ifu/frontend.scala:580`, `ifu/frontend.scala:581`, `ifu/fetch-buffer.scala:118`, `ifu/fetch-buffer.scala:119`, `exu/core.scala:554`, `lsu/lsu.scala:1251`, `exu/execution-units/execution-unit.scala:410`

## MEMORY_ORDERING-offline-1 — Store-to-load forwarding may return the wrong bytes

**category** MEMORY_ORDERING · **confidence** low

[model call failed: The read operation timed out] A load that partially overlaps an older in-flight store must be resolved from the store queue. Partial overlap, differing access sizes, and replay after a nack are all places where the implementation can return bytes the oracle would not.

- **preconditions** A load overlapping an older uncommitted store by less than the full access width.
- **stimulus** Store a doubleword, then load overlapping bytes and halfwords at offsets inside it, before the store can commit.
- **expected divergence** The load commits a different value than the oracle's.
- **evidence** `lsu/lsu.scala:183`, `lsu/lsu.scala:312`, `lsu/lsu.scala:314`, `lsu/lsu.scala:347`, `lsu/lsu.scala:472`, `lsu/lsu.scala:506`, `lsu/lsu.scala:1109`, `lsu/lsu.scala:1123`

## QUEUE_POINTER-offline-1 — Queue full/empty aliasing at wrap-around

**category** QUEUE_POINTER · **confidence** low

[model call failed: The read operation timed out] Head and tail pointers that alias when a queue is exactly full are a classic source of dropped or duplicated entries. The oracle has no queue at all, so any such loss shows up as a missing or repeated committed instruction.

- **preconditions** A queue driven to exactly its capacity, then one more entry pushed in the same cycle an entry is popped.
- **stimulus** A long dependent chain sized to fill the ROB or load/store queue exactly, followed by a burst that forces simultaneous push and pop.
- **expected divergence** A committed instruction missing from BOOM's trace, or its register write applied twice.
- **evidence** `util/util.scala:470`, `util/util.scala:473`, `util/util.scala:474`, `util/util.scala:501`, `util/util.scala:526`, `util/util.scala:530`, `ifu/fetch-buffer.scala:64`, `ifu/fetch-buffer.scala:82`
