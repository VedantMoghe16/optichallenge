# MP_RISK_MEMO — fork-semantics risk review of submission/myalgorithm.py (v2.1)

Scope: `algorithm()` (lines 981–1040) and `_portfolio_worker()` (lines 956–978) of
`/Users/vedantmoghe/Downloads/optichallenge/submission/myalgorithm.py`, against the OGC server
environment (Ubuntu 24.04, CPython 3.12, fork start method via `mp.get_context()`, shapely 2.1.2,
firejail, 4 cores). Claims about CPython internals were verified against
`multiprocessing/queues.py` (`Queue.__init__`, `Queue.get`, `Queue.put`) and
`multiprocessing/util._exit_function` on CPython 3.12/3.13 sources.

---

## 1. Parent thread state at fork time — VERDICT: SAFE

The parent creates `ctx = _mp.get_context()` and `queue = ctx.Queue()` (lines 995–996) and forks
four children at line 1005 before ever touching the queue. CPython's `Queue.put` starts the feeder
thread lazily (`if self._thread is None: self._start_thread()`), and the parent never calls `put`
— it only calls `get`/`get_nowait` (lines 1014, 1026), which spawn no thread; therefore the parent
is single-threaded at every `Process.start()`, and no queue lock (`_rlock`/`_wlock`/`_sem`) is
held at fork time. Children start their own feeder threads post-fork on their first
`put_nowait`/`put` (lines 970, 976), which is the safe direction.

## 2. terminate() on a child mid-put — VERDICT: RISK (low probability, unbounded consequence)

`p.terminate()` (line 1023) sends SIGTERM; if it lands while a child's feeder thread is mid
`write()` of a pickled solution larger than PIPE_BUF (4 KiB — real solutions with hundreds of
operations exceed this), a torn message is left in the pipe, and the parent never sees EOF because
it keeps its own copy of the write fd open (`Queue.__init__` holds `_reader` and `_writer`).
The parent's reads are `queue.get(timeout=wait)` in the collect loop (line 1014, wrapped in
`try/except Exception` at 1013–1018, breaking when no worker is alive) and `queue.get_nowait()`
in the drain loop (line 1026, `except Exception: break` at 1027–1028) — both handle *exceptions*
correctly, but the failure mode of a torn message is not an exception: in CPython's `Queue.get`,
`self._poll(...)` returns True on partial bytes and the subsequent `self._recv_bytes()` blocks
with **no timeout** until the announced byte count arrives, so both `get(timeout=...)` and
`get_nowait()` can hang forever; no `except` clause can fire. Exposure is confined to the
post-terminate drain loop (the collect loop runs before any terminate, so a tear there requires an
external OOM-kill), and probability is low because children's self-deadline
(`child_budget` ending ≈ `collect_margin + 0.5` ≈ 1.7 s before `start+limit`) expires before
`hard_end` (≈ 0.8 s before `start+limit`), so healthy workers exit before terminate ever fires —
but a straggler killed inside its ~0.5 s-throttled `put_nowait` window hangs the parent past the
grader's time limit, which is a zero, not a degraded score.

## 3. firejail / POSIX-semaphore failure — VERDICT: MITIGATED-BY-FALLTHROUGH

`ctx.Queue()` sits at line 996, inside the `try:` opened at line 993, and `Queue.__init__` creates
`ctx.Lock()`, `ctx.Lock()` (wlock) and `ctx.BoundedSemaphore()` **eagerly** at construction, so a
`sem_open`/`/dev/shm` failure raises immediately (milliseconds after `start`), is swallowed by
`except Exception: pass` (lines 1035–1036), and reaches line 1038 with
`remaining = max(0.05, limit - elapsed) ≈ limit` — the single-process `_solve` fall-through runs
with essentially the full budget. One residual sub-hazard: if `Process.start()` fails on worker
k > 0 (e.g. fork EAGAIN), the `except` path does **not** terminate workers 0..k-1, which keep
running as daemons and compete with the fall-through `_solve` for the cpulimit-throttled cores —
a quality degradation, not a correctness failure.

