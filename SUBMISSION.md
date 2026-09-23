# Submission: Finding BOOM CPU Bugs with an AI Loop and Two Reference Models

**Author:** Divya Kohli, University of California, Santa Cruz (dkohli1@ucsc.edu)
**Problem track:** Discovery of architectural/microarchitectural bugs in
open-source designs (BOOM core)
**Paper:** paper/paper.pdf (4 pages)
**Open-source loop:** <REPO URL>

## Description

We built a CHIA loop that looks for bugs in the BOOM out-of-order RISC-V core. It
runs a small test program on BOOM and on two reference models that follow the
RISC-V rules (Spike and Dromajo), then compares what they commit. If BOOM does
something different, that may be a bug.

Running Spike next to BOOM is an existing Chipyard feature, and we use it as is.
What we add is the layer on top, in five composable blocks: (1) read BOOM's
source to find risky spots and turn them into test ideas with file:line evidence;
(2) write small RISC-V test programs aimed at those spots, keeping only ones that
build, finish, and do real work; (3) run each on BOOM, Spike, and Dromajo and
compare committed state; (4) vote across the two reference models and sort each
difference into BOOM bug / reference-model bug / allowed difference / test-setup
problem / not sure; (5) measure quality by planting known bugs and checking how
many the loop finds.

Using two reference models instead of one is the main idea. With two, most cases
are decided by a majority vote instead of a person guessing which side is wrong.

## Results

On a set of planted bugs: recall is 8 of 8 over bugs that change committed state
on a single core, and precision is 100% (zero false bug calls on the clean
build). Three planted bugs are not observable on a single core and are left out of
recall, not counted as misses. The clearest result: the second reference model
found a bug the first one missed. The loop also flagged a disagreement between the
two reference models, which on inspection was a logging habit, not a real bug, and
the tool did not report it as one.

These are planted bugs; they show the method works. We have not yet found a new,
real bug in BOOM. The loop, its tests, and the planted-bug results are released
open-source and are designed as reusable CHIA blocks.
