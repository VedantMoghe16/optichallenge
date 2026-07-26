import json, glob, math
import numpy as np
from shapely.geometry import Polygon

files = sorted(glob.glob("/Users/vedantmoghe/Downloads/optichallenge/train 2/prob_*.json"),
               key=lambda f: int(f.split("_")[-1].split(".")[0])) + \
        sorted(glob.glob("/Users/vedantmoghe/Downloads/optichallenge/train/prob_*.json"),
               key=lambda f: int(f.split("_")[-1].split(".")[0]))

rows = []
agg_vc, agg_conv, agg_fill, agg_shrink, agg_gap = [], [], [], [], []
agg_slack = []
overhang_frac_all = []

for f in files:
    d = json.load(open(f))
    name = d["name"]
    W = d["weights"]; w1, w2, w3 = W["w1"], W["w2"], W["w3"]
    bays = d["bays"]; blocks = d["blocks"]
    bay_areas = [b["width"]*b["height"] for b in bays]
    tot_bay_area = sum(bay_areas)
    n = len(blocks)

    R = np.array([b["release_time"] for b in blocks])
    D = np.array([b["due_date"] for b in blocks])
    P = np.array([b["processing_time"] for b in blocks])
    L = np.array([b["workload"] for b in blocks])

    # per-block geometry (orientation 0)
    areas0 = []          # largest-layer area at orient 0
    l0_areas = []        # layer-0 area at orient 0
    Ks = []
    fits = np.zeros((n, len(bays)))   # can block fit in bay j in ANY orientation (union bbox)
    vcounts, convs, fills = [], [], []
    shrinks = []         # per multi-layer block: mean upper-layer area / layer0 area
    overhang = []        # per multi-layer block: frac of upper-layer area OUTSIDE layer0 poly
    pref_gap = []
    pref_bay_area = []

    for bi, b in enumerate(blocks):
        shp = b["shape"]
        o0 = shp[0]["layers"]
        polys0 = [Polygon(l) for l in o0]
        Ks.append(len(o0))
        la = [p.area for p in polys0]
        areas0.append(max(la))
        l0_areas.append(la[0])
        for l, p in zip(o0, polys0):
            vcounts.append(len(l))
            ch = p.convex_hull.area
            convs.append(p.area/ch if ch > 0 else 1)
            minx, miny, maxx, maxy = p.bounds
            bb = (maxx-minx)*(maxy-miny)
            fills.append(p.area/bb if bb > 0 else 1)
        if len(polys0) >= 2:
            p0 = polys0[0]
            ups = polys0[1:]
            shrinks.append(np.mean([p.area/p0.area for p in ups]))
            oh = [max(0.0, p.area - p.intersection(p0).area)/p.area for p in ups]
            overhang.append(np.mean(oh))
        # fit: union bbox over all layers, per orientation
        for j, bay in enumerate(bays):
            ok = False
            for o in shp:
                mnx = min(v[0] for l in o["layers"] for v in l)
                mxx = max(v[0] for l in o["layers"] for v in l)
                mny = min(v[1] for l in o["layers"] for v in l)
                mxy = max(v[1] for l in o["layers"] for v in l)
                if mxx-mnx <= bay["width"] and mxy-mny <= bay["height"]:
                    ok = True; break
            fits[bi, j] = ok
        s = sorted(b["bay_preferences"], reverse=True)
        pref_gap.append(s[0]-s[1])
        pref_bay_area.append(bay_areas[int(np.argmax(b["bay_preferences"]))])

    areas0 = np.array(areas0)
    slack = D - R - P
    agg_slack += list(slack)
    agg_vc += vcounts; agg_conv += convs; agg_fill += fills
    agg_shrink += shrinks; agg_gap += pref_gap
    overhang_frac_all += overhang

    # congestion
    horizon_D = int(D.max())
    demand = float((areas0*P).sum())
    supply_D = tot_bay_area*horizon_D
    # peak instantaneous demand on [R, R+P)
    T = int((R+P).max())+1
    inst = np.zeros(T)
    for a, r, p in zip(areas0, R, P):
        inst[r:r+p] += a
    peak = inst.max(); peak_t = int(inst.argmax())
    # avg concurrency demand over the busy window
    mean_inst = inst[inst > 0].mean()

    Karr = np.array(Ks)
    corr = np.nan
    if np.std(pref_bay_area) > 0 and np.std(areas0) > 0:
        corr = np.corrcoef(pref_bay_area, areas0)[0, 1]

    fit_pct = fits.mean(axis=0)*100  # % blocks fitting per bay
    fit_all = (fits.sum(axis=1) == len(bays)).mean()*100
    fit_one = (fits.sum(axis=1) == 1).mean()*100

    rows.append(dict(
        name=name, n=n, m=len(bays), bayA=tot_bay_area,
        w1=w1, w2=w2, w3=w3,
        maxR=int(R.max()), maxD=horizon_D, sumP=int(P.sum()),
        dsD=demand/supply_D,
        peak=peak/tot_bay_area, mean_inst=mean_inst/tot_bay_area, peak_t=peak_t,
        sl_min=int(slack.min()), sl_med=float(np.median(slack)), sl_mean=float(slack.mean()),
        sl_max=int(slack.max()), sl_neg=float((slack < 0).mean()*100), sl_le0=float((slack <= 0).mean()*100),
        K2=float((Karr >= 2).mean()*100), Kmax=int(Karr.max()),
        shrink=float(np.mean(shrinks)) if shrinks else np.nan,
        oh=float(np.mean(overhang)) if overhang else np.nan,
        gap_med=float(np.median(pref_gap)), gap_mean=float(np.mean(pref_gap)),
        gap0=float((np.array(pref_gap) == 0).mean()*100),
        corr=corr,
        w3w1=w3/w1, w2w1=w2/w1,
        div_days=w3*np.median(pref_gap)/w1,   # tardy-days equivalent of diverting median block
        fit_min=fit_pct.min(), fit_all=fit_all, fit_one=fit_one,
        blkA_med=float(np.median(areas0)), blkA_max=float(areas0.max()),
    ))

