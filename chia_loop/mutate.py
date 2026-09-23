"""Soundness block: mutation testing of the property set.

The failure mode this project is built to detect is a property set that passes
because it is over-constrained or vacuous rather than because the design is
correct. Mutation testing is the check: inject a defect into the RTL, re-run the
properties, and see whether anything fires. A high pass rate with a low kill
rate is a negative result and is reported as one.

Survivors -- mutants no property detects -- are the loop's next work item: each
one is a hole the agent is asked to write a new property for.

Three operator families:

  text       -- local token edits (& -> |, ~ dropped, constants flipped). Cheap
                and broad, but they cannot express a *structural* defect.
  SIG_SWAP   -- substitute one signal for another of the same declared width, on
                the right-hand side of an assignment. This is what reaches the
                control paths: `free_mask <= snapshot` becoming
                `free_mask <= next_mask` is a rollback that does not roll back,
                and no token edit produces it.
  COND_TRUE/ -- force an `if` condition to a constant, i.e. a guard that always
  COND_FALSE    or never fires. Covers "snapshot never taken" and "rollback
                always taken".

Signal widths are read from the declarations rather than elaborated, so the
swap classes are only as good as the source text -- adequate here, and it keeps
the block usable on any RTL without a synthesis step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# (name, pattern, replacement) applied to the code portion of a line, one
# occurrence at a time. Patterns avoid the multi-character operators they sit
# next to (&& vs &, || vs |) so mutants stay syntactically valid.
TEXT_OPERATORS: list[tuple[str, re.Pattern, str]] = [
    ("AND_TO_OR",  re.compile(r"(?<![&~])&(?![&=])"), "|"),
    ("OR_TO_AND",  re.compile(r"(?<![|])\|(?![|=])"), "&"),
    ("CONST_1_TO_0", re.compile(r"1'b1"), "1'b0"),
    ("CONST_0_TO_1", re.compile(r"1'b0"), "1'b1"),
    ("DROP_NOT",   re.compile(r"~"), ""),
    ("SHIFT_FLIP", re.compile(r"<<"), ">>"),
    ("EQ_TO_NE",   re.compile(r"=="), "!="),
    ("LOOP_BOUND", re.compile(r"< NUM_PREGS"), "< NUM_PREGS - 1"),
]

OPERATORS = TEXT_OPERATORS  # backwards-compatible alias

# Declarations: an optional direction, a type keyword, an optional range, a name.
DECL_RE = re.compile(
    r"^\s*(?:(?:input|output|inout)\s+)?(?:wire|reg|integer)\b\s*"
    r"(?:signed\s+)?(?:\[([^\]]*)\]\s*)?(\w+)"
)
# Assignment targets: `name =`, `name <=`, but not `==`, `!=`, `>=`.
ASSIGN_RE = re.compile(r"(?<![=!<>])\b(\w+)\s*(?:<=|=)(?![=])")
IDENT_RE = re.compile(r"\b\w+\b")

# Substituting these produces noise, not defects: the clock is structural and
# the loop counter is an elaboration-time integer.
NEVER_SWAP = {"clk", "i"}


@dataclass(frozen=True)
class Mutation:
    op: str
    line: int          # 1-indexed
    col: int           # 0-indexed, within the line
    old: str
    new: str

    @property
    def ident(self) -> str:
        tag = re.sub(r"\W", "", self.new) or "DEL"
        return f"{self.op}_L{self.line}C{self.col}_{tag}"

    def describe(self, src_lines: list[str]) -> str:
        return f"{self.ident}: line {self.line} `{src_lines[self.line - 1].strip()}`"


def _code_span(line: str) -> int:
    """Length of the line before any trailing // comment."""
    idx = line.find("//")
    return len(line) if idx < 0 else idx


