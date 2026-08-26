"""
Reads data/fantasypros.json (+ data/odds.json once that's live) and
renders the static site into _site/index.html, which the GitHub Actions
workflow then deploys to GitHub Pages.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

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
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str
    return dt.strftime("%b %d, %Y %I:%M %p UTC")


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
                rank=p.get("rank_ecr", ""),
                tier=p.get("tier", ""),
                name=p.get("player_name", ""),
                pos=p.get("player_position_id", ""),
                team=p.get("player_team_id", ""),
                bye=p.get("player_bye_week", ""),
                range=f"{p.get('rank_min','?')}-{p.get('rank_max','?')}",
            )
        )
    return "\n".join(rows)


def build_html(fp_data, odds_data):
    consensus = (fp_data or {}).get("consensus_rankings")
    fp_fetched_at = (fp_data or {}).get("fetched_at")
    odds_fetched_at = (odds_data or {}).get("fetched_at")
    has_odds = bool(odds_data and (odds_data.get("game_lines") or odds_data.get("player_props_by_event")))

    ranking_label = "Draft"
    if consensus:
        ranking_label = consensus.get("ranking_type_name", "draft").upper()

    rows_html = build_rankings_rows(consensus)

    odds_status = (
        "<span class='pill live'>live</span>" if has_odds
        else "<span class='pill pending'>pending Odds API key</span>"
    )

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
  header {{ max-width: 1000px; margin: 0 auto 24px; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; }}
  .status-row {{ display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; }}
  .pill {{
    display: inline-block; padding: 4px 10px; border-radius: 999px;
    font-size: 0.78rem; font-weight: 600; border: 1px solid var(--border);
  }}
  .pill.live {{ color: var(--good); border-color: var(--good); }}
  .pill.pending {{ color: var(--warn); border-color: var(--warn); }}
  main {{ max-width: 1000px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
  .panel {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px;
  }}
  .panel h2 {{ margin-top: 0; font-size: 1.1rem; }}
  .panel p.desc {{ color: var(--muted); font-size: 0.88rem; margin-top: -8px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 600; position: sticky; top: 0; background: var(--panel); }}
  tbody tr:hover {{ background: rgba(255,255,255,0.03); }}
  .empty {{ color: var(--muted); text-align: center; padding: 24px; }}
  .table-wrap {{ max-height: 560px; overflow-y: auto; overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }}
  .filters {{ display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }}
  .filters button {{
    background: transparent; color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 4px 10px; font-size: 0.82rem; cursor: pointer;
  }}
  .filters button.active {{ background: var(--accent); border-color: var(--accent); color: white; }}
  .placeholder {{ color: var(--muted); font-size: 0.9rem; padding: 24px; text-align: center; border: 1px dashed var(--border); border-radius: 8px; }}
  footer {{ max-width: 1000px; margin: 24px auto; color: var(--muted); font-size: 0.78rem; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>Vegas Fantasy Value Tool</h1>
  <div class="subtitle">FantasyPros consensus PPR rankings ({ranking_label} type -- switches to true ROS automatically after Week 1) &middot; MJS's league tool</div>
  <div class="status-row">
    <span class="pill live">FantasyPros: last updated {fmt_time(fp_fetched_at)}</span>
    {odds_status}
  </div>
</header>
<main>
  <section class="panel">
    <h2>Consensus PPR Rankings</h2>
    <p class="desc">Overall expert consensus rank (ECR), tier, and expert min-max range. Filter by position below.</p>
    <div class="filters" id="posFilters">
      <button class="active" data-pos="ALL">All</button>
      <button data-pos="QB">QB</button>
      <button data-pos="RB">RB</button>
      <button data-pos="WR">WR</button>
      <button data-pos="TE">TE</button>
      <button data-pos="K">K</button>
      <button data-pos="DST">DST</button>
    </div>
    <div class="table-wrap">
      <table id="rankTable">
        <thead>
          <tr><th>Rank</th><th>Tier</th><th>Player</th><th>Pos</th><th>Team</th><th>Bye</th><th>Range</th></tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>
  </section>

  <section class="panel">
    <h2>Rest-of-Season Value vs. Vegas</h2>
    <p class="desc">Vegas-implied ROS points vs. consensus rank, scored by points-above-replacement. Needs the Odds API player-prop feed.</p>
    <div class="placeholder">Coming online once the Odds API key is configured.</div>
  </section>

  <section class="panel">
    <h2>Weekly Start/Sit</h2>
    <p class="desc">This week's player props converted to projected PPR points, weighted by game implied total.</p>
    <div class="placeholder">Coming online once the Odds API key is configured.</div>
  </section>

  <section class="panel">
    <h2>Betting Edge</h2>
    <p class="desc">No-vig sharp-book consensus vs. each book's price &mdash; value bets and most-likely-to-hit, player props + game lines.</p>
    <div class="placeholder">Coming online once the Odds API key is configured.</div>
  </section>
</main>
<footer>
  Generated {fmt_time(datetime.now(timezone.utc).isoformat())} by a scheduled GitHub Actions run. Odds data last fetched: {fmt_time(odds_fetched_at)}.
</footer>
<script>
  const buttons = document.querySelectorAll('#posFilters button');
  const rows = document.querySelectorAll('#rankTable tbody tr');
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
</script>
</body>
</html>
"""
    return html


def main():
    fp_data = load_json("fantasypros.json")
    odds_data = load_json("odds.json")
    html = build_html(fp_data, odds_data)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(html)
    print(f"Wrote {SITE_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
