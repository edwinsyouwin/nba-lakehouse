-- Phase 1 acceptance: fact_team_game must have exactly two rows per game
-- (one per team). Any game with a different count is an error.
select game_id, count(*) as team_rows
from {{ ref('fact_team_game') }}
group by game_id
having count(*) <> 2