# ---- print tables ----
hdr = ["inst","n","m","bayA","w1","w2","w3","maxR","maxD","sumP","d/s(D)","peak","meanI",
       "slMin","slMed","sl<0%","sl<=0%","K>=2%","shrink","ovhg","gapMed","gap0%","corr",
       "w3/w1","divEq(d)","fitMin%","fitAll%","fit1%"]
print("\t".join(hdr))
for r in rows:
    print("\t".join([r["name"], str(r["n"]), str(r["m"]), str(r["bayA"]),
        str(r["w1"]), str(r["w2"]), str(r["w3"]),
        str(r["maxR"]), str(r["maxD"]), str(r["sumP"]),
        f'{r["dsD"]:.2f}', f'{r["peak"]:.2f}', f'{r["mean_inst"]:.2f}',
        str(r["sl_min"]), f'{r["sl_med"]:.0f}', f'{r["sl_neg"]:.0f}', f'{r["sl_le0"]:.0f}',
        f'{r["K2"]:.0f}', f'{r["shrink"]:.2f}' if not math.isnan(r["shrink"]) else "-",
        f'{r["oh"]:.2f}' if not math.isnan(r["oh"]) else "-",
        f'{r["gap_med"]:.0f}', f'{r["gap0"]:.0f}',
        f'{r["corr"]:.2f}' if not math.isnan(r["corr"]) else "-",
        f'{r["w3w1"]*1000:.1f}', f'{r["div_days"]:.3f}',
        f'{r["fit_min"]:.0f}', f'{r["fit_all"]:.0f}', f'{r["fit_one"]:.0f}']))

print()
sl = np.array(agg_slack)
print(f"AGG slack: min={sl.min()} med={np.median(sl):.0f} mean={sl.mean():.1f} max={sl.max()} | %<0={100*(sl<0).mean():.2f} %<=0={100*(sl<=0).mean():.2f} %<=2={100*(sl<=2).mean():.2f} %<=5={100*(sl<=5).mean():.2f}")
vc = np.array(agg_vc); cv = np.array(agg_conv); fl = np.array(agg_fill)
print(f"AGG vertices/layer: min={vc.min()} med={np.median(vc):.0f} mean={vc.mean():.1f} p95={np.percentile(vc,95):.0f} max={vc.max()}")
print(f"AGG convexity(area/hull): med={np.median(cv):.3f} mean={cv.mean():.3f} p05={np.percentile(cv,5):.3f} %<0.95={100*(cv<0.95).mean():.1f} %<0.8={100*(cv<0.8).mean():.1f}")
print(f"AGG bboxfill(area/bbox): med={np.median(fl):.3f} mean={fl.mean():.3f} p05={np.percentile(fl,5):.3f} %<0.7={100*(fl<0.7).mean():.1f} %<0.5={100*(fl<0.5).mean():.1f}")
sh = np.array(agg_shrink); oh = np.array(overhang_frac_all)
print(f"AGG upper-layer/layer0 area ratio (multi-layer blocks): med={np.median(sh):.3f} mean={sh.mean():.3f} p05={np.percentile(sh,5):.3f} p95={np.percentile(sh,95):.3f}")
print(f"AGG overhang frac (upper-layer area outside layer0): med={np.median(oh):.3f} mean={oh.mean():.3f} %>0.01={100*(oh>0.01).mean():.1f} max={oh.max():.3f}")
gp = np.array(agg_gap)
print(f"AGG pref gap best-2nd: med={np.median(gp):.0f} mean={gp.mean():.1f} %=0={100*(gp==0).mean():.1f} %>=50={100*(gp>=50).mean():.1f} max={gp.max()}")
