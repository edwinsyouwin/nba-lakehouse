-- SCD2 player dimension built from the snapshot. One row per player version.
with snap as (select * from {{ ref('snap_player') }})
select
    {{ dbt_utils.generate_surrogate_key(['player_id', 'dbt_valid_from']) }} as player_sk,
    player_id,
    player_name,
    player_name_last_first,
    roster_status,
    team_id,
    team_abbreviation,
    from_year,
    to_year,
    player_slug,
    dbt_valid_from           as valid_from,
    dbt_valid_to             as valid_to,
    (dbt_valid_to is null)   as is_current
from snap
