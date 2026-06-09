-- Grain: one row per play-by-play event.
{{ config(cluster_by=['game_id']) }}

with pbp as (select * from {{ ref('stg_play_by_play') }}),
game as (select game_id, game_sk, date_key, season_key from {{ ref('dim_game') }}),
team_cur as (select team_id, team_sk from {{ ref('dim_team') }} where is_current),
player_cur as (select player_id, player_sk from {{ ref('dim_player') }} where is_current)
select
    {{ dbt_utils.generate_surrogate_key(['pbp.game_id', 'pbp.action_number', 'pbp.action_seq']) }} as event_sk,
    g.game_sk,
    pbp.game_id,
    pbp.action_number,
    pbp.action_seq,
    pbp.period,
    pbp.clock,
    pbp.team_id,
    tc.team_sk,
    pbp.player_id,
    pl.player_sk,
    g.date_key,
    g.season_key,
    pbp.action_type,
    pbp.sub_type,
    pbp.description,
    pbp.score_home,
    pbp.score_away,
    pbp.is_field_goal,
    pbp.shot_result
from pbp
join game g on pbp.game_id = g.game_id
left join team_cur tc on pbp.team_id = tc.team_id
left join player_cur pl on pbp.player_id = pl.player_id
