# Verification status

generated: 2026-09-15 12:59:06

| check | result |
| --- | --- |
| golden simulation | PASS (5 seeds, 15000 cycles) |
| mutation kill rate | 94.4% (153/162) |
| bounded model check | PASS (depth 30) |
| unbounded proof | PASS, induction length 2 |
| cover reachability | PASS (all 4 cover points reachable; assumptions do not over-constrain the environment) |

## Cover points

An unreachable cover means the assumptions have over-constrained the environment.

| point | status | description |
| --- | --- | --- |
| `COVER_0` | REACHABLE | free list fully exhausted |
| `COVER_1` | REACHABLE | allocation of the last free preg |
| `COVER_2` | REACHABLE | rollback that actually undoes allocated state |
| `COVER_3` | REACHABLE | allocation reaches the top preg index |

## Surviving mutants

| mutant | line | source |
| --- | --- | --- |
| `SIG_SWAP_L34C33_free_mask_o` | 34 | `wire [NUM_PREGS-1:0] sel_oh  = free_mask & (~free_mask + 1'b1);` |
| `SIG_SWAP_L34C47_free_mask_o` | 34 | `wire [NUM_PREGS-1:0] sel_oh  = free_mask & (~free_mask + 1'b1);` |
| `SIG_SWAP_L35C35_free_mask_o` | 35 | `wire                 any_free = \|free_mask;` |
| `SIG_SWAP_L35C35_sel_oh` | 35 | `wire                 any_free = \|free_mask;` |
| `CONST_0_TO_1_L43C18_1b1` | 43 | `enc = {PREG_W{1'b0}};` |
| `SIG_SWAP_L45C10_alloc_clr` | 45 | `if (sel_oh[i]) enc = i[PREG_W-1:0];` |
| `SIG_SWAP_L53C6_alloc_req` | 53 | `alloc_valid ? sel_oh : {NUM_PREGS{1'b0}};` |
| `SIG_SWAP_L55C36_free_mask_o` | 55 | `wire [NUM_PREGS-1:0] next_mask = (free_mask & ~alloc_clr) \| dealloc_oh;` |
| `SIG_SWAP_L62C36_snapshot_o` | 62 | `if (br_rollback) free_mask <= snapshot;` |
