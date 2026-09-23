"""Commit-trace normalisation for multi-model comparison.

Each model emits a different trace format, so nothing downstream should ever see
a raw log line. Every source is normalised into a `CommitEvent` stream carrying
only *committed architectural state*: the PC, the instruction bits, the
privilege level, and the architectural register writes. Cycle counts, issue
order, speculative activity and microarchitectural signals are dropped here, on
purpose -- they are exactly the differences that are legal between a functional
oracle and an out-of-order implementation, and keeping them is how a comparison
loop drowns in false positives.

FORMAT CAVEAT: the two parsers below are written against the documented trace
formats and are validated by `tests/test_trace.py` against synthetic lines. They
have NOT yet been run against real Spike or BOOM output -- the toolchain is
still building. Expect to adjust the regexes on first contact; that is why the
parsers are isolated from the diff engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegWrite:
    file: str          # "x" integer, "f" float, "c" CSR
    index: int
    value: int

    def __str__(self) -> str:
        return f"{self.file}{self.index}=0x{self.value:016x}"


@dataclass
class CommitEvent:
    """One committed instruction, as both models agree to describe it."""

    pc: int
    insn: int
    priv: int | None = None
    writes: list[RegWrite] = field(default_factory=list)
    source_line: str = ""

    def arch_key(self) -> tuple:
        """The tuple the differ compares.

        x0 writes are dropped: writing the zero register is architecturally a
        no-op, and the two models disagree on whether to report it.
        """
        writes = tuple(sorted(
            (w.file, w.index, w.value)
            for w in self.writes
            if not (w.file == "x" and w.index == 0)
        ))
        return (self.pc, self.insn, writes)

    def describe(self) -> str:
        w = " ".join(str(x) for x in self.writes) or "-"
        return f"pc=0x{self.pc:016x} insn=0x{self.insn:08x} writes={w}"


# --- Spike-format commit log ------------------------------------------------
# Both models emit this. Spike (`--log-commits`) prefixes each line with the
# hart; BOOM (WithBoomCommitLogPrintf) omits the prefix but is otherwise
# identical -- BOOM's source calls it a dump "for comparison against ISA sim",
# and it is. Verified on the same program:
#
#   spike:  core   0: 3 0x0000000080000004 (0x006283b3) x7  0x0000000000000003
#   boom:            3 0x0000000080000004 (0x006283b3) x 7 0x0000000000000003
#
# So one parser serves both and the hart prefix is optional. Register-name
# spacing also differs between them ("x7  " vs "x 7 "), which the write pattern
# below absorbs.
SPIKE_RE = re.compile(
    r"^(?:core\s+(?P<hart>\d+):\s+)?(?P<priv>\d)\s+"
    r"0x(?P<pc>[0-9a-fA-F]+)\s+\((?P<insn>0x[0-9a-fA-F]+)\)(?P<tail>.*)$"
)
SPIKE_WRITE_RE = re.compile(
    r"\b(?P<file>[xfc])\s*(?P<idx>\d+)\s+0x(?P<val>[0-9a-fA-F]+)"
)


def parse_commit_log(text: str, hart: int = 0) -> list[CommitEvent]:
    """Parse a Spike-format commit log from either model.

    Lines without a hart prefix are attributed to hart 0, which is what BOOM's
    single-core commit log emits.
    """
    events: list[CommitEvent] = []
    for line in text.splitlines():
        m = SPIKE_RE.match(line.strip())
        if not m:
            continue
        if m.group("hart") is not None and int(m.group("hart")) != hart:
            continue
        writes = [
            RegWrite(w.group("file"), int(w.group("idx")), int(w.group("val"), 16))
            for w in SPIKE_WRITE_RE.finditer(m.group("tail"))
        ]
        events.append(CommitEvent(
            pc=int(m.group("pc"), 16),
            insn=int(m.group("insn"), 16),
            priv=int(m.group("priv")),
            writes=writes,
            source_line=line.rstrip(),
        ))
    return events


# --- BOOM / Rocket Chip tracer ---------------------------------------------
# The Chipyard Verilator harness emits, per core, per cycle:
#   C0:  84 [1] pc=[00000000800001f4] W[r 5=00000000800001f4][1] ... inst=[00000297]
# The `[1]` after the cycle count is the commit-valid bit; the `[1]` after the
# write value is the write-enable. Both must be set for the event to count.
BOOM_RE = re.compile(
    r"^C(?P<hart>\d+):\s+(?P<cycle>\d+)\s+\[(?P<valid>\d)\]\s+"
    r"pc=\[(?P<pc>[0-9a-fA-F]+)\]\s+"
    r"W\[r\s*(?P<wreg>\d+)=(?P<wval>[0-9a-fA-F]+)\]\[(?P<wen>\d)\]"
    r".*?inst=\[(?P<insn>[0-9a-fA-F]+)\]"
)


def parse_boom(text: str, hart: int = 0) -> list[CommitEvent]:
    events: list[CommitEvent] = []
    for line in text.splitlines():
        m = BOOM_RE.match(line.strip())
        if not m or int(m.group("hart")) != hart:
            continue
        if m.group("valid") != "1":
            continue                      # not a committed instruction
        writes = []
        if m.group("wen") == "1":
            writes.append(RegWrite("x", int(m.group("wreg")),
                                   int(m.group("wval"), 16)))
        events.append(CommitEvent(
            pc=int(m.group("pc"), 16),
            insn=int(m.group("insn"), 16),
            writes=writes,
            source_line=line.rstrip(),
        ))
    return events


def truncate_at_halt(events: list[CommitEvent],
                     repeat: int = 4) -> list[CommitEvent]:
    """Drop the trailing halt loop.

    Test programs signal completion by writing tohost and then spinning on
    `1: j 1b`. Spike only polls HTIF every 5000 instructions, so it retires
    thousands of spin iterations before noticing -- on the smoke test, 4985 of
    5000 committed instructions, 99.7% of the trace. BOOM will do the same.
    Comparing that tail costs simulation time and diff time and can never find
    a bug, so it is cut here.

    The signature is a self-loop: the same PC repeated with no architectural
    writes. Requiring zero writes is what keeps this from truncating a
    legitimate tight loop, which necessarily updates something.
    """
    if len(events) < repeat:
        return events
    run_pc, run_start = None, 0
    for i, ev in enumerate(events):
        if ev.pc == run_pc and not ev.writes:
            if i - run_start + 1 >= repeat:
                return events[:run_start]
        else:
            run_pc, run_start = ev.pc, i
            if ev.writes:
                run_pc = None       # a writing instruction cannot start a halt
    return events


# --- Dromajo (Esperanto reference model) --------------------------------------
# `dromajo --trace 0` emits, per retired instruction:
#   0 3 0x0000000080000004 (0x006283b3) x 7 0x0000000000000003
# i.e. <hartid> <priv> 0x<pc> (0x<insn>) <writes>, plus separate
# "csr_read:/csr_write:" lines. Values match Spike's exactly on the same
# program, so it is a genuine independent oracle rather than a reskin.
DROMAJO_RE = re.compile(
    r"^(?P<hart>\d+)\s+(?P<priv>\d)\s+"
    r"0x(?P<pc>[0-9a-fA-F]+)\s+\((?P<insn>0x[0-9a-fA-F]+)\)(?P<tail>.*)$"
)


def parse_dromajo(text: str, hart: int = 0) -> list[CommitEvent]:
    events: list[CommitEvent] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("csr_read:") or line.startswith("csr_write:"):
            continue
        m = DROMAJO_RE.match(line)
        if not m or int(m.group("hart")) != hart:
            continue
        writes = [
            RegWrite(w.group("file"), int(w.group("idx")), int(w.group("val"), 16))
            for w in SPIKE_WRITE_RE.finditer(m.group("tail"))
        ]
        events.append(CommitEvent(pc=int(m.group("pc"), 16),
                                  insn=int(m.group("insn"), 16),
                                  priv=int(m.group("priv")), writes=writes,
                                  source_line=line))
    return events


# Spike's own output is a commit log, so this is just the general parser.
parse_spike = parse_commit_log

PARSERS = {
    "spike": parse_commit_log,
    "commit_log": parse_commit_log,
    "dromajo": parse_dromajo,
    "boom": parse_boom,          # the TracerV port format, a different source
}


def parse(source: str, text: str, hart: int = 0) -> list[CommitEvent]:
    if source not in PARSERS:
        raise ValueError(f"unknown trace source {source!r}; "
                         f"expected one of {sorted(PARSERS)}")
    return PARSERS[source](text, hart=hart)
