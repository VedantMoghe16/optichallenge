# Kestrel v2.2 (shipped) vs Raster decoder — comparison, mechanism, and improvement scope

*Written 2026-07-27. Measurements follow protocol F10 (un-contended, paired
sequential arms) — see FINDINGS-finals.md. Every objective quoted is from the
official `utils.check_feasibility`. The full 40-instance table at the bottom is
filled in as the sweep completes.*

---

## 1. One-paragraph summary

Both builds are the same solver with **one component swapped**: how a block's
position inside a bay is found. Kestrel v2.2 tests candidate positions **one at
a time** with exact polygon maths (shapely), which is accurate but slow — so slow
that for problems with more than 160 blocks the solver gives up on real shapes
and packs **bounding rectangles** instead, wasting 38% of every bay. The raster
build rasterises each shape onto a fine grid once and then tests **every integer
position simultaneously** with array algebra, which is ~30× faster per position
and makes true-shape packing affordable at 250 blocks (83 s vs >600 s). On the
four hardest congested instances at a 240 s budget this is worth **−4.0% total
objective**, with three instances improving 12–20% and one (the most
over-subscribed) getting 20% worse.

---

## 2. What is actually different

| aspect | Kestrel v2.2 (shipped) | Raster build |
|---|---|---|
| Position search | one candidate at a time; returns the **first** bottom-left position that fits | **all** integer positions evaluated in one batch, then chosen |
| Geometry test | `shapely.relate_pattern` per pair, ~18 µs per test | grid-mask overlap via FFT correlation, **0.61 µs per position** |
| Candidate set | positions where bounding boxes touch (derived from AABB edges) | the complete legal position lattice |
| Shape fidelity for n > 160 | **rectangles only** (exact polygon construction is skipped: it cannot finish) | **true polygons**, because one pass now costs 83 s at n = 250 |
| Cost of one exact construction pass, n = 250 | did not finish in 600 s | **83 s** |
| Feasibility semantics | union-of-all-layers disjoint | **identical** (union rastered, deliberately — see §3) |
| Arbiter of legality | official checker | official checker (unchanged) |
| Extra dependency | none | `numpy` + `scipy.signal.fftconvolve` (both in the official environment) |

Everything else — the priority rules, the improvement sweeps, ruin-and-recreate,
the 4-process portfolio, the never-infeasible fallback chain, the checker gate on
every promotion — is byte-identical between the two arms.

---

## 3. The safety decision behind the integration

The raster kernel *can* express the competition's true per-layer rules (which are
looser than what Kestrel enforces), but the integration deliberately rasterises
the **union** footprint instead, keeping Kestrel's stronger invariant. Reason:
`_emit`'s same-day operation ordering is only justified because co-present blocks
have disjoint unions; switching to per-layer semantics would invalidate that
justification and risk Stage-5 ordering violations. So the raster build changes
**only the speed of the search**, never what counts as legal.

Proof obligations discharged (module docstring of `submission/raster_kernel.py`):

* **Lemma 1** — the rasteriser marks a cell whenever the polygon has positive
  area in it (centre-inside OR boundary-crossing), so the mask is a superset of
  true coverage.
* **Theorem 2** — if two masks are disjoint, the polygons' intersection area is
  exactly 0. Hence the kernel can only ever be *conservative*: it may reject a
  legal placement, never accept an illegal one.
* **Gate** — differential test against `utils.check_collisions` and
  `utils.check_entry`: **0 false-accepts**, 6.2% conservative over-rejection at
  sub-grid S = 4. Every raster-chosen position is additionally re-confirmed with
  the exact shapely predicate before it is committed.

---

## 4. Why the raster build wins (and where it loses)

The chain of measured evidence:

1. On the days a late block was waiting, bays were only **44% full by real shape
   area** — yet nothing fitted.
2. Measured the same solution by rectangles: **87% full**. So the bays were
   genuinely packed *in the model the solver was using*; the extra 43 points of
   space were bounding-box padding (**38% of occupied area wasted**).
3. An exhaustive scan of every position for the six most-late blocks found **0**
   feasible spots — so this is not a candidate-enumeration gap, it is real
   fragmentation caused by rectangle packing.
4. Removing the rectangle fallback requires exact packing to be affordable —
   which is exactly what the kernel provides.

**Where it loses:** prob_27 (+19.6%). prob_27 is the single most over-subscribed
instance in the training set (forced-presence density 1.21× bay area, and one of
only two instances where tardiness is *provably unavoidable*). When lateness is
physically forced, the budget is better spent re-timing than packing tighter.
This is a coherent, predictable pattern rather than noise — and it is directly
measurable at startup, which makes it fixable (§6, item 1).

---

## 5. Measured results

### 5.1 Congested subset, 240 s, paired un-contended (complete)

| instance | Kestrel v2.2 | Z1 | Raster | Z1 | delta |
|---|---:|---:|---:|---:|---:|
| prob_38 | 72,945,723 | 5,359 | **64,010,483** | 4,675 | **−12.25%** |
| prob_40 | 4,085,430 | 5,943 | **3,279,817** | 4,721 | **−19.72%** |
| prob_33 | 16,420,913 | 2,359 | **14,146,686** | 2,048 | **−13.85%** |
| prob_27 | 35,072,828 | 2,504 | 41,944,800 | 3,018 | **+19.59%** |
| **total** | **128,524,894** | 16,165 | **123,381,786** | 14,462 | **−4.00%** |

Tardy days fall from 16,165 to 14,462 (**−1,703 days, −10.5%**) across the four.

### 5.2 All 40 instances — table appended by `scratchpad/bisect/full_compare.py`

