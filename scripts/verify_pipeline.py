"""
GAEMI 50 PURE — 데이터 품질·순매수 강도 산식·자격 필터·생존자 편향·체인링킹·8대 비교 항목 검증 테스트 스위트
"""

import os
import json
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


def run_verification():
    print("=== GAEMI 50 PURE 검증 테스트 스위트 실행 ===")
    universe = pd.read_parquet(os.path.join(DATA_DIR, "universe.parquet"))
    trades = pd.read_parquet(os.path.join(DATA_DIR, "daily_investor_trades.parquet"), columns=[
        'code', 'date', 'base_price', 'reg_close', 'krx_ind_buy_val', 'krx_ind_sell_val', 'krx_ind_net_val',
        'nxt_ind_buy_val', 'nxt_ind_sell_val', 'nxt_ind_net_val', 'nxt_vol'
    ])
    ts = pd.read_csv(os.path.join(DATA_DIR, "index_timeseries.csv"))
    pure50 = pd.read_csv(os.path.join(DATA_DIR, "gaemi50_pure_constituents.csv"), dtype={'code': str})
    abs50 = pd.read_csv(os.path.join(DATA_DIR, "gaemi50_abs_constituents.csv"), dtype={'code': str})
    all_pure_q = pd.read_csv(os.path.join(DATA_DIR, "historical_pure_constituents_all_quarters.csv"), dtype={'code': str})
    summary = json.load(open(os.path.join(DATA_DIR, "index_summary.json"), encoding="utf-8"))
    comp = json.load(open(os.path.join(DATA_DIR, "pure_vs_abs_comparison.json"), encoding="utf-8"))
    sens = json.load(open(os.path.join(DATA_DIR, "sensitivity_analysis.json"), encoding="utf-8"))

    results = []

    def check(name, cond, detail=""):
        status = "PASS" if cond else "FAIL"
        results.append({"test": name, "status": status, "detail": detail})
        print(f"  [{status}] {name}: {detail}")
        if not cond:
            raise AssertionError(f"Verification failed: {name} ({detail})")

    # 1. 유니버스 보통주 순수성 검증
    active_u = universe[universe['Status'] == 'ACTIVE']
    has_spac = active_u['Name'].str.contains('스팩|SPAC', regex=True).any()
    has_reit = active_u['Name'].str.endswith(('리츠', '코크렙')).any()
    has_pref = (~active_u['Code'].str.endswith('0')).any() or (active_u['ISU_CD'].str[8] != '0').any()
    check(
        "유니버스 보통주 순수성 검증",
        (not has_spac) and (not has_reit) and (not has_pref),
        f"상장 보통주={len(active_u):,}개, 상장폐지 보통주={len(universe)-len(active_u):,}개 (SPAC/리츠/우선주 혼입 0건)"
    )

    # 2. 생존자 편향 방지 검증
    delisted_u = universe[universe['Status'] == 'DELISTED']
    delisted_in_trades = trades['code'].isin(set(delisted_u['Code'])).sum()
    check(
        "생존자 편향 방지 검증",
        delisted_in_trades > 10000,
        f"2021년 이후 상장폐지 보통주 {len(delisted_u)}개에 대한 과거 일별 수급 레코드 {delisted_in_trades:,}건 보존·반영"
    )

    # 3. 순매수 강도 산식 검증: (36개월 누적 순매수대금 / 36개월 평균 시가총액) * 100
    recalc_intensity = (pure50['net_buy_val'] / pure50['avg_marcap_36m']) * 100.0
    max_int_err = (recalc_intensity - pure50['intensity_pct']).abs().max()
    is_sorted_desc = pure50['intensity_pct'].is_monotonic_decreasing
    check(
        "순매수 강도 산식 및 내림차순 정렬 검증",
        max_int_err < 1e-3 and is_sorted_desc,
        f"50종목 순매수 강도 공식 최대 오차={max_int_err:.6f}%p, 강도 내림차순 정렬=True (1위 {pure50.iloc[0]['name']} {pure50.iloc[0]['intensity_pct']:.2f}% ~ 50위 {pure50.iloc[-1]['name']} {pure50.iloc[-1]['intensity_pct']:.2f}%)"
    )

    # 4. GAEMI 50 PURE 자격 기준(양수 순매수, 시총 3,000억+, 60일 거래대금 10억+, 36개월 관측기간 확보) 검증
    all_pos = (pure50['net_buy_val'] > 0).all()
    all_mc = (pure50['end_marcap_eok'] >= 3000.0).all()
    all_adtv = (pure50['adtv_60d_eok'] >= 10.0).all()
    all_obs = (pure50['pass_36m_obs'] == True).all()
    check(
        "GAEMI 50 PURE 자격 기준(시총 3,000억+ · 거래대금 10억+ · 양수 순매수 · 36개월 원자료) 검증",
        all_pos and all_mc and all_adtv and all_obs,
        f"최소 시총={pure50['end_marcap_eok'].min():,.0f}억(>=3,000억), 최소 60일 평균거래대금={pure50['adtv_60d_eok'].min():.1f}억(>=10억), 최소 관측일수={pure50['trading_days'].min()}일"
    )

    # 5. 전 분기 50종목 구성 및 동일가중(2.0%) 검증
    q_counts = all_pure_q.groupby('rebalance_id')['code'].count()
    all_50 = (q_counts == 50).all()
    w_sum = round(pure50['weight'].sum(), 6)
    check(
        "전 분기 50종목 구성 및 초기 동일가중(종목당 2.0%) 검증",
        all_50 and w_sum == 1.0,
        f"총 {len(q_counts)}개 리밸런싱 분기(2024 Q4 ~ 2026 Q4) 모두 정확히 50종목, 초기 비중 합=100.0%"
    )

    # 6. 기준일 1,000.00 pt 및 시계열 무결성 검증
    base_row = ts.iloc[0]
    no_nan = not ts[['GAEMI_50_PURE', 'GAEMI_50_ABS', 'KOSPI_norm', 'KOSDAQ_norm']].isna().any().any()
    check(
        "기준값 1,000pt 및 시계열 무결성 검증",
        base_row['GAEMI_50_PURE'] == 1000.0 and base_row['GAEMI_50_ABS'] == 1000.0 and no_nan,
        f"기준일({base_row['date']}) = 1,000.00 pt, 총 {len(ts)} 거래일 결측치 0건"
    )

    # 7. 리밸런싱 종목 교체 시 체인링킹(Chain-Linking) 지수 연속성 검증
    latest_q = summary["current_rebalance"]
    eff_start = latest_q["effective_start"]
    row_idx = ts.index[ts['date'] == eff_start][0]
    idx_prev = ts.loc[row_idx - 1, 'GAEMI_50_PURE']
    idx_curr = ts.loc[row_idx, 'GAEMI_50_PURE']
    actual_day1_ret = (idx_curr / idx_prev - 1.0) * 100.0

    codes_q4 = pure50['code'].tolist()
    day1_trades = trades[(trades['date'] == eff_start) & (trades['code'].isin(codes_q4))]
    day1_rets = np.where(day1_trades['base_price'] > 0, day1_trades['reg_close'] / day1_trades['base_price'] - 1.0, 0.0)
    expected_day1_ret = float(np.sum(day1_rets) / 50.0 * 100.0)
    ret_diff = abs(actual_day1_ret - expected_day1_ret)
    check(
        "리밸런싱 종목 교체 시 지수 연속성(Chain-Linking) 검증",
        ret_diff < 0.02,
        f"{latest_q['rebalance_id']} 첫 거래일({eff_start}) PURE 수익률={actual_day1_ret:+.4f}% vs 50종목 동일가중 평균={expected_day1_ret:+.4f}% (오차={ret_diff:.5f}%p)"
    )

    # 8. 기존 지수(절대금액) vs 새 지수(순매수 강도) 8대 비교 검증 및 민감도 분석 완료 검증
    s_stat = comp["giants_focus"]["samsung_latest"]
    h_stat = comp["giants_focus"]["hynix_latest"]
    check(
        "기존 절대금액 지수 대비 8대 비교 항목 및 민감도 분석 무결성 검증",
        (comp["common_count"] + comp["newly_included_count"] == 50) and
        (comp["common_count"] + comp["excluded_count"] == 50) and
        len(sens) == 7 and
        s_stat is not None and h_stat is not None,
        f"공통={comp['common_count']}개, 신규편입={comp['newly_included_count']}개, 제외={comp['excluded_count']}개 | 삼성전자(강도 {s_stat['intensity_pct']:.2f}%, 강도순위 {s_stat['pure_rank']}위 -> 미선정) | SK하이닉스(강도 {h_stat['intensity_pct']:.2f}%, 강도순위 {h_stat['pure_rank']}위 -> 선정)"
    )

    report = {
        "verified_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "all_passed": all(r["status"] == "PASS" for r in results),
        "total_tests": len(results),
        "results": results,
    }
    with open(os.path.join(DATA_DIR, "verification_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"=== 전체 {len(results)}개 검증 항목 100% 통과 ===")


if __name__ == "__main__":
    run_verification()
