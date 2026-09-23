"""Model execution: build a test program, run it on each model, get a trace.

The loop compares models, so every model is reduced to the same interface:
an ELF goes in, a normalised `CommitEvent` stream comes out. Anything
model-specific -- flags, log destinations, harness quirks -- is confined here.

Spike is the oracle. BOOM is the implementation under test and is not wired up
yet: it needs a built Chipyard, which is the next setup step.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import trace
from .tools import RunResult, run

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
PROGS = os.path.join(REPO, "tests", "progs")
LINKER = os.path.join(PROGS, "link.ld")

DEFAULT_ISA = "rv64gc"
DEFAULT_MARCH = "rv64imafdc_zicsr_zifencei"
DEFAULT_MABI = "lp64d"


@dataclass
class Toolchain:
    """Where the tools live. Mirrors setup/activate.sh."""

    riscv_prefix: str = os.path.join(TOOLS, "mamba", "envs", "chia", "riscv-tools")
    spike_prefix: str = os.path.join(TOOLS, "spike")

    @property
    def gcc(self) -> str:
        return os.path.join(self.riscv_prefix, "bin", "riscv64-unknown-elf-gcc")

    @property
    def objdump(self) -> str:
        return os.path.join(self.riscv_prefix, "bin",
                            "riscv64-unknown-elf-objdump")

    @property
    def spike(self) -> str:
        return os.path.join(self.spike_prefix, "bin", "spike")

    def env(self) -> dict[str, str]:
        """Process environment for running the tools.

        Spike shells out to `dtc` at startup to build the device tree, so the
        conda env's bin must be on PATH of the *child* process -- sourcing
        setup/activate.sh in the caller's shell does not reach a subprocess
        launched from Python.
        """
        e = dict(os.environ)
        conda_bin = os.path.join(TOOLS, "mamba", "envs", "chia", "bin")
        e["PATH"] = os.pathsep.join([
            os.path.join(self.spike_prefix, "bin"),
            os.path.join(self.riscv_prefix, "bin"),
            conda_bin,
            e.get("PATH", ""),
        ])
        e["RISCV"] = self.riscv_prefix
        return e

    def missing(self) -> list[str]:
        return [name for name, path in
                (("riscv64-unknown-elf-gcc", self.gcc), ("spike", self.spike))
                if not os.path.exists(path)]


TC = Toolchain()


def build_elf(source: str, out_elf: str, tc: Toolchain = TC,
              march: str = DEFAULT_MARCH, mabi: str = DEFAULT_MABI,
              timeout: int = 120) -> RunResult:
    """Assemble and link one bare-metal test program."""
    os.makedirs(os.path.dirname(out_elf), exist_ok=True)
    return run([
        tc.gcc,
        f"-march={march}", f"-mabi={mabi}",
        "-static", "-nostdlib", "-nostartfiles",
        "-fno-common", "-mcmodel=medany",
        f"-I{PROGS}", "-T", LINKER,
        source, "-o", out_elf,
    ], timeout=timeout, env=tc.env())


def run_spike(elf: str, tc: Toolchain = TC, isa: str = DEFAULT_ISA,
              max_insns: int | None = None, timeout: int = 300) -> RunResult:
    """Run the oracle with commit logging enabled.

    Spike writes the commit log to stderr, so callers must read the combined
    output rather than stdout alone.
    """
    cmd = [tc.spike, f"--isa={isa}", "--log-commits"]
    if max_insns is not None:
        cmd += ["--instructions", str(max_insns)]
    cmd.append(elf)
    return run(cmd, timeout=timeout, env=tc.env())


def spike_trace(elf: str, truncate: bool = True,
                **kw) -> tuple[list[trace.CommitEvent], RunResult]:
    res = run_spike(elf, **kw)
    events = trace.parse_spike(res.output)
    if truncate:
        events = trace.truncate_at_halt(events)
    return events, res


CHIPYARD = os.path.join(TOOLS, "src", "chipyard")
VERILATOR_DIR = os.path.join(CHIPYARD, "sims", "verilator")
DEFAULT_BOOM_CONFIG = "boom.v3.common.WithBoomCommitLogPrintf_MediumBoomV3Config"
DROMAJO = os.path.join(TOOLS, "mamba", "envs", "chia", "bin", "dromajo")


def have_dromajo() -> bool:
    return os.path.exists(DROMAJO)


def run_dromajo(elf: str, tc: "Toolchain" = None, timeout: int = 300) -> RunResult:
    """Run the Dromajo reference model with tracing from the first instruction.

    Dromajo is a second, independent ISA oracle (Esperanto). Its commit log
    matches Spike's values on the same program, which is what makes triangulation
    meaningful: two oracles that agree are strong evidence, and an oracle that
    stands alone is the suspect one.
    """
    return run([DROMAJO, "--trace", "0", os.path.abspath(elf)], timeout=timeout,
               env=(tc or TC).env())


def dromajo_trace(elf: str, truncate: bool = True,
                  **kw) -> tuple[list[trace.CommitEvent], RunResult]:
    res = run_dromajo(elf, **kw)
    events = trace.parse_dromajo(res.output)
    if truncate:
        events = trace.truncate_at_halt(events)
    return events, res


def boom_simulator(config: str = DEFAULT_BOOM_CONFIG) -> str | None:
    """Path to a built Chipyard Verilator simulator, or None."""
    path = os.path.join(VERILATOR_DIR, f"simulator-chipyard.harness-{config}")
    return path if os.path.exists(path) else None


def available_boom_simulators() -> list[str]:
    import glob
    return sorted(glob.glob(os.path.join(VERILATOR_DIR,
                                         "simulator-chipyard.harness-*")))


def run_boom(elf: str, config: str = DEFAULT_BOOM_CONFIG,
             tc: Toolchain = TC, timeout: int = 1800,
             verbose: bool = True, sim_path: str | None = None,
             max_cycles: int | None = None) -> RunResult:
    """Run the implementation with commit logging on.

    Chipyard fences simulator plusargs between `+permissive` and
    `+permissive-off`; anything outside that fence is handed to fesvr, which
    tries to open it as the program. That is why a bare `+verbose` fails with
    "could not open +verbose" instead of being ignored.

    The commit log is written to stderr, not stdout. Chipyard's own recipe pipes
    it through `spike-dasm` to expand DASM() markers into disassembly; that is
    cosmetic and skipped here, since the parser reads the raw instruction bits.
    """
    # The simulator runs with cwd set to the Verilator directory, so a relative
    # path would be resolved against the wrong place and fesvr would report a
    # missing file. Resolve before changing directory.
    elf = os.path.abspath(elf)
    # sim runs with cwd=VERILATOR_DIR, so a relative sim path would fail to exec;
    # absolutize it (this was a real false-positive source in triangulation).
    sim = os.path.abspath(sim_path) if sim_path else boom_simulator(config)
    if sim is None:                            # an archived per-mutant binary
        built = available_boom_simulators()
        raise FileNotFoundError(
            f"no simulator for config {config!r}. "
            + (f"Built configs: {[os.path.basename(b) for b in built]}"
               if built else "None built; run setup/03-boom-sim.sh.")
        )
    if not os.path.exists(sim):
        raise FileNotFoundError(f"simulator binary not found: {sim}")
    if False:
        built = available_boom_simulators()
        raise FileNotFoundError(
            f"no simulator for config {config!r}. "
            + (f"Built configs: {[os.path.basename(b) for b in built]}"
               if built else "None built; run setup/03-boom-sim.sh.")
        )
    cmd = [sim, "+permissive"]
    if verbose:
        cmd.append("+verbose")
    if max_cycles is not None:
        # Bound a non-terminating (derailed) mutant: it runs at most this many
        # cycles then stops with a full trace, instead of being killed on a
        # timeout and losing its output. A correct program finishes well under
        # the cap and exits normally.
        cmd.append(f"+max-cycles={max_cycles}")
    cmd += ["+permissive-off", elf]
    return run(cmd, cwd=VERILATOR_DIR, timeout=timeout, env=tc.env())


def boom_trace(elf: str, truncate: bool = True, config: str = DEFAULT_BOOM_CONFIG,
               sim_path: str | None = None, max_cycles: int | None = None,
               **kw) -> tuple[list[trace.CommitEvent], RunResult]:
    """Run BOOM and normalise its commit log.

    The commit-log fragment is documented in BOOM as dumping state "for
    comparison against ISA sim", so its format may match Spike's. Both parsers
    are tried and whichever yields events wins -- decided at runtime rather than
    assumed, because guessing wrong here silently produces an empty trace that
    looks like a divergence.
    """
    res = run_boom(elf, config=config, sim_path=sim_path,
                   max_cycles=max_cycles, **kw)
    # The commit-log fragment emits Spike format; the TraceIO port emits the
    # TracerV format. Try both rather than assume which config was built.
    events = trace.parse_commit_log(res.output)
    if not events:
        events = trace.parse_boom(res.output)
    if truncate:
        events = trace.truncate_at_halt(events)
    return events, res
