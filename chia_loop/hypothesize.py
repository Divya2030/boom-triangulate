"""Hypothesize block: propose where BOOM and the ISA oracle might disagree.

Blind stimulus generation wastes simulation budget on instruction sequences that
exercise nothing interesting. This block instead reads the RTL and nominates
specific *seams* -- places where an out-of-order implementation has to reconstruct
behaviour that the functional oracle gets for free -- then asks for concrete,
testable divergence hypotheses about them.

Two stages, deliberately separated:

  scan_seams()  deterministic, no model, no cost. A pattern sweep over the RTL
                that locates candidate regions and cites file:line evidence.
  propose()     model-backed. Turns seam evidence into structured hypotheses
                that the generate block can turn into test programs.

The split matters for the write-up: the seam scan is reproducible and auditable,
so a hypothesis can always be traced back to the lines of RTL that motivated it,
and the model's contribution can be measured against the offline baseline rather
than assumed.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .agent import Agent

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOM_V3 = os.path.join(REPO, "tools", "src", "chipyard", "generators", "boom",
                       "src", "main", "scala", "v3")

# Categories follow the problem areas named in the project plan. Each pattern is
# grounded in markers that actually occur in BOOM's source -- counts from v3:
# xcpt 170, bypass 48, maybe_full 19, wrap 18, TODO 53.
CATEGORY_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "EXCEPTION_PRIORITY": [
        ("xcpt_priority", r"\bxcpt\w*\s*(?::=|===|Mux)"),
        ("cause_select", r"\b(exc_cause|xcpt_cause|cause)\b.*(?:Mux|PriorityMux)"),
        ("priority_mux", r"\bPriorityMux\b"),
    ],
    "QUEUE_POINTER": [
        ("maybe_full", r"\bmaybe_full\b"),
        ("ptr_wrap", r"\bwrap\w*\b"),
        ("head_tail", r"\b(head|tail)\b\s*(?::=|\+|===)"),
        ("full_empty", r"\b(is_full|empty|full)\b\s*:="),
    ],
    "BYPASS_FORWARD": [
        ("bypass", r"\bbypass\w*\b"),
        ("forward", r"\bforward\w*\b"),
    ],
    "MEMORY_ORDERING": [
        ("ld_st_order", r"\b(ldq|stq)\w*\b.*\b(order|dep|conflict|forward)\w*"),
        ("fence", r"\b(fence|release|acquire)\w*\b"),
        ("nack_replay", r"\b(nack|replay)\w*\b"),
    ],
    "ACKNOWLEDGED_GAP": [
        ("todo", r"//.*\b(TODO|XXX|FIXME|HACK)\b"),
        ("disabled_feature", r"\brequire\(\s*!"),
    ],
}


@dataclass(frozen=True)
class Seam:
    """One cited location in the RTL that motivates a hypothesis."""

    category: str
    marker: str
    file: str          # relative to the scanned root
    line: int          # 1-indexed
    snippet: str

    @property
    def ref(self) -> str:
        return f"{self.file}:{self.line}"

    def to_dict(self) -> dict:
        return {"category": self.category, "marker": self.marker,
                "ref": self.ref, "snippet": self.snippet}


@dataclass
class Hypothesis:
    """A testable claim about where the two models may disagree."""

    id: str
    category: str
    title: str
    rationale: str
    evidence: list[str] = field(default_factory=list)   # file:line refs
    preconditions: str = ""       # machine state needed to reach the seam
    stimulus_sketch: str = ""     # what the generate block should build
    expected_divergence: str = "" # what would differ, and in which direction
    confidence: str = "unknown"   # high | medium | low | unknown
    provenance: str = "offline-heuristic"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "category": self.category, "title": self.title,
            "rationale": self.rationale, "evidence": self.evidence,
            "preconditions": self.preconditions,
            "stimulus_sketch": self.stimulus_sketch,
            "expected_divergence": self.expected_divergence,
            "confidence": self.confidence, "provenance": self.provenance,
        }


# Which markers actually support which claim. Without this, evidence is taken in
# filesystem order and a memory-ordering hypothesis ends up citing icache fence
# lines -- a real citation that does not support the claim being made.
MARKER_PRIORITY: dict[str, list[str]] = {
    "EXCEPTION_PRIORITY": ["xcpt_priority", "cause_select", "priority_mux"],
    "QUEUE_POINTER":      ["maybe_full", "ptr_wrap", "full_empty", "head_tail"],
    "BYPASS_FORWARD":     ["bypass", "forward"],
    "MEMORY_ORDERING":    ["ld_st_order", "nack_replay", "fence"],
    "ACKNOWLEDGED_GAP":   ["disabled_feature", "todo"],
}


def rank_seams(category: str, seams: list[Seam]) -> list[Seam]:
    """Order seams so the most claim-relevant evidence comes first.

    Ranks by marker specificity, then by how many seams the file contributes --
    a file dense in a category is more likely to be where that behaviour lives.
    """
    order = MARKER_PRIORITY.get(category, [])
    density: dict[str, int] = {}
    for seam in seams:
        density[seam.file] = density.get(seam.file, 0) + 1

    def key(seam: Seam) -> tuple:
        rank = order.index(seam.marker) if seam.marker in order else len(order)
        return (rank, -density.get(seam.file, 0), seam.file, seam.line)

    return sorted(seams, key=key)


def _is_comment_only(line: str) -> bool:
    return line.strip().startswith("//")


def scan_seams(root: str = BOOM_V3, categories: list[str] | None = None,
               max_per_marker: int | None = None) -> list[Seam]:
    """Deterministic sweep for candidate regions. No model, no cost.

    Comment-only lines are kept for ACKNOWLEDGED_GAP (a TODO *is* the evidence)
    and dropped elsewhere, where a match inside a comment is not RTL behaviour.
    """
    wanted = categories or list(CATEGORY_PATTERNS)
    seams: list[Seam] = []
    counts: dict[tuple[str, str], int] = {}

    for dirpath, _dirs, files in os.walk(root):
        for fname in sorted(files):
            if not fname.endswith(".scala"):
                continue
            path = os.path.join(dirpath, fname)
            rel = os.path.relpath(path, root)
            try:
                lines = open(path, errors="replace").read().splitlines()
            except OSError:
                continue

            for lineno, line in enumerate(lines, start=1):
                for cat in wanted:
                    for marker, pattern in CATEGORY_PATTERNS.get(cat, []):
                        if cat != "ACKNOWLEDGED_GAP" and _is_comment_only(line):
                            continue
                        if not re.search(pattern, line):
                            continue
                        key = (cat, marker)
                        if (max_per_marker is not None
                                and counts.get(key, 0) >= max_per_marker):
                            continue
                        counts[key] = counts.get(key, 0) + 1
                        seams.append(Seam(cat, marker, rel, lineno,
                                          line.strip()[:200]))
    return seams


def excerpt(root: str, rel: str, line: int, radius: int = 12) -> str:
    """Source window around a seam, for model context."""
    path = os.path.join(root, rel)
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return ""
    lo, hi = max(0, line - 1 - radius), min(len(lines), line + radius)
    out = []
    for n in range(lo, hi):
        mark = ">>" if n == line - 1 else "  "
        out.append(f"{mark} {n + 1:5d} | {lines[n]}")
    return "\n".join(out)


_PROMPT = """You are a verification engineer hunting for divergences between an \
out-of-order RISC-V implementation (BOOM) and independent ISA reference models \
(Spike, Dromajo).

