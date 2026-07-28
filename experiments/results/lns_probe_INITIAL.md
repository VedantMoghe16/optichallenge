# T1 LNS initial probe — NOT A PROMOTION GATE

Date: 2026-07-27  
Baseline: `f116296`, single-process `_solve`, variant 1  
Candidate: uncommitted `experiments/myalgorithm_lns_prototype.py`  
Protocol: sequential baseline then candidate; objectives from
`utils.check_feasibility`; all outputs checker-feasible.

The machine running the repository-wide raster comparison is separate from the
machine used for these local probes. These results are preserved for diagnosis
only. No candidate verdict is valid until the binding 40×60 s and 20×240 s
paired gates are run on an idle machine.

| instance | limit | baseline | candidate | delta | completed / accepted | direct LNS gain |
|---|---:|---:|---:|---:|---:|---:|
| prob_21 | 30 s | 1,196,330 | 1,196,330 | 0.00% | 7 / 7 | 0 |
| prob_27 | 30 s | 37,476,183 | 37,476,183 | 0.00% | 3 / 3 | 0 |
| prob_33 | 30 s | 17,074,960 | 16,495,223 | −3.40% | 4 / 4 | 580,987 |
| prob_38 | 30 s | 76,696,223 | 76,264,974 | −0.56% | 3 / 3 | 1,416,839 |

Direct LNS improvement rates calculated from candidate deltas and time inside
the large-neighborhood operator:

- prob_33: approximately 65,400 objective units/LNS-second.
- prob_38: approximately 214,500 objective units/LNS-second.
- prob_21 and prob_27: equal-objective geometric rearrangements only.

Short-limit diagnostic: prob_33 at 10 s was +3.29% worse after the completion
fix. This confirms that the experimental branch must remain gated by available
search time; it is not suitable for unconditional activation.

Implementation findings:

1. The first draft displaced too much productive Kestrel reinsertion time and
   was +13.2% on prob_33@10 s.
2. Early regret choices frequently stranded the final block. Reserving the
   incumbent slots of not-yet-repaired blocks made every measured neighborhood
   complete.
3. Retaining a substantial legacy-polish warm start changed prob_33@30 s from
   a regression into a measured improvement.
4. No genuinely worsening LAHC move was accepted in this sample. The observed
   gains came from no-worse related repairs and retained Kestrel polishing, so
   late acceptance itself remains unproven.
5. The instrumentation originally divided total warm-start gain by LNS-only
   seconds. The prototype now records `lns_move_best_gain` separately; the
   corrected rates above use only direct LNS gain.

