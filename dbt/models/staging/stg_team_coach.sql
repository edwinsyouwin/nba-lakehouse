-- One row per coach/trainer per team-season (grain: team_id + season + coach_id).
-- Source: commonteamroster Coaches result set. NBA Stats coverage is uneven —
-- some team-seasons omit the head coach or return only trainers — so downstream
-- models should not assume exactly one head coach per team-season.
with src as (select * from {{ source('bronze', 'commonteamroster__Coaches') }}),
typed as (
    select
        cast(TEAM_ID as bigint)                            as team_id,
        -- payload SEASON is the start year ('2023'); render the '2023-24' label.
        SEASON || '-' || right(cast(cast(SEASON as int) + 1 as string), 2) as season,
        cast(COACH_ID as bigint)                           as coach_id,
        cast(FIRST_NAME as string)                         as first_name,
        cast(LAST_NAME as string)                          as last_name,
        cast(COACH_NAME as string)                         as coach_name,
        cast(COACH_TYPE as string)                         as coach_type,
        try_cast(IS_ASSISTANT as int)                      as is_assistant_code,
        case when COACH_TYPE = 'Head Coach' then true else false end      as is_head_coach,
        case when COACH_TYPE = 'Assistant Coach' then true else false end as is_assistant_coach,
        try_cast(SORT_SEQUENCE as int)                     as sort_sequence,
        try_cast(SUB_SORT_SEQUENCE as int)                 as sub_sort_sequence
    from src
)
select * from typed
-- Defensive against multi-slice Bronze: one row per coach per team-season.
qualify row_number() over (
    partition by team_id, season, coach_id
    order by sort_sequence nulls last, sub_sort_sequence nulls last
) = 1
