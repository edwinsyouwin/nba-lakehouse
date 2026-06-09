-- Static shot-zone dimension (seed-backed).
select
    {{ dbt_utils.generate_surrogate_key(['shot_zone']) }} as shot_zone_key,
    shot_zone,
    zone_group,
    cast(typical_value as int) as typical_value
from {{ ref('shot_zones') }}
