-- DNP players have empty numeric fields, so use try_cast (null = did not play).
with src as (select * from {{ source('bronze', 'boxscoretraditionalv3__PlayerStats') }})
select
    cast(gameId as string)                      as game_id,
    cast(teamId as bigint)                      as team_id,
    cast(teamTricode as string)                 as team_tricode,
    cast(personId as bigint)                    as player_id,
    cast(nameI as string)                       as player_name,
    cast(position as string)                    as position,
    cast(comment as string)                     as comment,
    cast(jerseyNum as string)                   as jersey_num,
    {{ minutes_to_seconds('minutes') }}         as seconds_played,
    try_cast(fieldGoalsMade as int)             as fgm,
    try_cast(fieldGoalsAttempted as int)        as fga,
    try_cast(fieldGoalsPercentage as double)    as fg_pct,
    try_cast(threePointersMade as int)          as fg3m,
    try_cast(threePointersAttempted as int)     as fg3a,
    try_cast(threePointersPercentage as double) as fg3_pct,
    try_cast(freeThrowsMade as int)             as ftm,
    try_cast(freeThrowsAttempted as int)        as fta,
    try_cast(freeThrowsPercentage as double)    as ft_pct,
    try_cast(reboundsOffensive as int)          as oreb,
    try_cast(reboundsDefensive as int)          as dreb,
    try_cast(reboundsTotal as int)              as reb,
    try_cast(assists as int)                    as ast,
    try_cast(steals as int)                     as stl,
    try_cast(blocks as int)                     as blk,
    try_cast(turnovers as int)                  as tov,
    try_cast(foulsPersonal as int)              as pf,
    try_cast(points as int)                     as points,
    try_cast(plusMinusPoints as double)         as plus_minus
from src
-- one row per game-player (tolerant of at-least-once Bronze loads)
qualify row_number() over (partition by gameId, personId order by points desc nulls last) = 1
