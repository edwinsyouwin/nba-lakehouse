-- play-by-play v3 occasionally reuses actionNumber within a game, so the natural
-- key (game_id, action_number) is not unique. Add a deterministic tiebreaker
-- (action_seq) so downstream surrogate keys stay unique without dropping events.
with src as (select * from {{ source('bronze', 'playbyplayv3__PlayByPlay') }}),
typed as (
    select
        cast(gameId as string)                  as game_id,
        try_cast(actionNumber as int)           as action_number,
        cast(clock as string)                   as clock,
        try_cast(period as int)                 as period,
        try_cast(nullif(teamId, '0') as bigint) as team_id,
        cast(teamTricode as string)             as team_tricode,
        try_cast(nullif(personId, '0') as bigint) as player_id,
        cast(playerName as string)              as player_name,
        cast(actionType as string)              as action_type,
        cast(subType as string)                 as sub_type,
        cast(description as string)             as description,
        try_cast(scoreHome as int)              as score_home,
        try_cast(scoreAway as int)              as score_away,
        case when lower(isFieldGoal) in ('1', 'true') then true else false end as is_field_goal,
        cast(shotResult as string)              as shot_result,
        try_cast(shotDistance as double)        as shot_distance,
        try_cast(xLegacy as double)             as x_legacy,
        try_cast(yLegacy as double)             as y_legacy
    from src
)
select
    *,
    row_number() over (
        partition by game_id, action_number
        order by description nulls last, shot_result nulls last,
                 team_id nulls last, player_id nulls last
    ) as action_seq
from typed
