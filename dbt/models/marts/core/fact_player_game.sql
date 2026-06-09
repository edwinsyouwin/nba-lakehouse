-- Grain: one row per player per game.
{{ config(cluster_by=['game_date', 'team_id']) }}

with pg as (select * from {{ ref('int_player_game__unified') }}),
game as (
    select game_id, game_sk, game_date, date_key, season_key, home_team_id, away_team_id
    from {{ ref('dim_game') }}
),
team_cur as (select team_id, team_sk from {{ ref('dim_team') }} where is_current),
player_cur as (select player_id, player_sk from {{ ref('dim_player') }} where is_current)
select
    {{ dbt_utils.generate_surrogate_key(['pg.game_id', 'pg.player_id']) }} as player_game_sk,
    g.game_sk,
    pg.game_id,
    pg.player_id,
    pg.team_id,
    case when pg.team_id = g.home_team_id then g.away_team_id else g.home_team_id end as opponent_team_id,
    pl.player_sk,
    tc.team_sk,
    g.date_key,
    g.season_key,
    g.game_date,
    pg.player_name,
    pg.position,
    pg.comment,
    (pg.comment is null or pg.comment = '') as did_play,
    pg.seconds_played,
    pg.fgm, pg.fga, pg.fg_pct,
    pg.fg3m, pg.fg3a, pg.fg3_pct,
    pg.ftm, pg.fta, pg.ft_pct,
    pg.oreb, pg.dreb, pg.reb,
    pg.ast, pg.stl, pg.blk, pg.tov, pg.pf,
    pg.points, pg.plus_minus,
    pg.offensive_rating, pg.defensive_rating, pg.net_rating,
    pg.usage_pct, pg.efg_pct, pg.ts_pct, pg.pace, pg.possessions, pg.pie
from pg
join game g on pg.game_id = g.game_id
left join team_cur tc on pg.team_id = tc.team_id
left join player_cur pl on pg.player_id = pl.player_id
