"""Unit tests for trace normalisation and divergence detection.

These use synthetic trace lines. They pin down the diff semantics -- which
differences count, which are ignored, how divergences are classified -- so that
when the parsers meet real Spike and BOOM output, a regex fix cannot silently
change what the loop considers a bug.
"""
import unittest

from chia_loop.diff import UNSTABLE_CSRS, compare, csr_of
from chia_loop.trace import parse_boom, parse_spike

SPIKE = """\
core   0: 3 0x0000000080000000 (0x00000297) x 5 0x0000000080000000
core   0: 3 0x0000000080000004 (0x00450513) x10 0x0000000080000004
core   0: 3 0x0000000080000008 (0x00028067)
"""

BOOM = """\
C0:        84 [1] pc=[0000000080000000] W[r 5=0000000080000000][1] R[r 0=0] inst=[00000297] DASM(00000297)
C0:        85 [1] pc=[0000000080000004] W[r10=0000000080000004][1] R[r10=0] inst=[00450513] DASM(00450513)
C0:        86 [1] pc=[0000000080000008] W[r 0=0000000000000000][0] R[r 5=0] inst=[00028067] DASM(00028067)
C0:        87 [0] pc=[00000000deadbeef] W[r 1=0000000000000000][0] R[r 0=0] inst=[00000013] DASM(00000013)
"""


class TestParsers(unittest.TestCase):
    def test_spike_fields(self):
        ev = parse_spike(SPIKE)
        self.assertEqual(len(ev), 3)
        self.assertEqual(ev[0].pc, 0x80000000)
        self.assertEqual(ev[0].insn, 0x00000297)
        self.assertEqual(ev[0].priv, 3)
        self.assertEqual([(w.file, w.index) for w in ev[0].writes], [("x", 5)])
        self.assertEqual(ev[2].writes, [])

    def test_boom_skips_invalid_commits(self):
        ev = parse_boom(BOOM)
        # The last line has the commit-valid bit clear and must not appear.
        self.assertEqual(len(ev), 3)
        self.assertEqual([e.pc for e in ev],
                         [0x80000000, 0x80000004, 0x80000008])

    def test_boom_ignores_disabled_write(self):
        ev = parse_boom(BOOM)
        self.assertEqual(ev[2].writes, [])   # write-enable is 0


class TestDiff(unittest.TestCase):
    def test_identical_streams_are_clean(self):
        res = compare(parse_spike(SPIKE), parse_boom(BOOM))
        self.assertTrue(res.clean, res.to_dict())
        self.assertEqual(res.matched, 3)

    def test_register_value_divergence(self):
        bad = BOOM.replace("W[r10=0000000080000004]", "W[r10=00000000deadbeef]")
        res = compare(parse_spike(SPIKE), parse_boom(bad))
        self.assertFalse(res.clean)
        self.assertEqual(res.divergence.kind, "REG_WRITE")
        self.assertEqual(res.divergence.index, 1)
        self.assertEqual(res.divergence.hint, "NEEDS_TRIAGE")

    def test_control_flow_divergence(self):
        bad = BOOM.replace("pc=[0000000080000008]", "pc=[0000000080000010]")
        res = compare(parse_spike(SPIKE), parse_boom(bad))
        self.assertFalse(res.clean)
        self.assertEqual(res.divergence.kind, "CONTROL_FLOW")

    def test_instruction_bits_divergence(self):
        bad = BOOM.replace("inst=[00450513]", "inst=[00450613]")
        res = compare(parse_spike(SPIKE), parse_boom(bad))
        self.assertFalse(res.clean)
        self.assertEqual(res.divergence.kind, "INSN_BITS")

    def test_x0_write_is_not_a_divergence(self):
        """Models disagree about reporting x0 writes; that is not a bug."""
        spike = SPIKE + "core   0: 3 0x000000008000000c (0x00000013) x 0 0x0\n"
        boom = BOOM.replace(
            "C0:        87 [0]",
            "C0:        87 [1] pc=[000000008000000c] W[r 0=0000000000000000][1] "
            "R[r 0=0] inst=[00000013] DASM(00000013)\nC0:        88 [0]")
        res = compare(parse_spike(spike), parse_boom(boom))
        self.assertTrue(res.clean, res.to_dict())

    def test_sync_pc_skips_boot_prefix(self):
        spike = ("core   0: 3 0x0000000000001000 (0x00000297) x 5 0x1000\n"
                 + SPIKE)
        res = compare(parse_spike(spike), parse_boom(BOOM),
                      start_pc=0x80000000)
        self.assertTrue(res.clean, res.to_dict())
        self.assertEqual(res.sync_index_ref, 1)
        self.assertEqual(res.sync_index_dut, 0)

    def test_missing_sync_pc_is_reported(self):
        res = compare(parse_spike(SPIKE), parse_boom(BOOM), start_pc=0xdead)
        self.assertFalse(res.clean)
        self.assertEqual(res.divergence.kind, "TRACE_END")

    def test_truncated_stream(self):
        short = "\n".join(BOOM.splitlines()[:2]) + "\n"
        res = compare(parse_spike(SPIKE), parse_boom(short))
        self.assertFalse(res.clean)
        self.assertEqual(res.divergence.kind, "TRACE_END")


