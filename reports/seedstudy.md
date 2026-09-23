# Seeded-defect recall study

generated: 2026-09-22 15:43:12

| metric | value |
| --- | --- |
| seeds in catalog | 11 |
| evaluated | 11 |
| built successfully | 11 |
| observable in committed state | 8 |
| caught (triaged RTL_DEFECT) | 8 |
| architecturally silent | 3 |
| **recall over observable seeds** | **100%** |
| total RTL_DEFECT calls | 8 |

Recall's denominator is observable seeds only: a defect that never changes committed state under bare-metal stimulus cannot be caught by any differential test, and is reported as such rather than counted as a miss.

| seed | category | status | detector |
| --- | --- | --- | --- |
| `BYPASS_RS1_DISABLED` | BYPASS_FORWARD | CAUGHT | acknowledged_gap_1 |
| `BYPASS_RS1_MATCH_WRONG` | BYPASS_FORWARD | CAUGHT | acknowledged_gap_1 |
| `BYPASS_RS1_ZERO_GUARD` | BYPASS_FORWARD | CAUGHT | acknowledged_gap_1 |
| `BYPASS_RS2_DISABLED` | BYPASS_FORWARD | CAUGHT | acknowledged_gap_1 |
| `BYPASS_RS2_MATCH_WRONG` | BYPASS_FORWARD | CAUGHT | acknowledged_gap_1 |
| `BYPASS_RS2_ZERO_GUARD` | BYPASS_FORWARD | CAUGHT | acknowledged_gap_1 |
| `FENCEI_EARLY` | MEMORY_ORDERING | NOT_OBSERVABLE | — |
| `FORWARD_STD_VAL_STUCK` | MEMORY_ORDERING | CAUGHT | acknowledged_gap_1 |
| `FWD_IRESP_EARLY` | MEMORY_ORDERING | CAUGHT | queue_pointer_1 |
| `MOV_WRONG_OPERAND` | BYPASS_FORWARD | NOT_OBSERVABLE | — |
| `ORDER_FAIL_SUPPRESSED` | MEMORY_ORDERING | NOT_OBSERVABLE | — |
