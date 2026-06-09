-- Cross-fact reconciliation: made field goals derived from play-by-play
-- (fact_shot) must equal field goals made in the box score (fact_player_game),
-- per game + team, for games that have both.
with shots as (
    select game_id, team_id, count_if(is_made) as made_fg
    from {{ ref('fact_shot') }}
    group by game_id, team_id
),
box as (
    select game_id, team_id, sum(fgm) as box_fgm
    from {{ ref('fact_player_game') }}
    group by game_id, team_id
)
select s.game_id, s.team_id, s.made_fg, b.box_fgm
from shots s
join box b using (game_id, team_id)
where s.made_fg <> b.box_fgm
