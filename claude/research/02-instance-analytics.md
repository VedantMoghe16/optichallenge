== OGC 2026 TRAINING DATA ANALYSIS (40 instances) ==

TABLE 1 — per instance (inst | n | m | totBayArea | w1/w2/w3 | maxR | maxD | sumP | demand/supply@maxD | peakInstDemand/bayArea | slackMed | %slack<=0 | %K>=2 | prefGapMed | w3*gapMed/w1 [tardy-day equiv of diverting median block] | fitMin% [worst bay])

```
inst    n   m  bayA  w1    w2 w3  maxR maxD sumP d/s  peak sMed s<=0% K2% gap divEq fitMin
p1     100  2  1992 29091  7 200   42  55   735 0.28 0.47  1   26   85  56 0.39  100
p2     100  3  4382 29091 10 150   43  53   739 0.18 0.35  1   24   83  47 0.24  100
p3     100  3  7424 26667 10 150   47  58   760 0.17 0.33  1   39   86  46 0.26  100
p4     100  2  5782 21918  7 200   57  64   755 0.24 0.41  1   35   85  75 0.68  100
p5     150  3  5872 16000  7 150   78  86  1143 0.18 0.33  2   29   82  41 0.38   99
p6     150  3  8198 29630  7 150   42  57  1138 0.27 0.45  1   24   81  54 0.27  100
p7     150  3  4876 17778  7 150   70  85  1138 0.19 0.36  1   24   88  45 0.38  100
p8     150  2  5866 10000  4 200  125 136  1078 0.15 0.29  1   27   92  69 1.38  100
p9     200  3  9369 13333  5 150   94 103  1490 0.21 0.33  1   32   98  44 0.50   93
p10    200  4  6613 14545  7 133   86 100  1539 0.16 0.28  2   24   97  29 0.27  100
p11    200  4 13727 22857  7 133   55  67  1539 0.24 0.41  1   31   86  33 0.19  100
p12    200  4  7752 21918  7 133   57  69  1488 0.22 0.39  1   34   86  32 0.19  100
p13    250  4 10876 18605  5 133   67  80  1930 0.26 0.42  1   32   82  32 0.23   99
p14    250  4  8924 17778  5 133   70  82  1882 0.24 0.42  1   23   96  30 0.23   97
p15    250  4  9640 14815  5 133   85 100  1854 0.20 0.37  1   32   83  37 0.33   96
p16    250  4 10815  8889  5 133  141 150  1932 0.14 0.30  2   25   84  32 0.47   98
p17    300  4 10377  9697  4 133  129 144  2270 0.16 0.31  1   28   85  40 0.55   98
p18    300  4  7849 13333  4 133   94 108  2270 0.22 0.37  1   28   83  35 0.35  100
p19    300  4 10223 10667  4 133  117 129  2214 0.17 0.34  1   26   83  36 0.44  100
p20    300  5 12763 26667  6 125   47  59  2224 0.29 0.47  1   23   85  25 0.12   98
p21    100  3 10137 13333 10 150   47  83  2208 0.38 0.77  4    7   85  62 0.70   97
p22    100  2  5199 13333  3 400   47  67  1115 0.31 0.51  2   17   83  92 2.76   99
p23    100  2  5050 13559  7 200   46  68  1636 0.50 0.85  3   11   82  69 1.02  100
p24    100  3  6342 13333  5 300   47  77  1666 0.29 0.60  4   11   99  42 0.95  100
p25    100  2  6080   667  1  20   47  86  2158 0.50 1.26  6    8   81  71 2.13  100
p26    150  3  7062 13333  7 150   47  76  2538 0.48 0.97  4    8  100  71 0.80   99
p27    150  2  3728 13333  2 400   47  80  3190 0.77 1.61  4    9   86  76 2.28   99
p28    150  3  7211 13333  3 300   47  72  2483 0.45 0.86  4   10   80  48 1.09  100
p29    150  3  3024 13333  3 300   47  62  1655 0.33 0.54  2   22   85  70 1.58  100
p30    150  2  6024 13333  4 200   47  66  1697 0.49 0.89  2   19   81  74 1.11  100
p31    200  4  7095 13333  3 267   47  86  4299 0.46 0.88  5    8   84  68 1.36  100
p32    200  3  5220  3333  5 600   47  70  2291 0.44 0.85  2   22   98  45 8.10   98
p33    200  3  7814  6667 10 150   47  76  3359 0.59 1.12  4   11   85  46 1.05  100
p34    200  4  8436  3333  7 533   47  77  3287 0.42 0.73  3   10   84  36 5.84  100
p35    200  3  9534 13333  5 150   47  65  2276 0.43 0.82  2   16   82  50 0.56  100
p36    250  4  6185   667  1  13   46  66  2846 0.44 0.73  2   20   83  59 1.15  100
p37    250  3  8313  3333  4 600   47  68  2877 0.54 0.94  2   17   89  43 7.74  100
p38    250  3  6527 13333  2 300   47  85  5337 0.80 1.55  4   11   89  52 1.18  100
p39    250  3  6805 13333  4 150   47  66  2780 0.55 0.96  2   21   83  60 0.68  100
p40    250  4  9556   667  1  13   47  83  5422 0.69 1.29  4   11   98  66 1.29  100
```

