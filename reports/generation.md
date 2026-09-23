# Generated test programs

generated: 2026-09-17 15:04:23
provenance: `offline-heuristic`

- synthesized: 5
- **accepted: 5**
- rejected, would not assemble: 0
- rejected, did not terminate: 0
- rejected, retired too little: 0

A rejected program is the gate working, not the loop failing: a program
that does nothing produces a clean comparison and proves nothing.

| program | hypothesis | verdict | retired | reason |
| --- | --- | --- | --- | --- |
| `acknowledged_gap_1` | ACKNOWLEDGED_GAP-offline-1 | accepted | 48 | accepted |
| `bypass_forward_1` | BYPASS_FORWARD-offline-1 | accepted | 20 | accepted |
| `exception_priority_1` | EXCEPTION_PRIORITY-offline-1 | accepted | 61 | accepted |
| `memory_ordering_1` | MEMORY_ORDERING-offline-1 | accepted | 32 | accepted |
| `queue_pointer_1` | QUEUE_POINTER-offline-1 | accepted | 176 | accepted |
