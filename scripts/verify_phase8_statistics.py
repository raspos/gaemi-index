"""
PHASE 8 — 자동 업데이트 무결성 및 하락장 취약성 통계 독립 재검증 (scripts/verify_phase8_statistics.py)

[검증 항목]
1. 원장 독립 재현: GAEMI 50 / 100 / 51~100 / 101~150 누적수익률 및 하락월 성적
2. 패널 회귀 표준오차 재계산:
   - 기존 OLS
   - 종목별 군집 표준오차 (Cluster by code)
   - 종목 × 분기 양방향 군집 표준오차 (Two-way cluster)
   - 소표본 분기 군집 대응 Wild Cluster Bootstrap (Rademacher, B=2,000)
3. 통제변수 보강: 직전 1개월·3개월·12개월 수익률, 거래대금(log ADTV), 과거 시장 베타 추가
4. 전체 적격 유니버스(표본선택 편향 제거) 및 극단치 윈저라이징(1%) 연속변수 검증
5. 코스닥 하락월 10개월 Leave-One-Out, A<B<C 월별 패턴 비율, Holm-Bonferroni 다중검정 보정
6. 일별(-1.73% vs -1.81%) vs 월별(-12.15% vs -10.61%) 결과 차이 요인 분해
"""

import os
import sys
import json
import math
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from ledger_loader import load_raw_ledger
from build_phase2_analytics import (
    prepare_audited_ledger,
    get_rebalance_schedule,
    evaluate_quarter_cross_section,
    build_matched_comparison_portfolio,
    compute_equal_weight_index_series,
    sanitize_for_json,
)

DATA_DIR = os.path.join(BASE_DIR, "data")


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def two_sided_p_from_t(t_val, df):
    if df <= 0 or not np.isfinite(t_val):
        return 1.0
    z = abs(t_val)
    if df < 30:
        z = z * (1.0 - 1.0 / (4.0 * df)) / math.sqrt(1.0 + (z * z) / (2.0 * df))
    return float(max(0.0, min(1.0, 2.0 * (1.0 - norm_cdf(z)))))


def t_crit_95(df):
    table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}
    if df in table:
        return table[df]
    return 1.96 if df > 30 else 2.131


def paired_test(a, b):
    d = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    n = len(d)
    mean_d = float(np.mean(d))
    std_d = float(np.std(d, ddof=1))
    se_d = std_d / math.sqrt(n) if n > 0 else 1e-9
    t_val = mean_d / se_d if se_d > 0 else 0.0
    p_val = two_sided_p_from_t(t_val, n - 1)
    tc = t_crit_95(n - 1)
    return {
        "n": int(n),
        "mean_diff_pctp": round(mean_d, 2),
        "median_diff_pctp": round(float(np.median(d)), 2),
        "std_diff_pctp": round(std_d, 2),
        "ci95_pctp": [round(mean_d - tc * se_d, 2), round(mean_d + tc * se_d, 2)],
        "t_stat": round(t_val, 3),
        "p_value": round(p_val, 4),
    }


