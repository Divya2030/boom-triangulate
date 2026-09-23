"""Tests for the triage block.

The rules that matter are the ones that stop a divergence being rounded up into
a bug report, so these concentrate on: mechanical verdicts firing where they
should, the offline path refusing to guess, an unrecognised model answer being
rejected, and only actionable findings reaching the feedback loop.
"""
import unittest

from chia_loop.diff import Divergence
from chia_loop.trace import CommitEvent, RegWrite
from chia_loop.triage import CLASSES, Finding, feedback_context, mechanical_verdict


def _ev(pc, insn, writes=()):
    return CommitEvent(pc=pc, insn=insn,
                       writes=[RegWrite("x", i, v) for i, v in writes])


class TestMechanicalVerdicts(unittest.TestCase):
    def test_unstable_counter_is_legal(self):
        # csrrs x10, cycle, x0
        d = Divergence(0, "REG_WRITE", "NEEDS_TRIAGE",
                       _ev(0x80000000, 0xC0002573, [(10, 100)]),
                       _ev(0x80000000, 0xC0002573, [(10, 999)]))
        cls, rationale, _ = mechanical_verdict(d, True)
        self.assertEqual(cls, "LEGAL_NONDETERMINISM")
        self.assertIn("cycle", rationale)

    def test_non_reproducible_is_inconclusive(self):
        d = Divergence(0, "REG_WRITE", "NEEDS_TRIAGE",
                       _ev(0x80000000, 0x13), _ev(0x80000000, 0x13))
        cls, _, _ = mechanical_verdict(d, False)
        self.assertEqual(cls, "INCONCLUSIVE")

    def test_empty_trace_is_distinguished_from_truncation(self):
        """Telling someone to raise the budget when the tool never ran wastes
        their time."""
        d = Divergence(0, "TRACE_END", "NEEDS_TRIAGE", None, None)
        cls, rationale, action = mechanical_verdict(d, True, ref_total=66,
                                                    dut_total=0)
        self.assertEqual(cls, "HARNESS_ARTIFACT")
        self.assertIn("no committed instructions", rationale)
        self.assertNotIn("budget", action)

    def test_truncation_still_suggests_budget(self):
        d = Divergence(0, "TRACE_END", "NEEDS_TRIAGE", None, None)
        _cls, _r, action = mechanical_verdict(d, True, ref_total=66,
                                              dut_total=40)
        self.assertIn("budget", action)

    def test_ordinary_divergence_has_no_mechanical_answer(self):
        """Real work must reach the judgement path, not be auto-classified."""
        d = Divergence(0, "REG_WRITE", "NEEDS_TRIAGE",
                       _ev(0x80000000, 0x00439e13, [(28, 0x30)]),
                       _ev(0x80000000, 0x00439e13, [(28, 0xbad)]))
        self.assertIsNone(mechanical_verdict(d, True))


class TestFeedbackLoop(unittest.TestCase):
    def _finding(self, cls):
        return Finding(id=f"f-{cls}", program_id="p1", hypothesis_id="h1",
                       classification=cls, rationale="because")

    def test_only_actionable_findings_feed_back(self):
        findings = [self._finding(c) for c in CLASSES]
        ctx = feedback_context(findings)
        self.assertEqual(len(ctx), 2)
        self.assertTrue(any("RTL_DEFECT" in c for c in ctx))
        self.assertTrue(any("MODEL_DEFECT" in c for c in ctx))
        self.assertFalse(any("HARNESS_ARTIFACT" in c for c in ctx))
        self.assertFalse(any("LEGAL_NONDETERMINISM" in c for c in ctx))

    def test_actionable_flag(self):
        self.assertTrue(self._finding("RTL_DEFECT").actionable)
        self.assertFalse(self._finding("INCONCLUSIVE").actionable)
        self.assertFalse(self._finding("HARNESS_ARTIFACT").actionable)

    def test_feedback_is_limited(self):
        findings = [self._finding("RTL_DEFECT") for _ in range(20)]
        self.assertEqual(len(feedback_context(findings, limit=3)), 3)


class TestClassSet(unittest.TestCase):
    def test_classes_are_the_five_the_plan_promises(self):
        self.assertEqual(set(CLASSES), {
            "RTL_DEFECT", "MODEL_DEFECT", "LEGAL_NONDETERMINISM",
            "HARNESS_ARTIFACT", "INCONCLUSIVE"})
