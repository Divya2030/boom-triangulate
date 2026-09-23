# legacy-formal — earlier formal-verification prototype

This folder holds an **earlier, separate prototype**, kept for reference. It is
**not** the project the paper describes.

Before the BOOM divergence-hunting loop, we built a small formal-verification
loop on a simplified BOOM-style register freelist. It writes SVA properties and
assumptions, proves them with yosys/SymbiYosys (bounded model checking and
k-induction), and uses mutation testing to check the property set is not vacuous.

Contents:

- `rtl/freelist.v` — the freelist design under test
- `verif/` — the shared shadow model, properties, and simulation testbench
- `formal/` — the SymbiYosys wrappers and config
- `Makefile` — drives the prototype (`make sim`, `make mutate`, `make formal`)

The Python that drives this prototype still lives in the main package
(`chia_loop/formal.py`, `mutate.py`, `campaign.py`, `simrun.py`) and its CLI
commands (`formal`, `mutate`) point at the files here. The paper mentions this
work only as a future direction: escalating a found difference to a bounded
formal check.
