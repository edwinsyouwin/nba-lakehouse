-- Grain: one row per player per season per team (regular season).
{{ config(cluster_by=['season', 'team_id']) }}

with pcs as (select * from {{ ref('stg_player_career_season') }}),
player_cur as (select player_id, player_sk, player_name from {{ ref('dim_player') }} where is_current),
team_cur as (select team_id, team_sk from {{ ref('dim_team') }} where is_current),
-- regular-season row of dim_season carries the season_key for a given season label
season as (
    select season, season_key
    from {{ ref('dim_season') }}
    where season_type = 'Regular Season'
)
select
    {{ dbt_utils.generate_surrogate_key(['pcs.player_id', 'pcs.season', 'pcs.team_id']) }} as player_season_sk,
    pcs.player_id,
    pl.player_sk,
    pl.player_name,
    pcs.season,
    s.season_key,
    pcs.team_id,
    tc.team_sk,
    pcs.team_abbreviation,
    pcs.player_age,
    pcs.gp,
    pcs.gs,
    pcs.minutes,
    pcs.points,
    pcs.reb,
    pcs.ast,
    pcs.stl,
    pcs.blk,
    pcs.tov,
    pcs.fgm, pcs.fga, pcs.fg3m, pcs.fg3a, pcs.ftm, pcs.fta
from pcs
left join player_cur pl on pcs.player_id = pl.player_id
left join team_cur tc on pcs.team_id = tc.team_id
left join season s on pcs.season = s.season
