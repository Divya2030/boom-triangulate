"""An agentic formal/dynamic verification loop for RTL, built as CHIA blocks.

Block layout mirrors the proposal:
  mutate  -> soundness check on the property set (does it catch injected bugs?)
  simrun  -> dynamic execution of the shared property set
  formal  -> proof execution via SymbiYosys
  agent   -> property synthesis and counterexample triage
  report  -> aggregation
"""

__version__ = "0.1.0"
