-- One row per player per team-season (grain: team_id + season + player_id).
-- Source: commonteamroster CommonTeamRoster result set — richer than
-- commonallplayers (jersey #, position, height/weight, college, age, experience,
-- how-acquired). EXP is 'R' for rookies; rendered to 0 here.
with src as (select * from {{ source('bronze', 'commonteamroster__CommonTeamRoster') }}),
typed as (
    select
        cast(TeamID as bigint)                             as team_id,
        -- payload SEASON is the start year ('2023'); render the '2023-24' label.
        SEASON || '-' || right(cast(cast(SEASON as int) + 1 as string), 2) as season,
        cast(PLAYER_ID as bigint)                          as player_id,
        cast(PLAYER as string)                             as player_name,
        cast(NICKNAME as string)                           as nickname,
        cast(PLAYER_SLUG as string)                        as player_slug,
        cast(NUM as string)                                as jersey_number,
        cast(POSITION as string)                           as position,
        cast(HEIGHT as string)                             as height,
        try_cast(WEIGHT as int)                            as weight_lbs,
        cast(BIRTH_DATE as string)                         as birth_date,
        try_cast(AGE as double)                            as age,
        case when EXP = 'R' then 0 else try_cast(EXP as int) end as experience_years,
        cast(SCHOOL as string)                             as school,
        cast(HOW_ACQUIRED as string)                       as how_acquired
    from src
)
select * from typed
-- Defensive against multi-slice Bronze: one row per player per team-season.
qualify row_number() over (
    partition by team_id, season, player_id order by player_id
) = 1