Below are locations in BOOM's RTL flagged as "{category}" seams -- places where the
implementation must reconstruct behaviour the reference gets for free.

Propose at most {limit} concrete, testable divergence hypotheses. A STRONG
hypothesis:
- names machine state reachable from a short bare-metal program (no OS, no
  interrupts unless the category is exceptions);
- predicts a divergence in COMMITTED state that lands in a specific integer
  register -- name which architectural effect (a wrong rdN value, a wrong
  forwarded operand, a dropped writeback), not a microarchitectural signal;
- can be provoked WITHOUT relying on data-dependent control flow, so the test
  can isolate the effect into one register rather than derailing execution;
- is NOT a timing-only difference (cycle counts are ignored by construction) and
  NOT dependent on multi-hart or external memory agents.
Reject a candidate that only manifests as a pipeline stall, a coverage point, or
a performance-counter value.

RTL evidence:
{evidence}

Respond as JSON: {{"hypotheses": [{{"title": ..., "rationale": ..., "evidence": \
["file:line", ...], "preconditions": ..., "stimulus_sketch": ..., \
"expected_divergence": "<the exact committed-state difference, e.g. 'x7 holds \
the pre-forward value 0x3 instead of 0x7'>", "confidence": "high"|"medium"|"low"}}]}}
"""


def _evidence_block(seams: list[Seam], root: str, radius: int,
                    max_excerpts: int) -> str:
    parts = []
    for seam in seams[:max_excerpts]:      # caller ranks before calling
        parts.append(f"--- {seam.ref}  (marker: {seam.marker})\n"
                     + excerpt(root, seam.file, seam.line, radius))
    return "\n\n".join(parts)


def _offline_hypotheses(category: str, seams: list[Seam]) -> list[Hypothesis]:
    """Deterministic baseline, so the block runs and is testable without credit.

    These are template claims keyed on the category. They are intentionally
    coarse: their purpose is to be the control the model's output is measured
    against, not to stand in for it.
    """
    templates = {
        "EXCEPTION_PRIORITY": (
            "Simultaneous exceptions may be prioritised differently",
            "When one instruction raises more than one exception condition in the "
            "same cycle, the oracle applies the architectural priority order. The "
            "implementation selects a cause through its own mux tree, and any "
            "disagreement appears as a different mcause/mtval and a different "
            "handler entry.",
            "An instruction that is simultaneously misaligned and page-faulting, "
            "or an illegal instruction inside a misaligned fetch.",
            "Trap on an instruction that satisfies two exception conditions at "
            "once; read mcause and mepc in the handler.",
            "Different mcause value written, hence different register state after "
            "the handler returns."),
        "QUEUE_POINTER": (
            "Queue full/empty aliasing at wrap-around",
            "Head and tail pointers that alias when a queue is exactly full are a "
            "classic source of dropped or duplicated entries. The oracle has no "
            "queue at all, so any such loss shows up as a missing or repeated "
            "committed instruction.",
            "A queue driven to exactly its capacity, then one more entry pushed "
            "in the same cycle an entry is popped.",
            "A long dependent chain sized to fill the ROB or load/store queue "
            "exactly, followed by a burst that forces simultaneous push and pop.",
            "A committed instruction missing from BOOM's trace, or its register "
            "write applied twice."),
        "BYPASS_FORWARD": (
            "Bypass network may forward a stale or wrong-width value",
            "Forwarding paths reconstruct a value before it is architecturally "
            "written back. Width handling and the choice among several eligible "
            "producers are where the implementation can disagree with a model "
            "that simply reads the register file.",
            "Back-to-back dependent instructions with differing operand widths, "
            "with the producer still in flight.",
            "Tight dependent chains mixing word and doubleword operations, and "
            "sign-extending loads feeding immediately into arithmetic.",
            "A register write with the wrong value, most likely wrong "
            "sign-extension in the upper bits."),
        "MEMORY_ORDERING": (
            "Store-to-load forwarding may return the wrong bytes",
            "A load that partially overlaps an older in-flight store must be "
            "resolved from the store queue. Partial overlap, differing access "
            "sizes, and replay after a nack are all places where the "
            "implementation can return bytes the oracle would not.",
            "A load overlapping an older uncommitted store by less than the full "
            "access width.",
            "Store a doubleword, then load overlapping bytes and halfwords at "
            "offsets inside it, before the store can commit.",
            "The load commits a different value than the oracle's."),
        "ACKNOWLEDGED_GAP": (
            "Behaviour the RTL itself flags as unfinished",
            "The implementation carries explicit TODO/FIXME markers and disabled "
            "features. These are the author's own statement that something is "
            "incomplete, which makes them unusually cheap places to look.",
            "Whatever state the flagged code path governs.",
            "Read the cited lines and target the specific unfinished path.",
            "Unknown until the cited code is read; these seams need triage before "
            "they are worth simulation budget."),
    }
    title, rationale, pre, sketch, expect = templates[category]
    refs = [s.ref for s in rank_seams(category, seams)[:8]]
    return [Hypothesis(
        id=f"{category}-offline-1", category=category, title=title,
        rationale=rationale, evidence=refs, preconditions=pre,
        stimulus_sketch=sketch, expected_divergence=expect,
        confidence="low", provenance="offline-heuristic",
    )]


def propose(seams: list[Seam], agent: Agent | None = None,
            root: str = BOOM_V3, per_category: int = 3,
            radius: int = 12, max_excerpts: int = 10) -> list[Hypothesis]:
    """Turn seam evidence into structured hypotheses, one call per category."""
    agent = agent or Agent()
    by_cat: dict[str, list[Seam]] = {}
    for seam in seams:
        by_cat.setdefault(seam.category, []).append(seam)

    out: list[Hypothesis] = []
    for category, group in sorted(by_cat.items()):
        group = rank_seams(category, group)
        if not agent.online:
            out.extend(_offline_hypotheses(category, group))
            continue

        prompt = _PROMPT.format(
            category=category, limit=per_category,
            evidence=_evidence_block(group, root, radius, max_excerpts))
        try:
            raw = agent.complete(prompt)
        except Exception as exc:                       # noqa: BLE001
            fallback = _offline_hypotheses(category, group)
            for h in fallback:
                h.rationale = f"[model call failed: {exc}] " + h.rationale
            out.extend(fallback)
            continue

        from .agent import _parse_json
        data = _parse_json(raw)
        items = data.get("hypotheses", []) if isinstance(data, dict) else []
        if not items:
            out.extend(_offline_hypotheses(category, group))
            continue

        for n, item in enumerate(items[:per_category], start=1):
            out.append(Hypothesis(
                id=f"{category}-{n}",
                category=category,
                title=str(item.get("title", "")).strip(),
                rationale=str(item.get("rationale", "")).strip(),
                evidence=[str(e) for e in item.get("evidence", [])] or
                         [s.ref for s in group[:5]],
                preconditions=str(item.get("preconditions", "")).strip(),
                stimulus_sketch=str(item.get("stimulus_sketch", "")).strip(),
                expected_divergence=str(item.get("expected_divergence", "")).strip(),
                confidence=str(item.get("confidence", "unknown")).strip(),
                provenance=agent.provenance,
            ))
    return out
