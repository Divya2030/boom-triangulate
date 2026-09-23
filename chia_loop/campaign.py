"""Orchestration: wire the blocks into the loop described in the proposal.

    golden check -> mutation campaign -> survivor triage -> report

Mutant evaluation is embarrassingly parallel, which is the part that makes the
campaign compute-bound and worth running on a fleet rather than a laptop.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import mutate, report, simrun
from .agent import Agent

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, "build")
MUTANT_DIR = os.path.join(BUILD, "mutants")

DEFAULT_SEEDS = [1, 7, 42, 99, 1234]


def golden_check(seeds: list[int] | None = None, cycles: int = 3000) -> dict:
    """Precondition: the property set must pass on the unmutated design.

    A campaign run against a property set that already fails is meaningless, so
    this gates everything downstream.
    """
    seeds = seeds or DEFAULT_SEEDS
    workdir = os.path.join(BUILD, "golden")
    os.makedirs(workdir, exist_ok=True)
    v = simrun.check_rtl(simrun.GOLDEN_RTL, workdir, seeds, cycles,
                         stop_on_fail=False)
    return {
        "compiled": v.compiled,
        "passed": v.passed,
        "seeds": v.seeds_run,
        "seeds_failed": v.seeds_failed,
        "cycles_total": v.cycles,
        "failing_props": dict(v.failing_props),
        "note": v.log if not v.compiled else "",
    }


def _score_one(pair, seeds, cycles) -> dict:
    mut, text = pair
    path = os.path.join(MUTANT_DIR, f"{mut.ident}.v")
    with open(path, "w") as fh:
        fh.write(text)

    workdir = os.path.join(MUTANT_DIR, mut.ident)
    os.makedirs(workdir, exist_ok=True)
    v = simrun.check_rtl(path, workdir, seeds, cycles, stop_on_fail=True)

    if not v.compiled:
        verdict = "UNCOMPILABLE"
    elif v.killed:
        verdict = "KILLED"
    else:
        verdict = "SURVIVED"

    return {
        "id": mut.ident,
        "op": mut.op,
        "line": mut.line,
        "col": mut.col,
        "replacement": f"{mut.old!r} -> {mut.new!r}",
        "verdict": verdict,
        "failing_props": dict(v.failing_props),
        "first_fail_cycle": v.first_fail_cycle,
        "seeds_failed": v.seeds_failed,
        "path": os.path.relpath(path, REPO),
    }


def run_campaign(limit: int | None = None, seeds: list[int] | None = None,
                 cycles: int = 2000, jobs: int | None = None,
                 triage: bool = False, ops: list[str] | None = None) -> dict:
    seeds = seeds or DEFAULT_SEEDS
    jobs = jobs or min(8, (os.cpu_count() or 2))
    os.makedirs(MUTANT_DIR, exist_ok=True)

    src = open(simrun.GOLDEN_RTL).read()
    src_lines = src.splitlines()
    pairs = mutate.generate(src, limit=limit, seed=1, ops=ops)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(_score_one, p, seeds, cycles): p for p in pairs}
        for fut in as_completed(futures):
            results.append(fut.result())

    for r in results:
        r["source"] = src_lines[r["line"] - 1].strip()
    results.sort(key=lambda r: (r["line"], r["col"], r["op"]))

    killed = sum(1 for r in results if r["verdict"] == "KILLED")
    survived = sum(1 for r in results if r["verdict"] == "SURVIVED")
    uncompilable = sum(1 for r in results if r["verdict"] == "UNCOMPILABLE")
    scored = killed + survived

    record = {
        "generated": report.stamp(),
        "config": {"seeds": seeds, "cycles": cycles, "jobs": jobs,
                   "limit": limit, "ops": ops or "all"},
        "summary": {
            "total_mutants": len(results),
            "scored": scored,
            "killed": killed,
            "survived": survived,
            "uncompilable": uncompilable,
            "kill_rate_pct": (100.0 * killed / scored) if scored else 0.0,
        },
        "mutants": results,
    }

    if triage:
        agent = Agent()
        record["triage_provenance"] = agent.provenance
        for r in results:
            if r["verdict"] == "SURVIVED":
                r["triage"] = agent.triage_survivor(r, src).to_dict()

    return record
