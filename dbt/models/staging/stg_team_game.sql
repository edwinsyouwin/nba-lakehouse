-- One row per team per game (the grain of fact_team_game).
-- Older seasons predate some stats (no 3PT before 1979-80, no STL/TOV/OREB
-- splits earlier), so numeric fields use try_cast -> NULL for era-missing values.
with src as (select * from {{ source('bronze', 'leaguegamelog__LeagueGameLog') }})
select
    cast(GAME_ID as string)               as game_id,
    cast(TEAM_ID as bigint)               as team_id,
    cast(TEAM_ABBREVIATION as string)     as team_abbreviation,
    cast(SEASON_ID as string)             as season_id,
    cast(GAME_DATE as date)               as game_date,
    cast(MATCHUP as string)               as matchup,
    case when MATCHUP like '%vs.%' then true else false end as is_home,
    trim(right(MATCHUP, 3))               as opponent_abbreviation,
    cast(WL as string)                    as win_loss,
    case when WL = 'W' then 1 when WL = 'L' then 0 end as win_flag,
    try_cast(MIN as int)                  as team_minutes,
    try_cast(PTS as int)                  as points,
    try_cast(FGM as int)                  as fgm,
    try_cast(FGA as int)                  as fga,
    try_cast(FG_PCT as double)            as fg_pct,
    try_cast(FG3M as int)                 as fg3m,
    try_cast(FG3A as int)                 as fg3a,
    try_cast(FG3_PCT as double)           as fg3_pct,
    try_cast(FTM as int)                  as ftm,
    try_cast(FTA as int)                  as fta,
    try_cast(FT_PCT as double)            as ft_pct,
    try_cast(OREB as int)                 as oreb,
    try_cast(DREB as int)                 as dreb,
    try_cast(REB as int)                  as reb,
    try_cast(AST as int)                  as ast,
    try_cast(STL as int)                  as stl,
    try_cast(BLK as int)                  as blk,
    try_cast(TOV as int)                  as tov,
    try_cast(PF as int)                   as pf,
    try_cast(PLUS_MINUS as double)        as plus_minus
from src
