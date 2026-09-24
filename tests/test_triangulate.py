"""Tests for multi-oracle triangulation.

The whole value is that the vote is mechanical and correct, so these pin down
each outcome with synthetic three-way traces.
"""
import unittest

from chia_loop.trace import parse_commit_log
from chia_loop.triangulate import triangulate

# Two committed instructions at the program start; easy to perturb per stream.
BASE = ("3 0x0000000080000000 (0x00000297) x 5 0x0000000000000001\n"
        "3 0x0000000080000004 (0x00450513) x10 0x0000000000000002\n"
        "3 0x0000000080000008 (0x006283b3) x 7 0x0000000000000003\n"
        "3 0x000000008000000c (0x00439e13) x28 0x0000000000000030\n"
        "3 0x0000000080000010 (0x005e4eb3) x29 0x0000000000000031\n")


def ev(text):
    return parse_commit_log(text)


class TestTriangulation(unittest.TestCase):
    def test_all_agree_is_clean(self):
        t = triangulate(ev(BASE), ev(BASE), ev(BASE))
        self.assertEqual(t.verdict, "CLEAN")

    def test_boom_sole_outlier_is_rtl_defect(self):
        boom = BASE.replace("x10 0x0000000000000002", "x10 0x00000000deadbeef")
        t = triangulate(ev(boom), ev(BASE), ev(BASE))   # oracles agree, BOOM differs
        self.assertEqual(t.verdict, "RTL_DEFECT")
        self.assertEqual(t.outlier, "boom")
        self.assertEqual(t.confidence, "high")

    def test_boom_breaks_oracle_tie_model_defect(self):
        # boom==spike, dromajo differs -> Dromajo is the outlier (MODEL_DEFECT).
        dromajo = BASE.replace("x10 0x0000000000000002", "x10 0x0000000000000099")
        t = triangulate(ev(BASE), ev(BASE), ev(dromajo))
        self.assertEqual(t.verdict, "MODEL_DEFECT")
        self.assertEqual(t.outlier, "dromajo")

    def test_spike_is_outlier_model_defect(self):
        # boom==dromajo, spike differs -> Spike is the outlier (the seeded-Spike demo).
        spike = BASE.replace("x10 0x0000000000000002", "x10 0x0000000000000099")
        t = triangulate(ev(BASE), ev(spike), ev(BASE))
        self.assertEqual(t.verdict, "MODEL_DEFECT")
        self.assertEqual(t.outlier, "spike")

    def test_three_way_split_inconclusive(self):
        spike = BASE.replace("x 5 0x0000000000000001", "x 5 0x00000000000000aa")
        dromajo = BASE.replace("x 5 0x0000000000000001", "x 5 0x00000000000000bb")
        boom = BASE.replace("x 5 0x0000000000000001", "x 5 0x00000000000000cc")
        t = triangulate(ev(boom), ev(spike), ev(dromajo))
        self.assertEqual(t.verdict, "INCONCLUSIVE")

    def test_dromajo_outlier_is_model_defect(self):
        # BOOM and Spike agree; Dromajo alone differs.
        dromajo = BASE.replace("x 5 0x0000000000000001", "x 5 0x00000000cafef00d")
        t = triangulate(ev(BASE), ev(BASE), ev(dromajo))
        # Spike==Dromajo? no. BOOM==Dromajo? no. BOOM==Spike? yes -> oracle B (dromajo) outlier
        self.assertEqual(t.verdict, "MODEL_DEFECT")

    def test_actionable_flag(self):
        boom = BASE.replace("x10 0x0000000000000002", "x10 0x00000000deadbeef")
        self.assertTrue(triangulate(ev(boom), ev(BASE), ev(BASE)).actionable)
        self.assertFalse(triangulate(ev(BASE), ev(BASE), ev(BASE)).actionable)

    def test_pairwise_recorded(self):
        t = triangulate(ev(BASE), ev(BASE), ev(BASE))
        self.assertEqual(set(t.pairwise), {"boom_vs_spike", "boom_vs_dromajo",
                                           "spike_vs_dromajo"})


class TestEmptyTraceGuard(unittest.TestCase):
    def test_empty_boom_is_harness_artifact_not_rtl_defect(self):
        """A failed BOOM run must never be voted a bug."""
        t = triangulate([], ev(BASE), ev(BASE))
        self.assertEqual(t.verdict, "HARNESS_ARTIFACT")
        self.assertNotEqual(t.verdict, "RTL_DEFECT")

    def test_empty_oracle_is_harness_artifact(self):
        t = triangulate(ev(BASE), [], ev(BASE))
        self.assertEqual(t.verdict, "HARNESS_ARTIFACT")
