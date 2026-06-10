"""Unit tests for the Elo backtest stats (no warehouse needed)."""

import numpy as np
import pandas as pd

from nba_warehouse import elo_backtest as eb


def test_brier_and_logloss_perfect():
    assert eb.brier([1, 0, 1], [1, 0, 1]) == 0.0
    assert eb.log_loss([1, 0], [1, 0]) < 1e-6


def test_brier_known():
    # one prediction of 0.5 on outcome 1 -> (0.5-1)^2 = 0.25
    assert abs(eb.brier([1], [0.5]) - 0.25) < 1e-12


def test_auc_perfect_and_random():
    assert eb.auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]) == 1.0
    assert eb.auc([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5]) == 0.5  # all ties -> 0.5


def test_auc_half_when_reversed():
    assert eb.auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0


def test_reliability_table_bins():
    df = pd.DataFrame({"win_prob": [0.05, 0.15, 0.95], "won": [0, 0, 1]})
    rel = eb.reliability_table(df, bins=10)
    assert set(rel["bin"]) == {0, 1, 9}
    assert rel["n"].sum() == 3


def test_summarize_beats_baseline_on_calibrated_data():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 20000)
    y = (rng.uniform(0, 1, 20000) < p).astype(int)  # perfectly calibrated
    m = eb.summarize(pd.DataFrame({"win_prob": p, "won": y}))
    assert m["brier"] < m["brier_baseline"]      # skill > 0
    assert m["brier_skill"] > 0
    assert 0.6 < m["auc"] < 0.9
    assert m["ece"] < 0.02                        # well calibrated
