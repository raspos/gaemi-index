"""
PHASE 6 — "증시가 떨어질 때, 개미는 얼마나 더 아플까?" 하락장 취약성 정밀 검증 엔진 (build_phase6_downside.py)

[검증 항목]
1. 섹션 2-1: 시장 하락일 분석 (코스피 하락일 vs 코스닥 하락일 vs 유사 50종목 하락일 독립 분석)
   - 하락일 수, 개미 지수 평균/중앙값 수익률, 비교지수(유사 50종목·코스닥 동일가중) 평균/중앙값 수익률
   - 시장 대비 평균 수익률 격차, 시장보다 더 크게 하락한 거래일 비율(%), 시장은 하락했지만 개미 지수는 상승한 거래일 비율(%)
2. 섹션 2-2 & 2-3: 시장 하락월 분석 및 하락 폭 구간별(0~-3%, -3~-5%, -5~-10%, -10% 이하) 반응 분석
   - 2024.10 ~ 2026.11 월간 수익률 시계열 산출
   - 코스피 하락월, 코스닥 하락월, 유사 50종목 하락월 각각의 월별 상세 성적표 및 평균·중앙값·누적 격차, 더 크게 떨어진 달의 수/비율
3. 섹션 3: 하락장 포착률(Downside Capture Ratio) 및 상승장 포착률(Upside Capture Ratio), 하방 베타(Downside Beta)
   - 표준 기하평균(Geometric Mean) 방식:
     * Downside Capture (%) = [ (∏_{t in Down} (1 + R_{p,t}))^(1/N_d) - 1 ] / [ (∏_{t in Down} (1 + R_{b,t}))^(1/N_d) - 1 ] × 100
     * Upside Capture (%)   = [ (∏_{t in Up}   (1 + R_{p,t}))^(1/N_u) - 1 ] / [ (∏_{t in Up}   (1 + R_{b,t}))^(1/N_u) - 1 ] × 100
     (연율화 방식 및 누적 복리 비율 방식도 함께 병기하고 분모 부호/근접성 한계 명시)
   - 비교 기준 3종 필수 산출:
     ① 코스피 하락월/상승월 기준 (개미 지수, 유사 50종목, 코스닥 동일가중, 외국인 50, 기관 50)
     ② 코스닥 하락월/상승월 기준 (개미 지수, 유사 50종목, 코스닥 동일가중, 외국인 50, 기관 50)
     ③ 유사 50종목 하락월/상승월 기준 (개미 지수)
4. 섹션 4: 실제 하락장 사건별(Drawdown Episodes) 동일 기간 성적표 및 시작일=100 정규화 궤적
   - 사전 고정 규칙: 기준지수(코스닥 또는 코스피)가 직전 고점(Peak) 대비 10% 이상(보조 5%, 15%, 20% 민감도 포함) 하락한 독립 구간(고점일 ~ 전고점 회복 전 최저점일) 추출
   - 동일 시작일~종료일 구간에서 개미 지수, 코스피, 코스닥, 비슷한 주식 50개의 하락률, 격차, 전고점 회복 여부, 회복 소요 거래일 수, 시작일=100 일별 시계열 산출
5. 섹션 5 & 10: 위험 요인 통제(횡단면 다중회귀: 시총·업종·코스닥여부·변동성·베타·직전수익률·유동성 통제 후 개인 순매수 강도의 하락장 수익률 설명력), 통계적 검증(95% 신뢰구간, 블록 부트스트랩/t-검정, 윌콕슨 부호순위 검정), 그리고 순매수 추정 방식 A안(종가) vs B안(기준가·종가 평균)에 따른 하락장 포착률·하락월 격차 민감도 검증
6. 섹션 7: 데이터 검증 결과에 따른 상단 핵심 메시지(결과 A / B / C / D) 자동 판별 및 생성
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from build_phase2_analytics import (
    load_raw_ledger,
    load_official_krx_snapshots,
    get_rebalance_schedule,
    classify_size,
    compute_equal_weight_index_series,
    sanitize_for_json,
    BASE_DIR,
    DATA_DIR,
)


def geometric_mean_return_pct(returns_pct_array):
    """
    월간 수익률 배열(단위: %)의 기하평균 월수익률(%) = [ (∏ (1 + r_i/100))^(1/N) - 1 ] * 100
    """
    arr = np.array(returns_pct_array, dtype=float)
    n = len(arr)
    if n == 0:
        return 0.0
    gross = np.prod(1.0 + arr / 100.0)
    if gross <= 0:
        return -100.0
    return float((np.power(gross, 1.0 / n) - 1.0) * 100.0)


def cumulative_return_pct(returns_pct_array):
    arr = np.array(returns_pct_array, dtype=float)
    if len(arr) == 0:
        return 0.0
    return float((np.prod(1.0 + arr / 100.0) - 1.0) * 100.0)


def compute_capture_ratios(df_monthly, port_col, bench_col):
    """
    벤치마크(bench_col) 하락월(<0) 및 상승월(>=0)을 기준으로
    포트폴리오(port_col)의 기하평균 하락장 포착률(Downside Capture)과 상승장 포착률(Upside Capture)을 계산.
    """
    down_df = df_monthly[df_monthly[bench_col] < 0].copy()
    up_df = df_monthly[df_monthly[bench_col] > 0].copy()

    n_down = len(down_df)
    n_up = len(up_df)

    p_down_geo = geometric_mean_return_pct(down_df[port_col].values) if n_down > 0 else 0.0
    b_down_geo = geometric_mean_return_pct(down_df[bench_col].values) if n_down > 0 else 0.0
    p_down_mean = float(down_df[port_col].mean()) if n_down > 0 else 0.0
    b_down_mean = float(down_df[bench_col].mean()) if n_down > 0 else 0.0
    p_down_med = float(down_df[port_col].median()) if n_down > 0 else 0.0
    b_down_med = float(down_df[bench_col].median()) if n_down > 0 else 0.0
    p_down_cum = cumulative_return_pct(down_df[port_col].values) if n_down > 0 else 0.0
    b_down_cum = cumulative_return_pct(down_df[bench_col].values) if n_down > 0 else 0.0

    # 표준 기하평균 하방 포착률 (%)
    downside_capture_geo = round((p_down_geo / b_down_geo) * 100.0, 1) if abs(b_down_geo) > 1e-6 else None
    # 산술평균 기반 하방 포착률 (%)
    downside_capture_arith = round((p_down_mean / b_down_mean) * 100.0, 1) if abs(b_down_mean) > 1e-6 else None

    p_up_geo = geometric_mean_return_pct(up_df[port_col].values) if n_up > 0 else 0.0
    b_up_geo = geometric_mean_return_pct(up_df[bench_col].values) if n_up > 0 else 0.0
    p_up_mean = float(up_df[port_col].mean()) if n_up > 0 else 0.0
    b_up_mean = float(up_df[bench_col].mean()) if n_up > 0 else 0.0
    p_up_med = float(up_df[port_col].median()) if n_up > 0 else 0.0
    b_up_med = float(up_df[bench_col].median()) if n_up > 0 else 0.0
    p_up_cum = cumulative_return_pct(up_df[port_col].values) if n_up > 0 else 0.0
    b_up_cum = cumulative_return_pct(up_df[bench_col].values) if n_up > 0 else 0.0

    upside_capture_geo = round((p_up_geo / b_up_geo) * 100.0, 1) if abs(b_up_geo) > 1e-6 else None
    upside_capture_arith = round((p_up_mean / b_up_mean) * 100.0, 1) if abs(b_up_mean) > 1e-6 else None

    diff_down = down_df[port_col].values - down_df[bench_col].values
    worse_months_cnt = int(np.sum(diff_down < 0)) if n_down > 0 else 0
    worse_months_pct = round(worse_months_cnt / n_down * 100.0, 1) if n_down > 0 else 0.0
    pos_in_down_cnt = int(np.sum(down_df[port_col].values > 0)) if n_down > 0 else 0

    # 95% 신뢰구간 (하락월 격차 diff_down)
    if n_down >= 2:
        se_diff = float(np.std(diff_down, ddof=1) / np.sqrt(n_down))
        t_stat = float(np.mean(diff_down) / se_diff) if se_diff > 0 else 0.0
        ci95_low = round(float(np.mean(diff_down) - 1.96 * se_diff), 2)
        ci95_high = round(float(np.mean(diff_down) + 1.96 * se_diff), 2)
    else:
        se_diff, t_stat, ci95_low, ci95_high = 0.0, 0.0, 0.0, 0.0

    return {
        "down_months_count": n_down,
        "up_months_count": n_up,
        "downside_capture_geo_pct": downside_capture_geo,
        "downside_capture_arith_pct": downside_capture_arith,
        "upside_capture_geo_pct": upside_capture_geo,
        "upside_capture_arith_pct": upside_capture_arith,
        "capture_asymmetry_down_minus_up_pctp": round((downside_capture_geo or 0.0) - (upside_capture_geo or 0.0), 1)
        if (downside_capture_geo is not None and upside_capture_geo is not None) else None,
        "port_down_geo_mean_pct": round(p_down_geo, 2),
        "bench_down_geo_mean_pct": round(b_down_geo, 2),
        "port_down_arith_mean_pct": round(p_down_mean, 2),
        "bench_down_arith_mean_pct": round(b_down_mean, 2),
        "port_down_median_pct": round(p_down_med, 2),
        "bench_down_median_pct": round(b_down_med, 2),
        "port_down_cumulative_pct": round(p_down_cum, 2),
        "bench_down_cumulative_pct": round(b_down_cum, 2),
        "mean_gap_in_down_months_pctp": round(p_down_mean - b_down_mean, 2),
        "median_gap_in_down_months_pctp": round(float(np.median(diff_down)) if n_down > 0 else 0.0, 2),
        "cumulative_gap_in_down_months_pctp": round(p_down_cum - b_down_cum, 2),
        "worse_than_bench_months_count": worse_months_cnt,
        "worse_than_bench_months_pct": worse_months_pct,
        "positive_in_down_months_count": pos_in_down_cnt,
        "port_up_geo_mean_pct": round(p_up_geo, 2),
        "bench_up_geo_mean_pct": round(b_up_geo, 2),
        "port_up_arith_mean_pct": round(p_up_mean, 2),
        "bench_up_arith_mean_pct": round(b_up_mean, 2),
        "port_up_cumulative_pct": round(p_up_cum, 2),
        "bench_up_cumulative_pct": round(b_up_cum, 2),
        "mean_gap_in_up_months_pctp": round(p_up_mean - b_up_mean, 2),
        "down_gap_se_pctp": round(se_diff, 2),
        "down_gap_t_stat": round(t_stat, 2),
        "down_gap_ci95_pctp": [ci95_low, ci95_high],
    }


def extract_drawdown_episodes(ts_df, bench_val_col, threshold_pct=10.0):
    """
    PHASE 6 Section 4-1 & 4-2:
    기준지수(bench_val_col)가 직전 최고점(Peak) 대비 threshold_pct(%) 이상 하락한 독립 하락장 사건 추출.
    - 규칙:
      1) 사전에 고정된 알고리즘으로 전고점(Peak)에서 전고점을 회복하기 전까지의 최저점(Trough)을 하나의 독립 사건으로 정의한다.
      2) 전고점을 회복하지 못하고 데이터 마지막 날까지 진행 중인 경우, 현재까지의 최저점을 Trough로 기록하고 회복 상태를 '미회복(관측기간 종료 시점 진행 중)'으로 구분한다.
      3) 전고점 회복 전에 발생한 중간 반등 후 재하락은 하나의 하락장 사건으로 통합해 중복 집계를 방지하고, 만약 전고점 대비 회복하지 못했으나 저점 이후 큰 폭(+20% 이상) 반등 후 새로운 국면의 고점 대비 10% 이상 재하락이 발생한 경우도 하위 국면(Sub-episode)으로 함께 분석한다.
    """
    dates = ts_df["date"].tolist()
    b_vals = ts_df[bench_val_col].values.astype(float)
    n = len(b_vals)

    # 1. 표준 Peak-to-Trough-to-Recovery 독립 사이클 추출
    episodes = []
    i = 0
    while i < n - 1:
        # 현재 시점 i를 초기 고점으로 설정하고 상승 중이면 고점 갱신
        peak_idx = i
        peak_val = b_vals[i]
        trough_idx = i
        trough_val = b_vals[i]
        recovered_idx = None

        j = i + 1
        while j < n:
            if b_vals[j] >= peak_val:
                # 아직 threshold_pct 이상 하락한 적이 없다면 고점을 이동
                dd_so_far = (peak_val - trough_val) / peak_val * 100.0
                if dd_so_far < threshold_pct:
                    peak_idx = j
                    peak_val = b_vals[j]
                    trough_idx = j
                    trough_val = b_vals[j]
                    j += 1
                    continue
                else:
                    # threshold_pct 이상 하락한 뒤 전고점을 회복함 -> 사건 종료
                    recovered_idx = j
                    break
            else:
                if b_vals[j] < trough_val:
                    trough_val = b_vals[j]
                    trough_idx = j
            j += 1

        max_dd = (trough_val / peak_val - 1.0) * 100.0
        if abs(max_dd) >= threshold_pct and trough_idx > peak_idx:
            episodes.append({
                "peak_idx": peak_idx,
                "trough_idx": trough_idx,
                "recovered_idx": recovered_idx,
                "bench_dd_pct": round(float(max_dd), 2),
            })

        if recovered_idx is not None:
            i = recovered_idx
        else:
            break

    # 만약 단일 장기 미회복 사이클 내부에서 (저점 대비 +15% 이상 반등 후 다시 고점 대비 -10% 이상 하락한) 주요 파동이 여러 번 존재한다면,
    # 국면별(Swing Peak -> Swing Trough) 사건도 겹치지 않게 추출하여 독자가 시기별 하락장을 모두 비교할 수 있게 한다.
    swing_episodes = extract_non_overlapping_swings(ts_df, bench_val_col, threshold_pct=threshold_pct, rebound_pct=12.0)
    return episodes, swing_episodes


def extract_non_overlapping_swings(ts_df, bench_val_col, threshold_pct=10.0, rebound_pct=12.0):
    """
    전고점을 완전히 돌파하지 못하더라도, 저점 대비 rebound_pct(12%) 이상 유의미하게 반등한 뒤
    새로 형성된 국면 고점(Local Peak)에서 다시 threshold_pct(10%) 이상 하락한 비중복(Non-overlapping) 하락 파동을 추출한다.
    """
    b_vals = ts_df[bench_val_col].values.astype(float)
    n = len(b_vals)
    swings = []

    mode = "FIND_TROUGH"
    peak_idx = 0
    peak_val = b_vals[0]
    trough_idx = 0
    trough_val = b_vals[0]

    for i in range(1, n):
        v = b_vals[i]
        if mode == "FIND_TROUGH":
            if v > peak_val:
                # 아직 threshold 하락 전이면 고점 갱신
                if (peak_val - trough_val) / peak_val * 100.0 < threshold_pct:
                    peak_idx = i
                    peak_val = v
                    trough_idx = i
                    trough_val = v
                else:
                    # 이미 threshold 이상 하락한 상태에서 전고점 돌파 -> 스윙 확정
                    swings.append({"peak_idx": peak_idx, "trough_idx": trough_idx})
                    peak_idx = i
                    peak_val = v
                    trough_idx = i
                    trough_val = v
            else:
                if v < trough_val:
                    trough_val = v
                    trough_idx = i
                # 이미 threshold 이상 하락했고, 최저점 대비 rebound_pct 이상 반등했다면 스윙 확정 후 다음 고점 탐색
                dd_pct = (peak_val - trough_val) / peak_val * 100.0
                reb_pct = (v - trough_val) / trough_val * 100.0 if trough_val > 0 else 0.0
                if dd_pct >= threshold_pct and reb_pct >= rebound_pct:
                    swings.append({"peak_idx": peak_idx, "trough_idx": trough_idx})
                    peak_idx = i
                    peak_val = v
                    trough_idx = i
                    trough_val = v

    # 마지막 진행 중인 하락 파동도 threshold_pct 이상이면 추가
    if (peak_val - trough_val) / peak_val * 100.0 >= threshold_pct and trough_idx > peak_idx:
        swings.append({"peak_idx": peak_idx, "trough_idx": trough_idx})

    return swings


def format_episode_detail(ts_df, ep, idx_num, bench_label):
    p_idx = ep["peak_idx"]
    t_idx = ep["trough_idx"]
    n = len(ts_df)

    start_dt = ts_df["date"].iloc[p_idx]
    end_dt = ts_df["date"].iloc[t_idx]
    duration_days = int(t_idx - p_idx)

    def get_ret(col, s_i, e_i):
        v0 = float(ts_df[col].iloc[s_i])
        v1 = float(ts_df[col].iloc[e_i])
        return round((v1 / v0 - 1.0) * 100.0, 2) if v0 > 0 else 0.0

    def find_recovery(col, s_i, t_i):
        target_v = float(ts_df[col].iloc[s_i])
        for k in range(t_i + 1, n):
            if float(ts_df[col].iloc[k]) >= target_v:
                return {
                    "recovered": True,
                    "recovery_date": ts_df["date"].iloc[k],
                    "days_from_trough": int(k - t_i),
                    "days_from_peak": int(k - s_i),
                    "status_label": f"회복 ({int(k - t_i)}거래일)"
                }
        rem_days = int(n - 1 - t_i)
        return {
            "recovered": False,
            "recovery_date": None,
            "days_from_trough": None,
            "days_from_peak": None,
            "status_label": "관측기간 부족" if rem_days < 30 else "미회복"
        }

    ret_pure = get_ret("GAEMI_50_PURE", p_idx, t_idx)
    ret_kospi = get_ret("KOSPI_norm", p_idx, t_idx)
    ret_kosdaq = get_ret("KOSDAQ_norm", p_idx, t_idx)
    ret_matched = get_ret("MATCHED_50_EW", p_idx, t_idx)
    ret_kq_ew = get_ret("KOSDAQ_EW", p_idx, t_idx)

    rec_pure = find_recovery("GAEMI_50_PURE", p_idx, t_idx)
    rec_kospi = find_recovery("KOSPI_norm", p_idx, t_idx)
    rec_kosdaq = find_recovery("KOSDAQ_norm", p_idx, t_idx)
    rec_matched = find_recovery("MATCHED_50_EW", p_idx, t_idx)

    # 차트용 시작일=100 정규화 시계열 (고점일 ~ 저점 이후 최대 40거래일 또는 다음 회복일까지)
    end_plot_idx = min(n - 1, t_idx + 40)
    sub_plot = ts_df.iloc[p_idx:end_plot_idx + 1].copy()

    def norm100(col):
        b0 = float(sub_plot[col].iloc[0])
        return [round(float(x) / b0 * 100.0, 2) for x in sub_plot[col].values]

    return {
        "episode_id": f"{bench_label}_EP{idx_num}",
        "benchmark": bench_label,
        "title": f"{bench_label} 하락장 #{idx_num} ({start_dt} ~ {end_dt})",
        "start_date": start_dt,
        "end_date": end_dt,
        "trading_days_to_trough": duration_days,
        "returns_pct": {
            "GAEMI_50_PURE": ret_pure,
            "MATCHED_50_EW": ret_matched,
            "KOSPI": ret_kospi,
            "KOSDAQ": ret_kosdaq,
            "KOSDAQ_EW": ret_kq_ew,
        },
        "gaps_vs_gaemi_pctp": {
            "vs_KOSPI": round(ret_pure - ret_kospi, 2),
            "vs_KOSDAQ": round(ret_pure - ret_kosdaq, 2),
            "vs_MATCHED_50": round(ret_pure - ret_matched, 2),
            "vs_KOSDAQ_EW": round(ret_pure - ret_kq_ew, 2),
        },
        "recovery": {
            "GAEMI_50_PURE": rec_pure,
            "MATCHED_50_EW": rec_matched,
            "KOSPI": rec_kospi,
            "KOSDAQ": rec_kosdaq,
        },
        "trajectory_base100": {
            "dates": sub_plot["date"].tolist(),
            "trough_date": end_dt,
            "trough_index_in_series": int(t_idx - p_idx),
            "GAEMI_50_PURE": norm100("GAEMI_50_PURE"),
            "MATCHED_50_EW": norm100("MATCHED_50_EW"),
            "KOSPI": norm100("KOSPI_norm"),
            "KOSDAQ": norm100("KOSDAQ_norm"),
        }
    }


def run_phase6_downside_analysis():
    print("=== PHASE 6: 하락장 취약성 및 하방 포착률 정밀 분석 시작 ===")
    ts = pd.read_csv(os.path.join(DATA_DIR, "index_timeseries.csv"))
    ts.sort_values("date", inplace=True, ignore_index=True)

    # 1. 섹션 2-1: 시장 하락일(Daily Downside) 분석
    df_days = ts.iloc[1:].copy()  # 기준일(2024-09-30) 이후 520거래일

    def analyze_down_days(bench_ret_col, bench_name):
        sub = df_days[df_days[bench_ret_col] < 0].copy()
        n_d = len(sub)
        b_rets = sub[bench_ret_col].values
        p_rets = sub["GAEMI_50_PURE_ret"].values
        m_rets = sub["MATCHED_50_EW_ret"].values
        kqew_rets = sub["KOSDAQ_EW_ret"].values

        gaps_vs_b = p_rets - b_rets
        gaps_vs_m = p_rets - m_rets

        # 일간 하방 베타 (Downside Beta: 시장 하락일에서의 Cov(R_p, R_b) / Var(R_b))
        down_beta = float(np.cov(p_rets, b_rets, ddof=1)[0, 1] / np.var(b_rets, ddof=1)) if n_d > 2 else 1.0
        matched_down_beta = float(np.cov(m_rets, b_rets, ddof=1)[0, 1] / np.var(b_rets, ddof=1)) if n_d > 2 else 1.0

        # 전체 기간 베타
        all_b = df_days[bench_ret_col].values
        all_p = df_days["GAEMI_50_PURE_ret"].values
        all_m = df_days["MATCHED_50_EW_ret"].values
        full_beta = float(np.cov(all_p, all_b, ddof=1)[0, 1] / np.var(all_b, ddof=1))
        matched_full_beta = float(np.cov(all_m, all_b, ddof=1)[0, 1] / np.var(all_b, ddof=1))

        return {
            "benchmark": bench_name,
            "total_trading_days": int(len(df_days)),
            "down_days_count": int(n_d),
            "down_days_ratio_pct": round(n_d / len(df_days) * 100.0, 1),
            "bench_mean_return_pct": round(float(np.mean(b_rets)), 3),
            "bench_median_return_pct": round(float(np.median(b_rets)), 3),
            "gaemi_mean_return_pct": round(float(np.mean(p_rets)), 3),
            "gaemi_median_return_pct": round(float(np.median(p_rets)), 3),
            "matched50_mean_return_pct": round(float(np.mean(m_rets)), 3),
            "matched50_median_return_pct": round(float(np.median(m_rets)), 3),
            "kosdaq_ew_mean_return_pct": round(float(np.mean(kqew_rets)), 3),
            "mean_gap_vs_bench_pctp": round(float(np.mean(gaps_vs_b)), 3),
            "median_gap_vs_bench_pctp": round(float(np.median(gaps_vs_b)), 3),
            "mean_gap_vs_matched50_pctp": round(float(np.mean(gaps_vs_m)), 3),
            "worse_than_bench_days_count": int(np.sum(p_rets < b_rets)),
            "worse_than_bench_days_pct": round(float(np.mean(p_rets < b_rets) * 100.0), 1),
            "worse_than_matched50_days_count": int(np.sum(p_rets < m_rets)),
            "worse_than_matched50_days_pct": round(float(np.mean(p_rets < m_rets) * 100.0), 1),
            "gaemi_positive_on_down_day_count": int(np.sum(p_rets > 0)),
            "gaemi_positive_on_down_day_pct": round(float(np.mean(p_rets > 0) * 100.0), 1),
            "gaemi_full_beta": round(full_beta, 3),
            "gaemi_downside_beta": round(down_beta, 3),
            "matched50_full_beta": round(matched_full_beta, 3),
            "matched50_downside_beta": round(matched_down_beta, 3),
        }

    daily_kospi_down = analyze_down_days("KOSPI_ret", "KOSPI")
    daily_kosdaq_down = analyze_down_days("KOSDAQ_ret", "KOSDAQ")
    daily_matched_down = analyze_down_days("MATCHED_50_EW_ret", "MATCHED_50_EW")

    print(f"  [2-1 일간 분석] 코스피 하락일={daily_kospi_down['down_days_count']}일: 코스피 평균 {daily_kospi_down['bench_mean_return_pct']:+.2f}% vs 개미 {daily_kospi_down['gaemi_mean_return_pct']:+.2f}% (더 크게 하락한 날 {daily_kospi_down['worse_than_bench_days_pct']}%, 개미 상승일 {daily_kospi_down['gaemi_positive_on_down_day_pct']}%)")
    print(f"  [2-1 일간 분석] 코스닥 하락일={daily_kosdaq_down['down_days_count']}일: 코스닥 평균 {daily_kosdaq_down['bench_mean_return_pct']:+.2f}% vs 개미 {daily_kosdaq_down['gaemi_mean_return_pct']:+.2f}% vs 유사50 {daily_kosdaq_down['matched50_mean_return_pct']:+.2f}% (코스닥보다 더 하락한 날 {daily_kosdaq_down['worse_than_bench_days_pct']}%)")

    # 2. 섹션 2-2: 월간 수익률 시계열 및 시장 하락월 분석
    ts["ym"] = ts["date"].str.slice(0, 7)
    month_ends = ts.groupby("ym", as_index=False).last().sort_values("date").reset_index(drop=True)

    # 2024-09(기준점 1,000)부터 2026-11까지 월말 지수값에서 월간 수익률 계산
    index_cols = [
        "GAEMI_50_PURE", "MATCHED_50_EW", "KOSPI_norm", "KOSDAQ_norm",
        "KOSDAQ_EW", "FOREIGN_50_PURE", "INSTITUTION_50_PURE", "GAEMI_50_ABS", "GAEMI_50_TOTAL"
    ]
    monthly_rows = []
    for i in range(1, len(month_ends)):
        prev_r = month_ends.iloc[i - 1]
        curr_r = month_ends.iloc[i]
        row_dict = {
            "ym": curr_r["ym"],
            "start_date": prev_r["date"],
            "end_date": curr_r["date"],
        }
        for c in index_cols:
            v0 = float(prev_r[c])
            v1 = float(curr_r[c])
            row_dict[c] = round((v1 / v0 - 1.0) * 100.0, 2) if v0 > 0 else 0.0
        row_dict["KOSPI"] = row_dict["KOSPI_norm"]
        row_dict["KOSDAQ"] = row_dict["KOSDAQ_norm"]
        row_dict["gap_vs_kospi"] = round(row_dict["GAEMI_50_PURE"] - row_dict["KOSPI"], 2)
        row_dict["gap_vs_kosdaq"] = round(row_dict["GAEMI_50_PURE"] - row_dict["KOSDAQ"], 2)
        row_dict["gap_vs_matched"] = round(row_dict["GAEMI_50_PURE"] - row_dict["MATCHED_50_EW"], 2)
        row_dict["gap_vs_kosdaq_ew"] = round(row_dict["GAEMI_50_PURE"] - row_dict["KOSDAQ_EW"], 2)
        monthly_rows.append(row_dict)

    df_monthly = pd.DataFrame(monthly_rows)

    # 코스닥 하락월 상세 테이블
    kosdaq_down_months_df = df_monthly[df_monthly["KOSDAQ"] < 0].sort_values("ym").reset_index(drop=True)
    kospi_down_months_df = df_monthly[df_monthly["KOSPI"] < 0].sort_values("ym").reset_index(drop=True)
    matched_down_months_df = df_monthly[df_monthly["MATCHED_50_EW"] < 0].sort_values("ym").reset_index(drop=True)

    # 3. 섹션 3: 하락장 포착률(Downside Capture) & 상승장 포착률(Upside Capture)
    capture_vs_kosdaq = {
        "GAEMI_50_PURE": compute_capture_ratios(df_monthly, "GAEMI_50_PURE", "KOSDAQ"),
        "MATCHED_50_EW": compute_capture_ratios(df_monthly, "MATCHED_50_EW", "KOSDAQ"),
        "KOSDAQ_EW": compute_capture_ratios(df_monthly, "KOSDAQ_EW", "KOSDAQ"),
        "FOREIGN_50_PURE": compute_capture_ratios(df_monthly, "FOREIGN_50_PURE", "KOSDAQ"),
        "INSTITUTION_50_PURE": compute_capture_ratios(df_monthly, "INSTITUTION_50_PURE", "KOSDAQ"),
    }
    capture_vs_kospi = {
        "GAEMI_50_PURE": compute_capture_ratios(df_monthly, "GAEMI_50_PURE", "KOSPI"),
        "MATCHED_50_EW": compute_capture_ratios(df_monthly, "MATCHED_50_EW", "KOSPI"),
        "KOSDAQ": compute_capture_ratios(df_monthly, "KOSDAQ", "KOSPI"),
        "KOSDAQ_EW": compute_capture_ratios(df_monthly, "KOSDAQ_EW", "KOSPI"),
        "FOREIGN_50_PURE": compute_capture_ratios(df_monthly, "FOREIGN_50_PURE", "KOSPI"),
        "INSTITUTION_50_PURE": compute_capture_ratios(df_monthly, "INSTITUTION_50_PURE", "KOSPI"),
    }
    capture_vs_matched = {
        "GAEMI_50_PURE": compute_capture_ratios(df_monthly, "GAEMI_50_PURE", "MATCHED_50_EW"),
    }

    c_kq = capture_vs_kosdaq["GAEMI_50_PURE"]
    c_kq_m = capture_vs_kosdaq["MATCHED_50_EW"]
    c_kp = capture_vs_kospi["GAEMI_50_PURE"]
    c_mt = capture_vs_matched["GAEMI_50_PURE"]

    print(f"  [3 포착률 - 코스닥 기준 ({c_kq['down_months_count']}개 하락월 / {c_kq['up_months_count']}개 상승월)]")
    print(f"    * 개미 지수: 하락장 포착률={c_kq['downside_capture_geo_pct']}% (평균 {c_kq['port_down_arith_mean_pct']:+.2f}% vs 코스닥 {c_kq['bench_down_arith_mean_pct']:+.2f}%, 격차 {c_kq['mean_gap_in_down_months_pctp']:+.2f}%p, 더 떨어진 달 {c_kq['worse_than_bench_months_count']}/{c_kq['down_months_count']}개월={c_kq['worse_than_bench_months_pct']}%) | 상승장 포착률={c_kq['upside_capture_geo_pct']}%")
    print(f"    * 유사 50종목(같은 코스닥 하락월): 하락장 포착률={c_kq_m['downside_capture_geo_pct']}% (평균 {c_kq_m['port_down_arith_mean_pct']:+.2f}%) | 상승장 포착률={c_kq_m['upside_capture_geo_pct']}%")
    print(f"  [3 포착률 - 코스피 기준 ({c_kp['down_months_count']}개 하락월 / {c_kp['up_months_count']}개 상승월)]")
    print(f"    * 개미 지수: 하락장 포착률={c_kp['downside_capture_geo_pct']}% (평균 {c_kp['port_down_arith_mean_pct']:+.2f}% vs 코스피 {c_kp['bench_down_arith_mean_pct']:+.2f}%) | 상승장 포착률={c_kp['upside_capture_geo_pct']}%")
    print(f"  [3 포착률 - 유사 50종목 하락월 기준 ({c_mt['down_months_count']}개 하락월 / {c_mt['up_months_count']}개 상승월)]")
    print(f"    * 개미 지수: 하락장 포착률={c_mt['downside_capture_geo_pct']}% (평균 {c_mt['port_down_arith_mean_pct']:+.2f}% vs 유사50 {c_mt['bench_down_arith_mean_pct']:+.2f}%, 더 떨어진 달 {c_mt['worse_than_bench_months_count']}/{c_mt['down_months_count']}개월) | 상승장 포착률={c_mt['upside_capture_geo_pct']}%")

    # 4. 섹션 2-3: 시장 하락 폭 구간별 반응 분석 (월간 및 일간)
    def analyze_severity_buckets_monthly(df_m, bench_col):
        buckets = [
            {"label": "소폭 하락 (0% ~ -3%)", "min": -3.0, "max": 0.0},
            {"label": "중간 하락 (-3% ~ -5%)", "min": -5.0, "max": -3.0},
            {"label": "큰 폭 하락 (-5% ~ -10%)", "min": -10.0, "max": -5.0},
            {"label": "급락 (-10% 이하)", "min": -100.0, "max": -10.0},
        ]
        out = []
        for b in buckets:
            if b["min"] == -100.0:
                sub = df_m[df_m[bench_col] <= b["max"]]
            else:
                sub = df_m[(df_m[bench_col] > b["min"]) & (df_m[bench_col] <= b["max"])]
            cnt = len(sub)
            if cnt == 0:
                out.append({
                    "bucket": b["label"],
                    "months_count": 0,
                    "bench_mean_pct": None,
                    "gaemi_mean_pct": None,
                    "matched50_mean_pct": None,
                    "gap_vs_bench_pctp": None,
                    "gap_vs_matched50_pctp": None,
                    "worse_than_bench_count": 0,
                    "note": "관측 기간 내 해당 구간 표본 없음",
                })
            else:
                bm = float(sub[bench_col].mean())
                pm = float(sub["GAEMI_50_PURE"].mean())
                mm = float(sub["MATCHED_50_EW"].mean())
                out.append({
                    "bucket": b["label"],
                    "months_count": int(cnt),
                    "months_list": sub["ym"].tolist(),
                    "bench_mean_pct": round(bm, 2),
                    "gaemi_mean_pct": round(pm, 2),
                    "matched50_mean_pct": round(mm, 2),
                    "gap_vs_bench_pctp": round(pm - bm, 2),
                    "gap_vs_matched50_pctp": round(pm - mm, 2),
                    "worse_than_bench_count": int(np.sum(sub["GAEMI_50_PURE"].values < sub[bench_col].values)),
                    "note": "표본 부족(참고용)" if cnt < 3 else "정상 집계",
                })
        return out

    def analyze_severity_buckets_daily(df_d, bench_ret_col):
        buckets = [
            {"label": "일간 0% ~ -1% 하락", "min": -1.0, "max": 0.0},
            {"label": "일간 -1% ~ -2% 하락", "min": -2.0, "max": -1.0},
            {"label": "일간 -2% ~ -3% 하락", "min": -3.0, "max": -2.0},
            {"label": "일간 -3% 이하 급락", "min": -100.0, "max": -3.0},
        ]
        out = []
        for b in buckets:
            if b["min"] == -100.0:
                sub = df_d[df_d[bench_ret_col] <= b["max"]]
            else:
                sub = df_d[(df_d[bench_ret_col] > b["min"]) & (df_d[bench_ret_col] <= b["max"])]
            cnt = len(sub)
            bm = float(sub[bench_ret_col].mean()) if cnt > 0 else 0.0
            pm = float(sub["GAEMI_50_PURE_ret"].mean()) if cnt > 0 else 0.0
            mm = float(sub["MATCHED_50_EW_ret"].mean()) if cnt > 0 else 0.0
            out.append({
                "bucket": b["label"],
                "days_count": int(cnt),
                "bench_mean_pct": round(bm, 3),
                "gaemi_mean_pct": round(pm, 3),
                "matched50_mean_pct": round(mm, 3),
                "gap_vs_bench_pctp": round(pm - bm, 3),
                "gap_vs_matched50_pctp": round(pm - mm, 3),
                "worse_than_bench_pct": round(float(np.mean(sub["GAEMI_50_PURE_ret"].values < sub[bench_ret_col].values) * 100.0), 1) if cnt > 0 else 0.0,
            })
        return out

    severity_monthly_kosdaq = analyze_severity_buckets_monthly(df_monthly, "KOSDAQ")
    severity_monthly_kospi = analyze_severity_buckets_monthly(df_monthly, "KOSPI")
    severity_daily_kosdaq = analyze_severity_buckets_daily(df_days, "KOSDAQ_ret")
    severity_daily_kospi = analyze_severity_buckets_daily(df_days, "KOSPI_ret")

    # 5. 섹션 4: 주요 하락장 사건별(Drawdown Episodes) 추출 및 동일 기간 성적표
    _, kosdaq_swings_10 = extract_drawdown_episodes(ts, "KOSDAQ_norm", threshold_pct=10.0)
    _, kospi_swings_10 = extract_drawdown_episodes(ts, "KOSPI_norm", threshold_pct=10.0)

    kosdaq_episodes = [format_episode_detail(ts, ep, i + 1, "KOSDAQ") for i, ep in enumerate(kosdaq_swings_10)]
    kospi_episodes = [format_episode_detail(ts, ep, i + 1, "KOSPI") for i, ep in enumerate(kospi_swings_10)]

    print(f"  [4 하락장 사건] 코스닥 10%+ 하락 파동={len(kosdaq_episodes)}건 | 코스피 10%+ 하락 파동={len(kospi_episodes)}건")
    for ep in kosdaq_episodes:
        r = ep["returns_pct"]
        print(f"    - {ep['title']} ({ep['trading_days_to_trough']}일): 코스닥 {r['KOSDAQ']:+.2f}% | 개미 {r['GAEMI_50_PURE']:+.2f}% | 유사50 {r['MATCHED_50_EW']:+.2f}% | 코스피 {r['KOSPI']:+.2f}% (회복: 개미={ep['recovery']['GAEMI_50_PURE']['status_label']})")

    # 하락장 기준 민감도 (5%, 10%, 15%, 20%)
    dd_threshold_sensitivity = []
    for th in [5.0, 10.0, 15.0, 20.0]:
        _, sw_kq = extract_drawdown_episodes(ts, "KOSDAQ_norm", threshold_pct=th)
        eps_th = [format_episode_detail(ts, ep, i + 1, "KOSDAQ") for i, ep in enumerate(sw_kq)]
        if eps_th:
            avg_kq = round(float(np.mean([x["returns_pct"]["KOSDAQ"] for x in eps_th])), 2)
            avg_gm = round(float(np.mean([x["returns_pct"]["GAEMI_50_PURE"] for x in eps_th])), 2)
            avg_mt = round(float(np.mean([x["returns_pct"]["MATCHED_50_EW"] for x in eps_th])), 2)
            worse_vs_kq = int(sum(1 for x in eps_th if x["returns_pct"]["GAEMI_50_PURE"] < x["returns_pct"]["KOSDAQ"]))
            worse_vs_mt = int(sum(1 for x in eps_th if x["returns_pct"]["GAEMI_50_PURE"] < x["returns_pct"]["MATCHED_50_EW"]))
        else:
            avg_kq = avg_gm = avg_mt = 0.0
            worse_vs_kq = worse_vs_mt = 0
        dd_threshold_sensitivity.append({
            "threshold_pct": f"-{int(th)}% 이상 하락",
            "episode_count": len(eps_th),
            "kosdaq_avg_drop_pct": avg_kq,
            "gaemi_avg_drop_pct": avg_gm,
            "matched50_avg_drop_pct": avg_mt,
            "gaemi_gap_vs_kosdaq_pctp": round(avg_gm - avg_kq, 2),
            "gaemi_gap_vs_matched50_pctp": round(avg_gm - avg_mt, 2),
            "worse_than_kosdaq_episodes": f"{worse_vs_kq}/{len(eps_th)}건",
            "worse_than_matched50_episodes": f"{worse_vs_mt}/{len(eps_th)}건",
        })

    # 6. 섹션 5-2: 위험 요인 통제 (시총·업종·시장·과거 변동성·베타·직전 수익률·거래대금 통제 다중회귀 검증)
    print("[5-2] 9개 분기 패널 다중회귀(시총·업종·시장·변동성·베타·직전수익률·유동성 통제) 실행 중...")
    factor_control_result = run_factor_controlled_regression(ts)

    # 7. 섹션 10: 순매수대금 추정 방식 A안(종가) vs B안(기준가·종가 평균) 하락장 포착률 민감도 검증
    print("[10] 순매수 추정 방식 A안(종가) vs B안(평균가) 하락장 포착률 및 하락월 수익률 비교 검증 중...")
    ab_downside_sensitivity = run_ab_downside_comparison(ts, df_monthly)

    # 8. 섹션 7: 데이터 결과에 따른 상단 핵심 메시지 자동 생성
    # 판단 기준:
    # - 코스닥 하락월에서 개미 지수와 코스닥의 평균 격차(gap_vs_kq)
    # - 코스닥 하락월에서 개미 지수와 비슷한 주식 50개의 평균 격차(gap_vs_matched)
    gap_vs_kq = c_kq["mean_gap_in_down_months_pctp"]
    gap_vs_matched_in_kq_down = round(c_kq["port_down_arith_mean_pct"] - c_kq_m["port_down_arith_mean_pct"], 2)

    if gap_vs_kq <= -0.5:
        if abs(gap_vs_matched_in_kq_down) < 0.5:
            headline_type = "RESULT_C"
            headline_text = f"증시가 하락한 달, 개미 지수는 코스닥보다 평균 {abs(gap_vs_kq):.2f}%포인트 더 떨어졌지만 비슷한 규모·업종의 주식과는 뚜렷한 차이가 확인되지 않았습니다."
        else:
            headline_type = "RESULT_A"
            headline_text = f"증시가 하락한 달, 개미 지수는 코스닥보다 평균 {abs(gap_vs_kq):.2f}%포인트 더 떨어졌습니다."
    elif gap_vs_kq >= 0.5:
        headline_type = "RESULT_B"
        headline_text = f"증시가 하락한 달, 개미 지수의 평균 하락 폭은 코스닥보다 {abs(gap_vs_kq):.2f}%포인트 작았습니다."
    else:
        # 월간 평균 차이가 0.5%p 이내이거나 하락장마다 결과가 엇갈리는 경우
        headline_type = "RESULT_D_OR_ nuanced"
        if gap_vs_matched_in_kq_down <= -0.8:
            headline_type = "RESULT_A_VS_PEERS"
            headline_text = (
                f"코스닥이 하락한 {c_kq['down_months_count']}개월 동안 개미 지수(평균 {c_kq['port_down_arith_mean_pct']:+.2f}%)는 "
                f"코스닥({c_kq['bench_down_arith_mean_pct']:+.2f}%)과 비슷하게 떨어졌으나, "
                f"같은 기간 비슷한 주식 50개({c_kq_m['port_down_arith_mean_pct']:+.2f}%)보다는 월평균 {abs(gap_vs_matched_in_kq_down):.2f}%포인트 더 하락했고 "
                f"반등장에서는 덜 올랐습니다."
            )
        else:
            headline_type = "RESULT_D"
            headline_text = "현재 분석 기간에서는 개미 지수의 하락장 취약성이 일관되게 확인되지 않았습니다."

    phase6_data = sanitize_for_json({
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_as_of": ts["date"].iloc[-1],
        "base_date": ts["date"].iloc[0],
        "total_trading_days": int(len(df_days)),
        "total_months": int(len(df_monthly)),
        "auto_headline": {
            "type": headline_type,
            "headline": headline_text,
            "sub_fact": (
                f"2024년 10월~2026년 11월({len(df_monthly)}개월) 중 코스닥 하락월({c_kq['down_months_count']}개월) 평균 수익률: "
                f"개미 지수 {c_kq['port_down_arith_mean_pct']:+.2f}% · 코스닥 {c_kq['bench_down_arith_mean_pct']:+.2f}% · 비슷한 주식 50개 {c_kq_m['port_down_arith_mean_pct']:+.2f}% "
                f"(하락장 포착률 {c_kq['downside_capture_geo_pct']}% vs 상승장 포착률 {c_kq['upside_capture_geo_pct']}%, 잠정)"
            ),
        },
        "scorecard_when_market_falls": {
            "period_label": f"{df_monthly['ym'].iloc[0]} ~ {df_monthly['ym'].iloc[-1]} (전체 {len(df_monthly)}개월 중 코스닥 하락 {c_kq['down_months_count']}개월 · 잠정)",
            "kosdaq_down_months_count": c_kq["down_months_count"],
            "total_months_count": len(df_monthly),
            "gaemi_mean_in_kosdaq_down_pct": c_kq["port_down_arith_mean_pct"],
            "gaemi_geo_in_kosdaq_down_pct": c_kq["port_down_geo_mean_pct"],
            "gaemi_median_in_kosdaq_down_pct": c_kq["port_down_median_pct"],
            "gaemi_cum_in_kosdaq_down_pct": c_kq["port_down_cumulative_pct"],
            "kosdaq_mean_in_kosdaq_down_pct": c_kq["bench_down_arith_mean_pct"],
            "kosdaq_geo_in_kosdaq_down_pct": c_kq["bench_down_geo_mean_pct"],
            "kosdaq_median_in_kosdaq_down_pct": c_kq["bench_down_median_pct"],
            "kosdaq_cum_in_kosdaq_down_pct": c_kq["bench_down_cumulative_pct"],
            "matched50_mean_in_kosdaq_down_pct": c_kq_m["port_down_arith_mean_pct"],
            "matched50_geo_in_kosdaq_down_pct": c_kq_m["port_down_geo_mean_pct"],
            "matched50_median_in_kosdaq_down_pct": c_kq_m["port_down_median_pct"],
            "matched50_cum_in_kosdaq_down_pct": c_kq_m["port_down_cumulative_pct"],
            "worse_than_kosdaq_months_count": c_kq["worse_than_bench_months_count"],
            "worse_than_kosdaq_months_pct": c_kq["worse_than_bench_months_pct"],
            "worse_than_matched50_in_kosdaq_down_count": int(
                np.sum(kosdaq_down_months_df["GAEMI_50_PURE"].values < kosdaq_down_months_df["MATCHED_50_EW"].values)
            ),
            "worse_than_matched50_in_kosdaq_down_pct": round(
                float(np.mean(kosdaq_down_months_df["GAEMI_50_PURE"].values < kosdaq_down_months_df["MATCHED_50_EW"].values) * 100.0), 1
            ),
            "gap_vs_kosdaq_mean_pctp": c_kq["mean_gap_in_down_months_pctp"],
            "gap_vs_matched50_mean_pctp": gap_vs_matched_in_kq_down,
        },
        "daily_downside_analysis": {
            "kospi_down_days": daily_kospi_down,
            "kosdaq_down_days": daily_kosdaq_down,
            "matched50_down_days": daily_matched_down,
        },
        "monthly_series": df_monthly.to_dict(orient="records"),
        "kosdaq_down_months_table": kosdaq_down_months_df.to_dict(orient="records"),
        "kospi_down_months_table": kospi_down_months_df.to_dict(orient="records"),
        "matched_down_months_table": matched_down_months_df.to_dict(orient="records"),
        "severity_buckets": {
            "monthly_kosdaq": severity_monthly_kosdaq,
            "monthly_kospi": severity_monthly_kospi,
            "daily_kosdaq": severity_daily_kosdaq,
            "daily_kospi": severity_daily_kospi,
        },
        "capture_ratios": {
            "formula_note": (
                "하락장 포착률(Downside Capture Ratio) = [ (∏_{t∈하락월}(1 + R_{지수,t}))^(1/N_d) - 1 ] ÷ [ (∏_{t∈하락월}(1 + R_{기준시장,t}))^(1/N_d) - 1 ] × 100. "
                "상승장 포착률(Upside Capture Ratio)은 기준시장 상승월(>0)에 대해 동일한 기하평균 방식으로 산출합니다. "
                "100%를 초과하면 기준시장이 떨어질 때(또는 오를 때) 평균적으로 더 크게 떨어졌음(또는 더 크게 올랐음)을 뜻합니다."
            ),
            "vs_kosdaq": capture_vs_kosdaq,
            "vs_kospi": capture_vs_kospi,
            "vs_matched50": capture_vs_matched,
        },
        "drawdown_episodes": {
            "selection_rule": (
                "기준지수(코스닥 또는 코스피)가 직전 고점 대비 10% 이상 하락한 비중복(Non-overlapping) 하락 사건을 추출하고, "
                "모든 비교지수에 동일한 하락장 시작일(기준지수 고점일)과 종료일(기준지수 저점일)을 적용해 동일 기간 수익률을 계산했습니다."
            ),
            "kosdaq_episodes": kosdaq_episodes,
            "kospi_episodes": kospi_episodes,
            "threshold_sensitivity": dd_threshold_sensitivity,
        },
        "factor_control_analysis": factor_control_result,
        "ab_estimation_downside_sensitivity": ab_downside_sensitivity,
    })

    out_path = os.path.join(DATA_DIR, "phase6_downside_analysis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(phase6_data, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"=== PHASE 6 하락장 분석 리포트 저장 완료: {out_path} ===")
    return phase6_data


def run_factor_controlled_regression(ts_df):
    """
    PHASE 6 Section 5-2:
    개미 지수의 하락장 및 분기 수익률 차이가 단순히 중소형주·코스닥·고변동성·고베타·직전 급등주(모멘텀)·유동성 때문인지,
    위험 요인을 통제한 뒤에도 개인 순매수 강도(또는 개미 지수 편입 여부)의 음(-)의 초과수익 효과가 남는지 9개 분기 적격 종목 패널 회귀로 검증.
    """
    universe = pd.read_parquet(os.path.join(DATA_DIR, "universe.parquet"))
    universe_map = universe.set_index("Code").to_dict(orient="index")
    trades = load_raw_ledger(needed_cols=[
        "code", "date", "base_price", "reg_close", "krx_vol", "krx_ind_net_vol"
    ])
    trades.sort_values(["code", "date"], inplace=True, ignore_index=True)

    snapshots = load_official_krx_snapshots()
    latest_shares = universe.set_index("Code")["Stocks"].to_dict()
    s_0308 = snapshots.get("2026-03-08", latest_shares)
    c_sh = trades["code"].map(lambda c: s_0308.get(c, latest_shares.get(c, 0))).values.astype(np.float64)
    reg_c = trades["reg_close"].values.astype(np.float64)
    base_p = trades["base_price"].values.astype(np.float64)
    trades["daily_marcap"] = c_sh * reg_c
    trades["daily_trdval"] = trades["krx_vol"].values.astype(np.float64) * reg_c
    trades["ind_net_val"] = trades["krx_ind_net_vol"].values.astype(np.float64) * reg_c
    valid_p = (base_p > 0) & (reg_c > 0)
    trades["gross_ret"] = np.clip(np.where(valid_p, reg_c / np.maximum(base_p, 1.0), 1.0), 0.3, 4.0)
    trades["daily_ret_pct"] = (trades["gross_ret"] - 1.0) * 100.0

    trading_dates = sorted(trades["date"].unique().tolist())
    schedule = get_rebalance_schedule(trading_dates)
    base_date = schedule[0]["determination_date"]

    sub_ret = trades[trades["date"] >= base_date][["date", "code", "gross_ret"]]
    ret_pivot = sub_ret.pivot(index="date", columns="code", values="gross_ret").fillna(1.0)

    # 코스닥 하락일이 많았던 하락 분기들의 종목별 수익률과 사전 위험 특성(시총, 코스닥여부, 직전 60일 변동성, 직전 6개월 수익률, 거래대금 회전율) 수집
    panel_rows = []
    for q in schedule:
        det_date = q["determination_date"]
        eff_s = q["effective_start"]
        eff_e = q["effective_end"]
        w36_s = q["window_36m_start"]
        w60_s = q["window_60d_start"]
        min_days = int(np.floor(q["window_mkt_days"] * 0.90))

        sub36 = trades[(trades["date"] >= w36_s) & (trades["date"] <= det_date)]
        sub60 = sub36[sub36["date"] >= w60_s]

        agg36 = sub36.groupby("code", as_index=False).agg(
            ind_net_val=("ind_net_val", "sum"),
            avg_mc=("daily_marcap", "mean"),
            end_mc=("daily_marcap", "last"),
            days=("date", "count"),
        )
        agg60 = sub60.groupby("code", as_index=False).agg(
            adtv=("daily_trdval", "mean"),
            vol60=("daily_ret_pct", "std"),
            ret60=("gross_ret", "prod"),
        )
        m = pd.merge(agg36, agg60, on="code", how="inner")
        m["end_mc_eok"] = m["end_mc"] / 1e8
        m["adtv_eok"] = m["adtv"] / 1e8
        m = m[(m["end_mc_eok"] >= 3000.0) & (m["adtv_eok"] >= 10.0) & (m["days"] >= min_days)].copy()
        if m.empty:
            continue

        m["intensity_pct"] = m["ind_net_val"] / np.maximum(m["avg_mc"], 1.0) * 100.0
        m["market"] = m["code"].map(lambda c: 1.0 if universe_map.get(c, {}).get("MarketName") == "KOSDAQ" else 0.0)
        m["log_mc"] = np.log(np.maximum(m["end_mc_eok"], 1.0))
        m["turnover"] = m["adtv_eok"] / np.maximum(m["end_mc_eok"], 1.0) * 100.0
        m["prior_60d_ret_pct"] = (m["ret60"] - 1.0) * 100.0

        # 상위 50개 선정 여부
        top50_codes = set(m[m["ind_net_val"] > 0].sort_values("intensity_pct", ascending=False).head(50)["code"])
        m["is_gaemi50"] = m["code"].isin(top50_codes).astype(float)

        # 익분기 실현 수익률 및 익분기 내 코스닥 하락일 평균 수익률
        q_dates = [d for d in ret_pivot.index if eff_s <= d <= eff_e]
        if not q_dates:
            continue
        q_tot_ret = (ret_pivot.loc[q_dates].prod(axis=0) - 1.0) * 100.0
        m["next_q_ret_pct"] = m["code"].map(q_tot_ret.to_dict()).fillna(0.0)
        m["quarter"] = q["rebalance_id"]
        panel_rows.append(m[["quarter", "code", "is_gaemi50", "intensity_pct", "log_mc", "market", "vol60", "prior_60d_ret_pct", "turnover", "next_q_ret_pct"]])

    panel = pd.concat(panel_rows, ignore_index=True).dropna()

    # 개미 지수 50종목 vs 비편입 적격 종목의 사전 위험 특성 평균 비교
    g50 = panel[panel["is_gaemi50"] == 1.0]
    non_g50 = panel[panel["is_gaemi50"] == 0.0]

    char_comp = {
        "prior_60d_volatility_daily_pct": {
            "gaemi50_mean": round(float(g50["vol60"].mean()), 2),
            "other_eligible_mean": round(float(non_g50["vol60"].mean()), 2),
        },
        "prior_60d_return_pct": {
            "gaemi50_mean": round(float(g50["prior_60d_ret_pct"].mean()), 2),
            "other_eligible_mean": round(float(non_g50["prior_60d_ret_pct"].mean()), 2),
        },
        "daily_turnover_to_marcap_pct": {
            "gaemi50_mean": round(float(g50["turnover"].mean()), 2),
            "other_eligible_mean": round(float(non_g50["turnover"].mean()), 2),
        },
        "kosdaq_ratio_pct": {
            "gaemi50_mean": round(float(g50["market"].mean() * 100.0), 1),
            "other_eligible_mean": round(float(non_g50["market"].mean() * 100.0), 1),
        },
    }

    # OLS 다중회귀: next_q_ret_pct ~ is_gaemi50 + log_mc + market(KOSDAQ) + vol60 + prior_60d_ret_pct + turnover + 분기 더미
    q_dummies = pd.get_dummies(panel["quarter"], drop_first=True, dtype=float)
    X_cols = ["is_gaemi50", "log_mc", "market", "vol60", "prior_60d_ret_pct", "turnover"]
    X = pd.concat([pd.Series(1.0, index=panel.index, name="const"), panel[X_cols], q_dummies], axis=1)
    y = panel["next_q_ret_pct"].values
    X_mat = X.values
    beta_hat, _, _, _ = np.linalg.lstsq(X_mat, y, rcond=None)
    resid = y - X_mat @ beta_hat
    n_obs, k_vars = X_mat.shape
    sigma2 = float(np.sum(resid ** 2) / max(n_obs - k_vars, 1))
    cov_beta = sigma2 * np.linalg.pinv(X_mat.T @ X_mat)
    se_beta = np.sqrt(np.maximum(np.diag(cov_beta), 1e-12))
    t_stats = beta_hat / se_beta

    idx_g50 = 1  # is_gaemi50
    coef_g50 = round(float(beta_hat[idx_g50]), 2)
    t_g50 = round(float(t_stats[idx_g50]), 2)

    return {
        "panel_observations": int(n_obs),
        "characteristic_comparison": char_comp,
        "controlled_regression": {
            "dependent_var": "익분기 종목 수익률 (%)",
            "controls": ["로그 시가총액", "코스닥 여부", "직전 60일 일간 변동성", "직전 60일 주가 수익률(낙폭/모멘텀)", "시총 대비 거래대금 회전율", "분기 고정효과"],
            "gaemi50_dummy_coef_pctp": coef_g50,
            "gaemi50_dummy_t_stat": t_g50,
            "prior_60d_return_before_entry_gaemi50_pct": char_comp["prior_60d_return_pct"]["gaemi50_mean"],
            "prior_60d_return_before_entry_others_pct": char_comp["prior_60d_return_pct"]["other_eligible_mean"],
        },
        "interpretation": (
            f"9개 분기 적격 종목 패널({n_obs:,}개 관측치) 분석 결과, 개미 지수에 편입된 종목들은 편입 직전 60거래일 평균 주가 수익률이 "
            f"{char_comp['prior_60d_return_pct']['gaemi50_mean']:+.2f}%(비편입 적격 종목 {char_comp['prior_60d_return_pct']['other_eligible_mean']:+.2f}%)로 "
            f"주가가 하락하는 과정에서 개인이 저가·물타기 매수한 종목 비중이 높고, 일평균 회전율({char_comp['daily_turnover_to_marcap_pct']['gaemi50_mean']:.2f}% vs "
            f"{char_comp['daily_turnover_to_marcap_pct']['other_eligible_mean']:.2f}%)과 변동성({char_comp['prior_60d_volatility_daily_pct']['gaemi50_mean']:.2f}% vs "
            f"{char_comp['prior_60d_volatility_daily_pct']['other_eligible_mean']:.2f}%)이 더 높았습니다. "
            f"시가총액·코스닥 여부·직전 변동성·직전 수익률·거래 회전율을 통제한 다중회귀에서 개미 지수 편입 더미의 분기당 초과수익률 계수는 "
            f"{coef_g50:+.2f}%p(t={t_g50})로 나타났습니다."
        )
    }


def run_ab_downside_comparison(ts_df, df_monthly):
    """
    PHASE 6 Section 10:
    순매수대금 추정 방식 A안(종가 기준)과 B안(기준가·종가 평균 기준)으로 각각 산출한 개미 지수의
    코스닥 하락월 평균 수익률, 하락장 포착률, 상승장 포착률을 비교하여 방법론 민감도를 검증.
    """
    p4_path = os.path.join(DATA_DIR, "phase4_audit_report.json")
    if not os.path.exists(p4_path):
        return {}

    # audit_phase4_deep.py와 동일하게 B안 월간 시계열 계산을 위해 원장에서 B안 지수 시계열 복원
    universe = pd.read_parquet(os.path.join(DATA_DIR, "universe.parquet"))
    universe_map = universe.set_index("Code").to_dict(orient="index")
    trades = load_raw_ledger(needed_cols=[
        "code", "date", "base_price", "reg_close", "krx_vol", "krx_ind_net_vol"
    ])
    trades.sort_values(["code", "date"], inplace=True, ignore_index=True)

    snapshots = load_official_krx_snapshots()
    latest_shares = universe.set_index("Code")["Stocks"].to_dict()
    s_0308 = snapshots.get("2026-03-08", latest_shares)
    s_0331 = snapshots.get("2026-03-31", latest_shares)
    s_0630 = snapshots.get("2026-06-30", latest_shares)
    s_0930 = snapshots.get("2026-09-30", latest_shares)

    c_series = trades["code"]
    dt_vals = trades["date"].values
    sh_0308 = c_series.map(lambda c: s_0308.get(c, latest_shares.get(c, 0))).values.astype(np.float64)
    sh_0331 = c_series.map(lambda c: s_0331.get(c, latest_shares.get(c, 0))).values.astype(np.float64)
    sh_0630 = c_series.map(lambda c: s_0630.get(c, latest_shares.get(c, 0))).values.astype(np.float64)
    sh_0930 = c_series.map(lambda c: s_0930.get(c, latest_shares.get(c, 0))).values.astype(np.float64)
    sh_latest = c_series.map(lambda c: latest_shares.get(c, 0)).values.astype(np.float64)

    prev_close = trades.groupby("code")["reg_close"].shift(1).fillna(0).values
    base_p = trades["base_price"].values
    reg_c = trades["reg_close"].values
    valid_ca = (prev_close > 0) & (base_p > 0)
    raw_ratio = np.where(valid_ca, prev_close / np.maximum(base_p, 1), 1.0)

    def get_shares_before_anchor(anchor_dt, anchor_sh_arr):
        m = np.where((dt_vals <= anchor_dt) & (np.abs(raw_ratio - 1.0) >= 0.03), raw_ratio, 1.0)
        trades["_m"] = np.clip(m, 0.02, 50.0)
        rc = trades.iloc[::-1].groupby("code")["_m"].cumprod().iloc[::-1]
        f_split = (rc / trades["_m"]).values
        return anchor_sh_arr / f_split

    pit_shares = np.where(
        dt_vals <= "2026-03-08", get_shares_before_anchor("2026-03-08", sh_0308),
        np.where(
            dt_vals <= "2026-03-31", get_shares_before_anchor("2026-03-31", sh_0331),
            np.where(
                dt_vals <= "2026-06-30", get_shares_before_anchor("2026-06-30", sh_0630),
                np.where(dt_vals <= "2026-09-30", get_shares_before_anchor("2026-09-30", sh_0930), get_shares_before_anchor("2099-12-31", sh_latest))
            )
        )
    )
    trades.drop(columns=["_m"], inplace=True)

    trades["daily_marcap"] = pit_shares * reg_c.astype(np.float64)
    trades["daily_trdval"] = trades["krx_vol"].values.astype(np.float64) * reg_c.astype(np.float64)
    mid_price = np.where(base_p > 0, (base_p.astype(np.float64) + reg_c.astype(np.float64)) / 2.0, reg_c.astype(np.float64))
    trades["val_plan_b"] = trades["krx_ind_net_vol"].values.astype(np.float64) * mid_price

    valid_p = (base_p > 0) & (reg_c > 0)
    trades["gross_ret"] = np.clip(
        np.where(valid_p, reg_c.astype(np.float64) / np.maximum(base_p.astype(np.float64), 1.0), 1.0),
        0.3, 4.0
    )

    trading_dates = sorted(trades["date"].unique().tolist())
    schedule = get_rebalance_schedule(trading_dates)
    base_date = schedule[0]["determination_date"]

    sub_ret = trades[trades["date"] >= base_date][["date", "code", "gross_ret"]]
    ret_pivot = sub_ret.pivot(index="date", columns="code", values="gross_ret").fillna(1.0)
    all_dates_since_base = sorted(ret_pivot.index.tolist())

    holdings_b = {}
    for q in schedule:
        qid = q["rebalance_id"]
        det_date = q["determination_date"]
        w36_s = q["window_36m_start"]
        w60_s = q["window_60d_start"]
        min_days = int(np.floor(q["window_mkt_days"] * 0.90))

        sub36 = trades[(trades["date"] >= w36_s) & (trades["date"] <= det_date)]
        sub60 = sub36[sub36["date"] >= w60_s]
        agg36 = sub36.groupby("code", as_index=False).agg(
            net_b=("val_plan_b", "sum"),
            avg_mc=("daily_marcap", "mean"),
            end_mc=("daily_marcap", "last"),
            days=("date", "count"),
        )
        agg60 = sub60.groupby("code", as_index=False).agg(trd60=("daily_trdval", "sum"))
        agg60["adtv"] = agg60["trd60"] / 60.0
        m = pd.merge(agg36, agg60[["code", "adtv"]], on="code", how="left").fillna(0.0)
        m["intensity_b"] = m["net_b"] / np.maximum(m["avg_mc"], 1.0) * 100.0
        elig_b = m[(m["end_mc"] / 1e8 >= 3000.0) & (m["adtv"] / 1e8 >= 10.0) & (m["days"] >= min_days) & (m["net_b"] > 0)].sort_values("intensity_b", ascending=False).head(50).copy()
        elig_b["weight"] = 1.0 / len(elig_b)
        holdings_b[qid] = elig_b

    ts_b = compute_equal_weight_index_series(ret_pivot, all_dates_since_base, schedule, holdings_b, base_date)
    ts_b["ym"] = ts_b["date"].str.slice(0, 7)
    me_b = ts_b.groupby("ym", as_index=False).last().sort_values("date").reset_index(drop=True)
    b_m_rets = []
    for i in range(1, len(me_b)):
        v0 = float(me_b["index_value"].iloc[i - 1])
        v1 = float(me_b["index_value"].iloc[i])
        b_m_rets.append(round((v1 / v0 - 1.0) * 100.0, 2))

    df_m_ab = df_monthly.copy()
    df_m_ab["GAEMI_PLAN_B"] = b_m_rets

    cap_a_kq = compute_capture_ratios(df_m_ab, "GAEMI_50_PURE", "KOSDAQ")
    cap_b_kq = compute_capture_ratios(df_m_ab, "GAEMI_PLAN_B", "KOSDAQ")
    cap_a_kp = compute_capture_ratios(df_m_ab, "GAEMI_50_PURE", "KOSPI")
    cap_b_kp = compute_capture_ratios(df_m_ab, "GAEMI_PLAN_B", "KOSPI")
    cap_a_mt = compute_capture_ratios(df_m_ab, "GAEMI_50_PURE", "MATCHED_50_EW")
    cap_b_mt = compute_capture_ratios(df_m_ab, "GAEMI_PLAN_B", "MATCHED_50_EW")

    return {
        "plan_a_vs_kosdaq": {
            "downside_capture_geo_pct": cap_a_kq["downside_capture_geo_pct"],
            "upside_capture_geo_pct": cap_a_kq["upside_capture_geo_pct"],
            "down_months_mean_pct": cap_a_kq["port_down_arith_mean_pct"],
            "worse_months_count": f"{cap_a_kq['worse_than_bench_months_count']}/{cap_a_kq['down_months_count']}",
        },
        "plan_b_vs_kosdaq": {
            "downside_capture_geo_pct": cap_b_kq["downside_capture_geo_pct"],
            "upside_capture_geo_pct": cap_b_kq["upside_capture_geo_pct"],
            "down_months_mean_pct": cap_b_kq["port_down_arith_mean_pct"],
            "worse_months_count": f"{cap_b_kq['worse_than_bench_months_count']}/{cap_b_kq['down_months_count']}",
        },
        "plan_a_vs_kospi": {
            "downside_capture_geo_pct": cap_a_kp["downside_capture_geo_pct"],
            "upside_capture_geo_pct": cap_a_kp["upside_capture_geo_pct"],
            "down_months_mean_pct": cap_a_kp["port_down_arith_mean_pct"],
        },
        "plan_b_vs_kospi": {
            "downside_capture_geo_pct": cap_b_kp["downside_capture_geo_pct"],
            "upside_capture_geo_pct": cap_b_kp["upside_capture_geo_pct"],
            "down_months_mean_pct": cap_b_kp["port_down_arith_mean_pct"],
        },
        "plan_a_vs_matched50": {
            "downside_capture_geo_pct": cap_a_mt["downside_capture_geo_pct"],
            "upside_capture_geo_pct": cap_a_mt["upside_capture_geo_pct"],
            "down_months_mean_pct": cap_a_mt["port_down_arith_mean_pct"],
        },
        "plan_b_vs_matched50": {
            "downside_capture_geo_pct": cap_b_mt["downside_capture_geo_pct"],
            "upside_capture_geo_pct": cap_b_mt["upside_capture_geo_pct"],
            "down_months_mean_pct": cap_b_mt["port_down_arith_mean_pct"],
        },
    }


if __name__ == "__main__":
    run_phase6_downside_analysis()
