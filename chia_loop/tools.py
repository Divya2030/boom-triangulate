"""Tool discovery and subprocess helpers.

Every external tool is optional. Blocks that need a missing tool report that
plainly rather than failing deep inside a stack trace, so the loop degrades to
whatever the current machine can actually run.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass


@dataclass
class RunResult:
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str
    seconds: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def missing(*tools: str) -> list[str]:
    return [t for t in tools if not have(t)]


def run(cmd: list[str], cwd: str | None = None, timeout: int = 300,
        env: dict[str, str] | None = None) -> RunResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            env=env,
        )
        return RunResult(cmd, proc.returncode, proc.stdout, proc.stderr,
                         time.monotonic() - start)
    except subprocess.TimeoutExpired as exc:
        return RunResult(cmd, 124, exc.stdout or "", f"TIMEOUT after {timeout}s",
                         time.monotonic() - start)
    except FileNotFoundError as exc:
        return RunResult(cmd, 127, "", str(exc), time.monotonic() - start)
