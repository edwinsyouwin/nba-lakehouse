"""Interactive report: over the last 10 seasons, attribute each season's active
"vets" (>=4 completed seasons) to the team where they spent the first 4 years of
their career.

- Line chart: thick, low-opacity team-colored bands. Each data point is the team
  logo (custom DOM overlay). Logos overlap by default; hovering a cluster fans
  them out horizontally (CSS) and shows a per-logo tooltip placed above the point
  so it never overlaps the logos.
- Custom legend: each entry shows the team's logo on its colored line; hovering an
  entry highlights that line and dims the rest.
- Bar chart: teams ranked desc by % of vet-years, bars in team color with logo
  backdrop; follows the line-chart hover season (defaults to current).
- Counts <-> % of vet-years toggle; per-season pool summary; data table.

Logos vendored from React-NBA-Logos (ChrisKatsaras, ISC); see reports/logos/.
Offline-capable: falls back to reports/_cache.json when the warehouse is unavailable.
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
CACHE = HERE / "_cache.json"

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
SECONDARY = {
    "ATL": "#C1D32F", "BOS": "#BA9653", "BKN": "#FFFFFF", "CHA": "#00788C",
    "CHI": "#000000", "CLE": "#FDBB30", "DAL": "#B8C4CA", "DEN": "#FEC524",
    "DET": "#1D42BA", "GSW": "#FFC72C", "HOU": "#C4CED4", "IND": "#FDBB30",
    "LAC": "#1D428A", "LAL": "#FDB927", "MEM": "#F5B112", "MIA": "#F9A01B",
    "MIL": "#EEE1C6", "MIN": "#78BE20", "NOP": "#C8102E", "NYK": "#F58426",
    "OKC": "#EF3B24", "ORL": "#C4CED4", "PHI": "#ED174C", "PHX": "#E56020",
    "POR": "#000000", "SAC": "#63727A", "SAS": "#000000", "TOR": "#B4B5B8",
    "UTA": "#F9A01B", "WAS": "#E31837",
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


def compute(df: pd.DataFrame) -> dict:
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


# Placeholders are replaced (not str.format) so JS braces stay single.
TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>First-4-Years Dev Team — 10yr Trend</title>
<link rel="icon" href="data:,">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
 body{font:14px -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1117;color:#e6e6e6}
 .wrap{max-width:1100px;margin:0 auto;padding:24px}
 h1{font-size:22px;margin:0 0 4px} h3{margin:26px 0 8px} p.sub{color:#9aa4b2;margin:0 0 14px}
 .chartrow{display:flex;gap:14px;align-items:flex-start}
 #chartwrap{position:relative;flex:1;min-width:0}
 #chart{height:560px}
 #logolayer{position:absolute;inset:0;pointer-events:none;z-index:5}
 .cluster{position:absolute;height:16px;transform:translate(-50%,-50%);pointer-events:auto}
 .cluster .dot{position:absolute;left:50%;top:50%;width:13px;height:13px;margin:-6.5px 0 0 -6.5px;
   border-radius:50%;border:2px solid;box-sizing:border-box;cursor:pointer;
   transition:transform .12s, opacity .12s;box-shadow:0 1px 2px rgba(0,0,0,.5)}
 .cluster:hover .dot{transform:translateX(var(--off))}
 .cluster .dot:hover{transform:translateX(var(--off)) scale(1.35);z-index:7}
 #tip{position:absolute;pointer-events:none;background:#161a23;border:1px solid #2a3142;border-radius:6px;
   padding:6px 9px;font-size:12px;color:#e6e6e6;transform:translate(-50%,-100%);max-width:280px;
   display:none;z-index:60;box-shadow:0 4px 14px rgba(0,0,0,.45)}
 #tip .tiphead{font-weight:700;margin-bottom:4px;color:#9aa4b2}
 #tip .tipteam{display:inline-flex;align-items:center;gap:3px;margin:2px 7px 2px 0;font-weight:600}
 #tip .tipteam img{width:15px;height:15px}
 #legend{width:120px;flex:none;display:flex;flex-direction:column;gap:5px;max-height:560px;overflow-y:auto}
 .legrow{display:inline-flex;align-items:center;gap:6px;cursor:pointer;font-size:11px;color:#cbd5e1;opacity:.92}
 .legrow:hover{opacity:1}
 .legline{position:relative;display:inline-block;width:48px;border-top:3px solid;height:0}
 .legline img{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:18px;height:18px}
 .leglbl{font-weight:600}
 .toggle{margin:6px 0} .toggle button{background:#1b2030;color:#cbd5e1;border:1px solid #2a3142;padding:6px 12px;cursor:pointer}
 .toggle button.on{background:#3b82f6;color:#fff;border-color:#3b82f6}
 table{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}
 th,td{padding:4px 8px;text-align:right;border-bottom:1px solid #232838} th:first-child,td:first-child{text-align:left}
 th{position:sticky;top:0;background:#161a23;color:#cbd5e1} tr:hover td{background:#161a23}
 .summary td.k{color:#9aa4b2}
 #bars{display:flex;align-items:flex-end;gap:5px;height:360px;padding-top:18px;overflow-x:auto}
 .barcol{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;flex:1;min-width:28px;transition:opacity .12s;cursor:pointer}
 .barcol.pinned .bar{box-shadow:inset 0 0 0 1px rgba(255,255,255,.18),0 0 0 2px #3b82f6}
 .legrow.pinned{color:#fff;font-weight:700}
 .legrow.pinned .leglbl::after{content:" ●";color:#3b82f6;font-size:9px}
 #teamTable tr{transition:opacity .12s}
 .barval{font-size:10px;color:#9aa4b2;margin-bottom:3px}
 .bar{width:34px;border-radius:4px 4px 0 0;position:relative;overflow:hidden;
   box-shadow:inset 0 0 0 1px rgba(255,255,255,.18);transition:filter .12s}
 .bar:hover{filter:brightness(1.15)} .bar:hover .tint{opacity:.55}
 .bar .logo{position:absolute;inset:0;background-position:center;background-repeat:no-repeat;background-size:cover}
 .bar .tint{position:absolute;inset:0;opacity:.74;transition:opacity .12s}
 .barlbl{font-size:10px;color:#cbd5e1;margin-top:4px;font-weight:600}
</style></head><body><div class="wrap">
<h1>Where the league grew up — first-4-years development team</h1>
<p class="sub">Each season's active "vets" (≥4 completed seasons) attributed to the team where they spent the
first 4 years of their career. Hover a cluster to fan logos apart; hover a legend entry to isolate a team.</p>

<div class="toggle">
  <button id="bCount" class="on" onclick="setMode('count')">Counts</button>
  <button id="bPct" onclick="setMode('pct')">% of vet-years</button>
  <button id="bClear" onclick="clearPins()" style="margin-left:14px">Clear selection</button>
</div>
<div class="chartrow">
  <div id="chartwrap"><div id="chart"></div><div id="logolayer"></div><div id="tip"></div></div>
  <div id="legend"></div>
</div>

<h3 id="barTitle">% of vet-years by team (desc)</h3>
<p class="sub">Current season by default; hover a cluster in the line chart to see that season.</p>
<div id="bars"></div>

<h3>Per-season player pool</h3>
<table class="summary">
 <tr><th>Metric</th>__SUMMARY_HEAD__</tr>
 <tr><td class="k">Active players</td>__ROW_ACTIVE__</tr>
 <tr><td class="k">Vets (≥4 seasons)</td>__ROW_VETS__</tr>
 <tr><td class="k">Below threshold</td>__ROW_BELOW__</tr>
 <tr><td class="k">Vet %</td>__ROW_VETPCT__</tr>
</table>

<h3 id="tblTitle">Vets attributed, by team × season (counts)</h3>
<table id="teamTable"></table>

<script>
const SEASONS=__SEASONS__, TEAMS=__TEAMS__, COUNTS=__COUNTS__, VETS=__VETS__,
      COLORS=__COLORS__, SECOND=__SECOND__, LOGOS=__LOGOS__;
const CUR=SEASONS[SEASONS.length-1], LPX=26;
let MODE='count';
function val(t,j){const c=COUNTS[t][j];return MODE==='count'?c:(VETS[j]?+(100*c/VETS[j]).toFixed(1):0);}
function pctOf(t,j){return VETS[j]?+(100*COUNTS[t][j]/VETS[j]).toFixed(1):0;}

// Dark-page display color: invert near-black primaries (e.g. BKN #000 -> #FFF)
// so they stay visible on the black background; the "negative" of the color.
function _lum(h){const v=i=>parseInt(h.slice(i,i+2),16)/255,f=c=>c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4);
  return 0.2126*f(v(1))+0.7152*f(v(3))+0.0722*f(v(5));}
function _neg(h){const n=i=>(255-parseInt(h.slice(i,i+2),16)).toString(16).padStart(2,'0');return '#'+n(1)+n(3)+n(5);}
function disp(h){h=h||'#888888';return _lum(h)<0.012?_neg(h):h;}
const DCOLORS={}; TEAMS.forEach(t=>DCOLORS[t]=disp(COLORS[t]));

function lineTraces(){
  return TEAMS.map(t=>({x:SEASONS.map((_,j)=>j),y:SEASONS.map((_,j)=>val(t,j)),name:t,
    mode:'lines',type:'scatter',opacity:0.3,hoverinfo:'skip',line:{color:DCOLORS[t],width:11}}));}

function draw(){return Plotly.react('chart',lineTraces(),{
   paper_bgcolor:'#0f1117',plot_bgcolor:'#0f1117',font:{color:'#cbd5e1'},
   margin:{t:10,r:10,b:40,l:48},hovermode:false,showlegend:false,
   xaxis:{title:'Season',gridcolor:'#232838',tickmode:'array',
          tickvals:SEASONS.map((_,j)=>j),ticktext:SEASONS,range:[-0.5,SEASONS.length-0.5]},
   yaxis:{title:MODE==='count'?'Active vets':'% of season vet-years',gridcolor:'#232838'}
 },{responsive:true}).then(layoutLogos);}

function layoutLogos(){
  const gd=document.getElementById('chart'), fl=gd&&gd._fullLayout;
  if(!fl||!fl._size) return;
  const xa=fl.xaxis, ya=fl.yaxis, sp=15, layer=document.getElementById('logolayer');
  layer.innerHTML='';
  for(let j=0;j<SEASONS.length;j++){
    const groups={};
    for(const t of TEAMS){const y=val(t,j);(groups[y]=groups[y]||[]).push(t);}
    for(const y in groups){
      const arr=groups[y], k=arr.length;
      const cx=xa._offset+xa.l2p(j), cy=ya._offset+ya.l2p(+y);
      const c=document.createElement('div'); c.className='cluster';
      c.style.left=cx+'px'; c.style.top=cy+'px'; c.style.width=Math.max(13,k*sp)+'px';
      const season=SEASONS[j];
      arr.forEach((t,i)=>{
        const off=(i-(k-1)/2)*sp;
        const d=document.createElement('div'); d.className='dot'; d.dataset.team=t;
        d.style.background=SECOND[t]||'#fff'; d.style.borderColor=DCOLORS[t]||'#888';
        d.style.setProperty('--off',off+'px');
        c.appendChild(d);
      });
      c.addEventListener('mouseenter',()=>{showCluster(arr,season,val(arr[0],j),cx,cy,k*sp);renderBars(season);});
      c.addEventListener('mouseleave',()=>{hideTip();renderBars(CUR);});
      layer.appendChild(c);
    }
  }
  applyHL();
}
// One tooltip for the whole cluster (all tied teams), placed above the fanned
// row so it never intersects the logos.
function showCluster(arr,season,v,cx,cy,fanW){
  const tip=document.getElementById('tip'), u=MODE==='pct'?'%':'';
  const items=arr.map(t=>'<span class="tipteam">'+(LOGOS[t]?'<img src="'+LOGOS[t]+'">':'')+t+'</span>').join('');
  const head=season+' · '+v+u+(arr.length>1?(' · '+arr.length+' teams'):'');
  tip.innerHTML='<div class="tiphead">'+head+'</div>'+items;
  tip.style.left=cx+'px'; tip.style.top=(cy-13)+'px'; tip.style.display='block';
}
function hideTip(){document.getElementById('tip').style.display='none';}

function buildLegend(){
  const el=document.getElementById('legend');
  el.innerHTML=[...TEAMS].sort().map(t=>'<span class="legrow" data-team="'+t+'">'+
    '<span class="legline" style="border-color:'+DCOLORS[t]+'">'+
    (LOGOS[t]?'<img src="'+LOGOS[t]+'">':'')+'</span><span class="leglbl">'+t+'</span></span>').join('');
  el.querySelectorAll('.legrow').forEach(r=>{
    r.addEventListener('mouseenter',()=>highlight(r.dataset.team));
    r.addEventListener('mouseleave',()=>highlight(null));
  });
}
const PINNED=new Set(); let HOVER=null;
function _active(){const s=new Set(PINNED); if(HOVER)s.add(HOVER); return s;}
function applyHL(){
  const s=_active(), on=s.size>0;
  Plotly.restyle('chart',{opacity:TEAMS.map(t=>on?(s.has(t)?0.95:0.05):0.3)});
  document.querySelectorAll('#logolayer .dot').forEach(d=>{
    d.style.opacity = on?(s.has(d.dataset.team)?'1':'0.12'):'';});
  document.querySelectorAll('#bars .barcol').forEach(b=>{
    b.style.opacity = on?(s.has(b.dataset.team)?'1':'0.22'):'';
    b.classList.toggle('pinned',PINNED.has(b.dataset.team));});
  document.querySelectorAll('#teamTable tr[data-team]').forEach(r=>{
    const sel=s.has(r.dataset.team);
    r.style.opacity = on?(sel?'1':'0.3'):'';
    r.style.background = sel?'rgba(59,130,246,.16)':'';});
  document.querySelectorAll('.legrow').forEach(r=>r.classList.toggle('pinned',PINNED.has(r.dataset.team)));
}
function highlight(team){HOVER=team;applyHL();}              // transient (legend hover)
function togglePin(team){PINNED.has(team)?PINNED.delete(team):PINNED.add(team);applyHL();}  // persistent
function clearPins(){PINNED.clear();applyHL();}

function renderBars(season){
  const j=SEASONS.indexOf(season);
  const rows=TEAMS.map(t=>({t,v:pctOf(t,j)})).sort((a,b)=>b.v-a.v);
  const mx=Math.max(...rows.map(r=>r.v),1), H=300;
  document.getElementById('bars').innerHTML=rows.map(r=>{
    const h=Math.max(8,Math.round(r.v/mx*H)), col=DCOLORS[r.t]||'#888', logo=LOGOS[r.t];
    return '<div class="barcol" data-team="'+r.t+'" title="'+r.t+' '+season+': '+r.v+'%">'+
      '<div class="barval">'+r.v+'%</div>'+
      '<div class="bar" style="height:'+h+'px">'+
      (logo?'<div class="logo" style="background-image:url('+logo+')"></div>':'')+
      '<div class="tint" style="background:'+col+'"></div></div>'+
      '<div class="barlbl">'+r.t+'</div></div>';
  }).join('');
  document.getElementById('barTitle').textContent=season+(season===CUR?' (current)':'')+' — % of vet-years by team (desc)';
  applyHL();
}
function renderTable(){
  let h='<tr><th>Team</th>'+SEASONS.map(s=>'<th>'+s+'</th>').join('')+'</tr>';
  for(const t of TEAMS) h+='<tr data-team="'+t+'"><td>'+t+'</td>'+SEASONS.map((_,j)=>'<td>'+val(t,j)+(MODE==='pct'?'%':'')+'</td>').join('')+'</tr>';
  document.getElementById('teamTable').innerHTML=h;
  document.getElementById('tblTitle').textContent='Vets attributed, by team × season ('+(MODE==='count'?'counts':'% of vet-years')+')';
}
function setMode(m){MODE=m;
  document.getElementById('bCount').classList.toggle('on',m==='count');
  document.getElementById('bPct').classList.toggle('on',m==='pct');
  draw();renderBars(CUR);renderTable();}
let _rz; window.addEventListener('resize',()=>{clearTimeout(_rz);_rz=setTimeout(layoutLogos,250);});
draw();buildLegend();renderBars(CUR);renderTable();
document.getElementById('bars').addEventListener('click',e=>{
  const b=e.target.closest('.barcol'); if(b&&b.dataset.team) togglePin(b.dataset.team);});
</script>
</div></body></html>"""


def cells(vals, suffix=""):
    return "".join(f"<td>{v}{suffix}</td>" for v in vals)


def render(data):
    s, teams = data["seasons"], data["teams"]
    repl = {
        "__SEASONS__": json.dumps(s),
        "__TEAMS__": json.dumps(teams),
        "__COUNTS__": json.dumps(data["counts"]),
        "__VETS__": json.dumps(data["vets"]),
        "__COLORS__": json.dumps({t: COLORS.get(t, "#888888") for t in teams}),
        "__SECOND__": json.dumps({t: SECONDARY.get(t, "#FFFFFF") for t in teams}),
        "__LOGOS__": json.dumps(logo_uris(teams)),
        "__SUMMARY_HEAD__": "".join(f"<th>{x}</th>" for x in s),
        "__ROW_ACTIVE__": cells(data["active"]),
        "__ROW_VETS__": cells(data["vets"]),
        "__ROW_BELOW__": cells(data["below"]),
        "__ROW_VETPCT__": cells(data["vet_pct"], suffix="%"),
    }
    html = TEMPLATE
    for k, v in repl.items():
        html = html.replace(k, v)
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
