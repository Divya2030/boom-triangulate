# Poster outline — "Finding BOOM CPU Bugs with an AI Loop and Two Reference Models"
Divya Kohli · UC Santa Cruz · A3 × CHIA Hackathon, MICRO 2026
Layout: landscape, 3 columns. Read each column top to bottom.

================================================================
HEADER (full width)
================================================================
- Title (large): Finding BOOM CPU Bugs with an AI Loop and Two Reference Models
- Divya Kohli, UC Santa Cruz · dkohli1@ucsc.edu
- Small logos: CHIA / A3 / UCSC
- One-line thesis (big, bold): "The hard part isn't finding a difference — it's
  deciding what a difference MEANS."

================================================================
COLUMN 1 — THE PROBLEM
================================================================
1. Motivation (short)
   - Comparing a CPU to a reference model is a standard way to find bugs.
   - Chipyard already runs Spike next to BOOM. Running the comparison is easy.
   - Hard part: what to test, and what a difference means.

2. The core question (boxed, central)
   - When BOOM and a reference disagree, it can be:
     RTL bug · reference-model bug · allowed difference · test-setup artifact.
   - Prior fuzzers focus on FINDING differences. We focus on DECIDING.

3. Where we sit vs. prior work (small table)
   - DIFUZZRTL / ProcessorFuzz / SimFuzz: find real bugs at scale (SimFuzz: 14
     new, 7 CVEs). Strong at discovery + throughput.
   - Ours: not competing on discovery; contribution is CLASSIFICATION via a
     two-reference vote. (Cite: DIFUZZRTL, ProcessorFuzz, SimFuzz, Cascade.)

================================================================
COLUMN 2 — THE APPROACH  (the visual centerpiece)
================================================================
4. Pipeline diagram (biggest visual): 5 CHIA blocks left→right
   Pick spots (read RTL) → Write tests (gate) → Run (BOOM+Spike+Dromajo)
   → Vote & decide (triangulate) → Measure (planted bugs)
   - Callouts: "423 seams found in BOOM v3 source, each with file:line"
               "test gate: must build, finish, do real work"

5. The idea that's new — multi-oracle triangulation (diagram: 3 nodes voting)
   - B=BOOM, A1=Spike, A2=Dromajo, compared on COMMITTED state only.
   - A1=A2=B → clean · A1=A2≠B → RTL bug · B=Ai≠Aj → oracle bug ·
     A1≠A2 → oracle mismatch.
   - "Two references turn 'which side is wrong?' into a mechanical vote."

6. Honesty built into the loop (small icons/bullets)
   - mechanical rules before any model call · high bar for 'RTL bug' ·
     provenance on every verdict · integrity check on every mutant binary.

================================================================
COLUMN 3 — RESULTS & HONEST LIMITS
================================================================
7. Planted-bug study (headline numbers, big)
   - Recall over observable bugs: 8 / 8
   - Precision: 100% (0 false bug calls on the clean build)
   - 3 bugs not observable single-core → excluded, not counted as misses.
   - Small results table (found vs not-observable).

8. Key finding (boxed — the strongest story)
   - "The second reference caught a bug the first one missed."
   - A store-to-load forwarding bug derailed the program → looked like a broken
     test to one reference. The vote caught it: both references agree, BOOM is
     the outlier → RTL bug. (Tiny before/after trace snippet.)

9. Honest limitations (bulleted — this EARNS credibility here)
   - Planted bugs prove the method; no new organic BOOM bug found.
   - Single-core bare-metal can't reach every bug (SimFuzz-class discovery needs
     scale we don't have).
   - Targeting not yet isolated; two references agreed on all real state, so the
     oracle-bug case is designed-in, not yet demonstrated.

10. Takeaway + links
    - "Classification-first, honest triage, mechanical multi-oracle vote —
      reusable CHIA blocks."
    - QR code → github.com/Divya2030/boom-triangulate
    - Toolchain: Spike + Dromajo + Chipyard BOOM v3, fully scripted, MIT.

================================================================
VISUAL NOTES
================================================================
- 2 diagrams do the heavy lifting: the 5-block pipeline, and the 3-node vote.
- 1 results table + 1 boxed "key finding" with a 3-line trace snippet.
- Color: one accent (teal), semantic green/amber for found/not-observable.
- Keep text sparse; let the pipeline + vote diagrams carry it.
