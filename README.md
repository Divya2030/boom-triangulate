# Finding BOOM CPU bugs with an AI loop and two reference models

This is a CHIA loop that looks for bugs in the [BOOM](https://github.com/riscv-boom/riscv-boom)
out-of-order RISC-V core. It runs a small test program on BOOM and on reference
models that follow the RISC-V rules, then compares what they commit. If BOOM does
something different, that may be a bug.

Built for the A3 × CHIA hackathon (MICRO 2026 A3 Workshop).

**Live results dashboard:** https://boom-divergence-hunter.netlify.app/
· **poster:** https://boom-triangulate-poster.netlify.app/

## The idea

Running a CPU next to a reference model is a common way to find bugs. Chipyard
already lets you run Spike next to BOOM, so that part is not new. The hard part is
deciding **what** to test, writing tests that reach the tricky cases, and, most of
all, deciding **what a difference means**. A difference can be a BOOM bug, a bug in
the reference model, a difference the rules allow, or just a broken test.

This loop works on that last problem. What it adds on top of the existing
co-simulation:

- it reads BOOM's source to choose where to test,
- it writes small test programs aimed at those spots,
- it uses **two** reference models (Spike and Dromajo), not one, so it can often
  decide by a majority vote instead of guessing.

## The five parts

| block | file | what it does |
| --- | --- | --- |
| pick spots | `chia_loop/hypothesize.py` | read BOOM RTL, find risky spots, turn them into test ideas (with `file:line` evidence) |
| write tests | `chia_loop/generate.py` | turn each idea into a small RISC-V program; keep only ones that build, finish, and do real work |
| run + compare | `chia_loop/models.py`, `chia_loop/diff.py` | run on Spike, Dromajo, and BOOM; compare committed state |
| vote + decide | `chia_loop/triangulate.py`, `chia_loop/triage.py` | vote with two references; sort each difference into BOOM bug / reference bug / allowed / test-setup / not sure |
| measure | `chia_loop/seeds.py`, `chia_loop/seedstudy.py` | plant known bugs and measure how many the loop finds |

## Results

We plant known bugs in BOOM's source and check how many the loop finds. Latest run:

- **recall: 8 of 8** bugs that change committed state on a single core were found,
- **precision: 100%** — zero false bug calls on the clean build,
- three planted bugs are **not observable** on a single core (two need more than one
  core; one is never triggered by our tests) and are left out of recall, not counted
  as misses.

The clearest result: the **second reference model found a bug the first one missed**.
A store-to-load forwarding bug threw the program off course, so a single reference
read the difference as a broken test. The vote caught it — both references agree,
BOOM is the odd one out, so it is a BOOM bug.

These are planted bugs. They show the method works; we have not yet found a new,
real bug in BOOM.

## Setup

Everything installs without root. Run the setup scripts in order:

```bash
bash setup/00-toolchain.sh      # micromamba, riscv-gcc, verilator, dromajo, dtc
bash setup/01-spike.sh          # build Spike (pinned commit)
bash setup/02-chipyard.sh       # Chipyard (lean)
bash setup/02b-riscv-prefix.sh  # merge the toolchain prefixes
bash setup/03-boom-sim.sh       # build the BOOM Verilator model
```

The model calls use Gemini. Put a key in `.gemini.key` (git-ignored) or set
`GEMINI_API_KEY`. With no key, the loop still runs on a fixed offline path and is
fully testable at no cost. Every result records where it came from (a fixed rule,
the offline path, or which model).

## Run

```bash
python3 -m chia_loop hypothesize   # find risky spots, make test ideas
python3 -m chia_loop generate      # write and check test programs
python3 -m chia_loop triangulate --prog tests/progs/smoke.S   # Spike + Dromajo + BOOM vote
python3 -m chia_loop hunt          # the whole loop end to end
python3 -m chia_loop seedstudy --dry-run   # validate the planted-bug set
python3 -m chia_loop seedstudy     # the planted-bug study (rebuilds BOOM per bug)
```

Reports are written to `reports/`.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

58 tests, most of them checks that the test gate and the decision rules reject what
they should.

## What is ours and what is not

Running Spike next to BOOM is an existing Berkeley feature (Chipyard co-simulation),
and we use it as is. What this project adds is the layer on top: choosing the tests,
writing them, voting with two references, and deciding what each difference means.

## Notes

- The proposal named gem5 as the third model. We use Dromajo instead: committed-state
  comparison needs functional reference models, and two ISA references give a cleaner
  vote than a timing model would.
- Not committed to git: the toolchain under `tools/` (large, built by the setup
  scripts), build outputs, and `.gemini.key`.

## License

MIT. See `LICENSE`.
