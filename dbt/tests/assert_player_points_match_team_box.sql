-- Cross-fact reconciliation: for every game present in fact_player_game, the sum
-- of player points per team must equal that team's points in fact_team_game.
with pg as (
    select game_id, team_id, sum(points) as player_points
    from {{ ref('fact_player_game') }}
    group by game_id, team_id
),
tg as (
    select game_id, team_id, points as team_points
    from {{ ref('fact_team_game') }}
)
select pg.game_id, pg.team_id, pg.player_points, tg.team_points
from pg
join tg using (game_id, team_id)
where pg.player_points <> tg.team_points
