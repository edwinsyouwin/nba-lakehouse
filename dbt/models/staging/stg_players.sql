with src as (select * from {{ source('bronze', 'commonallplayers__CommonAllPlayers') }}),
typed as (
    select
        cast(PERSON_ID as bigint)                as player_id,
        cast(DISPLAY_FIRST_LAST as string)       as player_name,
        cast(DISPLAY_LAST_COMMA_FIRST as string) as player_name_last_first,
        cast(ROSTERSTATUS as int)                as roster_status,
        cast(nullif(TEAM_ID, '0') as bigint)     as team_id,
        cast(TEAM_ABBREVIATION as string)        as team_abbreviation,
        cast(FROM_YEAR as int)                   as from_year,
        cast(TO_YEAR as int)                     as to_year,
        cast(PLAYER_SLUG as string)              as player_slug
    from src
)
-- One row per player (defensive against multi-slice Bronze): keep most recent.
select * from typed
qualify row_number() over (
    partition by player_id order by to_year desc nulls last, from_year desc nulls last
) = 1
