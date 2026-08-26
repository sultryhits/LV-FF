"""
Shared computation logic: turns raw FantasyPros + Odds API JSON into the
three derived views the site shows (Rest-of-Season Value, Weekly Start/Sit,
Betting Edge). Kept separate from build_site.py so the math is easy to find
and re-test on its own.

Nothing in here hits the network -- it only transforms already-fetched
data/fantasypros.json and data/odds.json. Every function is defensive about
missing/malformed keys (empty lists in, empty lists out) since this runs
unattended in GitHub Actions with no one watching for a stack trace.
"""
import re
from datetime import date, datetime, timezone

# ---------------------------------------------------------------------------
# Odds math
# ---------------------------------------------------------------------------

def american_to_prob(price):
    """Raw (vig-included) implied probability from an American odds price."""
    if price is None:
        return None
    if price > 0:
        return 100.0 / (price + 100.0)
    return -price / (-price + 100.0)


def american_to_decimal(price):
    if price is None:
        return None
    if price > 0:
        return 1.0 + price / 100.0
    return 1.0 + 100.0 / (-price)


def devig_two_way(price_a, price_b):
    """
    Remove the vig from a two-outcome market (Over/Under, a spread's two
    sides, a moneyline's two sides) and return (fair_prob_a, fair_prob_b)
    that sum to exactly 1.0.
    """
    pa = american_to_prob(price_a)
    pb = american_to_prob(price_b)
    if pa is None or pb is None:
        return None, None
    total = pa + pb
    if total <= 0:
        return None, None
    return pa / total, pb / total


def devig_market_outcomes(outcomes_by_book):
    """
    outcomes_by_book: list of (book_title, [(name_a, price_a), (name_b, price_b)])
    for the SAME two-way market (same line) across multiple books.

    Returns {outcome_name: consensus_fair_prob}, averaging the no-vig fair
    probability for each side across every book that posted it. This
    cross-book average is our "sharp consensus" proxy -- the free tier of
    the odds feed doesn't give us a single designated sharp book (like
    Pinnacle), so we approximate one by pooling the major US books instead.
    """
    fair_probs = {}
    for _book_title, outcomes in outcomes_by_book:
        if len(outcomes) != 2:
            continue
        (name_a, price_a), (name_b, price_b) = outcomes
        fa, fb = devig_two_way(price_a, price_b)
        if fa is None:
            continue
        fair_probs.setdefault(name_a, []).append(fa)
        fair_probs.setdefault(name_b, []).append(fb)
    return {name: sum(vals) / len(vals) for name, vals in fair_probs.items() if vals}


# ---------------------------------------------------------------------------
# Name / team matching helpers
# ---------------------------------------------------------------------------

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name):
    """Lowercase, strip punctuation/suffixes, so 'A.J. Brown' == 'aj brown'."""
    if not name:
        return ""
    n = name.lower().strip().replace(".", "").replace("'", "")
    n = re.sub(r"[^a-z0-9\s\-]", "", n)
    parts = [p for p in n.split() if p not in _SUFFIXES]
    return " ".join(parts)


# FantasyPros uses short abbreviations; the Odds API uses full team names.
# Used only to attach game context (implied total, opponent) to a player --
# never used for the FantasyPros<->Odds player match itself, which is by name.
TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAC",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
# A couple of common abbreviation variants FantasyPros may use.
_ABBR_ALIASES = {"JAX": "JAC", "LA": "LAR", "WSH": "WAS"}


def _abbr_matches(fp_abbr, full_team_name):
    if not fp_abbr or not full_team_name:
        return False
    fp_abbr = _ABBR_ALIASES.get(fp_abbr, fp_abbr)
    return TEAM_ABBR.get(full_team_name) == fp_abbr


# ---------------------------------------------------------------------------
# Season week / games-remaining helpers
# ---------------------------------------------------------------------------

# Tuesday before the Week 1 opener (Wed Sept 9, 2026) -- a "football week"
# runs Tue-to-Tue so Thu/Sun/Mon games of the same slate land together.
_SEASON_WEEK1_START = date(2026, 9, 8)
REGULAR_SEASON_WEEKS = 18
GAMES_PER_TEAM = 17  # 18 weeks, one bye


def current_season_week(today=None):
    """Returns 0 during the preseason, else 1-18."""
    today = today or datetime.now(timezone.utc).date()
    if today < _SEASON_WEEK1_START:
        return 0
    delta_days = (today - _SEASON_WEEK1_START).days
    week = delta_days // 7 + 1
    return max(1, min(week, REGULAR_SEASON_WEEKS))