## 4. Boundary math at limit = 20.0, n_blocks = 8 — VERDICT: SAFE

Both `limit >= 20.0` and `n_blocks >= 8` (line 992) are satisfied with equality, so the mp path
runs. Symbolically at limit = 20: `collect_margin = max(1.2, 0.6) = 1.2` (line 997);
`child_budget = max(5.0, 20 − 1.2 − elapsed − 0.5) = max(5.0, 18.3 − elapsed) ≈ 18.3` (lines
998–999, floored at 5.0 so it can never be ≤ 0); `hard_end = start + 20 − max(0.8, 0.4) =
start + 19.2` (line 1008). Inside the child, `_solve` computes `reserve = max(0.20, min(4.0,
0.732)) = 0.732`, so the child's own deadline is ≈ `start + 17.6` and its final blocking `put`
lands ≈ 0.9 s before `hard_end` — children normally exit before terminate. The collect-loop wait
`min(0.5, max(0.05, hard_end − now))` (line 1013) is always ≥ 0.05. No negative or zero interval
exists at either boundary.

## 5. Fork + shapely/GEOS state — VERDICT: SAFE

At fork time the parent has performed no geometry work inside `algorithm()`; pre-fork shapely
state can only exist in the module caches if a *previous* `algorithm()` call in the same process
took the single-process fall-through (line 1039). Every worker's first act inside `_solve` is
`_MOVE_CACHE.clear(); _PAIR_CACHE.clear(); _ORIENT_CACHE.clear()` (lines 772–774) followed by a
fresh `_precompute_geometry(prob_info)` (line 775), so all three caches are cleared **in the
child, post-fork**, and every geometry the child ever queries is built by that child — no
pre-fork shapely object is used post-fork (freeing inherited COW geometries via `dict.clear()` is
plain heap deallocation in the child's own address space and is safe). shapely 2.x uses
per-thread GEOS context handles; since the parent is single-threaded and GEOS-quiescent at fork
(item 1), the child's main thread inherits a valid, unshared context — no known GEOS fork hazard
applies to this pattern.

## 6. daemon=True children + early parent return — VERDICT: SAFE

The parent terminates live workers (lines 1021–1023) and `join(0.05)`s all of them (lines
1031–1032); SIGTERM'd children die in milliseconds, and any unreaped zombie is reaped either by
`Process.start()`'s internal `_cleanup()` on the next `algorithm()` call or by multiprocessing's
atexit `util._exit_function`, which terminates then `join()`s remaining daemon children at
interpreter exit. Under firejail's PID namespace, firejail acts as init and reaps/kills any
orphan when the sandboxed interpreter exits, so nothing can outlive the evaluation. The only
theoretical atexit hang (`join()` without timeout on a child stuck in D-state uninterruptible
I/O) has no plausible trigger here — workers do pure CPU + pipe writes.

---

## Highest residual risk and proposed change

**Highest residual risk: item 2** — the post-terminate drain loop (lines 1024–1030) can block
forever in `queue.get_nowait()` on a message torn by `terminate()`, because `_poll()` succeeds on
partial data and `_recv_bytes()` then blocks without timeout; `except Exception` cannot catch a
hang, and the parent would overshoot the grader's wall clock (score 0 for the instance). The
window is milliseconds wide and only reachable when a straggler is still alive at `hard_end`, but
the consequence is the worst possible one.

**Concrete small change** (new-version file only; v2.1 is frozen): run the drain in a sacrificial
daemon thread with a bounded join, so a torn message costs at most 0.25 s instead of a hang:

```python
import threading

def _drain(q, out):
    try:
        while True:
            out.append(q.get_nowait())
    except Exception:
        pass

items = []
t = threading.Thread(target=_drain, args=(queue, items), daemon=True)
t.start()
t.join(0.25)
for item in items:
    if best is None or item[0] < best[0]:
        best = item
```

Secondary (optional, item 3): in the `except Exception` handler of the mp block, terminate any
already-started workers before falling through, so a partial `Process.start()` failure does not
leave daemons competing with the single-process `_solve` for the throttled cores.
