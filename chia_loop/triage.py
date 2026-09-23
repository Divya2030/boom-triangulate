"""Triage block: classify a divergence.

A raw mismatch is not a bug report. It is one of five things, and saying which
is the whole job:

  RTL_DEFECT            the implementation is wrong
  MODEL_DEFECT          the oracle is wrong
  LEGAL_NONDETERMINISM  both are right; the difference is architecturally allowed
  HARNESS_ARTIFACT      neither model is wrong; the comparison is
  INCONCLUSIVE          the evidence does not support a call

Order of work matters. Cases decidable by construction are decided first, with
no model call and no cost: an unstable counter CSR is legal by definition, a
truncated trace is a harness problem, and a divergence that does not reproduce
is not evidence of anything. Only what survives that filter is worth a model
call, and the model is given real evidence -- disassembly at both program
counters, the surrounding trace, and the RTL seam the hypothesis cited -- rather
than being asked to guess from a one-line summary.

The bar for RTL_DEFECT is deliberately high. Reporting a false BOOM bug to the
people who wrote BOOM costs more than missing a real one, so anything the
evidence does not settle comes back INCONCLUSIVE rather than being rounded up.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import models, trace
from .agent import Agent, _parse_json
from .diff import UNSTABLE_CSRS, Divergence, compare, csr_of
from .generate import TestProgram
from .hypothesize import Hypothesis
from .tools import run

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLASSES = ("RTL_DEFECT", "MODEL_DEFECT", "LEGAL_NONDETERMINISM",
           "HARNESS_ARTIFACT", "INCONCLUSIVE")

OBJDUMP_RE = re.compile(r"^\s*([0-9a-f]+):\s+([0-9a-f]+)\s+(.*)$")


@dataclass
class Finding:
    id: str
    program_id: str
    hypothesis_id: str
    classification: str
    confidence: str = "unknown"
    rationale: str = ""
    recommended_action: str = ""
    reproducible: bool | None = None
    divergence: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    provenance: str = "mechanical"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "program_id": self.program_id,
            "hypothesis_id": self.hypothesis_id,
            "classification": self.classification,
            "confidence": self.confidence, "rationale": self.rationale,
            "recommended_action": self.recommended_action,
            "reproducible": self.reproducible,
            "divergence": self.divergence, "evidence": self.evidence,
            "provenance": self.provenance,
        }

    @property
    def actionable(self) -> bool:
        return self.classification in ("RTL_DEFECT", "MODEL_DEFECT")


def disassemble_window(elf: str, pc: int, radius: int = 4) -> list[str]:
    """Instructions around a program counter, straight from objdump."""
    res = run([models.TC.objdump, "-d", elf], env=models.TC.env(), timeout=120)
    if not res.ok:
        return []
    rows: list[tuple[int, str]] = []
    for line in res.stdout.splitlines():
        m = OBJDUMP_RE.match(line)
        if m:
            rows.append((int(m.group(1), 16), line.strip()))
    idx = next((n for n, (addr, _) in enumerate(rows) if addr == pc), None)
    if idx is None:
        return []
    lo, hi = max(0, idx - radius), min(len(rows), idx + radius + 1)
    return [("=> " if n == idx else "   ") + rows[n][1] for n in range(lo, hi)]


def gather_evidence(program: TestProgram, divergence: Divergence,
                    elf: str, hypothesis: Hypothesis | None = None) -> dict:
    """Assemble everything a human would want before making the call."""
    ev: dict = {"program": program.id, "kind": divergence.kind,
                "detail": divergence.detail}

    if divergence.ref is not None:
        ev["oracle_disassembly"] = disassemble_window(elf, divergence.ref.pc)
        csr = csr_of(divergence.ref.insn)
        if csr is not None:
            ev["oracle_csr"] = (f"0x{csr:03x} "
                                f"({UNSTABLE_CSRS.get(csr, 'not a counter')})")
    if divergence.dut is not None and (divergence.ref is None
                                       or divergence.dut.pc != divergence.ref.pc):
        ev["implementation_disassembly"] = disassemble_window(elf,
                                                              divergence.dut.pc)
    ev["trace_context"] = [{"oracle": r, "implementation": d}
                           for r, d in divergence.context[-6:]]
    if hypothesis is not None:
        ev["hypothesis"] = {
            "id": hypothesis.id, "title": hypothesis.title,
            "category": hypothesis.category,
            "expected_divergence": hypothesis.expected_divergence,
            "rtl_evidence": hypothesis.evidence[:6],
        }
    return ev


def reproduce(elf: str, runs: int = 2, start_pc: int = 0x80000000,
              boom_config: str = models.DEFAULT_BOOM_CONFIG) -> tuple[bool, str]:
    """Re-run both models and check the divergence lands in the same place.

    A divergence that does not reproduce is not a finding. Both of these models
    are deterministic, so a difference between runs points at the harness, not
    at the design.
    """
    signatures = []
    for _ in range(runs):
        ref, _ = models.spike_trace(elf)
        dut, _ = models.boom_trace(elf, config=boom_config)
        res = compare(ref, dut, start_pc=start_pc)
        d = res.divergence
        signatures.append("clean" if d is None
                          else f"{d.kind}@{d.index}:"
                               f"{d.dut.pc if d.dut else '-'}")
    return len(set(signatures)) == 1, signatures[0]


def mechanical_verdict(divergence: Divergence, reproducible: bool | None,
                       ref_total: int | None = None,
                       dut_total: int | None = None
                       ) -> tuple[str, str, str] | None:
    """Decide the cases that need no judgement. Returns (class, rationale, action)."""
    if reproducible is False:
        return ("INCONCLUSIVE",
                "The divergence did not reproduce across repeated runs. Both "
                "models are deterministic, so an unstable result indicates the "
                "harness rather than the design.",
                "Stabilise the harness and re-run before spending analysis on "
                "this.")

    if divergence.kind == "TRACE_END":
        # An empty trace and a short one look the same to the differ but mean
        # very different things: one is a tool that failed to run at all, the
        # other is a run that was cut short. Telling the user to raise the
        # instruction budget when the simulator never started wastes their time.
        empty = [name for name, total in (("oracle", ref_total),
                                          ("implementation", dut_total))
                 if total == 0]
        if empty:
            return ("HARNESS_ARTIFACT",
                    f"The {' and '.join(empty)} produced no committed "
                    "instructions at all. That is a tool invocation failure, "
                    "not a short run: nothing was compared.",
                    "Check the model command line and its exit status; the run "
                    "did not execute the program.")
        return ("HARNESS_ARTIFACT",
                "One trace ended early. That is a truncated or timed-out run, "
                "not a disagreement about architectural state.",
                "Raise the instruction or cycle budget and re-run.")

    for ev in (divergence.ref, divergence.dut):
        if ev is None:
            continue
        csr = csr_of(ev.insn)
        if csr in UNSTABLE_CSRS:
            return ("LEGAL_NONDETERMINISM",
                    f"The diverging instruction reads {UNSTABLE_CSRS[csr]} "
                    f"(CSR 0x{csr:03x}), a free-running counter. A functional "
                    "oracle and a cycle-accurate implementation are not "
                    "required to agree on its value.",
                    "Exclude counter reads from the comparison, or mask this "
                    "register in the test.")
    return None


_PROMPT = """You are triaging a divergence between an out-of-order RISC-V \
implementation (BOOM) and a functional ISA oracle (Spike).

