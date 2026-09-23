"""Catalog of seeded defects for the recall study.

Each seed is a small, precisely located edit to BOOM's Scala RTL at one of the
seams the hypothesize block cites. Seeds are the ground-truth control set: we
know each one is a defect, so the loop's ability to catch it is a recall number,
and any RTL_DEFECT the loop reports on an unseeded baseline is a false positive.

Seeds are anchored by an exact substring rather than a line number, so the
catalog survives edits to the file above the seam and a mismatch is caught at
validation time instead of silently patching the wrong line. `find` must occur
exactly once in `file`; `seedstudy --dry-run` enforces that.

Observability is not assumed. A single-core, bare-metal comparison cannot
observe every microarchitectural defect in committed state; the harness probes
each missed seed to separate "our tests did not catch it" from "no test could,
because the mutant never changes committed state." Both are honest outcomes and
are reported distinctly.
"""
from __future__ import annotations

from dataclasses import dataclass

BOOM_REL = "tools/src/chipyard/generators/boom/src/main/scala/v3"


@dataclass(frozen=True)
class Seed:
    id: str
    file: str            # relative to BOOM_REL
    find: str            # exact substring, must be unique in the file
    replace: str
    category: str
    note: str            # what the defect breaks, in one line


SEEDS: list[Seed] = [
    Seed(
        id="ORDER_FAIL_SUPPRESSED",
        file="lsu/lsu.scala",
        find="            ldq(i).bits.order_fail := true.B",
        replace="            ldq(i).bits.order_fail := false.B",
        category="MEMORY_ORDERING",
        note="memory-ordering failure never raised: an out-of-order load that "
             "should replay is allowed to commit stale data (RVWMO violation).",
    ),
    Seed(
        id="FENCEI_EARLY",
        file="lsu/lsu.scala",
        find="io.core.fencei_rdy    := !stq_nonempty && io.dmem.ordered",
        replace="io.core.fencei_rdy    := io.dmem.ordered",
        category="MEMORY_ORDERING",
        note="FENCE.I reports ready before the store queue drains: a store to "
             "the instruction stream may not be visible to the refetch.",
    ),
    Seed(
        id="FORWARD_STD_VAL_STUCK",
        file="lsu/lsu.scala",
        find="ldq(f_idx).bits.forward_std_val := true.B",
        replace="ldq(f_idx).bits.forward_std_val := false.B",
        category="MEMORY_ORDERING",
        note="store-to-load forwarding validity dropped: a load that should "
             "forward from an older store instead reads memory.",
    ),
    Seed(
        id="BYPASS_RS1_DISABLED",
        file="exu/register-read/register-read.scala",
        find="&& lrs1_rtype === RT_FIX && (prs1 =/= 0.U)",
        replace="&& lrs1_rtype =/= RT_FIX && (prs1 =/= 0.U)",
        category="BYPASS_FORWARD",
        note="integer rs1 operand never bypasses: a dependent instruction reads "
             "the register file before the producer has written it, committing a "
             "stale rs1 value. Directly observable in a dependent arithmetic chain.",
    ),
    Seed(
        id="BYPASS_RS2_DISABLED",
        file="exu/register-read/register-read.scala",
        find="&& lrs2_rtype === RT_FIX && (prs2 =/= 0.U)",
        replace="&& lrs2_rtype =/= RT_FIX && (prs2 =/= 0.U)",
        category="BYPASS_FORWARD",
        note="integer rs2 operand never bypasses: same defect on the rs2 path, "
             "committing a stale rs2 value in a back-to-back dependent chain.",
    ),
    Seed(
        id="MOV_WRONG_OPERAND",
        file="exu/execution-units/functional-unit.scala",
        find="Mux(io.req.bits.uop.uopc === uopMOV, io.req.bits.rs2_data, alu.io.out))",
        replace="Mux(io.req.bits.uop.uopc === uopMOV, io.req.bits.rs1_data, alu.io.out))",
        category="BYPASS_FORWARD",
        note="register-move micro-op forwards rs1 instead of rs2: a MOV commits "
             "the wrong source operand. Observable when a MOV is issued, though "
             "MOV uops are less common than plain arithmetic.",
    ),
    Seed(
        id="BYPASS_RS1_MATCH_WRONG",
        file="exu/register-read/register-read.scala",
        find="(prs1 === bypass.bits.uop.pdst)",
        replace="(prs2 === bypass.bits.uop.pdst)",
        category="BYPASS_FORWARD",
        note="rs1 bypass matches on the rs2 tag: a dependent instruction forwards "
             "the wrong producer's value into rs1.",
    ),
    Seed(
        id="BYPASS_RS2_MATCH_WRONG",
        file="exu/register-read/register-read.scala",
        find="(prs2 === bypass.bits.uop.pdst)",
        replace="(prs1 === bypass.bits.uop.pdst)",
        category="BYPASS_FORWARD",
        note="rs2 bypass matches on the rs1 tag: the wrong producer's value is "
             "forwarded into rs2.",
    ),
    Seed(
        id="BYPASS_RS1_ZERO_GUARD",
        file="exu/register-read/register-read.scala",
        find="lrs1_rtype === RT_FIX && (prs1 =/= 0.U)",
        replace="lrs1_rtype === RT_FIX && (prs1 === 0.U)",
        category="BYPASS_FORWARD",
        note="rs1 bypass fires only for physical register 0, so real dependent "
             "reads never forward and commit a stale rs1.",
    ),
    Seed(
        id="BYPASS_RS2_ZERO_GUARD",
        file="exu/register-read/register-read.scala",
        find="lrs2_rtype === RT_FIX && (prs2 =/= 0.U)",
        replace="lrs2_rtype === RT_FIX && (prs2 === 0.U)",
        category="BYPASS_FORWARD",
        note="same zero-guard flip on the rs2 path, committing a stale rs2.",
    ),
    Seed(
        id="FWD_IRESP_EARLY",
        file="lsu/lsu.scala",
        find="(forward_uop.dst_rtype === RT_FIX) && data_ready && live",
        replace="(forward_uop.dst_rtype === RT_FIX) && true.B && live",
        category="MEMORY_ORDERING",
        note="load result marked valid before the forwarded data is ready, so a "
             "load can commit stale bytes.",
    ),
]