def ols_with_cluster_ses(X, y, cluster_code, cluster_q, rng_seed=42):
    """
    OLS, 1-way cluster (code), 1-way cluster (quarter), 2-way cluster (code x quarter),
    and Wild Cluster Bootstrap (by quarter, Rademacher weights, B=2000) for coefficient index 1.
    """
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta

    # A. Classic OLS
    s2 = float(np.dot(resid, resid) / max(n - k, 1))
    cov_ols = s2 * XtX_inv
    se_ols = math.sqrt(max(cov_ols[1, 1], 1e-18))

    # Helper for meat matrix sum_g (X_g' e_g)(X_g' e_g)'
    def cluster_cov(groups):
        uniq = {}
        for idx, g in enumerate(groups):
            uniq.setdefault(g, []).append(idx)
        G = len(uniq)
        meat = np.zeros((k, k), dtype=np.float64)
        for idxs in uniq.values():
            Xg = X[idxs]
            eg = resid[idxs]
            s = Xg.T @ eg
            meat += np.outer(s, s)
        dfc = (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1))
        return dfc * (XtX_inv @ meat @ XtX_inv), G

    cov_c, G_c = cluster_cov(cluster_code)
    se_c = math.sqrt(max(cov_c[1, 1], 1e-18))

    cov_q, G_q = cluster_cov(cluster_q)
    se_q = math.sqrt(max(cov_q[1, 1], 1e-18))

    # White HC1 for intersection in 2-way cluster
    meat_w = (X.T * (resid ** 2)) @ X
    cov_w = (n / max(n - k, 1)) * (XtX_inv @ meat_w @ XtX_inv)
    var_2way = max(cov_c[1, 1] + cov_q[1, 1] - cov_w[1, 1], cov_c[1, 1], 1e-18)
    se_2way = math.sqrt(var_2way)

    # Wild Cluster Bootstrap by Quarter (Rademacher weights, null imposed or residual bootstrap)
    # Using restricted WCB (null: beta_1 = 0)
    X_r = np.delete(X, 1, axis=1)
    beta_r, _, _, _ = np.linalg.lstsq(X_r, y, rcond=None)
    y_hat_r = X_r @ beta_r
    e_r = y - y_hat_r

    q_vals = np.asarray(cluster_q)
    uniq_qs = np.unique(q_vals)
    q_masks = [q_vals == qv for qv in uniq_qs]

    t_orig_q = float(beta[1] / se_q)
    rng = np.random.default_rng(rng_seed)
    B = 2000
    t_boot = np.empty(B, dtype=np.float64)
    # Precompute XtX_inv @ X.T for speed
    P = XtX_inv @ X.T
    for b in range(B):
        w = rng.choice([-1.0, 1.0], size=len(uniq_qs))
        e_star = np.empty(n, dtype=np.float64)
        for qi, m in enumerate(q_masks):
            e_star[m] = e_r[m] * w[qi]
        y_star = y_hat_r + e_star
        b_star = P @ y_star
        res_star = y_star - X @ b_star
        # cluster SE by quarter in bootstrap sample
        meat_bq = np.zeros((k, k), dtype=np.float64)
        for m in q_masks:
            s = X[m].T @ res_star[m]
            meat_bq += np.outer(s, s)
        dfc_q = (G_q / max(G_q - 1, 1)) * ((n - 1) / max(n - k, 1))
        cov_bq = dfc_q * (XtX_inv @ meat_bq @ XtX_inv)
        se_bq = math.sqrt(max(cov_bq[1, 1], 1e-18))
        t_boot[b] = b_star[1] / se_bq

    p_wcb = float(np.mean(np.abs(t_boot) >= abs(t_orig_q)))

    b1 = float(beta[1])
    return {
        "n_obs": int(n),
        "n_clusters_code": int(G_c),
        "n_clusters_quarter": int(G_q),
        "coef_raw": b1,
        "ols": {
            "coef_per_10pct": round(b1 * 10.0, 4),
            "se_per_10pct": round(se_ols * 10.0, 4),
            "t_stat": round(b1 / se_ols, 3),
            "p_value": round(two_sided_p_from_t(b1 / se_ols, n - k), 4),
        },
        "cluster_code": {
            "coef_per_10pct": round(b1 * 10.0, 4),
            "se_per_10pct": round(se_c * 10.0, 4),
            "t_stat": round(b1 / se_c, 3),
            "p_value": round(two_sided_p_from_t(b1 / se_c, G_c - 1), 4),
        },
        "cluster_quarter": {
            "coef_per_10pct": round(b1 * 10.0, 4),
            "se_per_10pct": round(se_q * 10.0, 4),
            "t_stat": round(b1 / se_q, 3),
            "p_value": round(two_sided_p_from_t(b1 / se_q, G_q - 1), 4),
        },
        "cluster_twoway": {
            "coef_per_10pct": round(b1 * 10.0, 4),
            "se_per_10pct": round(se_2way * 10.0, 4),
            "t_stat": round(b1 / se_2way, 3),
            "p_value": round(two_sided_p_from_t(b1 / se_2way, min(G_c, G_q) - 1), 4),
        },
        "wild_cluster_bootstrap_quarter": {
            "coef_per_10pct": round(b1 * 10.0, 4),
            "se_per_10pct": round(se_q * 10.0, 4),
            "t_stat": round(t_orig_q, 3),
            "p_value": round(p_wcb, 4),
            "bootstrap_reps": B,
        },
    }


