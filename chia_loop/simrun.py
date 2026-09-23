"""Dynamic execution block: compile and run the property set under Icarus.

Parses the testbench's machine-readable verdict lines into a structured result
so downstream blocks (mutation scoring, triage) never scrape raw logs.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field

from .tools import RunResult, have, run

ASSERT_RE = re.compile(r"ASSERT_FAIL prop=(\S+) cycle=(\d+)")
SUMMARY_RE = re.compile(r"SUMMARY cycles=(\d+) fails=(\d+)")
RESULT_RE = re.compile(r"RESULT (PASS|FAIL)")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "verif", "tb_freelist.v")
INCDIR = os.path.join(REPO, "verif")
GOLDEN_RTL = os.path.join(REPO, "rtl", "freelist.v")


@dataclass
class SimVerdict:
    """Outcome of running the property set against one RTL variant."""

    compiled: bool = True
    passed: bool = False
    cycles: int = 0
    failing_props: Counter = field(default_factory=Counter)
    first_fail_cycle: int | None = None
    seeds_run: list[int] = field(default_factory=list)
    seeds_failed: list[int] = field(default_factory=list)
    log: str = ""

    @property
    def killed(self) -> bool:
        """True when at least one property fired -- i.e. the bug was detected."""
        return self.compiled and not self.passed


def compile_rtl(rtl_path: str, out_vvp: str, timeout: int = 120) -> RunResult:
    os.makedirs(os.path.dirname(out_vvp), exist_ok=True)
    return run(
        ["iverilog", "-g2012", "-I", INCDIR, "-o", out_vvp, rtl_path, TB],
        timeout=timeout,
    )


def run_one(vvp: str, seed: int, cycles: int, maxfail: int = 5,
            timeout: int = 120) -> RunResult:
    return run(
        ["vvp", vvp, f"+seed={seed}", f"+cycles={cycles}", f"+maxfail={maxfail}"],
        timeout=timeout,
    )


def check_rtl(rtl_path: str, workdir: str, seeds: list[int],
              cycles: int = 2000, stop_on_fail: bool = True) -> SimVerdict:
    """Run the property set against one RTL variant across several seeds.

    stop_on_fail short-circuits as soon as a seed detects the bug, which is what
    mutation scoring wants: one detection is enough to call a mutant killed.
    """
    if not have("iverilog") or not have("vvp"):
        return SimVerdict(compiled=False, log="iverilog/vvp not installed")

    name = os.path.splitext(os.path.basename(rtl_path))[0]
    vvp = os.path.join(workdir, f"{name}.vvp")

    build = compile_rtl(rtl_path, vvp)
    if not build.ok:
        return SimVerdict(compiled=False, log=build.output[-4000:])

    verdict = SimVerdict(compiled=True, passed=True)
    logs: list[str] = []

    for seed in seeds:
        res = run_one(vvp, seed, cycles)
        verdict.seeds_run.append(seed)
        logs.append(res.output)

        for prop, cyc in ASSERT_RE.findall(res.output):
            verdict.failing_props[prop] += 1
            cyc_i = int(cyc)
            if verdict.first_fail_cycle is None or cyc_i < verdict.first_fail_cycle:
                verdict.first_fail_cycle = cyc_i

        m = SUMMARY_RE.search(res.output)
        if m:
            verdict.cycles += int(m.group(1))

        r = RESULT_RE.search(res.output)
        seed_failed = (r is None) or (r.group(1) == "FAIL") or not res.ok
        if seed_failed:
            verdict.passed = False
            verdict.seeds_failed.append(seed)
            if stop_on_fail:
                break

    verdict.log = "\n".join(logs)[-8000:]
    return verdict
