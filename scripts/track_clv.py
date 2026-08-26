"""
Snapshots the no-vig consensus fair probability for every game-line and
player-prop selection each time the pipeline runs, and freezes a "closing"
value once that game's kickoff has passed. This is how the Betting Edge tab
validates itself over the season: if the fair number for the sides we'd
flag as value keeps drifting the same direction after we see it, that's
a sharp early read; if it drifts randomly, the model's edge is noise.

Reads data/odds.json (already fetched this run) and updates
data/clv_history.json in place. That history file is intentionally the only
thing in data/ that gets committed back to the repo -- see .gitignore --
since it needs to persist across runs, while fantasypros.json/odds.json are
just full-refresh caches with no need for history.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compute import (  # noqa: E402
    bet_key,
    find_best_bets_game_lines,
    find_best_bets_player_props,
)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ODDS_PATH = DATA_DIR / "odds.json"
HISTORY_PATH = DATA_DIR / "clv_history.json"

PRUNE_CLOSED_AFTER_DAYS = 45


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def main():
    odds_data = load_json(ODDS_PATH, {})
    history = load_json(HISTORY_PATH, {})
    now_iso = datetime.now(timezone.utc).isoformat()

    all_bets = find_best_bets_game_lines(odds_data) + find_best_bets_player_props(odds_data)

    # Multiple books produce multiple rows per (matchup/market/selection),
    # but they all carry the same consensus fair_prob by construction --
    # just take one representative row per key.
    seen = {}
    for bet in all_bets:
        k = bet_key(bet)
        seen.setdefault(k, bet)

    for k, bet in seen.items():
        commence_dt = parse_iso(bet.get("commence_time"))
        is_closed = bool(commence_dt and commence_dt <= datetime.now(timezone.utc))

        entry = history.get(k)
        if entry is None:
            entry = {
                "matchup": bet["matchup"],
                "market": bet["market"],
                "selection": bet["selection"],
                "player": bet.get("player"),
                "line": bet.get("line"),
                "commence_time": bet.get("commence_time"),
                "opening_fair_prob": bet["fair_prob"],
                "opening_observed_at": now_iso,
                "latest_fair_prob": bet["fair_prob"],
                "latest_observed_at": now_iso,
                "closed": False,
            }
            history[k] = entry
        elif not entry.get("closed"):
            entry["latest_fair_prob"] = bet["fair_prob"]
            entry["latest_observed_at"] = now_iso

        if is_closed and not entry.get("closed"):
            entry["closing_fair_prob"] = entry["latest_fair_prob"]
            entry["closed"] = True

    # Keep the file from growing forever -- drop closed entries whose game
    # was long enough ago that we've already learned what we're going to
    # learn from them.
    pruned = {}
    for k, entry in history.items():
        if not entry.get("closed"):
            pruned[k] = entry
            continue
        commence_dt = parse_iso(entry.get("commence_time"))
        if not commence_dt or (datetime.now(timezone.utc) - commence_dt).days <= PRUNE_CLOSED_AFTER_DAYS:
            pruned[k] = entry

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(pruned, indent=2))
    closed_count = sum(1 for e in pruned.values() if e.get("closed"))
    print(f"Tracked {len(pruned)} CLV entries ({closed_count} closed)")


if __name__ == "__main__":
    main()
