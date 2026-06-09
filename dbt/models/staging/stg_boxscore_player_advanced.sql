-- DNP players have empty advanced fields; possessions arrives as a float string.
with src as (select * from {{ source('bronze', 'boxscoreadvancedv3__PlayerStats') }})
select
    cast(gameId as string)                           as game_id,
    cast(personId as bigint)                         as player_id,
    try_cast(offensiveRating as double)              as offensive_rating,
    try_cast(defensiveRating as double)              as defensive_rating,
    try_cast(netRating as double)                    as net_rating,
    try_cast(assistPercentage as double)             as assist_pct,
    try_cast(assistToTurnover as double)             as assist_to_turnover,
    try_cast(offensiveReboundPercentage as double)   as oreb_pct,
    try_cast(defensiveReboundPercentage as double)   as dreb_pct,
    try_cast(reboundPercentage as double)            as reb_pct,
    try_cast(turnoverRatio as double)                as turnover_ratio,
    try_cast(effectiveFieldGoalPercentage as double) as efg_pct,
    try_cast(trueShootingPercentage as double)       as ts_pct,
    try_cast(usagePercentage as double)              as usage_pct,
    try_cast(pace as double)                         as pace,
    try_cast(possessions as double)                  as possessions,
    try_cast(PIE as double)                          as pie
from src
-- one row per game-player (tolerant of at-least-once Bronze loads)
qualify row_number() over (partition by gameId, personId order by PIE desc nulls last) = 1
