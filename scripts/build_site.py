"""
Reads data/fantasypros.json, data/odds.json, and data/clv_history.json and
renders the static site into _site/index.html, which the GitHub Actions
workflow then deploys to GitHub Pages.

All the actual math (PPR conversion, no-vig devig, value-gap ranking) lives
in compute.py -- this file is just presentation.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import compute

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "_site"


def load_json(name):
    path = DATA_DIR / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def fmt_time(iso_str):
    if not iso_str:
        return "never"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return iso_str
    return dt.strftime("%b %d, %Y %I:%M %p UTC")


def fmt_kickoff(iso_str):
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return iso_str
    return dt.strftime("%a %m/%d %I:%M %p UTC")


def esc(val):
    return "" if val is None else str(val)


def signed(n, decimals=1, suffix=""):
    if n is None:
        return "-"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.{decimals}f}{suffix}"


# ---------------------------------------------------------------------------
# Section: Consensus rankings (unchanged from before, still the top panel)
# ---------------------------------------------------------------------------

def build_rankings_rows(consensus):
    if not consensus or "players" not in consensus:
        return "<tr><td colspan='7' class='empty'>No ranking data yet.</td></tr>"
    rows = []
    for p in consensus["players"][:150]:
        rows.append(
            "<tr data-pos=\"{pos}\">"
            "<td>{rank}</td><td>{tier}</td><td>{name}</td><td>{pos}</td>"
            "<td>{team}</td><td>{bye}</td><td>{range}</td>"
            "</tr>".format(
                rank=esc(p.get("rank_ecr")),
                tier=esc(p.get("tier")),
                name=esc(p.get("player_name")),
                pos=esc(p.get("player_position_id")),
                team=esc(p.get("player_team_id")),
                bye=esc(p.get("player_bye_week")),
                range=f"{p.get('rank_min', '?')}-{p.get('rank_max', '?')}",
            )
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Section: Rest-of-season value vs. Vegas
# ---------------------------------------------------------------------------

def build_ros_value_rows(ros_rows):
    if not ros_rows:
        return "<tr><td colspan='8' class='empty'>No matched player-prop data yet -- props are usually posted within about a week of kickoff, so this fills in as game week approaches.</td></tr>"
    out = []
    for r in ros_rows[:150]:
        gap = r["value_gap"]
        gap_class = "good" if gap > 0 else ("warn" if gap < 0 else "")
        out.append(
            "<tr data-pos=\"{pos}\">"
            "<td>{name}</td><td>{pos}</td><td>{team}</td>"
            "<td>{consensus_rank}</td><td>{vegas_rank}</td>"
            "<td class=\"{gap_class}\">{gap}</td>"
            "<td>{weekly}</td><td>{ros}</td>"
            "</tr>".format(
                name=esc(r["name"]), pos=esc(r["pos"]), team=esc(r["team"]),
                consensus_rank=r["consensus_pos_rank"], vegas_rank=r["vegas_pos_rank"],
                gap_class=gap_class, gap=signed(gap, 0),
                weekly=r["weekly_vegas_pts"], ros=r["ros_vegas_pts"],
            )
        )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Section: Weekly start/sit
# ---------------------------------------------------------------------------

def build_startsit_rows(rows):
    if not rows:
        return "<tr><td colspan='6' class='empty'>No matched player-prop data yet for this week.</td></tr>"
    out = []
    for r in rows[:150]:
        implied = r["implied_team_total"]
        out.append(
            "<tr data-pos=\"{pos}\">"
            "<td>{name}</td><td>{pos}</td><td>{team}</td>"
            "<td>{opp}</td><td>{implied}</td><td>{pts}</td>"
            "</tr>".format(
                name=esc(r["name"]), pos=esc(r["pos"]), team=esc(r["team"]),
                opp=esc(r["opponent"]),
                implied=implied if implied is not None else "-",
                pts=r["weekly_vegas_pts"],
            )
        )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Section: Betting edge
# ---------------------------------------------------------------------------

def _bet_label(b):
    if "player" in b:
        line = f" {b['line']}" if b.get("line") is not None else ""
        return f"{b['player']} {b['selection']}{line} ({b['market'].replace('player_', '')})"
    return f"{b['selection']} ({b['market']})"


def build_value_bet_rows(bets):
    if not bets:
        return "<tr><td colspan='6' class='empty'>No priced markets yet.</td></tr>"
    out = []
    for b in bets:
        out.append(
            "<tr>"
            "<td>{matchup}</td><td>{kickoff}</td><td>{bet}</td>"
            "<td>{book}</td><td>{price}</td><td class=\"good\">{ev}</td>"
            "</tr>".format(
                matchup=esc(b["matchup"]), kickoff=fmt_kickoff(b.get("commence_time")),
                bet=_bet_label(b), book=esc(b["book"]),
                price=signed(b["price"], 0), ev=signed(b["ev_pct"], 1, "%"),
            )
        )
    return "\n".join(out)


def build_most_likely_rows(bets):
    if not bets:
        return "<tr><td colspan='5' class='empty'>No priced markets yet.</td></tr>"
    out = []
    for b in bets:
        out.append(
            "<tr>"
            "<td>{matchup}</td><td>{kickoff}</td><td>{bet}</td>"
            "<td>{prob}</td><td>{ev}</td>"
            "</tr>".format(
                matchup=esc(b["matchup"]), kickoff=fmt_kickoff(b.get("commence_time")),
                bet=_bet_label(b), prob=f"{b['fair_prob'] * 100:.1f}%",
                ev=signed(b["ev_pct"], 1, "%"),
            )
        )
    return "\n".join(out)


def build_anytime_td_rows(rows):
    if not rows:
        return "<tr><td colspan='4' class='empty'>No anytime-TD lines posted yet.</td></tr>"
    out = []
    for r in rows:
        out.append(
            "<tr><td>{matchup}</td><td>{player}</td><td>{price}</td><td>{prob}</td></tr>".format(
                matchup=esc(r["matchup"]), player=esc(r["player"]),
                price=signed(r["best_price"], 0), prob=f"{r['implied_prob_pct']:.1f}%",
            )
        )
    return "\n".join(out)


def build_clv_summary(clv_history):
    closed = [e for e in (clv_history or {}).values() if e.get("closed") and e.get("closing_fair_prob") is not None]
    total_tracked = len(clv_history or {})
    if not closed:
        return (
            f"<p class=\"desc\">Tracking {total_tracked} lines since the model went live. "
            "None have reached kickoff yet -- once games start closing, this panel will show whether "
            "the fair number we calculated when we first saw each line moved further in that direction by "
            "closing (a sharp early read) or drifted the other way (noise). That validation only becomes "
            "meaningful over many closed lines across the season, not any single one.</p>"
        )
    deltas = [e["closing_fair_prob"] - e["opening_fair_prob"] for e in closed]
    avg_delta = sum(deltas) / len(deltas)
    favorable = sum(1 for d in deltas if d > 0)
    return (
        f"<p class=\"desc\">{len(closed)} lines closed so far (of {total_tracked} tracked). "
        f"Average movement in the fair number from when we first saw it to kickoff: "
        f"{signed(avg_delta * 100, 2, ' pts')}. "
        f"{favorable}/{len(closed)} moved further toward our early read.</p>"
    )


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

POS_FILTER_HTML = """
<div class="filters" data-target="{table_id}">
  <button class="active" data-pos="ALL">All</button>
  <button data-pos="QB">QB</button>
  <button data-pos="RB">RB</button>
  <button data-pos="WR">WR</button>
  <button data-pos="TE">TE</button>
