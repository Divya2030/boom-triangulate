"""Proof-execution block.

Two backends:

  yosys (default) -- drives yosys directly and proves with its built-in SAT
    engine: bounded model checking via `sat -seq`, unbounded proof via
    `sat -tempinduct`. Needs no external SMT solver, which is why it is the
    backend that actually runs here.
  sby             -- SymbiYosys, for machines with a full solver stack
    (yices/boolector/z3). Config lives in formal/freelist.sby.

One tool footgun is encoded here deliberately: yosys's `sat` pass ignores
$assume cells unless `-set-assumes` is passed. Without it the solver starts from
an unconstrained state and reports a counterexample that cannot occur. Every
generated script passes the flag.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .tools import have, missing, run

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, "build")
SBY_FILE = os.path.join(REPO, "formal", "freelist.sby")

TASKS = ("bmc", "prove", "cover")

# Cover points declared in formal/freelist_cover.v, selected by -DCOVER_<n>.
COVER_POINTS = [
    (0, "free list fully exhausted"),
    (1, "allocation of the last free preg"),
    (2, "rollback that actually undoes allocated state"),
    (3, "allocation reaches the top preg index"),
]

PASS_RE = re.compile(r"no model found: SUCCESS!|Induction step proven: SUCCESS!")
FAIL_RE = re.compile(r"proof did fail|proof failed")
INIT_RE = re.compile(r"^\s+init \\?(\S+)\s+(-?\d+)\s+(\S+)\s+(\S+)\s*$", re.M)
INDUCT_RE = re.compile(r"Trying induction with length (\d+)")


@dataclass
class FormalVerdict:
    task: str
    status: str = "SKIPPED"     # PASS | FAIL | UNKNOWN | ERROR | SKIPPED
    backend: str = "yosys"
    seconds: float = 0.0
    note: str = ""
    counterexample: dict[str, str] = field(default_factory=dict)
    induction_length: int | None = None
    covers: list[dict] = field(default_factory=list)
    log: str = ""

    @property
    def proved(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict:
        d = {
            "task": self.task, "backend": self.backend, "status": self.status,
            "seconds": round(self.seconds, 2), "note": self.note,
        }
        if self.induction_length is not None:
            d["induction_length"] = self.induction_length
        if self.counterexample:
            d["counterexample_initial_state"] = self.counterexample
        if self.covers:
            d["covers"] = self.covers
        return d


def yosys_bin() -> str | None:
    """Locate a yosys, preferring an explicit override then the local venv."""
    override = os.environ.get("CHIA_YOSYS")
    if override:
        return override
    venv = os.path.join(REPO, ".venv", "bin", "yowasp-yosys")
    if os.path.exists(venv):
        return venv
    for cand in ("yowasp-yosys", "yosys"):
        if have(cand):
            return cand
    return None


def _write_script(name: str, lines: list[str]) -> str:
    os.makedirs(BUILD, exist_ok=True)
    path = os.path.join(BUILD, name)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _read(defines: list[str], sources: list[str]) -> list[str]:
    flags = " ".join(f"-D{d}" for d in defines)
    return [f"read_verilog -formal -sv {flags} -I verif {src}" for src in sources]


def _parse_counterexample(out: str) -> dict[str, str]:
    """Pull the initial-state table out of a failing sat run.

    This is what gets handed to triage: the state the solver had to invent to
    break the property is usually the shape of the missing invariant.
    """
    ce: dict[str, str] = {}
    for name, _dec, hexv, _bin in INIT_RE.findall(out):
        if name.startswith("$auto$"):
            continue                      # async2sync scaffolding, not design state
        ce[name] = f"0x{hexv}"
    return ce


def _run_yosys(script: str, timeout: int) -> tuple[str, float, int]:
    ys = yosys_bin()
    if ys is None:
        return "", 0.0, 127
    res = run([ys, "-s", script], cwd=REPO, timeout=timeout)
    return res.output, res.seconds, res.returncode


def run_bmc(depth: int = 30, timeout: int = 1800) -> FormalVerdict:
    v = FormalVerdict(task="bmc")
    script = _write_script("bmc.ys", [
        *_read(["FORMAL"], ["rtl/freelist.v", "formal/freelist_fv.v"]),
        "prep -top freelist_fv -flatten",
        "async2sync",
        "chformal -cover -remove",
        "chformal -lower",
        f"sat -verify -prove-asserts -set-assumes -seq {depth}",
    ])
    out, secs, rc = _run_yosys(script, timeout)
    return _finish(v, out, secs, rc, depth_note=f"depth {depth}")


def run_prove(maxsteps: int = 20, timeout: int = 1800) -> FormalVerdict:
    v = FormalVerdict(task="prove")
    script = _write_script("prove.ys", [
        *_read(["FORMAL"], ["rtl/freelist.v", "formal/freelist_fv.v"]),
        "prep -top freelist_fv -flatten",
        "async2sync",
        "chformal -cover -remove",
        "chformal -lower",
        f"sat -tempinduct -prove-asserts -set-assumes -verify -maxsteps {maxsteps}",
    ])
    out, secs, rc = _run_yosys(script, timeout)
    v = _finish(v, out, secs, rc, depth_note=f"maxsteps {maxsteps}")
    lengths = [int(n) for n in INDUCT_RE.findall(out)]
    if v.status == "PASS" and lengths:
        v.induction_length = max(lengths)
    return v


def run_cover(depth: int = 25, timeout: int = 1800) -> FormalVerdict:
    """Check each cover point by refutation.

    A cover that cannot be reached means the assumptions have over-constrained
    the environment (or the logic is dead). That is the failure mode this whole
    project is pointed at, so an unreachable cover is reported as FAIL.
    """
    v = FormalVerdict(task="cover")
    if yosys_bin() is None:
        v.note = "not run: no yosys on this machine"
        return v

    total = 0.0
    unreachable = 0
    for n, desc in COVER_POINTS:
        script = _write_script(f"cover{n}.ys", [
            *_read([f"COVER_{n}"], ["rtl/freelist.v", "formal/freelist_cover.v"]),
            "prep -top freelist_cover -flatten",
            "async2sync",
            "chformal -lower",
            f"sat -verify -prove-asserts -set-assumes -seq {depth}",
        ])
        out, secs, rc = _run_yosys(script, timeout)
        total += secs

        if FAIL_RE.search(out):
            status = "REACHABLE"        # counterexample = witness
        elif PASS_RE.search(out):
            status = "UNREACHABLE"      # no witness exists
            unreachable += 1
        else:
            status = "INCONCLUSIVE"

        v.covers.append({"id": f"COVER_{n}", "description": desc,
                         "status": status, "seconds": round(secs, 2)})

    v.seconds = total
    v.status = "PASS" if unreachable == 0 else "FAIL"
    v.note = (f"{unreachable} of {len(COVER_POINTS)} cover points unreachable"
              if unreachable else
              f"all {len(COVER_POINTS)} cover points reachable; assumptions do "
              "not over-constrain the environment")
    return v


def _finish(v: FormalVerdict, out: str, secs: float, rc: int,
            depth_note: str) -> FormalVerdict:
    v.seconds = secs
    v.log = out[-16000:]
    v.note = depth_note

    if rc == 127:
        v.status = "SKIPPED"
        v.note = ("not run: no yosys found. Install with "
                  "`python3 -m venv .venv && .venv/bin/pip install yowasp-yosys`, "
                  "or set CHIA_YOSYS.")
        return v
    if rc == 124:
        v.status = "UNKNOWN"
        v.note = f"{depth_note}: engine did not converge before the timeout"
        return v

    if FAIL_RE.search(out):
        v.status = "FAIL"
        v.counterexample = _parse_counterexample(out)
    elif PASS_RE.search(out):
        v.status = "PASS"
    else:
        v.status = "ERROR" if rc != 0 else "UNKNOWN"
    return v


def run_task(task: str, backend: str = "yosys", timeout: int = 1800,
             **kw) -> FormalVerdict:
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}; expected one of {TASKS}")

    if backend == "sby":
        absent = missing("yosys", "sby")
        v = FormalVerdict(task=task, backend="sby")
        if absent:
            v.note = (f"not run: {', '.join(absent)} not on PATH. The sby path "
                      "also needs an SMT solver; the yosys backend does not.")
            return v
        res = run(["sby", "-f", SBY_FILE, task],
                  cwd=os.path.join(REPO, "formal"), timeout=timeout)
        v.seconds = res.seconds
        v.log = res.output[-16000:]
        m = re.search(r"DONE \((PASS|FAIL|UNKNOWN|ERROR)", res.output, re.I)
        v.status = m.group(1).upper() if m else ("ERROR" if not res.ok else "UNKNOWN")
        return v

    if task == "bmc":
        return run_bmc(timeout=timeout, **kw)
    if task == "prove":
        return run_prove(timeout=timeout, **kw)
    return run_cover(timeout=timeout, **kw)