def games_remaining_for_player(current_week, bye_week):
    """
    Approximate games left this season. Doesn't attempt to reconstruct each
    team's full remaining schedule -- just "weeks left" minus a bye if it
    hasn't happened yet. Good enough for a pace-based estimate; treat the
    resulting rest-of-season total as directional, not exact.
    """
    if current_week <= 0:
        base = GAMES_PER_TEAM
    else:
        base = max(0, GAMES_PER_TEAM - (current_week - 1))
    try:
        bye_week = int(bye_week)
    except (TypeError, ValueError):
        bye_week = None
    if bye_week and current_week <= bye_week <= REGULAR_SEASON_WEEKS:
        base = max(0, base - 1)
    return base


# ---------------------------------------------------------------------------
# PPR scoring
# ---------------------------------------------------------------------------

STAT_MARKET_MAP = {
    "player_pass_yds": "pass_yds",
    "player_pass_tds": "pass_td",
    "player_pass_interceptions": "interceptions",
    "player_rush_yds": "rush_yds",
    "player_rush_tds": "rush_td",
    "player_receptions": "receptions",
    "player_reception_yds": "rec_yds",
    "player_reception_tds": "rec_td",
}


def ppr_points(stats):
    return (
        0.04 * stats.get("pass_yds", 0)
        + 4 * stats.get("pass_td", 0)
        - 2 * stats.get("interceptions", 0)
        + 0.1 * stats.get("rush_yds", 0)
        + 6 * stats.get("rush_td", 0)
        + 1 * stats.get("receptions", 0)
        + 0.1 * stats.get("rec_yds", 0)
        + 6 * stats.get("rec_td", 0)
    )


def extract_player_stat_lines(odds_data):
    """
    Walk every event's player-prop markets and build, per player:
        { stats: {pass_yds: 232.5, receptions: 6.5, ...}, home_team, away_team, commence_time }
    The Over/Under "point" value is the book's number for that stat -- an
    efficient-market estimate of the expected outcome -- so we use it
    directly as the projected stat. When multiple books post slightly
    different lines for the same player/stat, we average them.
    """
    player_stats = {}
    for event_id, event in (odds_data.get("player_props_by_event") or {}).items():
        if not event:
            continue
        for bk in event.get("bookmakers", []) or []:
            for market in bk.get("markets", []) or []:
                stat_key = STAT_MARKET_MAP.get(market.get("key"))
                if not stat_key:
                    continue
                for outcome in market.get("outcomes", []) or []:
                    if outcome.get("name") != "Over":
                        continue
                    player_name = outcome.get("description")
                    point = outcome.get("point")
                    if not player_name or point is None:
                        continue
                    key = normalize_name(player_name)
                    entry = player_stats.setdefault(key, {
                        "display_name": player_name,
                        "event_id": event_id,
                        "commence_time": event.get("commence_time"),
                        "home_team": event.get("home_team"),
                        "away_team": event.get("away_team"),
                        "stats": {},
                    })
                    entry["stats"].setdefault(stat_key, []).append(point)
    for entry in player_stats.values():
        for stat_key, values in list(entry["stats"].items()):
            entry["stats"][stat_key] = sum(values) / len(values)
    return player_stats


def extract_game_context(odds_data):
    """
    Returns { full_team_name: {implied_total, opponent, commence_time,
    spread, is_home, game_total} }, averaged across books.
    """
    context = {}
    for game in odds_data.get("game_lines") or []:
        home = game.get("home_team")
        away = game.get("away_team")
        commence = game.get("commence_time")
        totals_vals, home_spreads, away_spreads = [], [], []
        for bk in game.get("bookmakers", []) or []:
            for market in bk.get("markets", []) or []:
                if market.get("key") == "totals":
                    for o in market.get("outcomes", []) or []:
                        if o.get("name") == "Over" and o.get("point") is not None:
                            totals_vals.append(o["point"])
                elif market.get("key") == "spreads":
                    for o in market.get("outcomes", []) or []:
                        if o.get("point") is None:
                            continue
                        if o.get("name") == home:
                            home_spreads.append(o["point"])
                        elif o.get("name") == away:
                            away_spreads.append(o["point"])
        if not totals_vals or (not home_spreads and not away_spreads):
            continue
        total = sum(totals_vals) / len(totals_vals)
        if home_spreads:
            home_spread = sum(home_spreads) / len(home_spreads)
        else:
            home_spread = -(sum(away_spreads) / len(away_spreads))
        away_spread = -home_spread
        implied_home = total / 2 - home_spread / 2
        implied_away = total / 2 - away_spread / 2
        context[home] = {"implied_total": round(implied_home, 1), "opponent": away,
                          "commence_time": commence, "spread": home_spread,
                          "is_home": True, "game_total": round(total, 1)}
        context[away] = {"implied_total": round(implied_away, 1), "opponent": home,
                          "commence_time": commence, "spread": away_spread,
                          "is_home": False, "game_total": round(total, 1)}
    return context


