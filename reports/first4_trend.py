"""Build an interactive report: over the last 10 seasons, attribute each season's
active, established players (>=4 completed seasons = "vets") to the team where they
spent the first 4 years of their career, and chart the per-team trend.

Includes a per-season summary (vets vs. players below the 4-season threshold) and a
Counts <-> % of vet-years toggle.

Writes reports/first4_trend.html (self-contained, Plotly via CDN).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from databricks import sql

N_SEASONS = 10
THRESHOLD = 4
OUT = Path(__file__).parent / "first4_trend.html"


def fetch() -> pd.DataFrame:
    with sql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"].replace("https://", ""),
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
        catalog=os.environ.get("DATABRICKS_CATALOG", "nba_dev"),
    ) as c:
        cur = c.cursor()
        cur.execute("SELECT player_id, season, team_id, team_abbreviation FROM gold.fact_player_season")
        return pd.DataFrame(cur.fetchall(), columns=["pid", "season", "team_id", "abbr"])


def compute(df: pd.DataFrame):
    label = df.sort_values("season").groupby("team_id")["abbr"].last()
    df = df.copy()
    df["srank"] = df.groupby("pid")["season"].rank(method="dense").astype(int)
    nseason = df.groupby("pid")["season"].nunique()
    elig = nseason[nseason >= THRESHOLD].index
    d = df[df.pid.isin(elig)]
    f4 = d[d.srank <= THRESHOLD]
    g = (f4.groupby(["pid", "team_id"])
           .agg(seasons=("season", "nunique"), first=("season", "min"))
           .reset_index()
           .sort_values(["pid", "seasons", "first"], ascending=[True, False, True]))
    attr = g.groupby("pid").first().reset_index()
    attr["first4_team"] = attr.team_id.map(label)
    established = d[d.srank == THRESHOLD].groupby("pid")["season"].min().rename("established_by")
    attr = attr.merge(established, on="pid")

    seasons = sorted(df["season"].unique())[-N_SEASONS:]

    # every active player per season, with their completed-season count as of that season
    active = df[df.season.isin(seasons)][["pid", "season"]].drop_duplicates()
    completed = {s: df[df.season <= s].groupby("pid")["season"].nunique() for s in seasons}
    active = active.assign(
        completed=lambda x: [completed[s].get(p, 0) for p, s in zip(x.pid, x.season)]
    )
    active["is_vet"] = active.completed >= THRESHOLD

    # per-season summary
    summary = (active.groupby("season")
               .agg(active=("pid", "nunique"), vets=("is_vet", "sum")).reset_index())
    summary["below"] = summary["active"] - summary["vets"]
    summary["vet_pct"] = (100 * summary["vets"] / summary["active"]).round(1)

    # vets attributed to their first-4 team
    vets = active[active.is_vet].merge(attr[["pid", "first4_team"]], on="pid")
    mat = (vets.groupby(["first4_team", "season"]).size()
              .unstack(fill_value=0).reindex(columns=seasons, fill_value=0))
    mat = mat.loc[mat[seasons[-1]].sort_values(ascending=False).index]
    return seasons, mat, summary.set_index("season").reindex(seasons)


HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>First-4-Years Dev Team — 10yr Trend</title>
<link rel="icon" href="data:,">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
 body{{font:14px -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1117;color:#e6e6e6}}
 .wrap{{max-width:1100px;margin:0 auto;padding:24px}}
 h1{{font-size:22px;margin:0 0 4px}} h3{{margin:26px 0 8px}} p.sub{{color:#9aa4b2;margin:0 0 14px}}
 #chart{{height:560px}}
 table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}}
 th,td{{padding:4px 8px;text-align:right;border-bottom:1px solid #232838}} th:first-child,td:first-child{{text-align:left}}
 th{{position:sticky;top:0;background:#161a23;color:#cbd5e1}} tr:hover td{{background:#161a23}}
 .toggle{{margin:6px 0 2px}}
 .toggle button{{background:#1b2030;color:#cbd5e1;border:1px solid #2a3142;padding:6px 12px;cursor:pointer;font-size:13px}}
 .toggle button.on{{background:#3b82f6;color:#fff;border-color:#3b82f6}}
 .summary td.k{{color:#9aa4b2}}
</style></head><body><div class="wrap">
<h1>Where the league grew up — first-4-years development team</h1>
<p class="sub">Each season's active "vets" (players with ≥4 completed seasons) attributed to the team where they
spent the first 4 years of their career. Click legend entries to toggle teams.</p>

<div class="toggle">
  <button id="bCount" class="on" onclick="setMode('count')">Counts</button>
  <button id="bPct" onclick="setMode('pct')">% of vet-years</button>
</div>
<div id="chart"></div>

<h3>Per-season player pool</h3>
<table class="summary">
 <tr><th>Metric</th>{summary_head}</tr>
 <tr><td class="k">Active players</td>{row_active}</tr>
 <tr><td class="k">Vets (≥4 seasons)</td>{row_vets}</tr>
 <tr><td class="k">Below threshold</td>{row_below}</tr>
 <tr><td class="k">Vet %</td>{row_vetpct}</tr>
</table>

<h3 id="tblTitle">Vets attributed, by team × season (counts)</h3>
<table id="teamTable"></table>

<script>
const SEASONS = {seasons};
const TEAMS = {teams};
const COUNTS = {counts};   // team -> [per season]
const VETS = {vets};       // per season vet totals
let MODE = 'count';

function val(team, j){{
  const c = COUNTS[team][j];
  return MODE==='count' ? c : (VETS[j] ? +(100*c/VETS[j]).toFixed(1) : 0);
}}
function traces(){{
  return TEAMS.map(t => ({{x:SEASONS, y:SEASONS.map((_,j)=>val(t,j)), name:t,
                           mode:'lines+markers', type:'scatter'}}));
}}
function draw(){{
  Plotly.react('chart', traces(), {{
    paper_bgcolor:'#0f1117', plot_bgcolor:'#0f1117', font:{{color:'#cbd5e1'}},
    margin:{{t:10,r:10,b:40,l:48}}, hovermode:'x unified',
    xaxis:{{title:'Season',gridcolor:'#232838'}},
    yaxis:{{title: MODE==='count'?'Active vets':'% of season vet-years', gridcolor:'#232838'}},
    legend:{{orientation:'h',y:-0.18}}
  }}, {{responsive:true}});
}}
function renderTable(){{
  let h = '<tr><th>Team</th>'+SEASONS.map(s=>'<th>'+s+'</th>').join('')+'</tr>';
  for(const t of TEAMS){{
    h += '<tr><td>'+t+'</td>'+SEASONS.map((_,j)=>'<td>'+val(t,j)+(MODE==='pct'?'%':'')+'</td>').join('')+'</tr>';
  }}
  document.getElementById('teamTable').innerHTML = h;
  document.getElementById('tblTitle').textContent =
     'Vets attributed, by team × season ('+(MODE==='count'?'counts':'% of vet-years')+')';
}}
function setMode(m){{
  MODE=m;
  document.getElementById('bCount').classList.toggle('on', m==='count');
  document.getElementById('bPct').classList.toggle('on', m==='pct');
  draw(); renderTable();
}}
draw(); renderTable();
</script>
</div></body></html>"""


def cells(vals, suffix=""):
    return "".join(f"<td>{v}{suffix}</td>" for v in vals)


def main():
    df = fetch()
    seasons, mat, summ = compute(df)
    counts = {t: [int(mat.loc[t][s]) for s in seasons] for t in mat.index}
    vets = [int(summ.loc[s, "vets"]) for s in seasons]

    html = HTML.format(
        seasons=json.dumps(seasons),
        teams=json.dumps(list(mat.index)),
        counts=json.dumps(counts),
        vets=json.dumps(vets),
        summary_head="".join(f"<th>{s}</th>" for s in seasons),
        row_active=cells(int(summ.loc[s, "active"]) for s in seasons),
        row_vets=cells(int(summ.loc[s, "vets"]) for s in seasons),
        row_below=cells(int(summ.loc[s, "below"]) for s in seasons),
        row_vetpct=cells((f'{summ.loc[s, "vet_pct"]}' for s in seasons), suffix="%"),
    )
    OUT.write_text(html)
    print(f"wrote {OUT} ({len(mat)} teams x {len(seasons)} seasons)")
    print("vets/season:", dict(zip(seasons, vets)))
    print("below/season:", {s: int(summ.loc[s, "below"]) for s in seasons})


if __name__ == "__main__":
    main()
