"""
개미 지수 | GAEMI INDEX — PHASE 7: GAEMI 100 확대 및 하락장 취약성 검증 엔진

[산출 및 검증 범위]
1. 세 가지 개미 지수 + 비교지수 (2024-09-30 = 1,000, 동일 거래일·동일 기준):
   - GAEMI 50 (상위 50종목, 2% 동일가중)
   - GAEMI 100 (상위 100종목, 1% 동일가중)
   - GAEMI 51–100 (51~100위, 2% 동일가중)
   - GAEMI 101–150 (분석용), GAEMI 30 / 75 / 150 (종목 수 민감도 분석용)
   - 비슷한 주식 50개 (MATCHED_50_EW) & 비슷한 주식 100개 (MATCHED_100_EW, 매칭 한계 보고 포함)
2. 하락장·상승장 성적 비교 (일간·월간·기하 포착률·주요 하락장 사건별)
3. 순매수 강도(1~50 vs 51~100 vs 101~150)와 하락장 취약성 + 시총·업종·변동성 통제 회귀 검증
4. 분기별 종목 구성 비교 (규모·유동성·변동성·과거수익률·회전율)
5. 데이터 품질 검증 (A안 종가 vs B안 기준가·종가 평균: 50/100/51~100 일치율 및 성과 차이)
6. 통계적 검증 (월간 짝지은 t-검정·95% 신뢰구간 + 일간 Newey-West HAC 검정)
"""

import os
import json
import math
from datetime import datetime
import numpy as np
import pandas as pd

import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from build_phase2_analytics import (
    prepare_audited_ledger,
    get_rebalance_schedule,
    evaluate_quarter_cross_section,
    build_matched_comparison_portfolio,
    compute_equal_weight_index_series,
    sanitize_for_json,
    calc_perf_stats,
)

DATA_DIR = os.path.join(BASE_DIR, "data")


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def two_sided_p_from_t(t_val, df):
    """Normal/Student-t approximation for two-sided p-value without scipy dependency."""
    if df <= 0 or not np.isfinite(t_val):
        return 1.0
    z = abs(t_val)
    # For small df, use Cornish-Fisher / t-to-z adjustment
    if df < 30:
        z = z * (1.0 - 1.0 / (4.0 * df)) / math.sqrt(1.0 + (z * z) / (2.0 * df))
    p = 2.0 * (1.0 - norm_cdf(z))
    return float(max(0.0, min(1.0, p)))


def t_crit_95(df):
    """Approximate 95% two-sided t critical value."""
    table = {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 15: 2.131, 20: 2.086,
        25: 2.060, 30: 2.042,
    }
    if df <= 0:
        return 1.96
    if df in table:
        return table[df]
    if df > 30:
        return 1.96
    keys = sorted(table.keys())
    for i in range(len(keys) - 1):
        if keys[i] <= df <= keys[i + 1]:
            return table[keys[i]]
    return 2.0


def build_matched_100_with_diagnostics(df_all, gaemi100, max_marcap_ratio=4.0):
    """
    PHASE 7 Section 6: '비슷한 주식 100개' 구축 및 매칭 품질/한계 진단.
    - GAEMI 100 미포함 적격 보통주 중에서
      1순위: 동일 시장 + 동일 업종 (시총 비율 <= max_marcap_ratio)
      2순위: 동일 시장 내 시총 가장 유사 (시총 비율 <= max_marcap_ratio)
    - 시총 비율이 max_marcap_ratio를 초과하면 억지로 매칭하지 않고 미매칭으로 보고한다.
    """
    g100_codes = set(gaemi100["code"])
    pool = df_all[df_all["base_eligible"] & (~df_all["code"].isin(g100_codes))].copy()
    used_codes = set()
    matched_rows = []
    tier1_cnt = 0
    tier2_cnt = 0
    unmatched_list = []

    for _, p_row in gaemi100.iterrows():
        t_mkt = p_row["market"]
        t_ind = p_row["industry"]
        t_mc = max(float(p_row["end_marcap_eok"]), 1.0)
        avail = pool[~pool["code"].isin(used_codes)]
        if avail.empty:
            unmatched_list.append({"code": p_row["code"], "name": p_row["name"], "reason": "후보 고갈"})
            continue

        cand1 = avail[(avail["market"] == t_mkt) & (avail["industry"] == t_ind)]
        chosen = None
        tier = None
        if not cand1.empty:
            ratios1 = np.maximum(cand1["end_marcap_eok"] / t_mc, t_mc / np.maximum(cand1["end_marcap_eok"], 1.0))
            cand1_ok = cand1[ratios1 <= max_marcap_ratio]
            if not cand1_ok.empty:
                idx_best = (cand1_ok["end_marcap_eok"] - t_mc).abs().idxmin()
                chosen = cand1_ok.loc[idx_best]
                tier = 1
                tier1_cnt += 1

        if chosen is None:
            cand2 = avail[avail["market"] == t_mkt]
            if not cand2.empty:
                ratios2 = np.maximum(cand2["end_marcap_eok"] / t_mc, t_mc / np.maximum(cand2["end_marcap_eok"], 1.0))
                cand2_ok = cand2[ratios2 <= max_marcap_ratio]
                if not cand2_ok.empty:
                    idx_best = (cand2_ok["end_marcap_eok"] - t_mc).abs().idxmin()
                    chosen = cand2_ok.loc[idx_best]
                    tier = 2
                    tier2_cnt += 1

        if chosen is None:
            unmatched_list.append({
                "code": p_row["code"],
                "name": p_row["name"],
                "market": t_mkt,
                "industry": t_ind,
                "marcap_eok": round(t_mc, 1),
                "reason": f"동일 시장 내 시총 {max_marcap_ratio:.0f}배 이내 유사 종목 부재",
            })
            continue

        used_codes.add(chosen["code"])
        row_dict = chosen.to_dict()
        row_dict["match_tier"] = tier
        matched_rows.append(row_dict)

    df_matched = pd.DataFrame(matched_rows).reset_index(drop=True)
    if not df_matched.empty:
        df_matched["rank"] = range(1, len(df_matched) + 1)
        df_matched["weight"] = 1.0 / len(df_matched)

    diag = {
        "target_count": int(len(gaemi100)),
        "matched_count": int(len(df_matched)),
        "tier1_same_market_sector": int(tier1_cnt),
        "tier2_same_market_only": int(tier2_cnt),
        "unmatched_count": int(len(unmatched_list)),
        "unmatched_examples": unmatched_list[:5],
        "gaemi100_median_marcap_eok": round(float(gaemi100["end_marcap_eok"].median()), 1) if len(gaemi100) else 0.0,
        "matched100_median_marcap_eok": round(float(df_matched["end_marcap_eok"].median()), 1) if len(df_matched) else 0.0,
        "gaemi100_kosdaq_pct": round(float((gaemi100["market"] == "KOSDAQ").mean() * 100), 1) if len(gaemi100) else 0.0,
        "matched100_kosdaq_pct": round(float((df_matched["market"] == "KOSDAQ").mean() * 100), 1) if len(df_matched) else 0.0,
    }
    return df_matched, diag