def _resolve_team_context(prop_entry, fp_team_abbr, game_context):
    home, away = prop_entry.get("home_team"), prop_entry.get("away_team")
    if _abbr_matches(fp_team_abbr, home):
        return game_context.get(home)
    if _abbr_matches(fp_team_abbr, away):
        return game_context.get(away)
    return None


# ---------------------------------------------------------------------------
# Rest-of-season value vs. FantasyPros consensus
# ---------------------------------------------------------------------------

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")


def compute_ros_value(fp_consensus, player_stat_lines, current_week):
    """
    For each FantasyPros player matched to a posted prop line, extrapolate a
    rest-of-season Vegas-implied PPR total (this week's implied pace x games
    remaining), then rank players within their position by that estimate and
    by FantasyPros consensus rank, surfacing the biggest gaps as value.

    Caveat surfaced in the UI: positional rank here is computed only among
    players who have a posted prop line this week (mostly likely starters +
    clear pass-catchers), not the full depth chart FantasyPros ranks.
    """
    if not fp_consensus or "players" not in fp_consensus:
        return []
    rows = []
    for p in fp_consensus["players"]:
        name = p.get("player_name")
        pos = p.get("player_position_id")
        if not name or pos not in SKILL_POSITIONS:
            continue
        prop_entry = player_stat_lines.get(normalize_name(name))
        if not prop_entry:
            continue
        weekly_pts = ppr_points(prop_entry["stats"])
        if weekly_pts <= 0:
            continue
        gr = games_remaining_for_player(current_week, p.get("player_bye_week"))
        rows.append({
            "name": name,
            "pos": pos,
            "team": p.get("player_team_id"),
            "consensus_rank": p.get("rank_ecr") or 9999,
            "weekly_vegas_pts": round(weekly_pts, 1),
            "games_remaining": gr,
            "ros_vegas_pts": round(weekly_pts * gr, 1),
        })

    by_pos = {}
    for row in rows:
        by_pos.setdefault(row["pos"], []).append(row)
    for plist in by_pos.values():
        plist.sort(key=lambda r: r["consensus_rank"])
        for i, row in enumerate(plist, start=1):
            row["consensus_pos_rank"] = i
        plist.sort(key=lambda r: r["ros_vegas_pts"], reverse=True)
        for i, row in enumerate(plist, start=1):
            row["vegas_pos_rank"] = i
        for row in plist:
            row["value_gap"] = row["consensus_pos_rank"] - row["vegas_pos_rank"]

    all_rows = [row for plist in by_pos.values() for row in plist]
    all_rows.sort(key=lambda r: r["value_gap"], reverse=True)
    return all_rows


# ---------------------------------------------------------------------------
# Weekly start/sit
# ---------------------------------------------------------------------------

