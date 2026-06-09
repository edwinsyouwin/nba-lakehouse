-- Unify the per-game box-score variants into one wide player-game row.
-- (Phase 2: traditional + advanced; further variants join here in later phases.)
with t as (select * from {{ ref('stg_boxscore_player_traditional') }}),
adv as (select * from {{ ref('stg_boxscore_player_advanced') }})
select
    t.game_id,
    t.team_id,
    t.player_id,
    t.team_tricode,
    t.player_name,
    t.position,
    t.comment,
    t.seconds_played,
    -- traditional
    t.fgm, t.fga, t.fg_pct,
    t.fg3m, t.fg3a, t.fg3_pct,
    t.ftm, t.fta, t.ft_pct,
    t.oreb, t.dreb, t.reb,
    t.ast, t.stl, t.blk, t.tov, t.pf,
    t.points, t.plus_minus,
    -- advanced
    adv.offensive_rating, adv.defensive_rating, adv.net_rating,
    adv.usage_pct, adv.efg_pct, adv.ts_pct, adv.pace, adv.possessions, adv.pie
from t
left join adv using (game_id, player_id)
