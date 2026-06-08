-- SCD2 team dimension built from the snapshot. One row per team version.
with snap as (select * from {{ ref('snap_team') }})
select
    {{ dbt_utils.generate_surrogate_key(['team_id', 'dbt_valid_from']) }} as team_sk,
    team_id,
    team_name,
    team_abbreviation,
    team_city,
    team_nickname,
    team_state,
    year_founded,
    dbt_valid_from                       as valid_from,
    dbt_valid_to                         as valid_to,
    (dbt_valid_to is null)               as is_current
from snap
