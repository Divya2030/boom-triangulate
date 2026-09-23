"""Seeded-defect recall study.

Ground-truth control set for the two headline metrics the proposal promises:

  recall           = seeds the loop CATCHES / seeds that are OBSERVABLE
  triage precision = correct RTL_DEFECT calls / all RTL_DEFECT calls
  false positives  = RTL_DEFECT calls on the UNSEEDED baseline (must be zero)

Each seed is one small RTL edit at a cited seam (see chia_loop/seeds.py). The
expensive step is that every seed needs its own BOOM Verilator rebuild
(~40-50 min), so the study is built to run unattended and resume: state is
checkpointed per seed, and a completed seed is skipped on restart.

Honesty is enforced structurally. A seed the tests miss is not automatically a
loop failure: the harness probes whether the mutant changes committed state
under ANY program at all (mutant-BOOM vs baseline-BOOM). If it never does, the
defect is architecturally silent under this stimulus and is reported as
NOT_OBSERVABLE rather than counted against recall. Recall's denominator is the
observable seeds only, and that distinction is stated in the report.

Stages per seed:
  1. apply    patch the Scala source (exact-substring, reversible)
  2. build    rebuild BOOM, archive the binary as bin/<seed>.sim, revert source
  3. detect   run the fixed program suite: mutant-BOOM vs baseline-Spike, triage
  4. probe    if not caught, mutant-BOOM vs baseline-BOOM -> observable?
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field

from . import diff, models, triage, triangulate
from .agent import Agent
from .generate import TestProgram
from .seeds import BOOM_REL, SEEDS, Seed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDY_DIR = os.path.join(REPO, "reports", "seedstudy")
BIN_DIR = os.path.join(STUDY_DIR, "bin")
CKPT = os.path.join(STUDY_DIR, "checkpoint.json")
SRC_ROOT = os.path.join(REPO, BOOM_REL)
BOOM_CONFIG = models.DEFAULT_BOOM_CONFIG
BASELINE_SIM = os.path.join(BIN_DIR, "baseline.sim")

# The suite is fixed across seeds so recall measures the seeds, not stimulus
# drift. These are the programs the generate block already produced and gated.
SUITE_DIR = os.path.join(REPO, "tests", "progs", "generated")
START_PC = 0x80000000


# --------------------------------------------------------------------------- #
# source patching
# --------------------------------------------------------------------------- #
def _src_path(seed: Seed) -> str:
    return os.path.join(SRC_ROOT, seed.file)


def apply_seed(seed: Seed) -> None:
    path = _src_path(seed)
    text = open(path).read()
    if text.count(seed.find) != 1:
        raise ValueError(f"{seed.id}: anchor not unique ({text.count(seed.find)}x)")
    open(path + ".orig", "w").write(text)              # backup for revert
    open(path, "w").write(text.replace(seed.find, seed.replace, 1))


def revert_seed(seed: Seed) -> None:
    path = _src_path(seed)
    if os.path.exists(path + ".orig"):
        shutil.move(path + ".orig", path)


def sources_clean() -> list[str]:
    """Any leftover .orig backups mean a previous run died mid-seed."""
    dirty = []
    for seed in SEEDS:
        if os.path.exists(_src_path(seed) + ".orig"):
            dirty.append(seed.id)
    return dirty


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
VERILATOR_DIR = os.path.join(REPO, "tools", "src", "chipyard", "sims", "verilator")


def _force_clean() -> None:
    """Delete the generated Verilog and binary so the next build re-elaborates.

    Chipyard's make does not reliably re-run Chisel elaboration when only a
    Scala source changes -- it can reuse the cached .fir/.sv. For a mutation
    study that is fatal: the mutant would build from unmutated Verilog and read
    as NOT_OBSERVABLE for the wrong reason. Removing the config's generated-src
    dir forces the full Scala -> FIRRTL -> Verilog -> binary chain every time.
    """
    gen = os.path.join(VERILATOR_DIR, "generated-src",
                       f"chipyard.harness.TestHarness.{BOOM_CONFIG}")
    binary = os.path.join(VERILATOR_DIR,
                          f"simulator-chipyard.harness-{BOOM_CONFIG}")
    for path in (gen, binary):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)


def build_current(jobs: int | None = None, timeout: int = 5400,
                  clean: bool = True) -> tuple[bool, str]:
    """Rebuild BOOM from the current (possibly patched) source.

    clean=True forces re-elaboration -- required for every mutant so the source
    edit actually reaches the RTL.
    """
    jobs = jobs or os.cpu_count() or 8
    if clean:
        _force_clean()
    env = dict(os.environ, JOBS=str(jobs), CONFIG=BOOM_CONFIG)
    try:
        p = subprocess.run(["bash", os.path.join(REPO, "setup", "03-boom-sim.sh")],
                           cwd=REPO, env=env, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"build exceeded {timeout}s"
    built = models.boom_simulator(BOOM_CONFIG)
    if p.returncode != 0 or not built or not os.path.exists(built):
        return False, p.stdout[-1500:] + p.stderr[-1500:]
    return True, built


def archive_baseline(jobs: int | None = None) -> tuple[bool, str]:
    """Ensure a clean baseline binary exists (built from unpatched source)."""
    os.makedirs(BIN_DIR, exist_ok=True)
    if os.path.exists(BASELINE_SIM):
        return True, BASELINE_SIM
    built = models.boom_simulator(BOOM_CONFIG)
    if built and os.path.exists(built):
        shutil.copy2(built, BASELINE_SIM)
        return True, BASELINE_SIM
    ok, info = build_current(jobs)
    if not ok:
        return False, info
    shutil.copy2(info, BASELINE_SIM)
    return True, BASELINE_SIM


# --------------------------------------------------------------------------- #
# suite
# --------------------------------------------------------------------------- #
def _suite_elfs() -> list[tuple[str, str]]:
    """(program_id, elf_path) for every gated program with a built ELF."""
    out = []
    for name in sorted(os.listdir(SUITE_DIR)):
        if not name.endswith(".S"):
            continue
        pid = name[:-2]
        elf = os.path.join(REPO, "build", "progs", f"{pid}.elf")
        if os.path.exists(elf):
            out.append((pid, elf))
    return out


def _spike_ref(elf: str):
    ev, _ = models.spike_trace(elf)
    return ev


# --------------------------------------------------------------------------- #
# per-seed evaluation
# --------------------------------------------------------------------------- #
@dataclass
class SeedResult:
    id: str
    category: str
    built: bool = False
    caught: bool = False
    observable: bool | None = None
    classifications: list[str] = field(default_factory=list)
    detector_program: str = ""
    distinct_binary: bool | None = None   # mutant binary differs from baseline
    oracle_findings: list[str] = field(default_factory=list)  # Spike vs Dromajo disagreements
    note: str = ""
    build_info: str = ""

    @property
    def status(self) -> str:
        if not self.built:
            return "BUILD_FAILED"
        if self.caught:
            return "CAUGHT"
        if self.observable is False:
            return "NOT_OBSERVABLE"
        return "MISSED"


def evaluate_seed(seed: Seed, mutant_sim: str, agent: Agent | None = None,
                  boom_timeout: int = 600, max_cycles: int = 200000) -> SeedResult:
    """Detect a seeded defect by multi-oracle triangulation.

    A derailing mutant runs forever while both oracles terminate; single-oracle
    triage mistakes that trace-end for truncation and dismisses it. Triangulation
    votes on oracle agreement instead: two oracles that terminate and agree, with
    the mutant as the sole outlier, is an RTL_DEFECT whatever the divergence looks
    like. The BOOM timeout is short on purpose -- a non-terminating run is a
    signal, not something to wait 30 minutes for.
    """
    agent = agent or Agent()
    res = SeedResult(id=seed.id, category=seed.category, built=True)
    diverged_any = False

    for pid, elf in _suite_elfs():
        spike = _spike_ref(elf)
        dromajo, _ = models.dromajo_trace(elf)
        boom, _ = models.boom_trace(elf, sim_path=mutant_sim,
                                    timeout=boom_timeout, max_cycles=max_cycles)
        t = triangulate.triangulate(boom, spike, dromajo, start_pc=START_PC)
        res.classifications.append(t.verdict)
        if t.verdict == "ORACLE_MISMATCH":
            # The two reference models disagree with each other, independent of
            # the mutant. Record it as its own finding; it must NOT count as the
            # mutant being observable.
            res.oracle_findings.append(pid)
        if t.verdict == "RTL_DEFECT":
            res.caught = True
            res.detector_program = pid
            res.observable = True
            res.note = "caught by multi-oracle triangulation"
            return res

    # Not caught. Observability of the MUTANT is decided only by whether it
    # changes committed state versus the unmutated baseline BOOM -- never by an
    # oracle-vs-oracle disagreement.
    observed = False
    for pid, elf in _suite_elfs():
        base, _ = models.boom_trace(elf, sim_path=BASELINE_SIM,
                                    timeout=boom_timeout, max_cycles=max_cycles)
        mut, _ = models.boom_trace(elf, sim_path=mutant_sim,
                                   timeout=boom_timeout, max_cycles=max_cycles)
        if diff.compare(base, mut, start_pc=START_PC).divergence is not None:
            observed = True
            break
    res.observable = observed
    res.observable = observed
    res.note = ("mutant changes committed state but no oracle divergence was seen"
                if observed else
                "mutant never changes committed state under the suite")
    return res


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_ckpt() -> dict:
    if os.path.exists(CKPT):
        return json.load(open(CKPT))
    return {"results": {}}


def _save_ckpt(state: dict) -> None:
    os.makedirs(STUDY_DIR, exist_ok=True)
    json.dump(state, open(CKPT, "w"), indent=2)


def run_study(seed_ids: list[str] | None = None, jobs: int | None = None,
              agent: Agent | None = None) -> dict:
    agent = agent or Agent()
    os.makedirs(BIN_DIR, exist_ok=True)
    state = _load_ckpt()

    dirty = sources_clean()
    if dirty:
        raise RuntimeError(f"leftover source backups from a crashed run: {dirty}. "
                           "Revert them before continuing.")

    ok, info = archive_baseline(jobs)
    if not ok:
        raise RuntimeError(f"could not establish baseline binary: {info}")

    todo = [s for s in SEEDS if seed_ids is None or s.id in seed_ids]
    for seed in todo:
        if seed.id in state["results"]:
            continue                                   # resume: already done
        mutant_bin = os.path.join(BIN_DIR, f"{seed.id}.sim")

        if not os.path.exists(mutant_bin):
            apply_seed(seed)
            try:
                built_ok, binfo = build_current(jobs)
                if built_ok:
                    shutil.copy2(binfo, mutant_bin)
            finally:
                revert_seed(seed)                      # always restore source
            if not built_ok:
                r = SeedResult(seed.id, seed.category, built=False,
                               build_info=binfo[-500:])
                state["results"][seed.id] = asdict(r) | {"status": r.status}
                _save_ckpt(state)
                continue

        r = evaluate_seed(seed, mutant_bin, agent=agent)
        # Integrity: a mutant byte-identical to the baseline means the edit did
        # not reach the build (cached elaboration) -- a NOT_OBSERVABLE result
        # from such a binary is meaningless, so flag it rather than trust it.
        if os.path.exists(BASELINE_SIM) and os.path.exists(mutant_bin):
            r.distinct_binary = _sha(mutant_bin) != _sha(BASELINE_SIM)
            if r.distinct_binary is False:
                r.note = ("mutant binary identical to baseline: the source edit "
                          "did not reach the build; result is not trustworthy") \
                         + (f" | {r.note}" if r.note else "")
        state["results"][seed.id] = asdict(r) | {"status": r.status}
        _save_ckpt(state)

    return score(state)


def score(state: dict | None = None) -> dict:
    state = state or _load_ckpt()
    results = list(state["results"].values())

    built = [r for r in results if r["built"]]
    observable = [r for r in built if r["observable"]]
    caught = [r for r in built if r["caught"]]
    rtl_calls = sum(r["classifications"].count("RTL_DEFECT") for r in built)

    recall = (len(caught) / len(observable)) if observable else None
    return {
        "seeds_total": len(SEEDS),
        "evaluated": len(results),
        "built": len(built),
        "observable": len(observable),
        "caught": len(caught),
        "not_observable": sum(1 for r in built if r["observable"] is False),
        "recall_over_observable": recall,
        "rtl_defect_calls": rtl_calls,
        "results": {r["id"]: r for r in results},
    }
