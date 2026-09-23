"""Divergence detection between two committed-instruction streams.

The comparison is lockstep from a sync point and stops at the first divergence.
That is deliberate: once control flow splits, every later entry is noise, and a
loop that reports thousands of "divergences" from one root cause tells the agent
nothing it can act on.

Classification is the part that decides whether this is usable. A raw mismatch
is not a bug report -- it is one of three things, and the loop has to say which:

  RTL defect              the implementation is wrong
  model defect            the oracle is wrong
  legal nondeterminism    both are right and the difference is permitted

This module does not attempt the full call; it produces the evidence and a
mechanical hint for the cases that can be decided by construction (unstable
counter CSRs, trace truncation). The judgement call goes to the agent, which is
the point of the triage block.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .trace import CommitEvent

# Counter CSRs whose value legitimately differs between a functional oracle and
# a cycle-accurate implementation. A divergence whose only difference is a write
# sourced from one of these is not a bug in either model.
UNSTABLE_CSRS = {
    0xC00: "cycle",   0xC01: "time",    0xC02: "instret",
    0xC80: "cycleh",  0xC81: "timeh",   0xC82: "instreth",
    0xB00: "mcycle",  0xB02: "minstret",
    0xB80: "mcycleh", 0xB82: "minstreth",
}

SYSTEM_OPCODE = 0x73


def csr_of(insn: int) -> int | None:
    """CSR address if this is a CSR access, else None."""
    if (insn & 0x7F) != SYSTEM_OPCODE:
        return None
    funct3 = (insn >> 12) & 0x7
    if funct3 == 0:
        return None                      # ECALL/EBREAK/xRET, not a CSR op
    return (insn >> 20) & 0xFFF


@dataclass
class Divergence:
    index: int
    kind: str          # CONTROL_FLOW | INSN_BITS | REG_WRITE | TRACE_END
    hint: str          # LIKELY_LEGAL_NONDETERMINISM | NEEDS_TRIAGE | ...
    ref: CommitEvent | None
    dut: CommitEvent | None
    detail: str = ""
    context: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "hint": self.hint,
            "detail": self.detail,
            "reference": self.ref.describe() if self.ref else None,
            "dut": self.dut.describe() if self.dut else None,
            "context": [{"reference": r, "dut": d} for r, d in self.context],
        }


# ECALL and EBREAK. A valid instruction that traps is retired by BOOM's commit
# log but never appears in Spike's, which reports the handler entry instead.
# Verified on a trap sequence where both models then entered the same handler
# with the same mcause. An illegal instruction retires in neither, which is why
# only the valid-but-trapping ones need this.
# ECALL (0x73), EBREAK (0x100073) and its compressed form C.EBREAK (0x9002).
# The compressed form is easy to miss: the trace shows it as 0x00009002, and
# omitting it made the elision work for ecall and then fail two instructions
# later on ebreak.
TRAP_INSNS = {0x00000073, 0x00100073, 0x00009002}


@dataclass
class DiffResult:
    matched: int = 0
    divergence: Divergence | None = None
    ref_total: int = 0
    dut_total: int = 0
    sync_index_ref: int = 0
    sync_index_dut: int = 0
    trap_artifacts: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def clean(self) -> bool:
        return self.divergence is None

    def to_dict(self) -> dict:
        return {
            "clean": self.clean,
            "matched": self.matched,
            "reference_events": self.ref_total,
            "dut_events": self.dut_total,
            "sync": {"reference": self.sync_index_ref, "dut": self.sync_index_dut},
            "trap_log_artifacts_elided": self.trap_artifacts,
            "note": self.note,
            "divergence": self.divergence.to_dict() if self.divergence else None,
        }


def find_sync(ref: list[CommitEvent], dut: list[CommitEvent],
              start_pc: int | None) -> tuple[int, int]:
    """Locate the first index in each stream where comparison should begin.

    The two models do not agree on what happens before the test program starts
    -- different reset vectors, different bootrom. Comparing from index 0 would
    report that disagreement as a bug on every single run.
    """
    if start_pc is None:
        return 0, 0
    i = next((n for n, e in enumerate(ref) if e.pc == start_pc), None)
    j = next((n for n, e in enumerate(dut) if e.pc == start_pc), None)
    if i is None or j is None:
        return -1, -1
    return i, j


def _hint_for(ref: CommitEvent | None, dut: CommitEvent | None) -> str:
    """Mechanical classification for the cases decidable without judgement."""
    for ev in (ref, dut):
        if ev is None:
            continue
        csr = csr_of(ev.insn)
        if csr in UNSTABLE_CSRS:
            return "LIKELY_LEGAL_NONDETERMINISM"
    return "NEEDS_TRIAGE"


def compare(ref: list[CommitEvent], dut: list[CommitEvent],
            start_pc: int | None = None, context: int = 8,
            elide_trap_markers: bool = True) -> DiffResult:
    """Lockstep-compare two commit streams, stopping at the first divergence.

    `ref` is the oracle (Spike), `dut` the implementation (BOOM).

    With `elide_trap_markers`, a DUT-only retirement of ECALL/EBREAK that writes
    nothing and is immediately followed by the event the oracle is showing is
    skipped rather than reported. Without it every exception test reports a
    false CONTROL_FLOW divergence. Each elision is recorded in
    `trap_artifacts` so the adjustment is visible in the report rather than
    silently applied -- a differ that quietly resynchronises is a differ that
    can hide a real bug.
    """
    res = DiffResult(ref_total=len(ref), dut_total=len(dut))

    i, j = find_sync(ref, dut, start_pc)
    if i < 0:
        res.note = (f"sync PC 0x{start_pc:x} not found in both traces; "
                    "nothing compared")
        res.divergence = Divergence(0, "TRACE_END", "NEEDS_TRIAGE", None, None,
                                    detail=res.note)
        return res
    res.sync_index_ref, res.sync_index_dut = i, j

    history: list[tuple[str, str]] = []
    n = 0
    while i < len(ref) and j < len(dut):
        a, b = ref[i], dut[j]
        if a.arch_key() == b.arch_key():
            history.append((a.describe(), b.describe()))
            history = history[-context:]
            res.matched = n = n + 1
            i, j = i + 1, j + 1
            continue

        if (elide_trap_markers and not b.writes and b.insn in TRAP_INSNS
                and j + 1 < len(dut) and dut[j + 1].arch_key() == a.arch_key()):
            res.trap_artifacts.append(
                f"0x{b.pc:016x} insn=0x{b.insn:08x} (trapping instruction "
                "retired by the implementation, absent from the oracle)")
            j += 1
            continue

        if a.pc != b.pc:
            kind, detail = "CONTROL_FLOW", (
                f"oracle retired pc=0x{a.pc:016x}, implementation retired "
                f"pc=0x{b.pc:016x}")
        elif a.insn != b.insn:
            kind, detail = "INSN_BITS", (
                f"same pc=0x{a.pc:016x} but oracle fetched 0x{a.insn:08x} and "
                f"implementation fetched 0x{b.insn:08x}")
        else:
            kind, detail = "REG_WRITE", (
                f"same instruction at pc=0x{a.pc:016x}; oracle wrote "
                f"[{' '.join(str(w) for w in a.writes) or '-'}], implementation "
                f"wrote [{' '.join(str(w) for w in b.writes) or '-'}]")

        res.divergence = Divergence(n, kind, _hint_for(a, b), a, b,
                                    detail=detail, context=list(history))
        return res

    # One stream ran out. Truncation is usually a harness problem (timeout, sim
    # killed) rather than a design bug, so it is reported separately.
    if n == 0:
        res.note = "streams synced but no events compared"
    if i < len(ref) or j < len(dut):
        longer = "oracle" if i < len(ref) else "implementation"
        res.divergence = Divergence(
            n, "TRACE_END", "NEEDS_TRIAGE",
            ref[i] if i < len(ref) else None,
            dut[j] if j < len(dut) else None,
            detail=(f"{longer} has {abs((len(ref) - i) - (len(dut) - j))} more "
                    "committed instructions; likely a truncated run rather than "
                    "a design defect"),
            context=list(history))
    return res