class TestNondeterminismHint(unittest.TestCase):
    def test_csr_decode(self):
        # csrrs x10, cycle, x0  -> 0xC0002573
        self.assertEqual(csr_of(0xC0002573), 0xC00)
        self.assertIn(csr_of(0xC0002573), UNSTABLE_CSRS)
        self.assertIsNone(csr_of(0x00000013))   # addi is not a CSR op
        self.assertIsNone(csr_of(0x00000073))   # ecall is funct3==0

    def test_counter_read_is_flagged_legal(self):
        spike = "core   0: 3 0x0000000080000000 (0xc0002573) x10 0x0000000000000064\n"
        boom = ("C0: 84 [1] pc=[0000000080000000] W[r10=00000000000003e8][1] "
                "inst=[c0002573] DASM(c0002573)\n")
        res = compare(parse_spike(spike), parse_boom(boom))
        self.assertFalse(res.clean)
        self.assertEqual(res.divergence.kind, "REG_WRITE")
        self.assertEqual(res.divergence.hint, "LIKELY_LEGAL_NONDETERMINISM")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestHaltTruncation(unittest.TestCase):
    """Regression tests for the post-exit spin loop seen in real Spike output."""

    def test_spin_loop_is_dropped(self):
        from chia_loop.trace import truncate_at_halt
        body = SPIKE + "".join(
            "core   0: 3 0x0000000080000022 (0xa001)\n" for _ in range(50))
        ev = truncate_at_halt(parse_spike(body))
        self.assertEqual(len(ev), 3)
        self.assertEqual(ev[-1].pc, 0x80000008)

    def test_working_loop_is_kept(self):
        """A real loop writes registers, so it must survive truncation."""
        from chia_loop.trace import truncate_at_halt
        body = "".join(
            f"core   0: 3 0x0000000080000010 (0xfff58593) x11 0x{i:016x}\n"
            for i in range(20))
        ev = truncate_at_halt(parse_spike(body))
        self.assertEqual(len(ev), 20)

    def test_short_trace_unchanged(self):
        from chia_loop.trace import truncate_at_halt
        ev = parse_spike(SPIKE)
        self.assertEqual(len(truncate_at_halt(ev)), 3)


class TestTrapLogArtifact(unittest.TestCase):
    """BOOM retires a trapping ECALL/EBREAK; Spike reports only the handler."""

    ORACLE = ("core   0: 3 0x0000000080000010 (0x0000854a) x10 0x0000000000000002\n"
              "core   0: 3 0x0000000080000050 (0x34202973) x18 0x000000000000000b\n")
    IMPL = ("3 0x0000000080000010 (0x0000854a) x10 0x0000000000000002\n"
            "3 0x0000000080000012 (0x00000073)\n"
            "3 0x0000000080000050 (0x34202973) x18 0x000000000000000b\n")

    def test_elided_by_default_and_recorded(self):
        res = compare(parse_spike(self.ORACLE), parse_spike(self.IMPL))
        self.assertTrue(res.clean, res.to_dict())
        self.assertEqual(len(res.trap_artifacts), 1)
        self.assertIn("0x0000000080000012", res.trap_artifacts[0])

    def test_can_be_disabled(self):
        res = compare(parse_spike(self.ORACLE), parse_spike(self.IMPL),
                      elide_trap_markers=False)
        self.assertFalse(res.clean)
        self.assertEqual(res.divergence.kind, "CONTROL_FLOW")

    def test_does_not_elide_a_writing_instruction(self):
        """Only a no-write trapping instruction is an artifact."""
        impl = self.IMPL.replace("3 0x0000000080000012 (0x00000073)\n",
                                 "3 0x0000000080000012 (0x00000073) x11 0x99\n")
        res = compare(parse_spike(self.ORACLE), parse_spike(impl))
        self.assertFalse(res.clean)

    def test_does_not_elide_a_non_trapping_instruction(self):
        """An extra no-write instruction that is not ECALL/EBREAK is real."""
        impl = self.IMPL.replace("(0x00000073)", "(0x00000013)")
        res = compare(parse_spike(self.ORACLE), parse_spike(impl))
        self.assertFalse(res.clean)


class TestCompressedEbreak(unittest.TestCase):
    """C.EBREAK (0x9002) is the same artifact as ECALL and must also elide."""

    def test_compressed_ebreak_elided(self):
        oracle = ("core 0: 3 0x0000000080000016 (0x000085ca) x11 0x0000000b\n"
                  "core 0: 3 0x0000000080000050 (0x34202973) x18 0x00000003\n")
        impl = ("3 0x0000000080000016 (0x000085ca) x11 0x0000000b\n"
                "3 0x0000000080000018 (0x00009002)\n"
                "3 0x0000000080000050 (0x34202973) x18 0x00000003\n")
        res = compare(parse_spike(oracle), parse_spike(impl))
        self.assertTrue(res.clean, res.to_dict())
        self.assertEqual(len(res.trap_artifacts), 1)
