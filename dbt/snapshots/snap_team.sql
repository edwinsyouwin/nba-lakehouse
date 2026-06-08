{% snapshot snap_team %}
{{
  config(
    target_schema='silver',
    unique_key='team_id',
    strategy='check',
    check_cols=['team_name', 'team_abbreviation', 'team_city', 'team_nickname', 'team_state']
  )
}}
select team_id, team_name, team_abbreviation, team_city, team_nickname, team_state, year_founded
from {{ ref('stg_teams') }}
{% endsnapshot %}