def build_regression_matrices(df_panel, extra_controls=False, winsorize_intensity=False):
    df = df_panel.copy()
    if winsorize_intensity:
        hi = df["intensity_pct"].quantile(0.99)
        lo = df["intensity_pct"].quantile(0.01)
        df["intensity_pct"] = df["intensity_pct"].clip(lo, hi)

    req_cols = ["intensity_pct", "down_day_mean_ret_pct", "log_marcap", "vol_60d_pct", "is_kosdaq"]
    if extra_controls:
        req_cols += ["ret_1m_pct", "ret_3m_pct", "ret_12m_pct", "log_adtv60", "prior_beta_kq"]
    df = df.dropna(subset=req_cols).reset_index(drop=True)

    top_inds = df["industry"].value_counts().head(8).index.tolist()
    df["ind_grp"] = np.where(df["industry"].isin(top_inds), df["industry"], "OTHER")

    feat_cols = ["intensity_pct", "log_marcap", "vol_60d_pct", "is_kosdaq"]
    if extra_controls:
        feat_cols += ["ret_1m_pct", "ret_3m_pct", "ret_12m_pct", "log_adtv60", "prior_beta_kq"]

    X_df = pd.concat([
        df[feat_cols].astype(float),
        pd.get_dummies(df["quarter"], prefix="q", drop_first=True, dtype=float),
        pd.get_dummies(df["ind_grp"], prefix="ind", drop_first=True, dtype=float),
    ], axis=1)
    X = np.column_stack([np.ones(len(X_df)), X_df.values])
    y = df["down_day_mean_ret_pct"].values.astype(np.float64)
    return X, y, df["code"].tolist(), df["quarter"].tolist(), df