def _skippable(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("//") or stripped.startswith("`")


def signal_widths(src: str) -> dict[str, str]:
    """Map signal name -> declared width class, keyed by the range text.

    The range text is used verbatim (whitespace stripped) as the class key. Two
    signals are considered interchangeable when their declarations agree
    textually, which avoids needing to elaborate parameters.
    """
    widths: dict[str, str] = {}
    for line in src.splitlines():
        if _skippable(line):
            continue
        m = DECL_RE.match(line[: _code_span(line)])
        if not m:
            continue
        rng, name = m.group(1), m.group(2)
        if name in NEVER_SWAP:
            continue
        widths[name] = re.sub(r"\s+", "", rng) if rng else "1"
    return widths


def _protected_spans(line: str) -> list[tuple[int, int]]:
    """Character spans that must not be substituted.

    Two cases: the name being declared on a declaration line (substituting it
    would rename a port), and the target of an assignment (substituting it would
    move the write, which is a different and much noisier mutation than
    perturbing the value being written).
    """
    spans: list[tuple[int, int]] = []
    code = line[: _code_span(line)]

    m = DECL_RE.match(code)
    if m:
        spans.append(m.span(2))
    for m in ASSIGN_RE.finditer(code):
        spans.append(m.span(1))
    return spans


def _in_spans(pos: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= pos and end <= e for s, e in spans)


def discover_text(src: str) -> list[Mutation]:
    muts: list[Mutation] = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        if _skippable(line):
            continue
        limit = _code_span(line)
        if limit == 0:
            continue
        code = line[:limit]
        for op, pattern, repl in TEXT_OPERATORS:
            for m in pattern.finditer(code):
                muts.append(Mutation(op, lineno, m.start(), m.group(0), repl))
    return muts


def discover_signal_swaps(src: str) -> list[Mutation]:
    """Replace a right-hand-side signal with another of the same width.

    This is the family that reaches the rollback/snapshot logic: the defects
    that matter there are "restored the wrong value" and "captured the wrong
    value", both of which are signal substitutions rather than token edits.
    """
    widths = signal_widths(src)
    by_class: dict[str, list[str]] = {}
    for name, cls in widths.items():
        by_class.setdefault(cls, []).append(name)

    muts: list[Mutation] = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        if _skippable(line):
            continue
        limit = _code_span(line)
        if limit == 0:
            continue
        code = line[:limit]
        protected = _protected_spans(line)

        for m in IDENT_RE.finditer(code):
            name = m.group(0)
            if name not in widths or name in NEVER_SWAP:
                continue
            if _in_spans(m.start(), m.end(), protected):
                continue
            for other in sorted(by_class.get(widths[name], [])):
                if other == name:
                    continue
                muts.append(Mutation("SIG_SWAP", lineno, m.start(), name, other))
    return muts


def discover_conditions(src: str) -> list[Mutation]:
    """Force `if` conditions to constants: a guard that always or never fires."""
    muts: list[Mutation] = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        if _skippable(line):
            continue
        code = line[: _code_span(line)]
        for m in re.finditer(r"\bif\s*\(", code):
            open_paren = m.end() - 1
            depth, close = 0, None
            for idx in range(open_paren, len(code)):
                if code[idx] == "(":
                    depth += 1
                elif code[idx] == ")":
                    depth -= 1
                    if depth == 0:
                        close = idx
                        break
            if close is None:
                continue
            old = code[open_paren:close + 1]
            if old in ("(1'b1)", "(1'b0)"):
                continue
            muts.append(Mutation("COND_TRUE", lineno, open_paren, old, "(1'b1)"))
            muts.append(Mutation("COND_FALSE", lineno, open_paren, old, "(1'b0)"))
    return muts


def discover(src: str, ops: list[str] | None = None) -> list[Mutation]:
    """Enumerate candidate mutations across all families.

    `ops` filters by operator-name prefix, e.g. ["SIG_SWAP", "COND"] to focus a
    campaign on the structural families.
    """
    muts = discover_text(src) + discover_signal_swaps(src) + discover_conditions(src)
    if ops:
        muts = [m for m in muts if any(m.op.startswith(p) for p in ops)]
    return muts


def apply(src: str, mut: Mutation) -> str:
    lines = src.splitlines(keepends=True)
    line = lines[mut.line - 1]
    start, end = mut.col, mut.col + len(mut.old)
    if line[start:end] != mut.old:
        raise ValueError(f"{mut.ident}: source drifted from discovery")
    lines[mut.line - 1] = line[:start] + mut.new + line[end:]
    return "".join(lines)


def generate(src: str, limit: int | None = None, seed: int = 0,
             ops: list[str] | None = None) -> list[tuple[Mutation, str]]:
    """Produce (mutation, mutated source) pairs, deduplicated by result text.

    Deduplication matters: distinct operators can land on the same text (e.g.
    flipping a constant twice), and scoring the same mutant twice would skew the
    kill rate.
    """
    import random

    seen: set[str] = {src}
    pairs: list[tuple[Mutation, str]] = []
    candidates = discover(src, ops=ops)

    rng = random.Random(seed)
    rng.shuffle(candidates)

    for mut in candidates:
        try:
            text = apply(src, mut)
        except ValueError:
            continue
        if text in seen:
            continue
        seen.add(text)
        pairs.append((mut, text))
        if limit is not None and len(pairs) >= limit:
            break

    # Stable ordering for reproducible reports.
    pairs.sort(key=lambda p: (p[0].line, p[0].col, p[0].op, p[0].new))
    return pairs
