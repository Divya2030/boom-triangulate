"""Agentic block: property synthesis and failure triage.

Two execution modes, and every result carries its provenance so model output is
never confused with a rule-based guess:

  gemini:<model>     -- GEMINI_API_KEY is set; the model is queried over REST
  offline-heuristic  -- no key available; deterministic rules stand in

The offline path exists so the loop is runnable and testable without burning
API credit, and so CI can exercise the orchestration. It is not a substitute for
the model: its classifications are coarse by design.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent")
DEFAULT_MODEL = os.environ.get("CHIA_MODEL", "gemini-pro-latest")
DEFAULT_FAST_MODEL = os.environ.get("CHIA_MODEL_FAST", "gemini-3.6-flash")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Key-file fallback. Shell env vars do not persist across separate tool calls in
# some harnesses, and pasting a key into a chat transcript leaks it. So the key
# can instead live in a gitignored file, read once here. Precedence: an
# explicit argument, then $GEMINI_API_KEY, then $CHIA_GEMINI_KEY_FILE, then
# .gemini.key at the repo root.
_KEY_FILE = os.environ.get("CHIA_GEMINI_KEY_FILE",
                           os.path.join(_REPO, ".gemini.key"))


def load_api_key(explicit: str | None = None) -> str:
    if os.environ.get("CHIA_NO_MODEL"):
        return ""              # hard offline switch, used by the test suite
    if explicit:
        return explicit.strip()
    env = os.environ.get("GEMINI_API_KEY", "").strip()
    if env:
        return env
    try:
        with open(_KEY_FILE) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    return ""

CLASSES = ("DESIGN_BUG", "BAD_PROPERTY", "MISSING_ASSUMPTION", "COVERAGE_HOLE")


@dataclass
class Judgement:
    classification: str
    rationale: str
    suggestion: str = ""
    provenance: str = "offline-heuristic"
    raw: str = field(default="", repr=False)

    def to_dict(self) -> dict:
        return {
            "classification": self.classification,
            "rationale": self.rationale,
            "suggestion": self.suggestion,
            "provenance": self.provenance,
        }


class Agent:
    """Thin Gemini client with a deterministic offline fallback."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 timeout: int = 120):
        self.api_key = load_api_key(api_key)
        self.model = model
        self.timeout = timeout
        self.last_fallback = ""

    @property
    def online(self) -> bool:
        return bool(self.api_key)

    @property
    def provenance(self) -> str:
        return f"gemini:{self.model}" if self.online else "offline-heuristic"

    def complete(self, prompt: str, fast: bool = False) -> str:
        if not self.online:
            raise RuntimeError("no GEMINI_API_KEY set")
        model = DEFAULT_FAST_MODEL if fast else self.model
        try:
            return self._call(model, prompt)
        except urllib.error.HTTPError as exc:
            # 429 = quota. On the free tier Pro is heavily capped, so fall back
            # to the fast model once rather than losing the result. The finding
            # records provenance, so the fallback is visible downstream.
            if exc.code == 429 and model != DEFAULT_FAST_MODEL:
                self.last_fallback = f"{model}->{DEFAULT_FAST_MODEL} (429)"
                return self._call(DEFAULT_FAST_MODEL, prompt)
            raise

    def _call(self, model: str, prompt: str, max_retries: int = 4) -> str:
        # Free-tier limits produce 429 (quota) and transient 503/500. Retry with
        # exponential backoff so a burst of large RTL prompts does not fall back
        # to the offline baseline just because calls arrived too fast.
        delay = 5.0
        last: Exception | None = None
        for attempt in range(max_retries):
            try:
                return self._post(model, prompt)
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (429, 500, 503) and attempt < max_retries - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 60.0)
                    continue
                raise
        assert last is not None
        raise last

    def _post(self, model: str, prompt: str) -> str:
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }).encode()
        req = urllib.request.Request(
            ENDPOINT.format(model=model),
            data=body,
            headers={"Content-Type": "application/json",
                     "x-goog-api-key": self.api_key},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.load(resp)
        return payload["candidates"][0]["content"]["parts"][0]["text"]

    # -- triage ----------------------------------------------------------

    def triage_survivor(self, mutant: dict, rtl: str) -> Judgement:
        """Explain why no property caught this mutant, and propose one that would."""
        if not self.online:
            return _offline_survivor(mutant)

        prompt = _SURVIVOR_PROMPT.format(
            mutant_id=mutant["id"], op=mutant["op"], line=mutant["line"],
            source=mutant["source"], rtl=rtl,
        )
        try:
            text = self.complete(prompt)
        except (urllib.error.URLError, KeyError, RuntimeError, TimeoutError) as exc:
            j = _offline_survivor(mutant)
            j.rationale = f"[model call failed: {exc}] " + j.rationale
            return j

        data = _parse_json(text)
        return Judgement(
            classification=data.get("classification", "COVERAGE_HOLE"),
            rationale=data.get("rationale", "").strip(),
            suggestion=data.get("suggested_property", "").strip(),
            provenance=self.provenance,
            raw=text,
        )


_SURVIVOR_PROMPT = """You are a formal verification engineer reviewing a mutation-testing result.

A defect was injected into the RTL below and the existing property set did NOT
detect it. Explain the gap and propose one property that would catch it.

Mutant: {mutant_id}
Operator: {op}
Injected at line {line}: {source}

RTL under verification:
```verilog
{rtl}
```

Respond as JSON with keys:
  classification: one of DESIGN_BUG, BAD_PROPERTY, MISSING_ASSUMPTION, COVERAGE_HOLE
  rationale: two sentences on why the current properties miss this defect
  suggested_property: a single SystemVerilog assertion, or "" if the mutant is
    semantically equivalent to the original (in which case say so in rationale)
"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _offline_survivor(mutant: dict) -> Judgement:
    """Deterministic stand-in: map the mutation operator to a likely gap."""
    op = mutant.get("op", "")
    src = mutant.get("source", "")

    if op in ("CONST_1_TO_0", "CONST_0_TO_1") and "reset" in src.lower():
        return Judgement(
            "COVERAGE_HOLE",
            "Mutation touches reset-time initialisation, which the properties "
            "only observe after reset deasserts.",
            "Add a post-reset property constraining the initial free mask.",
        )
    if op == "LOOP_BOUND":
        return Judgement(
            "COVERAGE_HOLE",
            "Off-by-one in a loop bound only shows on the highest-numbered preg, "
            "which random stimulus may never allocate under this seed budget.",
            "Add a cover/property exercising allocation of the last preg index.",
        )
    if op in ("AND_TO_OR", "OR_TO_AND", "DROP_NOT", "SHIFT_FLIP"):
        return Judgement(
            "COVERAGE_HOLE",
            "Datapath mutation not distinguished by the current property set; "
            "either the affected path is unreachable under the assumptions, or "
            "the mutant is semantically equivalent.",
            "Strengthen the shadow-model comparison to check the allocated index "
            "itself, not only the free/allocated partition.",
        )
    return Judgement(
        "COVERAGE_HOLE",
        "No property distinguishes this mutant from the original design.",
        "Manual review required.",
    )