def compute_capture(df_m, port_col, bench_col):
    """기하수익률 방식의 하락장/상승장 포착률 및 실제 평균 수익률 계산."""
    down = df_m[df_m[bench_col] < 0]
    up = df_m[df_m[bench_col] > 0]

    def geo_annual_or_period(s):
        n = len(s)
        if n == 0:
            return 0.0
        comp = float(np.prod(1.0 + s.values))
        if comp <= 0:
            return -100.0
        return (comp ** (1.0 / n) - 1.0) * 100.0

    p_down_geo = geo_annual_or_period(down[port_col])
    b_down_geo = geo_annual_or_period(down[bench_col])
    down_cap = (p_down_geo / b_down_geo) * 100.0 if b_down_geo != 0 else 0.0

    p_up_geo = geo_annual_or_period(up[port_col])
    b_up_geo = geo_annual_or_period(up[bench_col])
    up_cap = (p_up_geo / b_up_geo) * 100.0 if b_up_geo != 0 else 0.0

    p_down_mean = float(down[port_col].mean() * 100.0) if len(down) else 0.0
    b_down_mean = float(down[bench_col].mean() * 100.0) if len(down) else 0.0
    p_up_mean = float(up[port_col].mean() * 100.0) if len(up) else 0.0
    b_up_mean = float(up[bench_col].mean() * 100.0) if len(up) else 0.0
    worse_cnt = int((down[port_col] < down[bench_col]).sum()) if len(down) else 0

    return {
        "down_months_count": int(len(down)),
        "up_months_count": int(len(up)),
        "downside_capture_pct": round(down_cap, 1),
        "upside_capture_pct": round(up_cap, 1),
        "down_month_mean_pct": round(p_down_mean, 2),
        "bench_down_mean_pct": round(b_down_mean, 2),
        "down_month_gap_pctp": round(p_down_mean - b_down_mean, 2),
        "up_month_mean_pct": round(p_up_mean, 2),
        "bench_up_mean_pct": round(b_up_mean, 2),
        "up_month_gap_pctp": round(p_up_mean - b_up_mean, 2),
        "worse_than_bench_months_count": worse_cnt,
        "worse_than_bench_months_pct": round(worse_cnt / len(down) * 100.0, 1) if len(down) else 0.0,
    }


def compute_beta_and_downside_beta(port_ret, bench_ret):
    """시장 베타 및 하방 베타(기준시장 < 0 거래일 기준)."""
    p = np.asarray(port_ret, dtype=np.float64)
    b = np.asarray(bench_ret, dtype=np.float64)
    var_b = np.var(b, ddof=1)
    beta = float(np.cov(p, b, ddof=1)[0, 1] / var_b) if var_b > 0 else 1.0

    mask = b < 0
    if mask.sum() >= 10:
        p_d, b_d = p[mask], b[mask]
        var_bd = np.var(b_d, ddof=1)
        down_beta = float(np.cov(p_d, b_d, ddof=1)[0, 1] / var_bd) if var_bd > 0 else 1.0
    else:
        down_beta = beta
    return round(beta, 3), round(down_beta, 3)


def newey_west_tstat(diff_series, max_lag=5):
    """Newey-West HAC t-statistic for paired daily return difference (accounts for autocorrelation & vol clustering)."""
    x = np.asarray(diff_series, dtype=np.float64)
    n = len(x)
    if n < 5:
        return 0.0, 0.0, 1.0
    mean_x = float(np.mean(x))
    e = x - mean_x
    gamma0 = float(np.dot(e, e) / n)
    var_nw = gamma0
    for lag in range(1, min(max_lag, n - 1) + 1):
        w = 1.0 - lag / (max_lag + 1.0)
        gamma_l = float(np.dot(e[lag:], e[:-lag]) / n)
        var_nw += 2.0 * w * gamma_l
    se = math.sqrt(max(var_nw / n, 1e-18))
    t_val = mean_x / se
    p_val = two_sided_p_from_t(t_val, n - 1)
    return round(mean_x * 100.0, 4), round(t_val, 3), round(p_val, 4)


