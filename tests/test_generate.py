"""Tests for the generate block.

The validation gate is the point of this block, so most of these are negative
controls: a gate that accepts everything would let the loop report clean
comparisons from programs that never executed anything.
"""
import os
import tempfile
import unittest

from chia_loop import models
from chia_loop.generate import (TEMPLATES, TestProgram, _sanitize, validate)
from chia_loop.hypothesize import Hypothesis

TOOLS_PRESENT = not models.TC.missing()


class TestSanitize(unittest.TestCase):
    def test_strips_structure_the_harness_supplies(self):
        body = _sanitize("""\
#include "common.S"
  .section .text.init
  .globl _start
_start:
  addi a0, a0, 1
""")
        self.assertNotIn(".section", body)
        self.assertNotIn("_start", body)
        self.assertNotIn("#include", body)
        self.assertIn("addi a0, a0, 1", body)

    def test_strips_tohost_writes(self):
        """A model-written tohost store would end the run early."""
        body = _sanitize("  la t0, tohost\n  addi a0, a0, 1\n")
        self.assertNotIn("tohost", body)
        self.assertIn("addi", body)

    def test_empty_body_stays_empty(self):
        self.assertEqual(_sanitize("  .section .text\n"), "")


class TestRender(unittest.TestCase):
    def test_trap_setup_only_when_requested(self):
        p = TestProgram("t1", "H-1", "BYPASS_FORWARD", "  nop\n", False)
        self.assertNotIn("TRAP_SETUP", p.render())
        q = TestProgram("t2", "H-2", "EXCEPTION_PRIORITY", "  nop\n", True)
        self.assertIn("TRAP_SETUP", q.render())

    def test_always_exits(self):
        p = TestProgram("t3", "H-3", "BYPASS_FORWARD", "  nop\n")
        self.assertIn("TEST_PASS", p.render())

    def test_records_provenance(self):
        p = TestProgram("t4", "H-4", "BYPASS_FORWARD", "  nop\n",
                        provenance="gemini:test")
        self.assertIn("gemini:test", p.render())


@unittest.skipUnless(TOOLS_PRESENT, "riscv toolchain / spike not built")
class TestValidationGate(unittest.TestCase):
    """Programs are written to a temp dir so the suite never leaves stray
    assembly in tests/progs/generated, which ships as part of the artifact."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = tmp.name

    def test_rejects_program_that_does_not_assemble(self):
        p = TestProgram("bad_asm", "H-x", "BYPASS_FORWARD",
                        "  this_is_not_an_instruction a0, a0\n")
        p.write(self.out)
        v = validate(p)
        self.assertFalse(v.ok)
        self.assertFalse(v.assembles)
        self.assertIn("assemble", v.reason)

    def test_rejects_program_that_does_nothing(self):
        """Trivial programs produce clean comparisons and prove nothing."""
        p = TestProgram("trivial", "H-y", "BYPASS_FORWARD", "  nop\n")
        p.write(self.out)
        v = validate(p, min_events=8)
        self.assertFalse(v.ok)
        self.assertTrue(v.assembles)
        self.assertTrue(v.terminates)
        self.assertLess(v.events, 8)
        self.assertIn("retired only", v.reason)

    def test_accepts_a_real_template(self):
        body, needs_trap = TEMPLATES["MEMORY_ORDERING"]
        p = TestProgram("tmpl_mem", "H-z", "MEMORY_ORDERING", body, needs_trap)
        p.write(self.out)
        v = validate(p)
        self.assertTrue(v.ok, v.reason)
        self.assertGreaterEqual(v.events, 8)

    def test_every_template_clears_the_gate(self):
        """The offline baseline has to meet the same bar as model output."""
        for category, (body, needs_trap) in TEMPLATES.items():
            with self.subTest(category=category):
                p = TestProgram(f"tmpl_{category.lower()}", "H-t", category,
                                body, needs_trap)
                p.write(self.out)
                v = validate(p)
                self.assertTrue(v.ok, f"{category}: {v.reason}")
