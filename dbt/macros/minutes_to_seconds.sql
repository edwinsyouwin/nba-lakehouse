{# Convert NBA "MM:SS" (or "PT34M21.00S"-style) minutes strings to integer seconds.
   Handles the two formats the Stats API uses across v2/v3 box scores. #}
{% macro minutes_to_seconds(col) -%}
    case
        when {{ col }} is null or trim({{ col }}) = '' then null
        when {{ col }} like 'PT%' then
            coalesce(cast(regexp_extract({{ col }}, 'PT(\\d+)M', 1) as int), 0) * 60
          + coalesce(cast(regexp_extract({{ col }}, 'M(\\d+)', 1) as int), 0)
        when {{ col }} like '%:%' then
            cast(split_part({{ col }}, ':', 1) as int) * 60
          + cast(split_part({{ col }}, ':', 2) as int)
        else cast(cast({{ col }} as double) * 60 as int)
    end
{%- endmacro %}
