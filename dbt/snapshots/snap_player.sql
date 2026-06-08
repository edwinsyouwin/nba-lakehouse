{% snapshot snap_player %}
{{
  config(
    target_schema='silver',
    unique_key='player_id',
    strategy='check',
    check_cols=['player_name', 'team_id', 'roster_status', 'team_abbreviation']
  )
}}
select player_id, player_name, player_name_last_first, roster_status,
       team_id, team_abbreviation, from_year, to_year, player_slug
from {{ ref('stg_players') }}
{% endsnapshot %}
