-- Grain: one row per team per game.
{{ config(cluster_by=['game_date', 'team_id']) }}

with tg as (select * from {{ ref('stg_team_game') }}),
games as (select game_id, home_team_id, away_team_id from {{ ref('int_games__deduped') }}),
team_cur as (select team_id, team_sk from {{ ref('dim_team') }} where is_current),
season as (select season_id, season_key from {{ ref('dim_season') }}),

with_opp as (
    select
        tg.*,
        case when tg.team_id = g.home_team_id then g.away_team_id else g.home_team_id end as opponent_team_id
    from tg
    join games g using (game_id)
)
select
    {{ dbt_utils.generate_surrogate_key(['o.game_id', 'o.team_id']) }} as team_game_sk,
    {{ dbt_utils.generate_surrogate_key(['o.game_id']) }}             as game_sk,
    o.game_id,
    o.team_id,
    o.opponent_team_id,
    tc.team_sk,
    oc.team_sk                                            as opponent_team_sk,
    cast(date_format(o.game_date, 'yyyyMMdd') as int)     as date_key,
    s.season_key,
    o.game_date,
    o.is_home,
    o.win_loss,
    o.win_flag,
    o.team_minutes,
    o.points,
    o.fgm, o.fga, o.fg_pct,
    o.fg3m, o.fg3a, o.fg3_pct,
    o.ftm, o.fta, o.ft_pct,
    o.oreb, o.dreb, o.reb,
    o.ast, o.stl, o.blk, o.tov, o.pf,
    o.plus_minus
from with_opp o
left join team_cur tc on o.team_id = tc.team_id
left join team_cur oc on o.opponent_team_id = oc.team_id
left join season s on o.season_id = s.season_id
