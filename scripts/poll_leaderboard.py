#!/usr/bin/env python3
"""OGC 2026 leaderboard poller. Pure stdlib.

Fetches the public leaderboard JSON, prints the current tier of every
watchlist team (plus any team names passed on argv), and diffs against
cached snapshots from the last 7 days stored next to this script in
`.leaderboard_cache/`.

Usage:
    python3 scripts/poll_leaderboard.py [extra_team_name ...]
    python3 scripts/poll_leaderboard.py --offline   # reuse newest cached raw fetch

The leaderboard schema is not officially documented, so extraction is
defensive: any dict carrying a team-name-like key is harvested, and its
tier/group is taken from a tier-like sibling key or inherited from an
enclosing group object.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = "https://d32m8h9cownzsg.cloudfront.net/public/leaderboard_group/latest.json"
WATCHLIST = ["tishii24", "古法编程", "ChatOPT", "OPTALL",
             "Qampo", "MSS", "A17"]
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         ".leaderboard_cache")
SEVEN_DAYS = 7 * 86400
PRUNE_AFTER = 30 * 86400

NAME_KEYS = ("team_name", "teamName", "team", "name", "nickname", "team_nm")
TIER_KEYS = ("group_rank", "tier", "group", "group_id", "groupId", "group_no",
             "groupNo", "level", "rank_group", "grade")


def fetch_raw():
    req = urllib.request.Request(URL, headers={"User-Agent": "ogc-poller/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _tier_of(d):
    for k in TIER_KEYS:
        if k in d and isinstance(d[k], (int, float, str)):
            return d[k]
    return None


def extract_teams(raw):
    """Return ({team_name: tier}, {team_name: official_7day_history_str}).

    Fast path: the verified live schema (2026-07) is
        {"generated_at": ..., "leaderboard": [
            {"team_name", "group_rank", "group_rank_7days",
             "nationality", "affiliation"}, ...]}
    Fallback: generic recursive walk for future schema drift.
    """
    tiers, hist = {}, {}
    rows = raw.get("leaderboard") if isinstance(raw, dict) else None
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = r.get("team_name")
            if isinstance(name, str) and name.strip():
                name = name.strip()
                tiers.setdefault(name, _tier_of(r))
                h = r.get("group_rank_7days")
                if isinstance(h, str):
                    hist[name] = h
    if not tiers:
        _walk_teams(raw, None, tiers)
    return tiers, hist


def _walk_teams(node, inherited_tier=None, out=None):
    """Walk arbitrary JSON; return {team_name: tier}."""
    if out is None:
        out = {}
    if isinstance(node, dict):
        tier = _tier_of(node)
        if tier is None:
            tier = inherited_tier
        name = None
        for k in NAME_KEYS:
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                name = v.strip()
                break
        # a dict that has BOTH a name and (somewhere) a tier is a team row;
        # a dict with a tier but no name is likely a group container.
        if name is not None and name not in out:
            out[name] = tier
        for v in node.values():
            _walk_teams(v, tier, out)
    elif isinstance(node, list):
        for v in node:
            _walk_teams(v, inherited_tier, out)
    return out


def load_snapshots():
    """Return [(epoch, {team: tier})] sorted oldest-first."""
    snaps = []
    if not os.path.isdir(CACHE_DIR):
        return snaps
    for fn in os.listdir(CACHE_DIR):
        if not (fn.startswith("snapshot_") and fn.endswith(".json")):
            continue
        path = os.path.join(CACHE_DIR, fn)
        try:
            with open(path) as f:
                d = json.load(f)
            snaps.append((float(d["ts"]), d["teams"], path))
        except (OSError, ValueError, KeyError):
            continue
    snaps.sort(key=lambda s: s[0])
    return snaps


def save_snapshot(ts, teams, raw):
    os.makedirs(CACHE_DIR, exist_ok=True)
    tag = time.strftime("%Y%m%dT%H%M%S", time.localtime(ts))
    with open(os.path.join(CACHE_DIR, "snapshot_%s.json" % tag), "w") as f:
        json.dump({"ts": ts, "teams": teams}, f, ensure_ascii=False)
    with open(os.path.join(CACHE_DIR, "latest_raw.json"), "w") as f:
        json.dump(raw, f, ensure_ascii=False)


def prune(now):
    for ts, _teams, path in load_snapshots():
        if now - ts > PRUNE_AFTER:
            try:
                os.remove(path)
            except OSError:
                pass


def fmt_tier(t):
    return "?" if t is None else str(t)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    offline = "--offline" in sys.argv[1:]
    watch = WATCHLIST + [a for a in args if a not in WATCHLIST]
    now = time.time()

    if offline:
        raw_path = os.path.join(CACHE_DIR, "latest_raw.json")
        try:
            with open(raw_path) as f:
                raw = json.load(f)
        except OSError:
            print("no cached raw fetch at %s (run once without --offline)" % raw_path)
            return 1
    else:
        try:
            raw = fetch_raw()
        except (urllib.error.URLError, OSError, ValueError) as e:
            print("fetch failed: %s" % e)
            return 1

    teams, hist7 = extract_teams(raw)
    if not teams:
        print("WARNING: no team entries recognized in leaderboard JSON "
              "(schema changed?). Raw saved to cache for inspection.")
    print("leaderboard: %d teams extracted @ %s (feed generated_at: %s)"
          % (len(teams),
             time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
             raw.get("generated_at", "?") if isinstance(raw, dict) else "?"))

    prev = [s for s in load_snapshots() if now - s[0] <= SEVEN_DAYS]
    last = prev[-1] if prev else None

    print()
    print("%-24s %-6s %-10s %-22s %s"
          % ("team", "tier", "vs last", "official 7d (old->new)", "our snapshots"))
    print("-" * 96)
    for name in watch:
        tier = teams.get(name)
        marker = "" if name in teams else "  (NOT FOUND on board)"
        if last is not None:
            old = last[1].get(name)
            if old is None and tier is None:
                delta = "-"
            elif old == tier:
                delta = "="
            else:
                delta = "%s->%s" % (fmt_tier(old), fmt_tier(tier))
        else:
            delta = "(no cache)"
        snap_hist = " ".join(fmt_tier(s[1].get(name)) for s in prev) or "-"
        print("%-24s %-6s %-10s %-22s %s%s"
              % (name, fmt_tier(tier), delta, hist7.get(name, "-"),
                 snap_hist, marker))

    # movement outside the watchlist vs the last snapshot (tier changes only)
    if last is not None:
        moved = []
        for name, tier in teams.items():
            old = last[1].get(name)
            if old is not None and old != tier and name not in watch:
                moved.append((name, old, tier))
        if moved:
            print()
            print("other tier movement since %s (%d teams):"
                  % (time.strftime("%m-%d %H:%M", time.localtime(last[0])), len(moved)))
            for name, old, new in sorted(moved)[:40]:
                print("  %-24s %s -> %s" % (name, fmt_tier(old), fmt_tier(new)))

    if not offline:
        save_snapshot(now, teams, raw)
        prune(now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
