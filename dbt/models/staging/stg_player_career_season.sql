-- One row per player per season per team (regular season).
-- Excludes the "TOT" rollup rows (team_id 0) the API emits for traded players,
-- so each row is a real player-team-season stint.
with src as (select * from {{ source('bronze', 'playercareerstats__SeasonTotalsRegularSeason') }})
select
    cast(PLAYER_ID as bigint)             as player_id,
    cast(SEASON_ID as string)             as season,
    try_cast(nullif(TEAM_ID, '0') as bigint) as team_id,
    cast(TEAM_ABBREVIATION as string)     as team_abbreviation,
    try_cast(PLAYER_AGE as int)           as player_age,
    try_cast(GP as int)                   as gp,
    try_cast(GS as int)                   as gs,
    try_cast(MIN as double)               as minutes,
    try_cast(PTS as int)                  as points,
    try_cast(REB as int)                  as reb,
    try_cast(AST as int)                  as ast,
    try_cast(STL as int)                  as stl,
    try_cast(BLK as int)                  as blk,
    try_cast(TOV as int)                  as tov,
    try_cast(FGM as int)                  as fgm,
    try_cast(FGA as int)                  as fga,
    try_cast(FG3M as int)                 as fg3m,
    try_cast(FG3A as int)                 as fg3a,
    try_cast(FTM as int)                  as ftm,
    try_cast(FTA as int)                  as fta
from src
where cast(TEAM_ABBREVIATION as string) <> 'TOT'
  and try_cast(nullif(TEAM_ID, '0') as bigint) is not null
-- one row per player-season-team (tolerant of at-least-once Bronze loads)
qualify row_number() over (
    partition by PLAYER_ID, SEASON_ID, TEAM_ID order by try_cast(GP as int) desc nulls last
) = 1
