-- One row per player per team: how long a player was with a team.
-- Answers "how many seasons did <player> play for <team>?"
-- Grain is (player_id, team_id); a franchise's abbreviation can change across
-- seasons (relocation/rename), so we take the most recent one via max_by.
select
    player_id,
    max(player_name)                       as player_name,
    team_id,
    max_by(team_abbreviation, season)      as team_abbreviation,
    count(distinct season)                 as seasons,
    min(season)                            as first_season,
    max(season)                            as last_season,
    sum(gp)                                as games_played,
    sum(points)                            as total_points
from {{ ref('fact_player_season') }}
group by player_id, team_id
