-- One row per (season, season_type) present in the game data.
-- SEASON_ID encodes type in the first char and the start year in the next four:
--   1=Pre Season, 2=Regular Season, 3=All-Star, 4=Playoffs, 5=Play-In
with ids as (
    select distinct season_id from {{ ref('stg_team_game') }}
),
parsed as (
    select
        season_id,
        cast(substr(season_id, 2, 4) as int) as season_start_year,
        substr(season_id, 1, 1)              as type_code
    from ids
)
select
    {{ dbt_utils.generate_surrogate_key(['season_id']) }} as season_key,
    season_id,
    concat(season_start_year, '-', lpad(cast((season_start_year + 1) % 100 as string), 2, '0')) as season,
    season_start_year,
    case type_code
        when '1' then 'Pre Season'
        when '2' then 'Regular Season'
        when '3' then 'All-Star'
        when '4' then 'Playoffs'
        when '5' then 'Play-In'
        else 'Unknown'
    end as season_type
from parsed