def paired_monthly_ci(vals, bench_vals):
    """Monthly sample mean, median, std, 95% CI, paired diff vs bench, t-stat, p-value."""
    x = np.asarray(vals, dtype=np.float64) * 100.0
    b = np.asarray(bench_vals, dtype=np.float64) * 100.0
    n = len(x)
    if n < 2:
        return {"n": int(n), "mean": 0.0, "median": 0.0, "std": 0.0, "ci95": [0.0, 0.0], "diff_mean": 0.0, "t_stat": 0.0, "p_value": 1.0}
    mean_x = float(np.mean(x))
    med_x = float(np.median(x))
    std_x = float(np.std(x, ddof=1))
    t_c = t_crit_95(n - 1)
    se_x = std_x / math.sqrt(n)
    diff = x - b
    mean_d = float(np.mean(diff))
    std_d = float(np.std(diff, ddof=1))
    se_d = std_d / math.sqrt(n) if std_d > 0 else 1e-9
    t_d = mean_d / se_d
    p_d = two_sided_p_from_t(t_d, n - 1)
    ci_d = [round(mean_d - t_c * se_d, 2), round(mean_d + t_c * se_d, 2)]
    return {
        "n": int(n),
        "mean_pct": round(mean_x, 2),
        "median_pct": round(med_x, 2),
        "std_pct": round(std_x, 2),
        "ci95_pct": [round(mean_x - t_c * se_x, 2), round(mean_x + t_c * se_x, 2)],
        "diff_mean_pctp": round(mean_d, 2),
        "diff_ci95_pctp": ci_d,
        "t_stat": round(t_d, 3),
        "p_value": round(p_d, 4),
    }


def compute_stock_prior_features(trades, det_date, codes):
    """Compute prior 60d volatility, 3m return, 12m return as of determination_date (zero look-ahead)."""
    sub = trades[(trades["date"] <= det_date) & (trades["code"].isin(codes))].copy()
    sub = sub.sort_values(["code", "date"])
    feats = {}
    for code, grp in sub.groupby("code"):
        rets = grp["gross_ret"].values - 1.0
        vol60 = float(np.std(rets[-60:], ddof=1) * math.sqrt(252) * 100.0) if len(rets) >= 20 else np.nan
        r3m = float((np.prod(grp["gross_ret"].values[-60:]) - 1.0) * 100.0) if len(rets) >= 20 else np.nan
        r12m = float((np.prod(grp["gross_ret"].values[-240:]) - 1.0) * 100.0) if len(rets) >= 120 else np.nan
        feats[code] = {"vol_60d_pct": vol60, "ret_3m_pct": r3m, "ret_12m_pct": r12m}
    return feats


def run_controlled_cross_sectional_regression(q_records):
    """
    PHASE 7 Section 4: 개별 종목 단위의 순매수 강도와 이후 하락장 일간 수익률 사이의 관계
    (로그 시가총액, 직전 60일 변동성, 코스닥 여부, 업종 더미 통제 후 OLS t-검정).
    """
    df = pd.DataFrame(q_records).dropna(subset=["intensity_pct", "down_day_mean_ret_pct", "log_marcap", "vol_60d_pct"])
    if len(df) < 30:
        return {"n_obs": int(len(df)), "spearman_r": 0.0, "ols_beta_intensity": 0.0, "ols_t_stat": 0.0, "ols_p_value": 1.0}

    spear = float(df["intensity_pct"].rank().corr(df["down_day_mean_ret_pct"].rank()))

    # Demean within (quarter x market x industry) or quarter + top-sector dummies
    top_inds = df["industry"].value_counts().head(8).index.tolist()
    df["ind_grp"] = np.where(df["industry"].isin(top_inds), df["industry"], "OTHER")
    X_parts = [
        df[["intensity_pct", "log_marcap", "vol_60d_pct", "is_kosdaq"]].astype(float),
        pd.get_dummies(df["quarter"], prefix="q", drop_first=True, dtype=float),
        pd.get_dummies(df["ind_grp"], prefix="ind", drop_first=True, dtype=float),
    ]
    X_df = pd.concat(X_parts, axis=1)
    X_mat = np.column_stack([np.ones(len(X_df)), X_df.values])
    y_vec = df["down_day_mean_ret_pct"].values.astype(np.float64)

    beta_hat, _, _, _ = np.linalg.lstsq(X_mat, y_vec, rcond=None)
    resid = y_vec - X_mat @ beta_hat
    n, k = X_mat.shape
    s2 = float(np.dot(resid, resid) / max(n - k, 1))
    cov_b = s2 * np.linalg.pinv(X_mat.T @ X_mat)
    se_int = math.sqrt(max(cov_b[1, 1], 1e-18))
    b_int = float(beta_hat[1])
    t_int = b_int / se_int
    p_int = two_sided_p_from_t(t_int, max(n - k, 1))

    # Raw (uncontrolled) slope
    X_raw = np.column_stack([np.ones(len(df)), df["intensity_pct"].values])
    b_raw, _, _, _ = np.linalg.lstsq(X_raw, y_vec, rcond=None)
    res_raw = y_vec - X_raw @ b_raw
    se_raw = math.sqrt(max((np.dot(res_raw, res_raw) / max(len(df) - 2, 1)) * np.linalg.pinv(X_raw.T @ X_raw)[1, 1], 1e-18))
    t_raw = float(b_raw[1]) / se_raw

    return {
        "n_obs": int(n),
        "spearman_corr_raw": round(spear, 4),
        "raw_slope_per_10pct_intensity": round(float(b_raw[1]) * 10.0, 4),
        "raw_t_stat": round(t_raw, 3),
        "raw_p_value": round(two_sided_p_from_t(t_raw, len(df) - 2), 4),
        "controlled_slope_per_10pct_intensity": round(b_int * 10.0, 4),
        "controlled_t_stat": round(t_int, 3),
        "controlled_p_value": round(p_int, 4),
        "controls": "분기 고정효과 · 시장(코스피/코스닥) · 업종 · 로그 시가총액 · 직전 60일 변동성",
    }


