{# Use the model's configured +schema verbatim (e.g. silver/gold) instead of dbt's
   default <target>_<schema> prefixing. Catalog isolation (nba vs nba_dev) is
   handled by the profile/--target, so schema names stay clean across envs. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
