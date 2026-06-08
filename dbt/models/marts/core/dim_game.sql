-- One row per game.
with g as (select * from {{ ref('int_games__deduped') }}),
team_cur as (select team_id, team_sk from {{ ref('dim_team') }} where is_current),
season as (select season_id, season_key from {{ ref('dim_season') }})
select
    {{ dbt_utils.generate_surrogate_key(['g.game_id']) }} as game_sk,
    g.game_id,
    g.game_date,
    cast(date_format(g.game_date, 'yyyyMMdd') as int)     as date_key,
    s.season_key,
    g.home_team_id,
    g.away_team_id,
    ht.team_sk                                            as home_team_sk,
    at.team_sk                                            as away_team_sk,
    g.home_abbreviation,
    g.away_abbreviation,
    g.home_points,
    g.away_points,
    g.home_win,
    (g.home_points + g.away_points)                       as total_points
from g
left join team_cur ht on g.home_team_id = ht.team_id
left join team_cur at on g.away_team_id = at.team_id
left join season s on g.season_id = s.season_id