def main():
    print("[PHASE 7] GAEMI 100 확대 및 하락장 취약성 검증 시작...")
    universe, trades, bench = prepare_audited_ledger()
    universe_map = universe.set_index("Code").to_dict(orient="index")

    trading_dates = sorted(trades["date"].unique().tolist())
    schedule = get_rebalance_schedule(trading_dates)
    base_date = schedule[0]["determination_date"]

    sub_ret = trades[trades["date"] >= base_date][["date", "code", "gross_ret"]]
    ret_pivot = sub_ret.pivot(index="date", columns="code", values="gross_ret").fillna(1.0)
    all_dates_since_base = sorted(ret_pivot.index.tolist())
    del sub_ret

    # 1. Holdings containers across 9 quarters
    holdings = {
        "GAEMI_30": {},
        "GAEMI_50": {},
        "GAEMI_75": {},
        "GAEMI_100": {},
        "GAEMI_150": {},
        "GAEMI_51_100": {},
        "GAEMI_101_150": {},
        "MATCHED_50_EW": {},
        "MATCHED_100_EW": {},
        "KOSDAQ_EW": {},
        "GAEMI_100_METHOD_B": {},
    }

    matched100_diag_by_q = []
    comp_rows_by_q = []
    ab_stab_rows = []
    cross_sec_records = []

    # Prepare Method B net value (base_price + reg_close) / 2
    trades["ind_net_val_b"] = trades["krx_ind_net_vol"] * ((trades["base_price"] + trades["reg_close"]) / 2.0)

    prev_sets = {"GAEMI_50": set(), "GAEMI_100": set(), "GAEMI_51_100": set()}
    prev_rank100 = {}
    first_entry_info_100 = {}

    # Benchmark daily returns for cross-sectional down-day evaluation
    b_sub = bench[bench["date"] >= base_date].sort_values("date").copy()
    b_sub["kq_ret"] = b_sub["KOSDAQ"].pct_change().fillna(0.0)
    kq_down_dates_set = set(b_sub[b_sub["kq_ret"] < 0]["date"])

    latest_df_all = None
    latest_ind100 = None

    for qi, q in enumerate(schedule):
        qid = q["rebalance_id"]
        det_date = q["determination_date"]
        eff_start = q["effective_start"]
        eff_end = q["effective_end"]

        df_all, ind50, _, _, _ = evaluate_quarter_cross_section(
            trades, universe_map, q, min_marcap_eok=3000.0, min_adtv_60d_eok=10.0, min_obs_ratio=0.90
        )
        elig_ind = df_all[df_all["is_eligible_pure"]].sort_values("intensity_pct", ascending=False).reset_index(drop=True)

        ind30 = elig_ind.head(30).copy()
        ind75 = elig_ind.head(75).copy()
        ind100 = elig_ind.head(100).copy()
        ind150 = elig_ind.head(150).copy()
        ind51_100 = elig_ind.iloc[50:100].copy()
        ind101_150 = elig_ind.iloc[100:150].copy()

        for sub_df in [ind30, ind50, ind75, ind100, ind150, ind51_100, ind101_150]:
            sub_df["rank"] = range(1, len(sub_df) + 1)
            sub_df["weight"] = 1.0 / len(sub_df) if len(sub_df) else 0.0

        matched50 = build_matched_comparison_portfolio(df_all, ind50)
        matched100, m100_diag = build_matched_100_with_diagnostics(df_all, ind100, max_marcap_ratio=4.0)
        m100_diag["quarter"] = qid
        matched100_diag_by_q.append(m100_diag)

        kq_elig = df_all[(df_all["market"] == "KOSDAQ") & df_all["base_eligible"]].copy()
        kq_elig["weight"] = 1.0 / len(kq_elig) if len(kq_elig) > 0 else 0.0

        # Method B ranking
        w_start = q["window_36m_start"]
        w_end = q["determination_date"]
        win_tr = trades[(trades["date"] >= w_start) & (trades["date"] <= w_end)]
        b_net = win_tr.groupby("code")["ind_net_val_b"].sum()
        df_all["ind_net_val_b"] = df_all["code"].map(b_net).fillna(0.0)
        df_all["ind_intensity_b_pct"] = np.where(
            df_all["avg_marcap_36m"] > 0, (df_all["ind_net_val_b"] / df_all["avg_marcap_36m"]) * 100.0, 0.0
        )
        elig_b = df_all[df_all["base_eligible"] & (df_all["ind_net_val_b"] > 0)].sort_values("ind_intensity_b_pct", ascending=False).reset_index(drop=True)
        b_top50 = set(elig_b.head(50)["code"])
        b_top100 = elig_b.head(100).copy()
        b_top100["weight"] = 1.0 / len(b_top100) if len(b_top100) else 0.0
        b_51_100 = set(elig_b.iloc[50:100]["code"])

        a50_set = set(ind50["code"])
        a100_set = set(ind100["code"])
        a51_100_set = set(ind51_100["code"])
        ab_stab_rows.append({
            "quarter": qid,
            "top50_overlap_pct": round(len(a50_set & b_top50) / 50.0 * 100.0, 1),
            "top100_overlap_pct": round(len(a100_set & set(b_top100["code"])) / 100.0 * 100.0, 1),
            "rank51_100_overlap_pct": round(len(a51_100_set & b_51_100) / 50.0 * 100.0, 1),
            "a100_kosdaq_pct": round(float((ind100["market"] == "KOSDAQ").mean() * 100.0), 1),
            "b100_kosdaq_pct": round(float((b_top100["market"] == "KOSDAQ").mean() * 100.0), 1),
            "a100_med_marcap_eok": round(float(ind100["end_marcap_eok"].median()), 1),
            "b100_med_marcap_eok": round(float(b_top100["end_marcap_eok"].median()), 1),
        })

        # Prior features for composition comparison (Section 5)
        codes_150 = set(ind150["code"])
        p_feats = compute_stock_prior_features(trades, det_date, codes_150)

        for label, sub_df in [("GAEMI_50", ind50), ("GAEMI_100", ind100), ("GAEMI_51_100", ind51_100)]:
            curr_s = set(sub_df["code"])
            added_cnt = len(curr_s - prev_sets[label]) if prev_sets[label] else len(curr_s)
            removed_cnt = len(prev_sets[label] - curr_s) if prev_sets[label] else 0
            prev_sets[label] = curr_s

            vols = [p_feats[c]["vol_60d_pct"] for c in sub_df["code"] if c in p_feats and np.isfinite(p_feats[c]["vol_60d_pct"])]
            r3s = [p_feats[c]["ret_3m_pct"] for c in sub_df["code"] if c in p_feats and np.isfinite(p_feats[c]["ret_3m_pct"])]
            r12s = [p_feats[c]["ret_12m_pct"] for c in sub_df["code"] if c in p_feats and np.isfinite(p_feats[c]["ret_12m_pct"])]

            top_sec = sub_df["industry"].value_counts().head(3)
            comp_rows_by_q.append({
                "quarter": qid,
                "index": label,
                "count": int(len(sub_df)),
                "kospi_pct": round(float((sub_df["market"] == "KOSPI").mean() * 100.0), 1),
                "kosdaq_pct": round(float((sub_df["market"] == "KOSDAQ").mean() * 100.0), 1),
                "marcap_median_eok": round(float(sub_df["end_marcap_eok"].median()), 1),
                "marcap_mean_eok": round(float(sub_df["end_marcap_eok"].mean()), 1),
                "adtv60_median_eok": round(float(sub_df["adtv_60d_eok"].median()), 1),
                "vol_60d_mean_pct": round(float(np.mean(vols)), 2) if vols else 0.0,
                "ret_3m_mean_pct": round(float(np.mean(r3s)), 2) if r3s else 0.0,
                "ret_12m_mean_pct": round(float(np.mean(r12s)), 2) if r12s else 0.0,
                "added_count": int(added_cnt),
                "removed_count": int(removed_cnt),
                "top_sectors": ", ".join([f"{k}({v})" for k, v in top_sec.items()]),
            })

        # Cross-sectional stock-level downside day returns in the upcoming effective quarter
        q_dates = [d for d in all_dates_since_base if eff_start <= d <= eff_end and d in kq_down_dates_set]
        if q_dates:
            sub_q_ret = ret_pivot.loc[q_dates]
            for _, row in ind150.iterrows():
                c = row["code"]
                if c in sub_q_ret.columns and c in p_feats:
                    d_mean = float((sub_q_ret[c].mean() - 1.0) * 100.0)
                    cross_sec_records.append({
                        "quarter": qid,
                        "code": c,
                        "intensity_pct": float(row["intensity_pct"]),
                        "log_marcap": math.log(max(float(row["end_marcap_eok"]), 1.0)),
                        "vol_60d_pct": p_feats[c]["vol_60d_pct"],
                        "is_kosdaq": 1.0 if row["market"] == "KOSDAQ" else 0.0,
                        "industry": row["industry"],
                        "down_day_mean_ret_pct": d_mean,
                    })

        # Track first entry & rank change for GAEMI 100 constituents table
        def calc_rank_delta_100(row):
            c = row["code"]
            curr_r = int(row["rank"])
            if not prev_rank100:
                return "초기편입"
            if c not in prev_rank100:
                return "NEW"
            diff = prev_rank100[c] - curr_r
            return f"▲ +{diff}" if diff > 0 else (f"▼ {diff}" if diff < 0 else "-")

        ind100["prev_quarter_rank"] = ind100["code"].map(lambda c: prev_rank100.get(c, None))
        ind100["rank_change_str"] = ind100.apply(calc_rank_delta_100, axis=1)
        for _, row in ind100.iterrows():
            c = row["code"]
            if c not in first_entry_info_100:
                first_entry_info_100[c] = {
                    "quarter": qid,
                    "det_date": det_date,
                    "eff_start": eff_start,
                    "entry_close": int(row["last_close"]),
                }
        prev_rank100 = ind100.set_index("code")["rank"].to_dict()

        holdings["GAEMI_30"][qid] = ind30
        holdings["GAEMI_50"][qid] = ind50
        holdings["GAEMI_75"][qid] = ind75
        holdings["GAEMI_100"][qid] = ind100
        holdings["GAEMI_150"][qid] = ind150
        holdings["GAEMI_51_100"][qid] = ind51_100
        holdings["GAEMI_101_150"][qid] = ind101_150
        holdings["MATCHED_50_EW"][qid] = matched50
        holdings["MATCHED_100_EW"][qid] = matched100
        holdings["KOSDAQ_EW"][qid] = kq_elig
        holdings["GAEMI_100_METHOD_B"][qid] = b_top100

        if qi == len(schedule) - 1:
            latest_df_all = df_all.copy()
            latest_ind100 = ind100.copy()

    # 2. Compute equal-weight index time series for all portfolios
    print("[PHASE 7] 11개 지수 시계열 백테스트 계산 중...")
    ts_dict = {}
    for key, h_by_q in holdings.items():
        df_s = compute_equal_weight_index_series(ret_pivot, all_dates_since_base, schedule, h_by_q, base_date=base_date, base_val=1000.0)
        ts_dict[key] = df_s[["date", "index_value"]].rename(columns={"index_value": key})

    merged = ts_dict["GAEMI_50"].copy()
    for key in ts_dict:
        if key != "GAEMI_50":
            merged = merged.merge(ts_dict[key], on="date", how="left")

    b_norm = bench[bench["date"] >= base_date].sort_values("date").copy()
    b_norm["KOSPI"] = b_norm["KOSPI"] / b_norm["KOSPI"].iloc[0] * 1000.0
    b_norm["KOSDAQ"] = b_norm["KOSDAQ"] / b_norm["KOSDAQ"].iloc[0] * 1000.0
    merged = merged.merge(b_norm[["date", "KOSPI", "KOSDAQ"]], on="date", how="left").ffill()

    # Daily returns
    all_keys = list(holdings.keys()) + ["KOSPI", "KOSDAQ"]
    df_ret = pd.DataFrame({"date": merged["date"]})
    for k in all_keys:
        df_ret[k] = merged[k].pct_change().fillna(0.0)

    df_days = df_ret.iloc[1:].copy()
    df_days["ym"] = df_days["date"].str.slice(0, 7)

    # Monthly returns using exact month-end index levels (aligned 100% with Phase 6)
    merged_ym = merged.copy()
    merged_ym["ym"] = merged_ym["date"].str.slice(0, 7)
    month_ends = merged_ym.groupby("ym", as_index=False).last().sort_values("ym").reset_index(drop=True)
    m_rows = []
    for i in range(1, len(month_ends)):
        prev_r = month_ends.iloc[i - 1]
        curr_r = month_ends.iloc[i]
        row = {"ym": curr_r["ym"]}
        for k in all_keys:
            v0, v1 = float(prev_r[k]), float(curr_r[k])
            row[k] = round((v1 / v0 - 1.0), 4) if v0 > 0 else 0.0
        m_rows.append(row)
    df_monthly = pd.DataFrame(m_rows)

    # 3. Performance, Capture, Daily/Monthly Downside, Betas, Statistical Tests
    k_rets = df_ret["KOSPI"].values * 100.0
    q_rets = df_ret["KOSDAQ"].values * 100.0

    perf_summary = {}
    for k in all_keys:
        stats = calc_perf_stats(merged[k].values, df_ret[k].values * 100.0, k_rets, q_rets)
        cap_kq = compute_capture(df_monthly, k, "KOSDAQ")
        cap_kp = compute_capture(df_monthly, k, "KOSPI")
        beta_kq, dbeta_kq = compute_beta_and_downside_beta(df_days[k].values, df_days["KOSDAQ"].values)
        beta_kp, dbeta_kp = compute_beta_and_downside_beta(df_days[k].values, df_days["KOSPI"].values)
        stats.update({
            "vs_kosdaq": cap_kq,
            "vs_kospi": cap_kp,
            "beta_kosdaq": beta_kq,
            "downside_beta_kosdaq": dbeta_kq,
            "beta_kospi": beta_kp,
            "downside_beta_kospi": dbeta_kp,
        })
        perf_summary[k] = stats

    # Daily downside comparison (KOSDAQ < 0 days)
    kq_down_days = df_days[df_days["KOSDAQ"] < 0]
    daily_down_table = {}
    for k in ["GAEMI_50", "GAEMI_100", "GAEMI_51_100", "GAEMI_101_150", "MATCHED_50_EW", "MATCHED_100_EW", "KOSDAQ_EW", "KOSPI", "KOSDAQ"]:
        s = kq_down_days[k].values * 100.0
        b = kq_down_days["KOSDAQ"].values * 100.0
        mean_diff_nw, nw_t, nw_p = newey_west_tstat(kq_down_days[k].values - kq_down_days["KOSDAQ"].values, max_lag=5)
        daily_down_table[k] = {
            "days": int(len(s)),
            "mean_pct": round(float(np.mean(s)), 3),
            "median_pct": round(float(np.median(s)), 3),
            "gap_vs_kosdaq_pctp": round(float(np.mean(s) - np.mean(b)), 3),
            "worse_than_kosdaq_pct": round(float((s < b).mean() * 100.0), 1),
            "up_on_down_day_pct": round(float((s > 0).mean() * 100.0), 1),
            "nw_hac_t_vs_kosdaq": nw_t,
            "nw_hac_p_vs_kosdaq": nw_p,
        }

    # Monthly statistical tests (Section 11)
    kq_down_m = df_monthly[df_monthly["KOSDAQ"] < 0]
    stat_tests = {}
    for k, match_k in [("GAEMI_50", "MATCHED_50_EW"), ("GAEMI_100", "MATCHED_100_EW"), ("GAEMI_51_100", "MATCHED_50_EW"), ("GAEMI_101_150", "MATCHED_100_EW")]:
        vs_kq = paired_monthly_ci(kq_down_m[k].values, kq_down_m["KOSDAQ"].values)
        vs_mt = paired_monthly_ci(kq_down_m[k].values, kq_down_m[match_k].values)
        stat_tests[k] = {
            "vs_kosdaq_down_months": vs_kq,
            "vs_matched_down_months": vs_mt,
            "matched_benchmark": match_k,
        }

    # Sub-period sensitivity (Section 7: first half vs second half)
    mid_idx = len(merged) // 2
    sensitivity_n = []
    for n_val, k in [(30, "GAEMI_30"), (50, "GAEMI_50"), (75, "GAEMI_75"), (100, "GAEMI_100"), (150, "GAEMI_150")]:
        p = perf_summary[k]
        r_h1 = (merged[k].iloc[mid_idx] / merged[k].iloc[0] - 1.0) * 100.0
        r_h2 = (merged[k].iloc[-1] / merged[k].iloc[mid_idx] - 1.0) * 100.0
        kq_h1 = (merged["KOSDAQ"].iloc[mid_idx] / merged["KOSDAQ"].iloc[0] - 1.0) * 100.0
        kq_h2 = (merged["KOSDAQ"].iloc[-1] / merged["KOSDAQ"].iloc[mid_idx] - 1.0) * 100.0
        sensitivity_n.append({
            "n_stocks": n_val,
            "key": k,
            "total_return_pct": p["total_return_pct"],
            "excess_vs_kosdaq_pctp": round(p["total_return_pct"] - perf_summary["KOSDAQ"]["total_return_pct"], 2),
            "mdd_pct": p["mdd_pct"],
            "ann_volatility_pct": p["ann_volatility_pct"],
            "downside_capture_kosdaq_pct": p["vs_kosdaq"]["downside_capture_pct"],
            "upside_capture_kosdaq_pct": p["vs_kosdaq"]["upside_capture_pct"],
            "corr_kosdaq": p["corr_kosdaq"],
            "first_half_excess_pctp": round(r_h1 - kq_h1, 2),
            "second_half_excess_pctp": round(r_h2 - kq_h2, 2),
        })

    # 4. Drawdown Episodes Comparison (using Phase 6 episodes)
    p6_path = os.path.join(DATA_DIR, "phase6_downside_analysis.json")
    episode_comp = []
    if os.path.exists(p6_path):
        p6 = json.load(open(p6_path, encoding="utf-8"))
        for ep in p6.get("drawdown_episodes", {}).get("kosdaq_episodes", []):
            sd, ed = ep["start_date"], ep["end_date"]
            sub_m = merged[(merged["date"] >= sd) & (merged["date"] <= ed)]
            if len(sub_m) < 2:
                continue
            rets_ep = {}
            for k in ["GAEMI_50", "GAEMI_100", "GAEMI_51_100", "MATCHED_50_EW", "MATCHED_100_EW", "KOSPI", "KOSDAQ"]:
                rets_ep[k] = round((float(sub_m[k].iloc[-1]) / float(sub_m[k].iloc[0]) - 1.0) * 100.0, 2)
            episode_comp.append({
                "episode_id": ep["episode_id"],
                "title": ep["title"],
                "start_date": sd,
                "end_date": ed,
                "trading_days": ep["trading_days_to_trough"],
                "returns_pct": rets_ep,
            })

    # 5. Controlled Cross-Sectional Regression (Section 4)
    cross_sec_reg = run_controlled_cross_sectional_regression(cross_sec_records)

    # 6. Composition 9-quarter averages (Section 5)
    df_comp = pd.DataFrame(comp_rows_by_q)
    comp_avg = {}
    for label, grp in df_comp.groupby("index"):
        comp_avg[label] = {
            "count": int(grp["count"].mean()),
            "kospi_pct": round(float(grp["kospi_pct"].mean()), 1),
            "kosdaq_pct": round(float(grp["kosdaq_pct"].mean()), 1),
            "marcap_median_eok": round(float(grp["marcap_median_eok"].mean()), 1),
            "marcap_mean_eok": round(float(grp["marcap_mean_eok"].mean()), 1),
            "adtv60_median_eok": round(float(grp["adtv60_median_eok"].mean()), 1),
            "vol_60d_mean_pct": round(float(grp["vol_60d_mean_pct"].mean()), 2),
            "ret_3m_mean_pct": round(float(grp["ret_3m_mean_pct"].mean()), 2),
            "ret_12m_mean_pct": round(float(grp["ret_12m_mean_pct"].mean()), 2),
            "avg_added_per_q": round(float(grp["added_count"].iloc[1:].mean()), 1),
            "avg_removed_per_q": round(float(grp["removed_count"].iloc[1:].mean()), 1),
        }

    # 7. Latest Top 100 Constituents export (Section 9-5)
    latest_ind100["tier"] = np.where(latest_ind100["rank"] <= 50, "1~50위", "51~100위")
    latest_ind100["first_entry_quarter"] = latest_ind100["code"].map(lambda c: first_entry_info_100[c]["quarter"])
    latest_ind100["first_entry_date"] = latest_ind100["code"].map(lambda c: first_entry_info_100[c]["eff_start"])
    latest_ind100["entry_close"] = latest_ind100["code"].map(lambda c: first_entry_info_100[c]["entry_close"])
    latest_ind100["ret_since_entry_pct"] = np.where(
        latest_ind100["entry_close"] > 0,
        (latest_ind100["last_close"] / latest_ind100["entry_close"] - 1.0) * 100.0,
        0.0,
    ).round(2)

    if "ind_net_val_eok" not in latest_ind100.columns:
        latest_ind100["ind_net_val_eok"] = (latest_ind100["ind_net_val"] / 1e8).round(2)
    cols_100 = [
        "rank", "tier", "code", "name", "market", "industry", "intensity_pct",
        "ind_net_val_eok", "avg_marcap_36m_eok", "end_marcap_eok", "last_close",
        "ret_since_entry_pct", "prev_quarter_rank", "rank_change_str",
        "first_entry_quarter", "first_entry_date",
    ]
    constituents_100 = latest_ind100[cols_100].to_dict(orient="records")

    # Stock trajectories for 51~100 (so clicking any stock in Top 100 works in Tab 2)
    extra_codes_51_100 = set(latest_ind100.iloc[50:100]["code"])
    sub_tr51 = trades[(trades["date"] >= "2023-10-01") & (trades["code"].isin(extra_codes_51_100))].copy()
    sub_tr51["ym"] = sub_tr51["date"].str.slice(0, 7)
    stock_trajectories_51_100 = {}
    for code, grp in sub_tr51.groupby("code"):
        grp = grp.sort_values("date")
        m_grp = grp.groupby("ym").agg(
            close=("reg_close", "last"),
            ind_net_eok=("krx_ind_net_val", lambda s: round(float(s.sum() / 1e8), 2)),
        ).reset_index()
        stock_trajectories_51_100[code] = m_grp.to_dict(orient="records")

    # 8. Method A vs B summary (Section 10)
    ab_df = pd.DataFrame(ab_stab_rows)
    ab_summary = {
        "avg_top50_overlap_pct": round(float(ab_df["top50_overlap_pct"].mean()), 1),
        "avg_top100_overlap_pct": round(float(ab_df["top100_overlap_pct"].mean()), 1),
        "avg_rank51_100_overlap_pct": round(float(ab_df["rank51_100_overlap_pct"].mean()), 1),
        "gaemi100_a_total_return_pct": perf_summary["GAEMI_100"]["total_return_pct"],
        "gaemi100_b_total_return_pct": perf_summary["GAEMI_100_METHOD_B"]["total_return_pct"],
        "gaemi100_a_downside_capture_pct": perf_summary["GAEMI_100"]["vs_kosdaq"]["downside_capture_pct"],
        "gaemi100_b_downside_capture_pct": perf_summary["GAEMI_100_METHOD_B"]["vs_kosdaq"]["downside_capture_pct"],
        "quarterly_rows": ab_stab_rows,
    }

    # 9. Objective Headline & Index Decision Summary (Section 8 & 14)
    p50 = perf_summary["GAEMI_50"]
    p100 = perf_summary["GAEMI_100"]
    p51 = perf_summary["GAEMI_51_100"]
    p101 = perf_summary["GAEMI_101_150"]

    # Determine intensity monotonicity empirically
    d50 = p50["vs_kosdaq"]["down_month_mean_pct"]
    d51 = p51["vs_kosdaq"]["down_month_mean_pct"]
    d101 = p101["vs_kosdaq"]["down_month_mean_pct"]
    monotonic_worse = (d50 < d51 < d101)

    phase7_payload = sanitize_for_json({
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base_date": base_date,
        "data_as_of": merged["date"].iloc[-1],
        "total_trading_days": int(len(df_days)),
        "total_months": int(len(df_monthly)),
        "perf_summary": perf_summary,
        "daily_downside_table": daily_down_table,
        "intensity_tiers": [
            {
                "tier": "1~50위 (GAEMI 50)",
                "key": "GAEMI_50",
                "down_month_mean_pct": p50["vs_kosdaq"]["down_month_mean_pct"],
                "up_month_mean_pct": p50["vs_kosdaq"]["up_month_mean_pct"],
                "downside_capture_pct": p50["vs_kosdaq"]["downside_capture_pct"],
                "upside_capture_pct": p50["vs_kosdaq"]["upside_capture_pct"],
                "mdd_pct": p50["mdd_pct"],
                "ann_volatility_pct": p50["ann_volatility_pct"],
                "beta_kosdaq": p50["beta_kosdaq"],
                "downside_beta_kosdaq": p50["downside_beta_kosdaq"],
            },
            {
                "tier": "51~100위",
                "key": "GAEMI_51_100",
                "down_month_mean_pct": p51["vs_kosdaq"]["down_month_mean_pct"],
                "up_month_mean_pct": p51["vs_kosdaq"]["up_month_mean_pct"],
                "downside_capture_pct": p51["vs_kosdaq"]["downside_capture_pct"],
                "upside_capture_pct": p51["vs_kosdaq"]["upside_capture_pct"],
                "mdd_pct": p51["mdd_pct"],
                "ann_volatility_pct": p51["ann_volatility_pct"],
                "beta_kosdaq": p51["beta_kosdaq"],
                "downside_beta_kosdaq": p51["downside_beta_kosdaq"],
            },
            {
                "tier": "101~150위",
                "key": "GAEMI_101_150",
                "down_month_mean_pct": p101["vs_kosdaq"]["down_month_mean_pct"],
                "up_month_mean_pct": p101["vs_kosdaq"]["up_month_mean_pct"],
                "downside_capture_pct": p101["vs_kosdaq"]["downside_capture_pct"],
                "upside_capture_pct": p101["vs_kosdaq"]["upside_capture_pct"],
                "mdd_pct": p101["mdd_pct"],
                "ann_volatility_pct": p101["ann_volatility_pct"],
                "beta_kosdaq": p101["beta_kosdaq"],
                "downside_beta_kosdaq": p101["downside_beta_kosdaq"],
            },
        ],
        "intensity_monotonic_worse": monotonic_worse,
        "controlled_regression": cross_sec_reg,
        "composition_avg": comp_avg,
        "composition_quarterly": comp_rows_by_q,
        "matched100_diagnostics": {
            "avg_matched_count": round(float(np.mean([d["matched_count"] for d in matched100_diag_by_q])), 1),
            "avg_tier1_same_sector": round(float(np.mean([d["tier1_same_market_sector"] for d in matched100_diag_by_q])), 1),
            "avg_tier2_same_market": round(float(np.mean([d["tier2_same_market_only"] for d in matched100_diag_by_q])), 1),
            "avg_unmatched": round(float(np.mean([d["unmatched_count"] for d in matched100_diag_by_q])), 1),
            "by_quarter": matched100_diag_by_q,
        },
        "sensitivity_n": sensitivity_n,
        "ab_stability": ab_summary,
        "statistical_tests": stat_tests,
        "episode_comparison": episode_comp,
        "timeseries_phase7": merged[["date", "GAEMI_50", "GAEMI_100", "GAEMI_51_100", "MATCHED_100_EW"]].to_dict(orient="records"),
        "constituents_100": constituents_100,
        "stock_trajectories_51_100": stock_trajectories_51_100,
    })

    out_path = os.path.join(DATA_DIR, "phase7_expansion_analysis.json")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(phase7_payload, f, ensure_ascii=False, indent=2, allow_nan=False)
    os.replace(tmp_path, out_path)

    print(f"[PHASE 7 완료] 저장: {out_path}")
    print(f"  GAEMI 50    : 누적 {p50['total_return_pct']:+.2f}% | MDD {p50['mdd_pct']:.2f}% | 하락포착 {p50['vs_kosdaq']['downside_capture_pct']}% | 상승포착 {p50['vs_kosdaq']['upside_capture_pct']}%")
    print(f"  GAEMI 100   : 누적 {p100['total_return_pct']:+.2f}% | MDD {p100['mdd_pct']:.2f}% | 하락포착 {p100['vs_kosdaq']['downside_capture_pct']}% | 상승포착 {p100['vs_kosdaq']['upside_capture_pct']}%")
    print(f"  GAEMI 51-100: 누적 {p51['total_return_pct']:+.2f}% | MDD {p51['mdd_pct']:.2f}% | 하락포착 {p51['vs_kosdaq']['downside_capture_pct']}% | 상승포착 {p51['vs_kosdaq']['upside_capture_pct']}%")
    print(f"  GAEMI 101-150: 누적 {p101['total_return_pct']:+.2f}% | 하락월평균 {d101:+.2f}% | 하락포착 {p101['vs_kosdaq']['downside_capture_pct']}%")
    print(f"  단조 취약성(1-50 < 51-100 < 101-150): {monotonic_worse} | 통제회귀 t={cross_sec_reg['controlled_t_stat']} (p={cross_sec_reg['controlled_p_value']})")


if __name__ == "__main__":
    main()
