"""Tests for the hypothesize block.

The seam scan is the auditable half of the block -- every hypothesis has to be
traceable back to cited RTL -- so these tests pin down what it does and does not
match, and that evidence selection is relevance-ranked rather than filesystem
ordered.
"""
import os
import tempfile
import unittest

from chia_loop.hypothesize import (BOOM_V3, excerpt, propose, rank_seams,
                                   scan_seams)

SAMPLE = {
    "lsu/lsu.scala": """\
package boom.v3.lsu
class LSU extends Module {
  val maybe_full = RegInit(false.B)
  val ldq_head = RegInit(0.U)
  when (io.ldq_order && stq_conflict) { nack := true.B }
  // TODO: this replay path is not exercised
  val do_replay = nack && !fence
}
""",
    "exu/rename.scala": """\
package boom.v3.exu
class RenameStage extends Module {
  val bypass_hit = Wire(Bool())
  bypass_hit := older_uop.pdst === uop.prs1
  // bypass mentioned only in a comment here
}
""",
}


def _write_tree(root):
    for rel, text in SAMPLE.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)


class TestSeamScan(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        _write_tree(self.root)
        self.seams = scan_seams(self.root)

    def test_finds_markers(self):
        markers = {s.marker for s in self.seams}
        self.assertIn("maybe_full", markers)
        self.assertIn("bypass", markers)
        self.assertIn("todo", markers)

    def test_comment_only_line_excluded_from_behavioural_category(self):
        """A `bypass` mention inside a comment is not RTL behaviour."""
        bypass_lines = [s.line for s in self.seams
                        if s.marker == "bypass" and "rename" in s.file]
        snippets = [s.snippet for s in self.seams if s.marker == "bypass"]
        self.assertTrue(bypass_lines)
        self.assertFalse(any(sn.startswith("//") for sn in snippets))

    def test_todo_comment_is_kept(self):
        """For ACKNOWLEDGED_GAP the comment *is* the evidence."""
        todos = [s for s in self.seams if s.marker == "todo"]
        self.assertTrue(todos)
        self.assertTrue(todos[0].snippet.startswith("//"))

    def test_max_per_marker_caps(self):
        capped = scan_seams(self.root, max_per_marker=1)
        by_marker = {}
        for s in capped:
            by_marker[s.marker] = by_marker.get(s.marker, 0) + 1
        self.assertTrue(all(n <= 1 for n in by_marker.values()))

    def test_ref_format(self):
        self.assertRegex(self.seams[0].ref, r"^[\w/.\-]+:\d+$")


class _TreeCase(unittest.TestCase):
    """Base with a synthetic source tree torn down even on assertion failure."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        _write_tree(self.root)


class TestRanking(_TreeCase):
    def test_preferred_marker_ranks_first(self):
        seams = [s for s in scan_seams(self.root)
                 if s.category == "MEMORY_ORDERING"]
        ranked = rank_seams("MEMORY_ORDERING", seams)
        if any(s.marker == "ld_st_order" for s in seams):
            self.assertEqual(ranked[0].marker, "ld_st_order")

    def test_unknown_category_is_stable_not_crashing(self):
        seams = scan_seams(self.root)
        self.assertEqual(len(rank_seams("NO_SUCH_CATEGORY", seams)), len(seams))


class TestOfflineProposal(_TreeCase):
    def test_one_hypothesis_per_category_with_evidence(self):
        seams = scan_seams(self.root)
        hyps = propose(seams, root=self.root)
        self.assertTrue(hyps)
        for h in hyps:
            self.assertTrue(h.evidence, f"{h.id} cites nothing")
            self.assertTrue(h.stimulus_sketch, f"{h.id} has no stimulus")
            self.assertEqual(h.provenance, "offline-heuristic")
            self.assertIn(h.confidence, {"high", "medium", "low", "unknown"})


class TestExcerpt(_TreeCase):
    def test_marks_the_target_line(self):
        text = excerpt(self.root, "lsu/lsu.scala", 3, radius=2)
        marked = [l for l in text.splitlines() if l.startswith(">>")]
        self.assertEqual(len(marked), 1)
        self.assertIn("maybe_full", marked[0])


@unittest.skipUnless(os.path.isdir(BOOM_V3), "BOOM source not present")
class TestAgainstRealBoom(unittest.TestCase):
    def test_memory_ordering_evidence_comes_from_the_lsu(self):
        """Relevance ranking must not cite icache fences for a load/store claim."""
        seams = [s for s in scan_seams(BOOM_V3)
                 if s.category == "MEMORY_ORDERING"]
        top = rank_seams("MEMORY_ORDERING", seams)[:5]
        self.assertTrue(all(s.file.startswith("lsu/") for s in top),
                        [s.ref for s in top])
