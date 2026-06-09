-- One row per team per game: efficiency + Dean Oliver "Four Factors".
-- This is the (non-proprietary) feature layer the analytics marts build on.
-- Grain matches fact_team_game (game_id, team_id).
--
-- Formulas are the standard public definitions:
--   possessions  ~ FGA + 0.44*FTA - OREB + TOV               (team estimate)
--   pace          = 48 * (Tm Poss + Opp Poss) / (2 * (Tm MP / 5))
--   off rating    = 100 * PTS / Poss      (points per 100 possessions)
--   def rating    = 100 * Opp PTS / Opp Poss
--   eFG%          = (FGM + 0.5*FG3M) / FGA
--   TOV%          = TOV / (FGA + 0.44*FTA + TOV)
--   OREB%         = OREB / (OREB + Opp DREB)
--   FT rate       = FTM / FGA
-- Defensive four factors are the opponent's offensive four factors.

with tg as (select * from {{ ref('fact_team_game') }}),

-- the opponent's box-score row for the same game
paired as (
    select
        t.*,
        o.points  as opp_points,
        o.fgm     as opp_fgm,
        o.fga     as opp_fga,
        o.fg3m    as opp_fg3m,
        o.fta     as opp_fta,
        o.ftm     as opp_ftm,
        o.oreb    as opp_oreb,
        o.dreb    as opp_dreb,
        o.tov     as opp_tov
    from tg t
    join tg o
      on t.game_id = o.game_id
     and t.opponent_team_id = o.team_id
),

poss as (
    select
        *,
        (fga + 0.44 * fta - oreb + tov)             as poss,
        (opp_fga + 0.44 * opp_fta - opp_oreb + opp_tov) as opp_poss
    from paired
)

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

    -- tempo
    poss,
    opp_poss,
    48.0 * (poss + opp_poss) / nullif(2.0 * (team_minutes / 5.0), 0) as pace,

    -- efficiency (points per 100 possessions)
    100.0 * points     / nullif(poss, 0)      as off_rating,
    100.0 * opp_points / nullif(opp_poss, 0)  as def_rating,
    100.0 * points     / nullif(poss, 0)
        - 100.0 * opp_points / nullif(opp_poss, 0) as net_rating,

    -- offensive four factors
    (fgm + 0.5 * fg3m) / nullif(fga, 0)                 as efg_pct,
    tov / nullif(fga + 0.44 * fta + tov, 0)             as tov_pct,
    oreb / nullif(oreb + opp_dreb, 0)                   as oreb_pct,
    ftm / nullif(fga, 0)                                as ft_rate,

    -- defensive four factors (opponent's offense)
    (opp_fgm + 0.5 * opp_fg3m) / nullif(opp_fga, 0)     as opp_efg_pct,
    opp_tov / nullif(opp_fga + 0.44 * opp_fta + opp_tov, 0) as opp_tov_pct,
    opp_oreb / nullif(opp_oreb + dreb, 0)               as opp_oreb_pct,
    opp_ftm / nullif(opp_fga, 0)                        as opp_ft_rate

from poss