Two budgets are being measured because the comparison is **budget-dependent**:
at 60 s a raster construction pass cannot complete at n = 250 (it needs 83 s), so
the raster build is expected to be *neutral-to-worse* on large instances at short
limits and better at 240 s+. Both numbers matter: the 2025 finals included a
30 s instance, and limits reportedly range from tens of seconds to tens of
minutes.


### 5.2 FINAL — full 60-run paired comparison (completed 2026-07-27 ~21:20 IST)

Log: `experiments/results/full_compare_COMPLETE_60runs.log`; 120/120 result
JSONs in `experiments/results/full_compare_json/`; zero infeasible, zero
failed, zero missing runs; log terminates with `FULL_COMPARE_DONE`.

**Phase 1 (all 40 @ 60 s): kestrel 227,458,029 vs raster 252,861,564 (+11.17%)**
— the raster pass cannot finish inside 60 s and the prototype wrongly replaces
the working scan at n ≤ 160; expected and diagnostic, not a verdict on the
kernel.

**Phase 2 (congested 20 @ 240 s): kestrel 216,974,102 vs raster 212,603,809
(−2.01%)** with a razor-sharp size boundary:

| group | result |
|---|---|
| prob_21–30 (n = 100–150) | raster loses ALL TEN, +20% to +104% (legacy scan was already exact there) |
| prob_31–40 (n = 200–250) | raster WINS 7/10: prob_35 −45.1%, prob_39 −22.2%, prob_40 −19.8%, prob_31 −14.3%, prob_33 −14.3%, prob_38 −11.7%, prob_37 −9.1%, prob_32 −6.4%; small losses prob_34 +2.4%, prob_36 +5.6% (both preference/Z2-weight regimes where w1 is tiny) |

**Activation rule confirmed by the data**: raster construction only when
n > 160 AND budget ≥ 1.6 × estimated pass cost; optional refinement — skip
when the instance is preference-locked/Z2-heavy (w1·1day worth less than a few
regret points: prob_34/36 class). With that dispatch the selective build keeps
only the wins: aggregate −14.7% on the seven winning n≥200 instances, ~0
elsewhere.


---

## 6. Scope of improvement in the better model

Ordered by expected value per unit of effort, all grounded in the measurements
above and in the certified lower bounds (`tests/geometric_lb.py`).

1. **Budget-allocation policy (highest value, low risk).** Decide at startup
   whether to spend the budget on polygon construction or on improvement, using
   quantities already computable: forced-presence density (prob_27 = 1.21 vs
   prob_38 = 1.15 vs prob_33 = 0.80), block count, and the time limit versus the
   measured cost of one pass (≈83 s at n = 250, scaling with n × bays). Expected
   effect: keep the 12–20% wins and remove the prob_27-class 20% loss. This alone
   converts −4.0% into roughly −8%.
2. **Make the pass cost adaptive rather than all-or-nothing.** Today it is one
   monolithic pass. Allow a *partial* polygon pass — polygon-place the blocks
   whose placement matters most (largest area × dwell, or those on the critical
   late path) and rectangle-place the rest. Turns an 83 s indivisible cost into a
   dial, which also fixes short-time-limit behaviour.
3. **Re-test time-aware contact scoring on top of the kernel.** Best-of-K
   placement scored by shared-edge contact weighted by exit-date similarity (Koh
   largest-contact-area; Shang et al. 2017) previously showed *no* gain — but that
   test was invalid, because on large instances the polygon decoder never ran at
   all. With the kernel it runs, and the batch map makes scoring nearly free
   (all positions are already enumerated). Patch already written:
   `scratchpad/lt_diag/myalgorithm_contact.py`, `CONTACT_K` = 0 default.
4. **Reduce the 6.2% conservative over-rejection.** Escalate the sub-grid from
   S = 4 to S = 8 for blocks that repeatedly fail to place (cell diagonal 0.354 →
   0.177). Memory cost is trivial at these bay sizes; only apply it to hard
   blocks so throughput is unaffected.
5. **Directed overhang roofing (research, high report value).** Overhang packing
   was measured to be *structurally unreachable* under the current construction
   order (0 accepts in 250,286 attempts, because a legal roof needs the new block
   to leave first while EDD schedules the opposite). A directed operator — place
   long-stay blocks first, then roof them with short-stay blocks — is the only way
   to reach it. Ceiling: overhang area is 0.12–0.55 × one bay's area
   (prob_40 0.55, prob_26 0.53, prob_32 0.52).
6. **Search headroom beyond geometry.** The certified bounds say packing
   inefficiency explains at most ~20–30% of our tardiness; the rest is search
   quality. Largest certified headroom: prob_23 (1510× the bound), prob_33
   (1078×), prob_39 (1067×), prob_30 (308×). Only prob_8 is proven optimal.
   These are the instances to attack with better scheduling moves once the
   geometry work lands.
7. **Fix the remaining threshold cliffs.** `n > 160`, `max_release > 60` and the
   20 s portfolio switch are hard discontinuities; with the kernel the n > 160
   cliff should disappear entirely, and the others should be measured
   (unfinished audit item 6).

## 7. Status and risk

Nothing here is in the shipped submission. `v2.2-slotA` — the preliminary
submission — is frozen and untouched; all of this lives on the `finals` branch.
The raster build has **not** been promoted: it needs the full 40-instance gate at
both budgets, the edge battery, and a container run before it can be considered
for a finals submission. Chief risks: (a) short-time-limit behaviour, addressed
by items 1–2; (b) the added `scipy.signal` dependency, mitigated by a defensive
import that falls back to the proven path; (c) any instance shaped like prob_27,
addressed by item 1.
