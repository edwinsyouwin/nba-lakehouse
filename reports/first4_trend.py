"""Interactive report: over the last 10 seasons, attribute each season's active
"vets" (>=4 completed seasons) to the team where they spent the first 4 years of
their career.

- Line chart of the per-team trend (Counts <-> % of vet-years toggle, per-point hover)
- Per-season pool summary (active / vets / below-threshold / vet %)
- Bar chart: teams ranked desc by % of vet-years, each bar in the team's primary
  color with its logo as a backdrop. Defaults to the current season; hovering a
  point in the line chart re-renders the bars for that season.

NBA team logos are vendored from React-NBA-Logos (ChrisKatsaras, ISC) and
converted to SVG; see reports/logos/.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pandas as pd
from databricks import sql

N_SEASONS = 10
THRESHOLD = 4
HERE = Path(__file__).parent
OUT = HERE / "first4_trend.html"
LOGO_DIR = HERE / "logos"

# Canonical NBA primary brand colors (current 30 franchises), keyed by current abbr.
COLORS = {
    "ATL": "#E03A3E", "BOS": "#007A33", "BKN": "#000000", "CHA": "#1D1160",
    "CHI": "#CE1141", "CLE": "#860038", "DAL": "#00538C", "DEN": "#0E2240",
    "DET": "#C8102E", "GSW": "#1D428A", "HOU": "#CE1141", "IND": "#002D62",
    "LAC": "#C8102E", "LAL": "#552583", "MEM": "#5D76A9", "MIA": "#98002E",
    "MIL": "#00471B", "MIN": "#0C2340", "NOP": "#0C2340", "NYK": "#006BB6",
    "OKC": "#007AC1", "ORL": "#0077C0", "PHI": "#006BB6", "PHX": "#1D1160",
    "POR": "#E03A3E", "SAC": "#5A2D81", "SAS": "#C4CED4", "TOR": "#CE1141",
    "UTA": "#002B5C", "WAS": "#002B5C",
}


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
    active = df[df.season.isin(seasons)][["pid", "season"]].drop_duplicates()
    completed = {s: df[df.season <= s].groupby("pid")["season"].nunique() for s in seasons}
    active["completed"] = [completed[s].get(p, 0) for p, s in zip(active.pid, active.season)]
    active["is_vet"] = active.completed >= THRESHOLD

    summary = (active.groupby("season")
               .agg(active=("pid", "nunique"), vets=("is_vet", "sum")).reset_index())
    summary["below"] = summary["active"] - summary["vets"]
    summary["vet_pct"] = (100 * summary["vets"] / summary["active"]).round(1)

    vet_attr = active[active.is_vet].merge(attr[["pid", "first4_team"]], on="pid")
    mat = (vet_attr.groupby(["first4_team", "season"]).size()
              .unstack(fill_value=0).reindex(columns=seasons, fill_value=0))
    mat = mat.loc[mat[seasons[-1]].sort_values(ascending=False).index]
    summ = summary.set_index("season").reindex(seasons)
    teams = list(mat.index)
    return dict(
        seasons=seasons, teams=teams,
        counts={t: [int(mat.loc[t][s]) for s in seasons] for t in teams},
        vets=[int(summ.loc[s, "vets"]) for s in seasons],
        active=[int(summ.loc[s, "active"]) for s in seasons],
        below=[int(summ.loc[s, "below"]) for s in seasons],
        vet_pct=[float(summ.loc[s, "vet_pct"]) for s in seasons],
    )


def logo_uris(teams) -> dict:
    out = {}
    for t in teams:
        p = LOGO_DIR / f"{t.lower()}.svg"
        if p.exists():
            out[t] = "data:image/svg+xml;base64," + base64.b64encode(p.read_bytes()).decode()
    return out


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
 .toggle{{margin:6px 0}} .toggle button{{background:#1b2030;color:#cbd5e1;border:1px solid #2a3142;padding:6px 12px;cursor:pointer}}
 .toggle button.on{{background:#3b82f6;color:#fff;border-color:#3b82f6}}
 .summary td.k{{color:#9aa4b2}}
 /* logo-backdrop bar chart */
 #bars{{display:flex;align-items:flex-end;gap:5px;height:360px;padding-top:18px;overflow-x:auto}}
 .barcol{{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;flex:1;min-width:28px}}
 .barval{{font-size:10px;color:#9aa4b2;margin-bottom:3px}}
 .bar{{width:30px;border-radius:4px 4px 0 0;position:relative;box-shadow:inset 0 0 0 1px rgba(255,255,255,.18);
       transition:filter .12s}}
 .bar:hover{{filter:brightness(1.18)}}
 .bar img{{position:absolute;top:4px;left:50%;transform:translateX(-50%);width:24px;height:24px;
           opacity:.95;filter:drop-shadow(0 1px 2px rgba(0,0,0,.55))}}
 .barlbl{{font-size:10px;color:#cbd5e1;margin-top:4px;font-weight:600}}
</style></head><body><div class="wrap">
<h1>Where the league grew up — first-4-years development team</h1>
<p class="sub">Each season's active "vets" (≥4 completed seasons) attributed to the team where they spent the
first 4 years of their career. Click legend entries to toggle teams.</p>

<div class="toggle">
  <button id="bCount" class="on" onclick="setMode('count')">Counts</button>
  <button id="bPct" onclick="setMode('pct')">% of vet-years</button>
</div>
<div id="chart"></div>

<h3 id="barTitle">% of vet-years by team (desc)</h3>
<p class="sub">Current season by default; hover a point in the line chart to see that season. Bars use each team's
primary color with its logo as a backdrop.</p>
<div id="bars"></div>

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
const SEASONS={seasons}, TEAMS={teams}, COUNTS={counts}, VETS={vets}, COLORS={colors}, LOGOS={logos};
const CUR=SEASONS[SEASONS.length-1];
let MODE='count';
function val(t,j){{const c=COUNTS[t][j];return MODE==='count'?c:(VETS[j]?+(100*c/VETS[j]).toFixed(1):0);}}
function pctOf(t,j){{return VETS[j]?+(100*COUNTS[t][j]/VETS[j]).toFixed(1):0;}}
function lineTraces(){{const u=MODE==='pct'?'%':'';
  return TEAMS.map(t=>({{x:SEASONS,y:SEASONS.map((_,j)=>val(t,j)),name:t,mode:'lines+markers',type:'scatter',
    hovertemplate:'<b>'+t+'</b><br>%{{x}}: %{{y}}'+u+'<extra></extra>'}}));}}
function draw(){{return Plotly.react('chart',lineTraces(),{{
   paper_bgcolor:'#0f1117',plot_bgcolor:'#0f1117',font:{{color:'#cbd5e1'}},
   margin:{{t:10,r:10,b:40,l:48}},hovermode:'closest',
   xaxis:{{title:'Season',gridcolor:'#232838'}},
   yaxis:{{title:MODE==='count'?'Active vets':'% of season vet-years',gridcolor:'#232838'}},
   legend:{{orientation:'h',y:-0.18}}}},{{responsive:true}}).then(bindHover);}}
function renderBars(season){{
  const j=SEASONS.indexOf(season);
  const rows=TEAMS.map(t=>({{t,v:pctOf(t,j)}})).sort((a,b)=>b.v-a.v);
  const mx=Math.max(...rows.map(r=>r.v),1), H=300;
  document.getElementById('bars').innerHTML = rows.map(r=>{{
    const h=Math.max(8,Math.round(r.v/mx*H)), col=COLORS[r.t]||'#888', logo=LOGOS[r.t];
    return '<div class="barcol" title="'+r.t+' '+season+': '+r.v+'%">'+
           '<div class="barval">'+r.v+'%</div>'+
           '<div class="bar" style="height:'+h+'px;background:'+col+'">'+
           (logo?'<img src="'+logo+'">':'')+'</div>'+
           '<div class="barlbl">'+r.t+'</div></div>';
  }}).join('');
  document.getElementById('barTitle').textContent=season+(season===CUR?' (current)':'')+' — % of vet-years by team (desc)';
}}
function renderTable(){{
  let h='<tr><th>Team</th>'+SEASONS.map(s=>'<th>'+s+'</th>').join('')+'</tr>';
  for(const t of TEAMS) h+='<tr><td>'+t+'</td>'+SEASONS.map((_,j)=>'<td>'+val(t,j)+(MODE==='pct'?'%':'')+'</td>').join('')+'</tr>';
  document.getElementById('teamTable').innerHTML=h;
  document.getElementById('tblTitle').textContent='Vets attributed, by team × season ('+(MODE==='count'?'counts':'% of vet-years')+')';
}}
function bindHover(){{const gd=document.getElementById('chart');
  if(gd.removeAllListeners){{gd.removeAllListeners('plotly_hover');gd.removeAllListeners('plotly_unhover');}}
  gd.on('plotly_hover',e=>{{if(e.points&&e.points.length)renderBars(e.points[0].x);}});
  gd.on('plotly_unhover',()=>renderBars(CUR));}}
function setMode(m){{MODE=m;
  document.getElementById('bCount').classList.toggle('on',m==='count');
  document.getElementById('bPct').classList.toggle('on',m==='pct');
  draw();renderTable();}}
draw();renderBars(CUR);renderTable();
</script>
</div></body></html>"""


