"""Instrument the layer-true path: where does the search time go, how often do
contested (overhang) placements get taken, and what happens afterwards?"""
import json, os, sys, time

def main():
    flag = sys.argv[1]           # "0" or "1"
    inst_path = sys.argv[2]
    tl = float(sys.argv[3])
    os.environ["KESTREL_LAYER_TRUE"] = flag
    sys.path.insert(0, ".")
    import myalgorithm as M, utils

    C = {"lt_calls": 0, "lt_accept": 0, "lt_time": 0.0,
         "union_calls": 0, "union_accept": 0, "union_time": 0.0,
         "find_calls": 0, "find_none": 0, "ins_calls": 0, "ins_none": 0,
         "constructs": 0, "sweeps": 0, "ruins": 0}

    if hasattr(M, "_safe_layers_position"):
        _lt = M._safe_layers_position
        def lt(*a, **k):
            C["lt_calls"] += 1
            t0 = time.perf_counter()
            r = _lt(*a, **k)
            C["lt_time"] += time.perf_counter() - t0
            if r: C["lt_accept"] += 1
            return r
        M._safe_layers_position = lt

    _up = M._safe_polygon_position
    def up(*a, **k):
        C["union_calls"] += 1
        t0 = time.perf_counter()
        r = _up(*a, **k)
        C["union_time"] += time.perf_counter() - t0
        if r: C["union_accept"] += 1
        return r
    M._safe_polygon_position = up

    _fib = M._find_in_bay
    def fib(*a, **k):
        C["find_calls"] += 1
        r = _fib(*a, **k)
        if r is None: C["find_none"] += 1
        return r
    M._find_in_bay = fib

    _bi = M._best_insertion
    def bi(*a, **k):
        C["ins_calls"] += 1
        r = _bi(*a, **k)
        if r is None: C["ins_none"] += 1
        return r
    M._best_insertion = bi

    for name, key in (("_construct", "constructs"), ("_single_reinsert_sweep", "sweeps"),
                      ("_ruin_recreate", "ruins")):
        orig = getattr(M, name)
        def mk(orig=orig, key=key):
            def f(*a, **k):
                C[key] += 1
                return orig(*a, **k)
            return f
        setattr(M, name, mk())

    prob = json.load(open(inst_path))
    t0 = time.time()
    obj, sol = M._solve(prob, timelimit=tl, variant=0)
    el = time.time() - t0
    r = utils.check_feasibility(prob, sol)
    out = {"flag": flag, "instance": prob["name"], "elapsed": round(el, 1),
           "objective": r["objective"], "Z1": r["obj1"], "feasible": r["feasible"], **C}
    out["lt_time"] = round(C["lt_time"], 2)
    out["union_time"] = round(C["union_time"], 2)
    print(json.dumps(out))

if __name__ == "__main__":
    main()
