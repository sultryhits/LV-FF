"""
Pulls NFL game lines (spreads/totals) and player props from The Odds API,
saving raw results to data/odds.json.

Requires env var ODDS_API_KEY. If it's not set, this script writes an
empty placeholder and exits cleanly -- it will NOT fail the pipeline, so
the FantasyPros half of the site can go live before you've signed up for
an odds data source.

IMPORTANT -- this part is unverified against a live account (we haven't
gotten an Odds API key yet as of writing this). The market key names
below (player_pass_yds, player_rush_yds, etc.) are The Odds API's
documented NFL player-prop market keys as of their public docs, but
sportsbook APIs change their market catalogs over time. The first time
you run this with a real key, check data/odds.json -- if it's empty or
errors out, the market keys are the first thing to check against
https://the-odds-api.com/sports-odds-data/nfl-odds.html
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "odds.json"

GAME_LINE_MARKETS = "h2h,spreads,totals"
PLAYER_PROP_MARKETS = ",".join([
    "player_pass_yds",
    "player_pass_tds",
    "player_pass_interceptions",
    "player_rush_yds",
    "player_rush_tds",
    "player_receptions",
    "player_reception_yds",
    "player_reception_tds",
    "player_anytime_td",
])


def api_key_or_none():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("ODDS_API_KEY not set -- skipping odds fetch (will retry once configured).", file=sys.stderr)
    return key


def fetch_game_lines(key):
    resp = requests.get(
        f"{BASE_URL}/sports/{SPORT}/odds",
        params={
            "apiKey": key,
            "regions": "us",
            "markets": GAME_LINE_MARKETS,
            "oddsFormat": "american",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Game lines request failed [{resp.status_code}]: {resp.text[:300]}", file=sys.stderr)
        return []
    return resp.json()


def fetch_events(key):
    resp = requests.get(
        f"{BASE_URL}/sports/{SPORT}/events",
        params={"apiKey": key},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Events request failed [{resp.status_code}]: {resp.text[:300]}", file=sys.stderr)
        return []
    return resp.json()


def fetch_player_props_for_event(key, event_id):
    resp = requests.get(
        f"{BASE_URL}/sports/{SPORT}/events/{event_id}/odds",
        params={
            "apiKey": key,
            "regions": "us",
            "markets": PLAYER_PROP_MARKETS,
            "oddsFormat": "american",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Player props request failed for event {event_id} [{resp.status_code}]: {resp.text[:300]}", file=sys.stderr)
        return None
    return resp.json()


def main():
    key = api_key_or_none()
    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "game_lines": [],
        "player_props_by_event": {},
    }

    if key:
        result["game_lines"] = fetch_game_lines(key)
        events = fetch_events(key)
        # Player props are billed per event pulled -- capping how many events
        # we hit per run keeps this predictable against the credit budget.
        # Raise MAX_EVENTS once you've seen real credit usage and know you
        # have headroom.
        MAX_EVENTS = int(os.environ.get("ODDS_MAX_EVENTS", "16"))
        for event in events[:MAX_EVENTS]:
            event_id = event.get("id")
            if not event_id:
                continue
            props = fetch_player_props_for_event(key, event_id)
            if props:
                result["player_props_by_event"][event_id] = props

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2))
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
