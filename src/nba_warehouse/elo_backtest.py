"""Calibration / skill metrics for the Elo pre-game win probabilities.

Pure functions (numpy/pandas only) so they're unit-testable without a warehouse.
Given per-game (win_prob, won) — one row per game, from the home team's
perspective using gold.analytics_team_elo.win_expected — these compute reliability
(calibration) tables and standard skill scores (Brier, log loss, AUC, ECE) plus a
base-rate baseline so you can see whether Elo actually beats "always pick home".
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def brier(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.mean((p - y) ** 2))


def log_loss(y, p, eps: float = 1e-12) -> float:
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(y, p) -> float:
    """ROC AUC via the rank (Mann-Whitney) identity, tie-safe."""
    y = np.asarray(y).astype(int)
    p = np.asarray(p, float)
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    sp = p[order]
    ranks = np.empty(len(p), float)
    i = 0
    while i < len(sp):  # average ranks for ties
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    sum_ranks_pos = ranks[y == 1].sum()
    return float((sum_ranks_pos - n1 * (n1 + 1) / 2) / (n1 * n0))


def reliability_table(df, prob="win_prob", out="won", bins=10) -> pd.DataFrame:
    d = df[[prob, out]].dropna().copy()
    d["bin"] = np.clip((d[prob] * bins).astype(int), 0, bins - 1)
    g = (d.groupby("bin")
           .agg(n=(out, "size"), mean_pred=(prob, "mean"), actual=(out, "mean"))
           .reset_index())
    g["bin_lo"] = g["bin"] / bins
    g["bin_hi"] = (g["bin"] + 1) / bins
    return g


def ece(rel: pd.DataFrame) -> float:
    """Expected calibration error: n-weighted mean |mean_pred - actual|."""
    total = rel["n"].sum()
    if total == 0:
        return float("nan")
    return float((rel["n"] / total * (rel["mean_pred"] - rel["actual"]).abs()).sum())


def summarize(df, prob="win_prob", out="won", bins=10) -> dict:
    d = df[[prob, out]].dropna()
    y, p = d[out].to_numpy(float), d[prob].to_numpy(float)
    base = float(y.mean()) if len(y) else float("nan")
    rel = reliability_table(d, prob, out, bins)
    return {
        "n": int(len(y)),
        "base_rate": base,                                   # actual home win rate
        "brier": brier(y, p),
        "brier_baseline": brier(y, np.full_like(y, base)),   # always predict base rate
        "brier_skill": (1 - brier(y, p) / brier(y, np.full_like(y, base))) if len(y) else float("nan"),
        "log_loss": log_loss(y, p),
        "auc": auc(y, p),
        "accuracy": float(np.mean((p >= 0.5) == (y == 1))) if len(y) else float("nan"),
        "ece": ece(rel),
    }


def by_season(df, season="season", prob="win_prob", out="won", bins=10) -> pd.DataFrame:
    rows = []
    for s, g in df.groupby(season):
        m = summarize(g, prob, out, bins)
        m[season] = s
        rows.append(m)
    return pd.DataFrame(rows).sort_values(season).reset_index(drop=True)