Classify it as exactly one of:
  RTL_DEFECT            the implementation is wrong
  MODEL_DEFECT          the oracle is wrong
  LEGAL_NONDETERMINISM  both are correct; the difference is architecturally permitted
  HARNESS_ARTIFACT      neither is wrong; the comparison or test setup is
  INCONCLUSIVE          the evidence does not settle it

The bar for RTL_DEFECT is high. A false report costs more than a missed one, so
choose INCONCLUSIVE unless the evidence below actually settles the question.
Note that commit-log conventions differ between the two: the implementation
retires some instructions the oracle never logs.

Divergence: {kind}
{detail}

Evidence:
{evidence}

Respond as JSON: {{"classification": ..., "confidence": "high"|"medium"|"low", \
"rationale": "<2-4 sentences citing the evidence>", "recommended_action": "..."}}
"""


def _format_evidence(ev: dict) -> str:
    parts = []
    for key in ("oracle_csr",):
        if key in ev:
            parts.append(f"{key}: {ev[key]}")
    for key in ("oracle_disassembly", "implementation_disassembly"):
        if ev.get(key):
            parts.append(f"{key}:\n" + "\n".join(ev[key]))
    if ev.get("trace_context"):
        rows = "\n".join(f"  {c['oracle']}  |  {c['implementation']}"
                         for c in ev["trace_context"])
        parts.append("trace context (oracle | implementation):\n" + rows)
    if ev.get("hypothesis"):
        h = ev["hypothesis"]
        parts.append(f"hypothesis under test: {h['title']} ({h['category']})\n"
                     f"  expected: {h['expected_divergence']}\n"
                     f"  rtl evidence: {', '.join(h['rtl_evidence'])}")
    return "\n\n".join(parts)


def triage(program: TestProgram, divergence: Divergence, elf: str,
           hypothesis: Hypothesis | None = None, agent: Agent | None = None,
           check_reproducible: bool = True,
           boom_config: str = models.DEFAULT_BOOM_CONFIG,
           ref_total: int | None = None,
           dut_total: int | None = None) -> Finding:
    agent = agent or Agent()
    fid = f"{program.id}-{divergence.kind.lower()}-{divergence.index}"

    repro: bool | None = None
    if check_reproducible:
        repro, _sig = reproduce(elf, boom_config=boom_config)

    evidence = gather_evidence(program, divergence, elf, hypothesis)

    verdict = mechanical_verdict(divergence, repro, ref_total, dut_total)
    if verdict is not None:
        cls, rationale, action = verdict
        return Finding(fid, program.id,
                       hypothesis.id if hypothesis else "", cls,
                       confidence="high", rationale=rationale,
                       recommended_action=action, reproducible=repro,
                       divergence=divergence.to_dict(), evidence=evidence,
                       provenance="mechanical")

    if not agent.online:
        return Finding(
            fid, program.id, hypothesis.id if hypothesis else "",
            "INCONCLUSIVE", confidence="low",
            rationale=("No mechanical rule settles this divergence and no model "
                       "is configured, so it is left unclassified rather than "
                       "guessed. The evidence is attached for manual review."),
            recommended_action=("Review the attached disassembly and trace "
                                "context, or set GEMINI_API_KEY for "
                                "model-backed triage."),
            reproducible=repro, divergence=divergence.to_dict(),
            evidence=evidence, provenance="offline-heuristic")

    prompt = _PROMPT.format(kind=divergence.kind, detail=divergence.detail,
                            evidence=_format_evidence(evidence))
    try:
        data = _parse_json(agent.complete(prompt))
    except Exception as exc:                                # noqa: BLE001
        return Finding(fid, program.id, hypothesis.id if hypothesis else "",
                       "INCONCLUSIVE", confidence="low",
                       rationale=f"Model call failed: {exc}",
                       reproducible=repro, divergence=divergence.to_dict(),
                       evidence=evidence, provenance="offline-heuristic")

    cls = str(data.get("classification", "")).strip().upper()
    if cls not in CLASSES:
        cls = "INCONCLUSIVE"
    return Finding(fid, program.id, hypothesis.id if hypothesis else "",
                   cls, confidence=str(data.get("confidence", "unknown")),
                   rationale=str(data.get("rationale", "")).strip(),
                   recommended_action=str(data.get("recommended_action", "")).strip(),
                   reproducible=repro, divergence=divergence.to_dict(),
                   evidence=evidence, provenance=agent.provenance)


def feedback_context(findings: list[Finding], limit: int = 8) -> list[str]:
    """Turn confirmed findings into context for the next hypothesize round.

    This is the loop closing: only findings that survived triage as real defects
    are fed back. Artifacts and legal differences are deliberately excluded --
    feeding them back would steer the next round toward more of the same noise.
    """
    out = []
    for f in findings:
        if not f.actionable:
            continue
        hyp = f.evidence.get("hypothesis", {})
        out.append(
            f"[{f.classification}] {hyp.get('title', f.program_id)}: "
            f"{f.rationale.strip()} (divergence: {f.divergence.get('detail','')})"
        )
        if len(out) >= limit:
            break
    return out
