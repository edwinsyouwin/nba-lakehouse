-- Collapse the two team-game rows into one canonical game row.
with tg as (select * from {{ ref('stg_team_game') }}),

home as (
    select game_id, game_date, season_id, team_id as home_team_id,
           team_abbreviation as home_abbreviation, points as home_points, win_flag as home_win
    from tg where is_home
),
away as (
    select game_id, team_id as away_team_id,
           team_abbreviation as away_abbreviation, points as away_points
    from tg where not is_home
)
select
    h.game_id,
    h.game_date,
    h.season_id,
    h.home_team_id,
    a.away_team_id,
    h.home_abbreviation,
    a.away_abbreviation,
    h.home_points,
    a.away_points,
    h.home_win
from home h
join away a using (game_id)
