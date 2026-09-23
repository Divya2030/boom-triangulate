# Mutation campaign

- generated: 2026-09-15 12:57:04
- mutants scored: 20 (excluded, would not compile: 0)
- killed: 18
- survived: 2
- **kill rate: 90.0%**

## Survivors -- property-set holes

Each survivor is a defect no property detected. These are the loop's
next work items: the agent is asked to synthesize a property that
would kill them.

| mutant | line | source |
| --- | --- | --- |
| `SIG_SWAP_L34C47_free_mask_o` | 34 | `wire [NUM_PREGS-1:0] sel_oh  = free_mask & (~free_mask + 1'b1);` |
| `SIG_SWAP_L35C35_sel_oh` | 35 | `wire                 any_free = \|free_mask;` |

## Kills by property

| property | mutants killed |
| --- | --- |
| `P1_mutex` | 11 |
| `P6_snap_mutex` | 10 |
| `P2_complete` | 9 |
| `P7_snap_complete` | 6 |
| `P3_no_dbl` | 4 |
| `P5_alloc_iff` | 4 |
| `P4_rollback` | 3 |