def main():
    print("[PHASE 8] 독립 재현 및 통계적 재검증 시작...")
    universe, trades, bench = prepare_audited_ledger()
    universe_map = universe.set_index("Code").to_dict(orient="index")

    trading_dates = sorted(trades["date"].unique().tolist())
    schedule = get_rebalance_schedule(trading_dates)
    base_date = schedule[0]["determination_date"]

    sub_ret = trades[trades["date"] >= base_date][["date", "code", "gross_ret"]]
    ret_pivot = sub_ret.pivot(index="date", columns="code", values="gross_ret").fillna(1.0)
    all_dates = sorted(ret_pivot.index.tolist())
    del sub_ret

    b_sub = bench[bench["date"] >= base_date].sort_values("date").copy()
    b_sub["kq_ret"] = b_sub["KOSDAQ"].pct_change().fillna(0.0)
    b_sub["kp_ret"] = b_sub["KOSPI"].pct_change().fillna(0.0)
    kq_ret_map = b_sub.set_index("date")["kq_ret"].to_dict()
    kq_down_dates_set = set(b_sub[b_sub["kq_ret"] < 0]["date"])

    # Pre-build benchmark return series for prior beta calculation
    bench_ret_df = bench.sort_values("date").copy()
    bench_ret_df["kq_r"] = bench_ret_df["KOSDAQ"].pct_change().fillna(0.0)
    bench_kq_map = bench_ret_df.set_index("date")["kq_r"].to_dict()

    h_50, h_100, h_51, h_101, h_m50 = {}, {}, {}, {}, {}
    panel_top150 = []
    panel_all_elig = []

    # Precompute daily stock returns for fast lookup
    trades_sorted = trades.sort_values(["code", "date"])

    for q in schedule:
        qid = q["rebalance_id"]
        det_date = q["determination_date"]
        eff_start = q["effective_start"]
        eff_end = q["effective_end"]

        df_all, ind50, _, _, _ = evaluate_quarter_cross_section(
            trades, universe_map, q, min_marcap_eok=3000.0, min_adtv_60d_eok=10.0, min_obs_ratio=0.90
        )
        elig_ind = df_all[df_all["is_eligible_pure"]].sort_values("intensity_pct", ascending=False).reset_index(drop=True)

        ind100 = elig_ind.head(100).copy()
        ind51_100 = elig_ind.iloc[50:100].copy()
        ind101_150 = elig_ind.iloc[100:150].copy()
        for sub_df in [ind50, ind100, ind51_100, ind101_150]:
            sub_df["weight"] = 1.0 / len(sub_df) if len(sub_df) else 0.0

        m50 = build_matched_comparison_portfolio(df_all, ind50)

        h_50[qid] = ind50
        h_100[qid] = ind100
        h_51[qid] = ind51_100
        h_101[qid] = ind101_150
        h_m50[qid] = m50

        # Prior features (no look-ahead: <= det_date)
        elig_codes = set(elig_ind["code"])
        sub_hist = trades_sorted[(trades_sorted["date"] <= det_date) & (trades_sorted["code"].isin(elig_codes))]
        q_dates_down = [d for d in all_dates if eff_start <= d <= eff_end and d in kq_down_dates_set]
        if not q_dates_down:
            continue
        sub_q_ret = ret_pivot.loc[q_dates_down]

        prior_map = {}
        for code, grp in sub_hist.groupby("code"):
            g_rets = grp["gross_ret"].values
            r = g_rets - 1.0
            dts = grp["date"].values
            vol60 = float(np.std(r[-60:], ddof=1) * math.sqrt(252) * 100.0) if len(r) >= 20 else np.nan
            r1m = float((np.prod(g_rets[-20:]) - 1.0) * 100.0) if len(r) >= 15 else np.nan
            r3m = float((np.prod(g_rets[-60:]) - 1.0) * 100.0) if len(r) >= 20 else np.nan
            r12m = float((np.prod(g_rets[-240:]) - 1.0) * 100.0) if len(r) >= 120 else np.nan
            # Prior 120d beta vs KOSDAQ
            if len(r) >= 60:
                r_b = r[-120:]
                kq_b = np.array([bench_kq_map.get(d, 0.0) for d in dts[-120:]], dtype=np.float64)
                vb = np.var(kq_b, ddof=1)
                beta_kq = float(np.cov(r_b, kq_b, ddof=1)[0, 1] / vb) if vb > 0 else np.nan
            else:
                beta_kq = np.nan
            prior_map[code] = {
                "vol_60d_pct": vol60,
                "ret_1m_pct": r1m,
                "ret_3m_pct": r3m,
                "ret_12m_pct": r12m,
                "prior_beta_kq": beta_kq,
            }

        for idx_pos, row in elig_ind.iterrows():
            c = row["code"]
            if c not in sub_q_ret.columns or c not in prior_map:
                continue
            d_mean = float((sub_q_ret[c].mean() - 1.0) * 100.0)
            pf = prior_map[c]
            rec = {
                "quarter": qid,
                "code": c,
                "rank": int(idx_pos + 1),
                "intensity_pct": float(row["intensity_pct"]),
                "log_marcap": math.log(max(float(row["end_marcap_eok"]), 1.0)),
                "log_adtv60": math.log(max(float(row["adtv_60d_eok"]), 0.1)),
                "vol_60d_pct": pf["vol_60d_pct"],
                "ret_1m_pct": pf["ret_1m_pct"],
                "ret_3m_pct": pf["ret_3m_pct"],
                "ret_12m_pct": pf["ret_12m_pct"],
                "prior_beta_kq": pf["prior_beta_kq"],
                "is_kosdaq": 1.0 if row["market"] == "KOSDAQ" else 0.0,
                "industry": row["industry"],
                "down_day_mean_ret_pct": d_mean,
            }
            panel_all_elig.append(rec)
            if idx_pos < 150:
                panel_top150.append(rec)

    # 1. Independent Backtest Reproduction
    s50 = compute_equal_weight_index_series(ret_pivot, all_dates, schedule, h_50, base_date, 1000.0)[["date", "index_value"]].rename(columns={"index_value": "GAEMI_50"})
    s100 = compute_equal_weight_index_series(ret_pivot, all_dates, schedule, h_100, base_date, 1000.0)[["date", "index_value"]].rename(columns={"index_value": "GAEMI_100"})
    s51 = compute_equal_weight_index_series(ret_pivot, all_dates, schedule, h_51, base_date, 1000.0)[["date", "index_value"]].rename(columns={"index_value": "GAEMI_51_100"})
    s101 = compute_equal_weight_index_series(ret_pivot, all_dates, schedule, h_101, base_date, 1000.0)[["date", "index_value"]].rename(columns={"index_value": "GAEMI_101_150"})
    sm50 = compute_equal_weight_index_series(ret_pivot, all_dates, schedule, h_m50, base_date, 1000.0)[["date", "index_value"]].rename(columns={"index_value": "MATCHED_50"})

    m = s50.merge(s100, on="date").merge(s51, on="date").merge(s101, on="date").merge(sm50, on="date")
    b_norm = bench[bench["date"] >= base_date].sort_values("date").copy()
    b_norm["KOSPI"] = b_norm["KOSPI"] / b_norm["KOSPI"].iloc[0] * 1000.0
    b_norm["KOSDAQ"] = b_norm["KOSDAQ"] / b_norm["KOSDAQ"].iloc[0] * 1000.0
    m = m.merge(b_norm[["date", "KOSPI", "KOSDAQ"]], on="date", how="left").ffill()
    m["ym"] = m["date"].str.slice(0, 7)

    cols_idx = ["GAEMI_50", "GAEMI_100", "GAEMI_51_100", "GAEMI_101_150", "MATCHED_50", "KOSPI", "KOSDAQ"]
    repro_cum = {c: round((float(m[c].iloc[-1]) / float(m[c].iloc[0]) - 1.0) * 100.0, 2) for c in cols_idx}

    month_ends = m.groupby("ym", as_index=False).last().sort_values("ym").reset_index(drop=True)
    m_rows = []
    for i in range(1, len(month_ends)):
        r0, r1 = month_ends.iloc[i - 1], month_ends.iloc[i]
        row = {"ym": r1["ym"]}
        for c in cols_idx:
            row[c] = round((float(r1[c]) / float(r0[c]) - 1.0) * 100.0, 2)
        m_rows.append(row)
    df_m = pd.DataFrame(m_rows)
    kq_dm = df_m[df_m["KOSDAQ"] < 0].reset_index(drop=True)
    kp_dm = df_m[df_m["KOSPI"] < 0].reset_index(drop=True)

    # 2. Panel Regression & Cluster SEs
    df_150 = pd.DataFrame(panel_top150)
    df_all_p = pd.DataFrame(panel_all_elig)

    X_base, y_base, cc_base, cq_base, df_b = build_regression_matrices(df_150, extra_controls=False, winsorize_intensity=False)
    reg_base = ols_with_cluster_ses(X_base, y_base, cc_base, cq_base)

    X_aug, y_aug, cc_aug, cq_aug, df_a = build_regression_matrices(df_150, extra_controls=True, winsorize_intensity=False)
    reg_aug = ols_with_cluster_ses(X_aug, y_aug, cc_aug, cq_aug)

    X_full, y_full, cc_full, cq_full, df_f = build_regression_matrices(df_all_p, extra_controls=False, winsorize_intensity=False)
    reg_full = ols_with_cluster_ses(X_full, y_full, cc_full, cq_full)

    X_full_aug, y_full_aug, cc_full_aug, cq_full_aug, _ = build_regression_matrices(df_all_p, extra_controls=True, winsorize_intensity=True)
    reg_full_aug_win = ols_with_cluster_ses(X_full_aug, y_full_aug, cc_full_aug, cq_full_aug)

    sample_struct = {
        "n_obs_top150": int(len(df_b)),
        "unique_stocks_top150": int(df_b["code"].nunique()),
        "n_quarters": int(df_b["quarter"].nunique()),
        "repeat_appearances_median": float(df_b.groupby("code").size().median()),
        "repeat_appearances_max": int(df_b.groupby("code").size().max()),
        "obs_per_quarter": df_b.groupby("quarter").size().to_dict(),
        "n_obs_full_eligible": int(len(df_f)),
        "unique_stocks_full_eligible": int(df_f["code"].nunique()),
        "kosdaq_down_days": int(len(kq_down_dates_set)),
        "kosdaq_down_months": int(len(kq_dm)),
    }

    # 3. Down-month Leave-One-Out & A < B < C Comparison
    loo_vs_kq = []
    loo_vs_m50 = []
    for i in range(len(kq_dm)):
        sub = kq_dm.drop(index=i)
        ym_out = kq_dm.iloc[i]["ym"]
        t_kq = paired_test(sub["GAEMI_50"], sub["KOSDAQ"])
        t_m50 = paired_test(sub["GAEMI_50"], sub["MATCHED_50"])
        loo_vs_kq.append({"dropped_ym": ym_out, **t_kq})
        loo_vs_m50.append({"dropped_ym": ym_out, **t_m50})

    a_lt_b = int((kq_dm["GAEMI_50"] < kq_dm["GAEMI_51_100"]).sum())
    b_lt_c = int((kq_dm["GAEMI_51_100"] < kq_dm["GAEMI_101_150"]).sum())
    abc_mono = int(((kq_dm["GAEMI_50"] < kq_dm["GAEMI_51_100"]) & (kq_dm["GAEMI_51_100"] < kq_dm["GAEMI_101_150"])).sum())

    pair_ab = paired_test(kq_dm["GAEMI_50"], kq_dm["GAEMI_51_100"])
    pair_bc = paired_test(kq_dm["GAEMI_51_100"], kq_dm["GAEMI_101_150"])
    pair_ac = paired_test(kq_dm["GAEMI_50"], kq_dm["GAEMI_101_150"])
    # Holm-Bonferroni adjustment for 3 comparisons
    p_list = sorted([(pair_ab["p_value"], "A-B"), (pair_bc["p_value"], "B-C"), (pair_ac["p_value"], "A-C")])
    holm_adj = {}
    for rank_i, (pv, lbl) in enumerate(p_list):
        holm_adj[lbl] = round(min(1.0, pv * (3 - rank_i)), 4)

    # 4. Daily vs Monthly Discrepancy Decomposition
    m_ret = m.copy()
    for c in cols_idx:
        m_ret[c] = m_ret[c].pct_change() * 100.0
    m_ret = m_ret.iloc[1:].copy()
    m_ret["ym"] = m_ret["date"].str.slice(0, 7)
    kq_down_ym_set = set(kq_dm["ym"])

    in_dm_days = m_ret[m_ret["ym"].isin(kq_down_ym_set)]
    in_dm_kq_down_days = in_dm_days[in_dm_days["KOSDAQ"] < 0]
    in_dm_kq_up_days = in_dm_days[in_dm_days["KOSDAQ"] > 0]
    all_kq_down_days = m_ret[m_ret["KOSDAQ"] < 0]

    daily_vs_monthly_decomp = {
        "all_kq_down_days_count": int(len(all_kq_down_days)),
        "all_kq_down_days_gaemi50_mean_pct": round(float(all_kq_down_days["GAEMI_50"].mean()), 3),
        "all_kq_down_days_kosdaq_mean_pct": round(float(all_kq_down_days["KOSDAQ"].mean()), 3),
        "in_down_months_kq_down_days_count": int(len(in_dm_kq_down_days)),
        "in_down_months_kq_down_days_gaemi50_mean_pct": round(float(in_dm_kq_down_days["GAEMI_50"].mean()), 3),
        "in_down_months_kq_down_days_kosdaq_mean_pct": round(float(in_dm_kq_down_days["KOSDAQ"].mean()), 3),
        "in_down_months_kq_up_days_count": int(len(in_dm_kq_up_days)),
        "in_down_months_kq_up_days_gaemi50_mean_pct": round(float(in_dm_kq_up_days["GAEMI_50"].mean()), 3),
        "in_down_months_kq_up_days_kosdaq_mean_pct": round(float(in_dm_kq_up_days["KOSDAQ"].mean()), 3),
        "outside_down_months_kq_down_days_count": int(len(all_kq_down_days) - len(in_dm_kq_down_days)),
    }

    report = sanitize_for_json({
        "reproduced_cumulative_returns_pct": repro_cum,
        "kosdaq_down_months_mean_pct": {c: round(float(kq_dm[c].mean()), 2) for c in cols_idx},
        "kospi_down_months_mean_pct": {c: round(float(kp_dm[c].mean()), 2) for c in cols_idx},
        "kosdaq_down_months_table": kq_dm[["ym", "GAEMI_50", "GAEMI_100", "GAEMI_51_100", "GAEMI_101_150", "MATCHED_50", "KOSDAQ", "KOSPI"]].to_dict(orient="records"),
        "sample_structure": sample_struct,
        "regression_top150_base": reg_base,
        "regression_top150_augmented": reg_aug,
        "regression_full_eligible_base": reg_full,
        "regression_full_eligible_aug_winsorized": reg_full_aug_win,
        "down_month_tests": {
            "gaemi50_vs_kosdaq": paired_test(kq_dm["GAEMI_50"], kq_dm["KOSDAQ"]),
            "gaemi50_vs_matched50": paired_test(kq_dm["GAEMI_50"], kq_dm["MATCHED_50"]),
            "loo_vs_kosdaq": loo_vs_kq,
            "loo_vs_matched50": loo_vs_m50,
            "abc_pattern_counts": {"n_months": int(len(kq_dm)), "a_lt_b": a_lt_b, "b_lt_c": b_lt_c, "a_lt_b_lt_c": abc_mono},
            "pair_ab": pair_ab,
            "pair_bc": pair_bc,
            "pair_ac": pair_ac,
            "holm_bonferroni_p": holm_adj,
        },
        "daily_vs_monthly_decomp": daily_vs_monthly_decomp,
    })

    out_path = os.path.join(DATA_DIR, "phase8_statistical_audit.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"\n[PHASE 8 저장 완료] {out_path}")
    print("1) 재현 누적수익률:", repro_cum)
    print("2) 코스닥 하락월 평균:", report["kosdaq_down_months_mean_pct"])
    print("3) Top150 기존모형 표준오차 비교:")
    for m_k in ["ols", "cluster_code", "cluster_quarter", "cluster_twoway", "wild_cluster_bootstrap_quarter"]:
        r = reg_base[m_k]
        print(f"   - {m_k:30s}: beta={r['coef_per_10pct']:+.4f}, SE={r['se_per_10pct']:.4f}, t={r['t_stat']:+.3f}, p={r['p_value']:.4f}")
    print("4) Top150 통제보강(과거1/3/12M수익률+유동성+베타) WCB:", reg_aug["wild_cluster_bootstrap_quarter"], "| cluster_code:", reg_aug["cluster_code"])
    print("5) 전체 적격 유니버스(N=", reg_full["n_obs"], ") OLS vs WCB:", reg_full["ols"], "| WCB:", reg_full["wild_cluster_bootstrap_quarter"])
    print("6) 일별 vs 월별 분해:", daily_vs_monthly_decomp)


if __name__ == "__main__":
    main()