</div>
"""

POS_FILTER_HTML_ALL = """
<div class="filters" data-target="{table_id}">
  <button class="active" data-pos="ALL">All</button>
  <button data-pos="QB">QB</button>
  <button data-pos="RB">RB</button>
  <button data-pos="WR">WR</button>
  <button data-pos="TE">TE</button>
  <button data-pos="K">K</button>
  <button data-pos="DST">DST</button>
</div>
"""


def build_html(fp_data, odds_data, clv_history):
    consensus = (fp_data or {}).get("consensus_rankings")
    fp_fetched_at = (fp_data or {}).get("fetched_at")
    odds_fetched_at = (odds_data or {}).get("fetched_at")
    odds_data = odds_data or {}
    has_odds = bool(odds_data.get("game_lines") or odds_data.get("player_props_by_event"))

    ranking_label = "Draft"
    if consensus:
        ranking_label = consensus.get("ranking_type_name", "draft").upper()

    current_week = compute.current_season_week()
    player_stat_lines = compute.extract_player_stat_lines(odds_data)
    game_context = compute.extract_game_context(odds_data)

    ros_rows = compute.compute_ros_value(consensus, player_stat_lines, current_week)
    startsit_rows = compute.compute_weekly_startsit(consensus, player_stat_lines, game_context)
    edge = compute.compute_betting_edge(odds_data)

    rankings_html = build_rankings_rows(consensus)
    ros_html = build_ros_value_rows(ros_rows)
    startsit_html = build_startsit_rows(startsit_rows)
    value_bets_html = build_value_bet_rows(edge["value_bets"])
    most_likely_html = build_most_likely_rows(edge["most_likely"])
    anytime_td_html = build_anytime_td_rows(edge["anytime_td"])
    clv_summary_html = build_clv_summary(clv_history)

    odds_status = (
        "<span class='pill live'>live</span>" if has_odds
        else "<span class='pill pending'>pending Odds API key</span>"
    )
    week_label = "preseason (Week 1 lines)" if current_week == 0 else f"Week {current_week}"

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vegas Fantasy Value Tool</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --text: #e8eaed; --muted: #9aa1ac;
    --accent: #4f8cff; --border: #262b35; --good: #3ecf8e; --warn: #e8b339;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 24px;
  }}
  header {{ max-width: 1100px; margin: 0 auto 24px; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; }}
  .status-row {{ display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; }}
  .pill {{
    display: inline-block; padding: 4px 10px; border-radius: 999px;
    font-size: 0.78rem; font-weight: 600; border: 1px solid var(--border);
  }}
  .pill.live {{ color: var(--good); border-color: var(--good); }}
  .pill.pending {{ color: var(--warn); border-color: var(--warn); }}
  main {{ max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
  .panel {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px;
  }}
  .panel h2 {{ margin-top: 0; font-size: 1.1rem; }}
  .panel h3 {{ font-size: 0.95rem; color: var(--muted); margin: 20px 0 8px; }}
  .panel p.desc {{ color: var(--muted); font-size: 0.88rem; margin-top: -8px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 600; position: sticky; top: 0; background: var(--panel); }}
  tbody tr:hover {{ background: rgba(255,255,255,0.03); }}
  td.good {{ color: var(--good); font-weight: 600; }}
  td.warn {{ color: var(--warn); }}
  .empty {{ color: var(--muted); text-align: center; padding: 24px; }}
  .table-wrap {{ max-height: 560px; overflow-y: auto; overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }}
  .table-wrap.short {{ max-height: 420px; }}
  .filters {{ display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }}
  .filters button {{
    background: transparent; color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 4px 10px; font-size: 0.82rem; cursor: pointer;
  }}
  .filters button.active {{ background: var(--accent); border-color: var(--accent); color: white; }}
  .placeholder {{ color: var(--muted); font-size: 0.9rem; padding: 24px; text-align: center; border: 1px dashed var(--border); border-radius: 8px; }}
  footer {{ max-width: 1100px; margin: 24px auto; color: var(--muted); font-size: 0.78rem; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>Vegas Fantasy Value Tool</h1>
  <div class="subtitle">FantasyPros consensus PPR rankings ({ranking_label} type -- switches to true ROS automatically after Week 1) &middot; {week_label} &middot; MJS's league tool</div>
  <div class="status-row">
    <span class="pill live">FantasyPros: last updated {fmt_time(fp_fetched_at)}</span>
    {odds_status}
  </div>
</header>
<main>
  <section class="panel">
    <h2>Consensus PPR Rankings</h2>
    <p class="desc">Overall expert consensus rank (ECR), tier, and expert min-max range. Filter by position below.</p>
    {POS_FILTER_HTML_ALL.format(table_id="rankTable")}
    <div class="table-wrap">
      <table id="rankTable">
        <thead>
          <tr><th>Rank</th><th>Tier</th><th>Player</th><th>Pos</th><th>Team</th><th>Bye</th><th>Range</th></tr>
        </thead>
        <tbody>
          {rankings_html}
        </tbody>
      </table>
    </div>
  </section>

  <section class="panel">
    <h2>Rest-of-Season Value vs. Vegas</h2>
    <p class="desc">This week's Vegas-implied PPR pace &times; estimated games remaining, ranked within position and compared against FantasyPros' consensus positional rank. Positive gap = Vegas likes them more than the fantasy community does (buy/hold); negative = the opposite (sell/fade). Ranked only among players with a posted prop line this week, and games-remaining is an approximation that doesn't fully account for bye weeks against the actual remaining schedule.</p>
    {POS_FILTER_HTML.format(table_id="rosTable")}
    <div class="table-wrap">
      <table id="rosTable">
        <thead>
          <tr><th>Player</th><th>Pos</th><th>Team</th><th>Consensus Pos Rank</th><th>Vegas Pos Rank</th><th>Gap</th><th>Weekly Pts</th><th>ROS Pts</th></tr>
        </thead>
        <tbody>
          {ros_html}
        </tbody>
      </table>
    </div>
  </section>

  <section class="panel">
    <h2>Weekly Start/Sit</h2>
    <p class="desc">This week's player props converted to projected PPR points, alongside the Vegas-implied point total for that player's team (higher implied team total = more expected scoring plays to go around).</p>
    {POS_FILTER_HTML.format(table_id="startsitTable")}
    <div class="table-wrap">
      <table id="startsitTable">
        <thead>
          <tr><th>Player</th><th>Pos</th><th>Team</th><th>Opponent</th><th>Team Implied Total</th><th>Projected PPR Pts</th></tr>
        </thead>
        <tbody>
          {startsit_html}
        </tbody>
      </table>
    </div>
  </section>

  <section class="panel">
    <h2>Betting Edge</h2>
    <p class="desc">Fair probability is a cross-book no-vig consensus (this tier doesn't include a single designated sharp book like Pinnacle, so several major US books are pooled as a proxy). EV% = fair probability &times; that book's payout &minus; 1, so positive EV means that specific book's price beats the consensus. Covers player props and game lines (moneyline/spread/total).</p>

    <h3>Value Bets (highest +EV%)</h3>
    <div class="table-wrap short">
      <table>
        <thead><tr><th>Matchup</th><th>Kickoff</th><th>Bet</th><th>Book</th><th>Price</th><th>EV%</th></tr></thead>
        <tbody>{value_bets_html}</tbody>
      </table>
    </div>

    <h3>Most Likely to Hit (highest fair probability)</h3>
    <div class="table-wrap short">
      <table>
        <thead><tr><th>Matchup</th><th>Kickoff</th><th>Bet</th><th>Fair Prob</th><th>Best EV%</th></tr></thead>
        <tbody>{most_likely_html}</tbody>
      </table>
    </div>

    <h3>Anytime TD (informational -- vig included, no paired "No" line to de-vig against)</h3>
    <div class="table-wrap short">
      <table>
        <thead><tr><th>Matchup</th><th>Player</th><th>Best Price</th><th>Implied Prob</th></tr></thead>
        <tbody>{anytime_td_html}</tbody>
      </table>
    </div>

    <h3>Model Validation: Closing Line Value</h3>
    {clv_summary_html}
  </section>
</main>
<footer>
  Generated {fmt_time(datetime.now(timezone.utc).isoformat())} by a scheduled GitHub Actions run. Odds data last fetched: {fmt_time(odds_fetched_at)}.
</footer>
<script>
  document.querySelectorAll('.filters').forEach(group => {{
    const table = document.getElementById(group.dataset.target);
    if (!table) return;
    const buttons = group.querySelectorAll('button');
    const rows = table.querySelectorAll('tbody tr');
    buttons.forEach(btn => {{
      btn.addEventListener('click', () => {{
        buttons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const pos = btn.dataset.pos;
        rows.forEach(row => {{
          row.style.display = (pos === 'ALL' || row.dataset.pos === pos) ? '' : 'none';
        }});
      }});
    }});
  }});
</script>
</body>
</html>
"""
    return html


def main():
    fp_data = load_json("fantasypros.json")
    odds_data = load_json("odds.json")
    clv_history = load_json("clv_history.json")
    html = build_html(fp_data, odds_data, clv_history)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(html)
    print(f"Wrote {SITE_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
