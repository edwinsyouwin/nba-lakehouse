-- Team efficiency + Dean Oliver "Four Factors" per team per game.
-- Built on the int_team_game__advanced feature layer.
select
    team_game_sk,
    game_sk,
    game_id,
    team_id,
    opponent_team_id,
    team_sk,
    opponent_team_sk,
    date_key,
    season_key,
    game_date,
    is_home,
    win_flag,
    poss,
    pace,
    off_rating,
    def_rating,
    net_rating,
    efg_pct,
    tov_pct,
    oreb_pct,
    ft_rate,
    opp_efg_pct,
    opp_tov_pct,
    opp_oreb_pct,
    opp_ft_rate
from {{ ref('int_team_game__advanced') }}
