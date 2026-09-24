"""Multi-oracle triangulation: classify a divergence by majority vote.

Every prior processor fuzzer (DIFUZZRTL, ProcessorFuzz, TheHuzz) compares the
implementation against a single golden model, so a divergence leaves the
question "which side is wrong?" to a human. With two independent oracles the
common cases become mechanical:

  implementation (BOOM) vs oracle A (Spike) vs oracle B (Dromajo)

  A == B == BOOM ......................... CLEAN
  A == B, BOOM differs ................... RTL_DEFECT   (both oracles agree; impl is the outlier)
  BOOM == A, B differs ................... MODEL_DEFECT (oracle B is the outlier)
  BOOM == B, A differs ................... MODEL_DEFECT (oracle A is the outlier)
  A != B (oracles disagree) ............. ORACLE_MISMATCH (a bug in one reference model)
  all three differ ...................... INCONCLUSIVE (hand to model-backed triage)

ProcessorFuzz reported a real bug in a reference model, so ORACLE_MISMATCH and
MODEL_DEFECT are not hypothetical outcomes. This turns the expensive, subjective
step into a vote for the majority of cases, and reserves the model call for the
genuinely ambiguous three-way split.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .diff import compare
from .trace import CommitEvent

VERDICTS = ("CLEAN", "RTL_DEFECT", "MODEL_DEFECT", "ORACLE_MISMATCH",
            "HARNESS_ARTIFACT", "INCONCLUSIVE")

# A run that retired nothing did not execute the program. Voting on an empty
# trace turns a tool failure into a fabricated RTL_DEFECT -- the exact
# overclaim this project refuses to make.
MIN_EVENTS = 4


@dataclass
class Triangulation:
    verdict: str
    confidence: str = "mechanical"
    outlier: str = ""            # which stream stands alone: boom | spike | dromajo
    rationale: str = ""
    pairwise: dict = field(default_factory=dict)   # clean/first-divergence per pair
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict, "confidence": self.confidence,
            "outlier": self.outlier, "rationale": self.rationale,
            "pairwise": self.pairwise, "detail": self.detail,
        }

    @property
    def actionable(self) -> bool:
        return self.verdict in ("RTL_DEFECT", "MODEL_DEFECT", "ORACLE_MISMATCH")


def _agree(a: list[CommitEvent], b: list[CommitEvent], start_pc: int | None) -> bool:
    """True if two commit streams match over committed state from the sync PC."""
    return compare(a, b, start_pc=start_pc).clean


def triangulate(boom: list[CommitEvent], spike: list[CommitEvent],
                dromajo: list[CommitEvent],
                start_pc: int | None = 0x80000000) -> Triangulation:
    """Vote on a divergence using two independent oracles.

    Names follow the module docstring: Spike and Dromajo are the oracles, BOOM
    the implementation under test.
    """
    counts = {"boom": len(boom), "spike": len(spike), "dromajo": len(dromajo)}
    empty = [name for name, n in counts.items() if n < MIN_EVENTS]
    if empty:
        return Triangulation(
            "HARNESS_ARTIFACT", "mechanical", "",
            f"{', '.join(empty)} retired fewer than {MIN_EVENTS} instructions: "
            "the run did not execute the program, so no comparison is valid.",
            {k: f"{v} events" for k, v in counts.items()},
            detail="empty or failed trace")

    bs = _agree(boom, spike, start_pc)      # BOOM == Spike?
    bd = _agree(boom, dromajo, start_pc)    # BOOM == Dromajo?
    sd = _agree(spike, dromajo, start_pc)   # Spike == Dromajo? (oracle agreement)

    pairwise = {"boom_vs_spike": "agree" if bs else "differ",
                "boom_vs_dromajo": "agree" if bd else "differ",
                "spike_vs_dromajo": "agree" if sd else "differ"}

    if bs and bd:
        # BOOM matches both oracles -> clean. (A stray oracle disagreement here
        # is a first-divergence/truncation artifact; the implementation is clean.)
        return Triangulation("CLEAN", "mechanical", "",
                             "Implementation agrees with both independent oracles.",
                             pairwise)

    # BOOM agrees with exactly one oracle: it breaks the tie and names the other
    # oracle as the outlier. This is the case single-golden-model tools cannot
    # decide -- a bug in a reference model, not in the implementation.
    if bd and not bs:
        return Triangulation("MODEL_DEFECT", "high", "spike",
                             "Implementation and Dromajo agree; Spike is the sole "
                             "outlier, so the defect is in that reference model.",
                             pairwise)
    if bs and not bd:
        return Triangulation("MODEL_DEFECT", "high", "dromajo",
                             "Implementation and Spike agree; Dromajo is the sole "
                             "outlier, so the defect is in that reference model.",
                             pairwise)

    # BOOM agrees with neither oracle.
    if sd:
        # Both oracles agree with each other; BOOM is the sole outlier.
        return Triangulation("RTL_DEFECT", "high", "boom",
                             "Both independent oracles agree and the implementation "
                             "is the sole outlier -- strong evidence of an "
                             "implementation defect.", pairwise)
    # All three disagree: no majority to trust.
    return Triangulation("INCONCLUSIVE", "low", "",
                         "Three-way split: implementation and both references all "
                         "disagree, so no side can be trusted; escalate to "
                         "model-backed triage with full evidence.", pairwise)