CACHE = HERE / "_cache.json"


def cells(vals, suffix=""):
    return "".join(f"<td>{v}{suffix}</td>" for v in vals)


def render(data):
    s, teams = data["seasons"], data["teams"]
    html = HTML.format(
        seasons=json.dumps(s), teams=json.dumps(teams),
        counts=json.dumps(data["counts"]), vets=json.dumps(data["vets"]),
        colors=json.dumps({t: COLORS.get(t, "#888888") for t in teams}),
        logos=json.dumps(logo_uris(teams)),
        summary_head="".join(f"<th>{x}</th>" for x in s),
        row_active=cells(data["active"]),
        row_vets=cells(data["vets"]),
        row_below=cells(data["below"]),
        row_vetpct=cells(data["vet_pct"], suffix="%"),
    )
    OUT.write_text(html)
    miss = [t for t in teams if t not in logo_uris(teams)]
    print(f"wrote {OUT} ({len(teams)} teams x {len(s)} seasons); logos missing: {miss or 'none'}")


def main():
    try:
        data = compute(fetch())
        CACHE.write_text(json.dumps(data))
        print("data source: warehouse (cache refreshed)")
    except Exception as e:
        if not CACHE.exists():
            raise
        data = json.loads(CACHE.read_text())
        print(f"data source: cache (warehouse unavailable: {type(e).__name__})")
    render(data)


if __name__ == "__main__":
    main()