TABLE 2 — Z2 exchange & bay dims (w2*meanL/w1 = tardy-day equiv of 1-block workload swap effect; w2*(sumL/m)/w1 = pathological full-imbalance in day-equiv)
```
set1 (p1-20):  w2*meanL/w1 = 0.019-0.047 days; w2*(sumL/m)/w1 = 0.89-2.96 days
set2 (p21-40): w2*meanL/w1 = 0.014-0.271; w2*(sumL/m)/w1 = 1.06-16.37
  Z2-sensitive outliers: p34(13.5), p37(14.3), p40(16.4), p32(9.4), p33(9.2), p36(8.4), p25(6.7)
Bay dims: widths 32-179, heights 15-29. Bays within an instance vary wildly in area (up to ~5x, e.g. p7: 36x23,32x22,176x19).
```

AGGREGATES
- SLACK (D-R-P): min=0, med=2, mean=2.4, max=14. %<0 = 0.00 (NO forced-tardy blocks anywhere). %<=0 = 21.5%, %<=2 = 63.1%, %<=5 = 90.1%. Set1 slack median 1 with ~23-39% at zero; set2 slack median 2-6, 7-22% at zero. Zero-slack blocks must enter exactly at R and exit at R+P to be on time.
- SHAPES: vertices/layer min 3, med 7, mean 6.8, p95 10, max 12 (small polygons — exact geometry cheap). Convexity (area/hull): med 0.986, mean 0.947, only 6.9% below 0.8 — shapes are mostly near-convex. Bbox fill: med 0.673, mean 0.685, 12.8% below 0.5 — AABB-based placement wastes ~33% area on median; true-shape (NFP/raster) packing has large headroom.
- LAYERS: K=1 13.3%, K=2 75.2%, K=3 5.6%, K=4 5.9%. Of 6505 multi-layer blocks: 26.6% identical layers, 35.7% all-shrink (pyramid), 34.9% all-GROW (mushroom — upper layers LARGER than base), 2.8% mixed. Upper/L0 area ratio: p05 0.48, med 1.00, p95 2.20. Overhang (upper-layer area outside layer-0 footprint): mean 15.6%, 40.3% of multi-layer blocks have >1% overhang, max 99.5%. Layer-aware packing (interlocking mushrooms over pyramids, tolerating overhang with induced exit-precedence) is a real lever, not a corner case.
- ORIENTATIONS: 90.1% of blocks have 8, 4.9% have 6, 3.8% have 4, 1.3% have 2.
- PREFERENCES: best-2nd gap med 45, mean 47.6, only 0.7% ties (gap=0), 45.7% have gap>=50, max 100. Correlation(preferred-bay area, block area) per instance: -0.13..0.18, essentially ZERO — preferences are not size-driven; no structural excuse needed to divert.
- FIT: fit is a NON-issue. Worst per-bay fit rate across all instances is 93% (p9); 35/40 instances have >=98% of blocks fitting every bay in some orientation; ~0% of blocks fit only one bay. Assignment is nearly unconstrained by geometry.

TAKEAWAYS
1. Two clear congestion regimes. Set1 (p1-20): d/s 0.14-0.29, peak inst demand 0.28-0.47 of bay area — loose; near-zero tardiness plausibly achievable, so Z3 (and residual Z2) decide ranking. Set2 (p21-40): d/s 0.29-0.80, peak demand 0.51-1.61; p25,p27,p33,p38,p40 have peak >1.0 (physically impossible to run all blocks in their [R,R+P) windows) — tardiness is unavoidable and packing density is the binding constraint.
2. Exchange rates: for set1, diverting the median block from its favorite bay costs 0.12-0.68 tardy-day equivalents (p8: 1.38) — one avoided tardy day pays for diverting 1-8 blocks. Set2 splits: preference-sensitive p32/p34/p37 (5.8-8.1 day-equiv per median diversion — treat Z3 nearly as hard constraint there) vs tardiness-dominant rest (0.6-2.8). Regime classification should be computed at runtime from w3*gapMed/w1.
3. Z2 is negligible per-block in set1 (~0.02-0.05 day-equiv per block swap) but material in p25,p32-34,p36-37,p40 where a fully lopsided assignment costs 7-16 day-equivalents; still second-order vs one tardy day except in those.
4. No negative slack: a perfect schedule with zero tardiness is not excluded by time windows anywhere; but 21% zero-slack blocks + peak demand >0.8 in set2 makes zero tardiness unreachable there — objective mass is in sequencing/packing set2-style instances.
5. Set2 structure: ALL releases in 0-47, P 5-31 (long), due dates 62-86 — a burst-arrival, long-dwell queueing problem. Set1: staggered releases over 0-141, short P 3-13 — a rolling flow problem.
6. Shapes are small (<=12 vertices), near-convex, but bbox-loose (median fill 0.67): polygon-true placement (NFP or fine raster) buys ~1/3 more effective capacity vs AABB — directly attacks the binding constraint in set2.
7. 86.7% of blocks are multi-layer with 35% mushrooms (upper > base): crane rule j>=k plus mushroom overhang enables deliberate under-tucking (place later short block beneath an earlier mushroom's overhang is disallowed by crane at entry — but placing mushroom AFTER a short neighbor lets it overhang the short one, forcing short to exit later). Precedence-aware layer packing is exploitable and novel-report-worthy.
8. Bays within an instance differ up to ~5x in area with u_j normalization in Z2; nearly all blocks fit all bays — assignment search space is effectively unconstrained, so the assignment master problem (Z2+Z3 exact, tardiness estimated) can be solved cleanly (e.g., MIP) and per-bay scheduling parallelized.

Script: /private/tmp/claude-501/-Users-vedantmoghe-Downloads-optichallenge/828d3afa-14fe-4679-bfb6-c94c0e22ac75/scratchpad/analyze.py