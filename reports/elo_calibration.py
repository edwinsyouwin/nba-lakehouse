"""Elo win-probability calibration backtest report.

Pulls one row per game (home team's pre-game win prob = analytics_team_elo.
win_expected, and the outcome) and renders a reliability diagram + skill metrics
(Brier, Brier skill score vs the base-rate baseline, log loss, AUC, ECE), plus a
per-season breakdown. Answers: is the Elo actually calibrated, and does it beat
"always pick home"?

Offline-capable: caches raw rows to reports/_elo_raw.csv and reuses them when the
warehouse is unavailable. Safe to run on the refresh schedule.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from databricks import sql

from nba_warehouse import elo_backtest as eb

HERE = Path(__file__).parent
OUT = HERE / "elo_calibration.html"
RAW = HERE / "_elo_raw.csv"
BINS = 10


def fetch() -> pd.DataFrame:
    with sql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"].replace("https://", ""),
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
        catalog=os.environ.get("DATABRICKS_CATALOG", "nba_dev"),
    ) as c:
        cur = c.cursor()
        cur.execute(
            "SELECT e.win_expected AS win_prob, e.won, s.season, s.season_type "
            "FROM gold.analytics_team_elo e JOIN gold.dim_season s USING (season_key) "
            "WHERE e.is_home = true AND e.won IS NOT NULL"
        )
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def load() -> pd.DataFrame | None:
    try:
        df = fetch()
        df.to_csv(RAW, index=False)
        print("data source: warehouse (raw cache refreshed)")
        return df
    except Exception as e:
        if RAW.exists():
            print(f"data source: cache (warehouse unavailable: {type(e).__name__})")
            return pd.read_csv(RAW, dtype={"season": str, "season_type": str})
        print(f"NO DATA YET: warehouse unavailable ({type(e).__name__}) and no {RAW.name}.")
        print("This will generate automatically once the serverless quota resets (cron).")
        return None


HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Elo win-probability calibration</title>
<link rel="icon" href="data:,">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
 body{font:14px -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1117;color:#e6e6e6}
 .wrap{max-width:1000px;margin:0 auto;padding:24px}
 h1{font-size:22px;margin:0 0 4px} h3{margin:24px 0 8px} p.sub{color:#9aa4b2;margin:0 0 16px}
 .cards{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 6px}
 .card{background:#161a23;border:1px solid #232838;border-radius:8px;padding:10px 14px;min-width:120px}
 .card .v{font-size:20px;font-weight:700} .card .k{color:#9aa4b2;font-size:11px;margin-top:2px}
 #reliability{height:460px} #counts{height:220px}
 table{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}
 th,td{padding:4px 8px;text-align:right;border-bottom:1px solid #232838} th:first-child,td:first-child{text-align:left}
 th{background:#161a23;color:#cbd5e1}
</style></head><body><div class="wrap">
<h1>Elo win-probability calibration backtest</h1>
<p class="sub">One row per game — home team's pre-game Elo win probability vs. actual outcome (__N__ games,
__SPAN__). A perfectly calibrated model sits on the diagonal; Brier skill &gt; 0 and AUC &gt; 0.5 mean it beats
"always pick home".</p>

<div class="cards">__CARDS__</div>

<h3>Reliability diagram</h3>
<div id="reliability"></div>
<h3>Prediction distribution</h3>
<div id="counts"></div>

<h3>By season</h3>
<table><tr><th>Season</th><th>Games</th><th>Brier</th><th>Brier skill</th><th>Log loss</th><th>AUC</th><th>ECE</th></tr>
__SEASON_ROWS__</table>

<script>
const REL=__REL__;
Plotly.newPlot('reliability',[
  {x:[0,1],y:[0,1],mode:'lines',line:{dash:'dot',color:'#5b6473'},name:'perfect',hoverinfo:'skip'},
  {x:REL.map(r=>r.mean_pred),y:REL.map(r=>r.actual),text:REL.map(r=>'n='+r.n),
   mode:'lines+markers',name:'Elo',line:{color:'#3b82f6'},
   marker:{size:REL.map(r=>Math.max(6,Math.sqrt(r.n))),color:'#3b82f6',line:{width:1,color:'#cbd5e1'}},
   hovertemplate:'pred %{x:.2f} · actual %{y:.2f}<br>%{text}<extra></extra>'}
],{paper_bgcolor:'#0f1117',plot_bgcolor:'#0f1117',font:{color:'#cbd5e1'},margin:{t:10,r:10,b:44,l:48},
   xaxis:{title:'Predicted home-win probability',range:[0,1],gridcolor:'#232838'},
   yaxis:{title:'Actual home-win rate',range:[0,1],gridcolor:'#232838'},showlegend:false},{responsive:true});
Plotly.newPlot('counts',[{x:REL.map(r=>r.mean_pred),y:REL.map(r=>r.n),type:'bar',marker:{color:'#3b82f6'},
   hovertemplate:'~%{x:.2f}: %{y} games<extra></extra>'}],
  {paper_bgcolor:'#0f1117',plot_bgcolor:'#0f1117',font:{color:'#cbd5e1'},margin:{t:10,r:10,b:44,l:48},
   xaxis:{title:'Predicted probability',range:[0,1],gridcolor:'#232838'},
   yaxis:{title:'Games',gridcolor:'#232838'}},{responsive:true});
</script>
</div></body></html>"""


def card(v, k):
    return f'<div class="card"><div class="v">{v}</div><div class="k">{k}</div></div>'


def render(df: pd.DataFrame):
    m = eb.summarize(df, bins=BINS)
    rel = eb.reliability_table(df, bins=BINS)
    seasons = eb.by_season(df, bins=BINS)
    span = f"{df['season'].min()}–{df['season'].max()}"

    cards = "".join([
        card(f"{m['n']:,}", "games"),
        card(f"{m['brier']:.4f}", "Brier (lower=better)"),
        card(f"{m['brier_skill']*100:.1f}%", "Brier skill vs base rate"),
        card(f"{m['log_loss']:.4f}", "Log loss"),
        card(f"{m['auc']:.3f}", "AUC"),
        card(f"{m['accuracy']*100:.1f}%", "Accuracy (p≥.5)"),
        card(f"{m['ece']:.4f}", "ECE (calibration err)"),
        card(f"{m['base_rate']*100:.1f}%", "Home win rate"),
    ])
    rows = "".join(
        f"<tr><td>{r.season}</td><td>{int(r.n):,}</td><td>{r.brier:.4f}</td>"
        f"<td>{r.brier_skill*100:.1f}%</td><td>{r.log_loss:.4f}</td>"
        f"<td>{r.auc:.3f}</td><td>{r.ece:.4f}</td></tr>"
        for r in seasons.itertuples()
    )
    rel_json = json.dumps([
        {"mean_pred": float(r.mean_pred), "actual": float(r.actual), "n": int(r.n)}
        for r in rel.itertuples()
    ])
    html = (HTML.replace("__N__", f"{m['n']:,}").replace("__SPAN__", span)
                .replace("__CARDS__", cards).replace("__SEASON_ROWS__", rows)
                .replace("__REL__", rel_json))
    OUT.write_text(html)
    print(f"wrote {OUT}  Brier={m['brier']:.4f} skill={m['brier_skill']*100:.1f}% "
          f"AUC={m['auc']:.3f} ECE={m['ece']:.4f}")


def main():
    df = load()
    if df is None:
        return
    render(df)


if __name__ == "__main__":
    main()
