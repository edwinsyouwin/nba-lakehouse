-- Grain: one row per field-goal attempt (derived from play-by-play).
{{ config(cluster_by=['game_id']) }}

with pbp as (
    select * from {{ ref('stg_play_by_play') }} where is_field_goal
),
classified as (
    select
        *,
        (lower(description) like '%3pt%') as is_three,
        case
            when lower(description) like '%3pt%' then 'Three Point'
            when shot_distance is null         then 'Unknown'
            when shot_distance <= 4            then 'Restricted Area'
            when shot_distance <= 14           then 'Paint (Non-RA)'
            else 'Mid-Range'
        end as shot_zone
    from pbp
),
game as (select game_id, game_sk, game_date, date_key, season_key from {{ ref('dim_game') }}),
team_cur as (select team_id, team_sk from {{ ref('dim_team') }} where is_current),
player_cur as (select player_id, player_sk from {{ ref('dim_player') }} where is_current),
zone as (select shot_zone, shot_zone_key from {{ ref('dim_shot_zone') }})
select
    {{ dbt_utils.generate_surrogate_key(['c.game_id', 'c.action_number', 'c.action_seq']) }} as shot_sk,
    g.game_sk,
    c.game_id,
    c.player_id,
    pl.player_sk,
    c.team_id,
    tc.team_sk,
    z.shot_zone_key,
    g.date_key,
    g.season_key,
    g.game_date,
    c.period,
    c.shot_zone,
    c.is_three,
    (c.shot_result = 'Made')                         as is_made,
    case when c.is_three then 3 else 2 end           as shot_value,
    case when c.shot_result = 'Made' then (case when c.is_three then 3 else 2 end) else 0 end as points,
    c.shot_distance,
    c.x_legacy,
    c.y_legacy,
    c.description
from classified c
join game g on c.game_id = g.game_id
left join team_cur tc on c.team_id = tc.team_id
left join player_cur pl on c.player_id = pl.player_id
left join zone z on c.shot_zone = z.shot_zone
