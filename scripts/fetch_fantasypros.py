"""
Pulls consensus rankings + projections from the FantasyPros v2 API and
saves the raw results to data/fantasypros.json.

Requires env var FANTASYPROS_API_KEY.

Notes on design:
- We always request type=ROS for consensus-rankings. Before Week 1 of the
  season, FantasyPros' API gracefully falls back to serving Draft rankings
  (it says so in the response itself via "ranking_type_name"/"type") --
  once real rest-of-season rankings exist (after Week 1), this same call
  starts returning them automatically. No code change needed at that
  transition; build_site.py reads the label back out of the response and
  displays whichever one is actually live.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.fantasypros.com/public/v2/json"
SEASON = os.environ.get("FANTASY_SEASON", "2026")
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "fantasypros.json"

POSITIONS_FOR_PROJECTIONS = "QB:RB:WR:TE"


def get(path, params):
    api_key = os.environ.get("FANTASYPROS_API_KEY")
    if not api_key:
        print("FANTASYPROS_API_KEY not set -- skipping FantasyPros fetch.", file=sys.stderr)
        return None
    url = f"{BASE_URL}{path}"
    resp = requests.get(
        url,
        headers={"x-api-key": api_key},
        params=params,
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"FantasyPros request failed [{resp.status_code}] {url} -> {resp.text[:300]}", file=sys.stderr)
        return None
    return resp.json()


def fetch_consensus_rankings():
    return get(
        f"/nfl/{SEASON}/consensus-rankings",
        {"position": "ALL", "scoring": "PPR", "type": "ROS"},
    )


def fetch_projections():
    return get(
        f"/nfl/{SEASON}/projections",
        {"positions": POSITIONS_FOR_PROJECTIONS, "scoring": "PPR", "week": 0},
    )


def main():
    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "consensus_rankings": fetch_consensus_rankings(),
        "projections": fetch_projections(),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2))
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