def compute_weekly_startsit(fp_consensus, player_stat_lines, game_context):
    if not fp_consensus or "players" not in fp_consensus:
        return []
    rows = []
    for p in fp_consensus["players"]:
        name = p.get("player_name")
        pos = p.get("player_position_id")
        if not name or pos not in SKILL_POSITIONS:
            continue
        prop_entry = player_stat_lines.get(normalize_name(name))
        if not prop_entry:
            continue
        weekly_pts = ppr_points(prop_entry["stats"])
        if weekly_pts <= 0:
            continue
        ctx = _resolve_team_context(prop_entry, p.get("player_team_id"), game_context)
        if ctx:
            opponent = ctx["opponent"]
            implied_total = ctx["implied_total"]
        else:
            home, away = prop_entry.get("home_team"), prop_entry.get("away_team")
            opponent = away if _abbr_matches(p.get("player_team_id"), home) else home
            implied_total = None
        rows.append({
            "name": name, "pos": pos, "team": p.get("player_team_id"),
            "opponent": opponent, "implied_team_total": implied_total,
            "weekly_vegas_pts": round(weekly_pts, 1),
            "consensus_rank": p.get("rank_ecr"),
        })
    rows.sort(key=lambda r: r["weekly_vegas_pts"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Betting edge
# ---------------------------------------------------------------------------

def find_best_bets_game_lines(odds_data):
    results = []
    for game in odds_data.get("game_lines") or []:
        home, away = game.get("home_team"), game.get("away_team")
        matchup = f"{away} @ {home}"
        commence = game.get("commence_time")
        market_books = {"h2h": [], "spreads": [], "totals": []}
        for bk in game.get("bookmakers", []) or []:
            title = bk.get("title")
            for market in bk.get("markets", []) or []:
                mk = market.get("key")
                if mk not in market_books:
                    continue
                outs = [(o["name"], o.get("price")) for o in market.get("outcomes", []) or []
                        if o.get("price") is not None]
                if len(outs) == 2:
                    market_books[mk].append((title, outs))
        for mk, books_outcomes in market_books.items():
            if not books_outcomes:
                continue
            fair = devig_market_outcomes(books_outcomes)
            if not fair:
                continue
            for title, outs in books_outcomes:
                for name, price in outs:
                    fp = fair.get(name)
                    if fp is None:
                        continue
                    dec = american_to_decimal(price)
                    ev = fp * dec - 1
                    results.append({
                        "matchup": matchup, "commence_time": commence,
                        "market": mk, "selection": name, "book": title,
                        "price": price, "fair_prob": round(fp, 4),
                        "ev_pct": round(ev * 100, 2),
                    })
    return results


def find_best_bets_player_props(odds_data):
    results = []
    for event_id, event in (odds_data.get("player_props_by_event") or {}).items():
        if not event:
            continue
        matchup = f"{event.get('away_team')} @ {event.get('home_team')}"
        commence = event.get("commence_time")
        grouped = {}
        for bk in event.get("bookmakers", []) or []:
            title = bk.get("title")
            for market in bk.get("markets", []) or []:
                mk = market.get("key")
                if mk == "player_anytime_td" or mk not in STAT_MARKET_MAP:
                    continue
                by_player = {}
                for o in market.get("outcomes", []) or []:
                    name = o.get("description")
                    side = o.get("name")
                    price = o.get("price")
                    point = o.get("point")
                    if not name or side not in ("Over", "Under") or price is None:
                        continue
                    by_player.setdefault(name, {})[side] = (price, point)
                for player_name, sides in by_player.items():
                    if "Over" in sides and "Under" in sides:
                        key = (mk, player_name, sides["Over"][1])
                        grouped.setdefault(key, []).append(
                            (title, [("Over", sides["Over"][0]), ("Under", sides["Under"][0])])
                        )
        for (mk, player_name, point), books_outcomes in grouped.items():
            fair = devig_market_outcomes(books_outcomes)
            if not fair:
                continue
            for title, outs in books_outcomes:
                for name, price in outs:
                    fp = fair.get(name)
                    if fp is None:
                        continue
                    dec = american_to_decimal(price)
                    ev = fp * dec - 1
                    results.append({
                        "matchup": matchup, "commence_time": commence,
                        "market": mk, "player": player_name, "line": point,
                        "selection": name, "book": title, "price": price,
                        "fair_prob": round(fp, 4), "ev_pct": round(ev * 100, 2),
                    })
    return results


def find_anytime_td_probabilities(odds_data):
    """
    Anytime-TD markets don't have a paired "No" outcome to de-vig against, so
    this is a raw (vig-included) implied probability from the best price
    seen across books -- informational, not an EV calculation.
    """
    results = []
    for event_id, event in (odds_data.get("player_props_by_event") or {}).items():
        if not event:
            continue
        matchup = f"{event.get('away_team')} @ {event.get('home_team')}"
        prices_by_player = {}
        for bk in event.get("bookmakers", []) or []:
            for market in bk.get("markets", []) or []:
                if market.get("key") != "player_anytime_td":
                    continue
                for o in market.get("outcomes", []) or []:
                    name = o.get("description")
                    price = o.get("price")
                    if not name or price is None:
                        continue
                    prices_by_player.setdefault(name, []).append(price)
        for player, prices in prices_by_player.items():
            best_price = max(prices)
            avg_implied = sum(american_to_prob(p) for p in prices) / len(prices)
            results.append({
                "matchup": matchup, "player": player,
                "best_price": best_price,
                "implied_prob_pct": round(avg_implied * 100, 1),
            })
    return results


def compute_betting_edge(odds_data):
    game_bets = find_best_bets_game_lines(odds_data)
    prop_bets = find_best_bets_player_props(odds_data)
    all_bets = game_bets + prop_bets
    value_bets = sorted([b for b in all_bets if b["ev_pct"] > 0],
                         key=lambda b: b["ev_pct"], reverse=True)[:40]
    most_likely = sorted(all_bets, key=lambda b: b["fair_prob"], reverse=True)[:40]
    anytime_td = sorted(find_anytime_td_probabilities(odds_data),
                         key=lambda b: b["implied_prob_pct"], reverse=True)[:30]
    return {"value_bets": value_bets, "most_likely": most_likely, "anytime_td": anytime_td}


def bet_key(bet):
    """Stable id for a bet used by track_clv.py to snapshot it over time."""
    if "player" in bet:
        return f"prop|{bet['matchup']}|{bet['market']}|{bet['player']}|{bet.get('line')}|{bet['selection']}"
    return f"game|{bet['matchup']}|{bet['market']}|{bet['selection']}"
