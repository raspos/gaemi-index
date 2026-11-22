"""
GAEMI 50 PURE — 순매수 강도(36개월 누적 개인 순매수대금 / 36개월 평균 시가총액 × 100) 기반
공식 대표지수 산출, 민감도 분석 및 기존 절대금액 지수와의 정밀 비교 엔진

[핵심 규칙]
1. 순매수 강도(%) = (36개월 개인 누적 순매수대금 / 36개월 평균 시가총액) * 100
2. 자격 기준 (기본 확정안):
   - 코스피·코스닥 일반 보통주 (ETF, ETN, SPAC, 우선주, 리츠, 외국기업, 인프라펀드 제외)
   - 양수 순매수 종목 (36개월 개인 누적 순매수대금 > 0)
   - 리밸런싱 기준일 시가총액 >= 3,000억 원
   - 최근 60거래일 일평균 거래대금(ADTV) >= 10억 원
   - 36개월 순매수 원자료 완전 확보 (신규 상장 왜곡 방지를 위해 36개월 윈도우 내 실제 거래일 >= 650일, 즉 약 90% 이상 관측된 종목만 인정)
3. 분기별 정기 리밸런싱 (3·6·9·12월 말 기준 집계 -> 익분기 첫 거래일 동일가중 2.0% 적용, 소급 적용 금지)
4. 기존 원장(universe.parquet, daily_investor_trades.parquet) 및 기존 지수 시계열 보존
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from ledger_loader import load_raw_ledger

DATA_DIR = os.path.join(BASE_DIR, "data")


def prepare_ledger_with_marcap():
    print("[1/6] 원장 로드 및 자본금 변동 보정 일별 시가총액·거래대금 복원 중...")
    universe = pd.read_parquet(os.path.join(DATA_DIR, "universe.parquet"))
    needed_cols = [
        'code', 'date', 'base_price', 'reg_close', 'krx_vol',
        'krx_ind_buy_val', 'krx_ind_sell_val', 'krx_ind_net_val', 'krx_ind_net_vol',
        'nxt_ind_net_val', 'total_ind_net_val'
    ]
    trades = load_raw_ledger(needed_cols=needed_cols, verify_integrity=True, sort_by_code_date=True)
    bench = pd.read_parquet(os.path.join(DATA_DIR, "benchmarks.parquet"))

    # 종목별 최신 상장주식수 매핑
    shares_map = universe.set_index('Code')['Stocks'].to_dict()
    latest_shares = trades['code'].map(shares_map).fillna(0).astype(np.float64)

    # 액면분할/병합/무상증자 등 자본금 변동 배율(ca_mult = 직전종가 / 당일기준가) 역산으로 시점별 상장주식수 복원
    prev_close = trades.groupby('code')['reg_close'].shift(1).fillna(0).values
    base_p = trades['base_price'].values
    reg_c = trades['reg_close'].values

    valid_ca = (prev_close > 0) & (base_p > 0)
    raw_ratio = np.where(valid_ca, prev_close / np.maximum(base_p, 1), 1.0)
    ca_mult = np.where(np.abs(raw_ratio - 1.0) > 0.005, raw_ratio, 1.0)
    ca_mult = np.clip(ca_mult, 0.02, 50.0)
    trades['ca_mult'] = ca_mult

    # 벡터화된 역방향 누적곱 (0.1초 완료)
    rev_cum = trades.iloc[::-1].groupby('code')['ca_mult'].cumprod().iloc[::-1]
    future_split_factor = (rev_cum / trades['ca_mult']).values
    trades.drop(columns=['ca_mult'], inplace=True)

    pit_shares = latest_shares.values / future_split_factor

    # 일별 시가총액(원) 및 일별 거래대금(원)
    trades['daily_marcap'] = pit_shares * reg_c.astype(np.float64)
    trades['daily_trdval'] = trades['krx_vol'].values.astype(np.float64) * reg_c.astype(np.float64)

    # 일별 총수익비율 (gross_ret = reg_close / base_price)
    valid_p = (base_p > 0) & (reg_c > 0)
    trades['gross_ret'] = np.clip(
        np.where(valid_p, reg_c.astype(np.float64) / np.maximum(base_p.astype(np.float64), 1.0), 1.0),
        0.3, 4.0
    )

    return universe, trades, bench


def get_rebalance_schedule(trading_dates):
    s_dates = pd.Series(sorted(trading_dates))
    df_dt = pd.DataFrame({'date': s_dates})
    df_dt['ym'] = df_dt['date'].str.slice(0, 7)
    month_ends = df_dt.groupby('ym')['date'].max().reset_index()
    month_ends['month'] = month_ends['ym'].str.slice(5, 7).astype(int)
    q_ends = month_ends[month_ends['month'].isin([3, 6, 9, 12])].sort_values('date').reset_index(drop=True)

    valid_q = q_ends[q_ends['date'] >= '2024-09-30'].reset_index(drop=True)
    schedule = []
    all_dates_list = sorted(trading_dates)

    for i in range(len(valid_q)):
        det_date = valid_q.loc[i, 'date']
        later_dates = [d for d in all_dates_list if d > det_date]
        if not later_dates:
            continue
        eff_start = later_dates[0]
        eff_end = valid_q.loc[i + 1, 'date'] if (i + 1 < len(valid_q)) else all_dates_list[-1]

        dt_obj = datetime.strptime(det_date, "%Y-%m-%d")
        q_num = (dt_obj.month - 1) // 3 + 1
        apply_label = f"{dt_obj.year + 1} Q1" if q_num == 4 else f"{dt_obj.year} Q{q_num + 1}"

        start_36m = (dt_obj - relativedelta(months=36) + relativedelta(days=1)).strftime("%Y-%m-%d")
        start_12m = (dt_obj - relativedelta(months=12) + relativedelta(days=1)).strftime("%Y-%m-%d")

        # 최근 60거래일 시작일 찾기
        dates_up_to_det = [d for d in all_dates_list if d <= det_date]
        start_60d = dates_up_to_det[max(0, len(dates_up_to_det) - 60)]

        # 해당 36개월 구간의 전체 시장 영업일 수
        window_mkt_days = len([d for d in all_dates_list if start_36m <= d <= det_date])

        schedule.append({
            "rebalance_id": apply_label,
            "determination_date": det_date,
            "effective_start": eff_start,
            "effective_end": eff_end,
            "window_36m_start": start_36m,
            "window_12m_start": start_12m,
            "window_60d_start": start_60d,
            "window_mkt_days": window_mkt_days,
        })
    return schedule


def evaluate_cross_section_at_date(
    trades, universe_map, q_info,
    min_marcap_eok=3000.0,
    min_adtv_60d_eok=10.0,
    min_obs_ratio=0.90
):
    """
    특정 분기 기준일(det_date) 시점의 전 종목 36개월 누적 순매수대금, 36개월 평균 시가총액,
    순매수 강도(%), 최근 60거래일 일평균 거래대금, 기준일 시가총액을 계산하고
    자격 요건 충족 여부와 전체 순위(강도 순위 & 절대금액 순위)를 산출.
    """
    det_date = q_info["determination_date"]
    w36_start = q_info["window_36m_start"]
    w60_start = q_info["window_60d_start"]
    mkt_days = q_info["window_mkt_days"]
    min_trading_days = int(np.floor(mkt_days * min_obs_ratio))

    sub36 = trades[(trades['date'] >= w36_start) & (trades['date'] <= det_date)]
    if sub36.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # 기준일(또는 직전 15일 내) 거래 중인 상장 종목 확인 (생존자 편향 방지)
    recent_cut = (datetime.strptime(det_date, "%Y-%m-%d") - relativedelta(days=15)).strftime("%Y-%m-%d")
    sub_recent = sub36[(sub36['date'] >= recent_cut) & (sub36['reg_close'] > 0)]
    active_at_det = set(sub_recent['code'].unique())

    valid_codes = set()
    for c in active_at_det:
        u_info = universe_map.get(c)
        if not u_info:
            continue
        del_dt = u_info.get('DelistingDate')
        if pd.notna(del_dt) and str(del_dt)[:10] <= det_date:
            continue
        valid_codes.add(c)

    sub36 = sub36[sub36['code'].isin(valid_codes)]
    sub60 = sub36[sub36['date'] >= w60_start]

    # 36개월 집계
    agg36 = sub36.groupby('code', as_index=False).agg(
        net_buy_val=('krx_ind_net_val', 'sum'),
        buy_val=('krx_ind_buy_val', 'sum'),
        sell_val=('krx_ind_sell_val', 'sum'),
        net_buy_vol=('krx_ind_net_vol', 'sum'),
        nxt_net_buy_val=('nxt_ind_net_val', 'sum'),
        total_net_buy_val=('total_ind_net_val', 'sum'),
        avg_marcap_36m=('daily_marcap', 'mean'),
        end_marcap=('daily_marcap', 'last'),
        last_close=('reg_close', 'last'),
        trading_days=('date', 'count'),
        first_obs_date=('date', 'min'),
    )

    # 최근 60거래일 일평균 거래대금 (60거래일 전체 일수로 나눔)
    agg60 = sub60.groupby('code', as_index=False).agg(
        trdval_60d_sum=('daily_trdval', 'sum'),
        days_60d=('date', 'count')
    )
    agg60['adtv_60d'] = agg60['trdval_60d_sum'] / 60.0

    df_all = pd.merge(agg36, agg60[['code', 'adtv_60d']], on='code', how='left')
    df_all['adtv_60d'] = df_all['adtv_60d'].fillna(0.0)

    # 단위 변환 (억 원) 및 순매수 강도 산출
    df_all['net_buy_eok'] = (df_all['net_buy_val'] / 1e8).round(2)
    df_all['avg_marcap_36m_eok'] = (df_all['avg_marcap_36m'] / 1e8).round(2)
    df_all['end_marcap_eok'] = (df_all['end_marcap'] / 1e8).round(2)
    df_all['adtv_60d_eok'] = (df_all['adtv_60d'] / 1e8).round(2)

    # 순매수 강도 = 36개월 개인 누적 순매수대금 / 36개월 평균 시가총액 * 100
    df_all['intensity_pct'] = np.where(
        df_all['avg_marcap_36m'] > 0,
        (df_all['net_buy_val'] / df_all['avg_marcap_36m']) * 100.0,
        0.0
    ).round(4)

    # 메타데이터 부착
    df_all['name'] = df_all['code'].map(lambda c: universe_map.get(c, {}).get('Name', c))
    df_all['market'] = df_all['code'].map(lambda c: universe_map.get(c, {}).get('MarketName', ''))
    df_all['industry'] = df_all['code'].map(lambda c: universe_map.get(c, {}).get('Industry', ''))
    df_all['status'] = df_all['code'].map(lambda c: universe_map.get(c, {}).get('Status', 'ACTIVE'))

    # 시가총액 규모 분류 (초대형 10조+, 대형 1조~10조, 중형 3,000억~1조, 소형 3,000억 미만)
    def classify_size(mc_eok):
        if mc_eok >= 100000:
            return "초대형주 (10조 이상)"
        elif mc_eok >= 10000:
            return "대형주 (1조~10조)"
        elif mc_eok >= 3000:
            return "중형주 (3,000억~1조)"
        else:
            return "소형주 (3,000억 미만)"

    df_all['size_bucket'] = df_all['end_marcap_eok'].map(classify_size)

    # 전체 종목 절대 순매수대금 순위 (양수 순매수 우선, 전 유니버스 기준)
    df_all = df_all.sort_values('net_buy_val', ascending=False).reset_index(drop=True)
    df_all['abs_rank_all'] = range(1, len(df_all) + 1)

    # 자격 요건 태깅
    df_all['pass_pos_netbuy'] = df_all['net_buy_val'] > 0
    df_all['pass_marcap'] = df_all['end_marcap_eok'] >= min_marcap_eok
    df_all['pass_adtv'] = df_all['adtv_60d_eok'] >= min_adtv_60d_eok
    df_all['pass_36m_obs'] = df_all['trading_days'] >= min_trading_days

    df_all['is_eligible_pure'] = (
        df_all['pass_pos_netbuy'] &
        df_all['pass_marcap'] &
        df_all['pass_adtv'] &
        df_all['pass_36m_obs']
    )

    # 탈락 사유 기록
    def get_exclude_reason(row):
        reasons = []
        if not row['pass_pos_netbuy']:
            reasons.append("순매도(음수)")
        if not row['pass_36m_obs']:
            reasons.append(f"36개월 관측미달({row['trading_days']}/{mkt_days}일, 신규상장)")
        if not row['pass_marcap']:
            reasons.append(f"시총 {min_marcap_eok:.0f}억 미만({row['end_marcap_eok']:.0f}억)")
        if not row['pass_adtv']:
            reasons.append(f"60일 평균거래대금 {min_adtv_60d_eok:.0f}억 미만({row['adtv_60d_eok']:.1f}억)")
        return ", ".join(reasons) if reasons else "적격"

    df_all['eligibility_note'] = df_all.apply(get_exclude_reason, axis=1)

    # 적격 종목 중 순매수 강도 순위 부여
    eligible = df_all[df_all['is_eligible_pure']].sort_values('intensity_pct', ascending=False).reset_index(drop=True)
    eligible['pure_rank'] = range(1, len(eligible) + 1)
    pure_rank_map = eligible.set_index('code')['pure_rank'].to_dict()
    df_all['pure_rank_eligible'] = df_all['code'].map(pure_rank_map)

    # 비적격 종목을 포함한 단순 강도 순위도 참고용 계산
    df_all_by_int = df_all.sort_values('intensity_pct', ascending=False).reset_index(drop=True)
    df_all_by_int['raw_intensity_rank'] = range(1, len(df_all_by_int) + 1)
    df_all['raw_intensity_rank'] = df_all['code'].map(df_all_by_int.set_index('code')['raw_intensity_rank'].to_dict())

    # 1) GAEMI 50 PURE 상위 50개
    pure_top50 = eligible.head(50).copy()
    pure_top50['rank'] = range(1, len(pure_top50) + 1)
    pure_top50['weight'] = 1.0 / len(pure_top50)

    # 2) 기존 GAEMI 50 (절대금액 상위 50개)
    abs_top50 = df_all.sort_values('net_buy_val', ascending=False).head(50).copy()
    abs_top50['rank'] = range(1, len(abs_top50) + 1)
    abs_top50['weight'] = 1.0 / len(abs_top50)

    return df_all, pure_top50, abs_top50


def compute_index_series(trades, schedule, holdings_by_q, base_date="2024-09-30", base_val=1000.0):
    all_codes = set()
    for _, df_h in holdings_by_q.items():
        all_codes.update(df_h['code'].tolist())

    sub = trades[(trades['code'].isin(all_codes)) & (trades['date'] >= base_date)].copy()
    ret_pivot = sub.pivot(index='date', columns='code', values='gross_ret').fillna(1.0)
    all_dates = sorted(ret_pivot.index.tolist())

    rows = [{
        "date": base_date,
        "index_value": round(base_val, 2),
        "daily_return_pct": 0.0,
        "rebalance_id": schedule[0]["rebalance_id"],
        "is_rebalance_date": True
    }]
    curr_val = base_val
    prev_val = base_val

    for q_info in schedule:
        q_id = q_info["rebalance_id"]
        eff_start = q_info["effective_start"]
        eff_end = q_info["effective_end"]
        df_h = holdings_by_q[q_id]
        codes = df_h['code'].tolist()
        n_stocks = len(codes)
        init_w = 1.0 / n_stocks

        q_dates = [d for d in all_dates if eff_start <= d <= eff_end]
        if not q_dates:
            continue

        rel_wealth = np.ones(n_stocks, dtype=float)
        q_base = curr_val

        for d_idx, dt in enumerate(q_dates):
            day_gross = np.array([ret_pivot.at[dt, c] if c in ret_pivot.columns else 1.0 for c in codes], dtype=float)
            rel_wealth = rel_wealth * day_gross
            port_rel = float(np.sum(init_w * rel_wealth))
            new_val = q_base * port_rel
            daily_ret = (new_val / prev_val - 1.0) * 100.0
            rows.append({
                "date": dt,
                "index_value": round(new_val, 2),
                "daily_return_pct": round(daily_ret, 4),
                "rebalance_id": q_id,
                "is_rebalance_date": (d_idx == 0)
            })
            prev_val = new_val
            curr_val = new_val

    return pd.DataFrame(rows)


def calc_performance_metrics(series_val, series_ret, bench_kospi_ret, bench_kosdaq_ret):
    vals = np.array(series_val, dtype=float)
    rets = np.array(series_ret[1:], dtype=float) / 100.0
    k_rets = np.array(bench_kospi_ret[1:], dtype=float) / 100.0
    q_rets = np.array(bench_kosdaq_ret[1:], dtype=float) / 100.0

    total_ret = (vals[-1] / vals[0] - 1.0) * 100.0
    peak = np.maximum.accumulate(vals)
    dd = (vals / peak - 1.0) * 100.0
    mdd = float(np.min(dd))
    ann_vol = float(np.std(rets, ddof=1) * np.sqrt(250) * 100.0) if len(rets) > 1 else 0.0

    corr_kospi = float(np.corrcoef(rets, k_rets)[0, 1]) if len(rets) > 2 else 0.0
    corr_kosdaq = float(np.corrcoef(rets, q_rets)[0, 1]) if len(rets) > 2 else 0.0

    return {
        "current": round(float(vals[-1]), 2),
        "daily_change_pt": round(float(vals[-1] - vals[-2]), 2),
        "daily_change_pct": round(float((vals[-1] / vals[-2] - 1.0) * 100.0), 2),
        "total_return_pct": round(float(total_ret), 2),
        "mdd_pct": round(mdd, 2),
        "ann_volatility_pct": round(ann_vol, 2),
        "corr_kospi": round(corr_kospi, 4),
        "corr_kosdaq": round(corr_kosdaq, 4),
        "high": round(float(np.max(vals)), 2),
        "low": round(float(np.min(vals)), 2),
    }


def run_sensitivity_analysis(trades, all_cross_sections, schedule, bench_merged):
    """
    시가총액 하한(1,000억 / 2,000억 / 3,000억 / 5,000억 / 1조) 및
    60일 일평균 거래대금 하한(5억 / 10억 / 20억 / 50억),
    그리고 신규상장 관측기간 규칙(90%=완전36개월 vs 무제한)에 대한 민감도 분석 수행.
    """
    print("[3/6] 최소 시가총액·거래대금·관측기간 민감도 분석 수행 중...")
    scenarios = [
        {"name": "시총 1,000억+ / 거래대금 5억+ / 36개월 완전관측", "mc": 1000, "adtv": 5, "obs": 0.90},
        {"name": "시총 2,000억+ / 거래대금 10억+ / 36개월 완전관측", "mc": 2000, "adtv": 10, "obs": 0.90},
        {"name": "시총 3,000억+ / 거래대금 10억+ / 36개월 완전관측 (최종 확정 기준)", "mc": 3000, "adtv": 10, "obs": 0.90, "is_baseline": True},
        {"name": "시총 3,000억+ / 거래대금 20억+ / 36개월 완전관측", "mc": 3000, "adtv": 20, "obs": 0.90},
        {"name": "시총 5,000억+ / 거래대금 10억+ / 36개월 완전관측", "mc": 5000, "adtv": 10, "obs": 0.90},
        {"name": "시총 1조 원+ / 거래대금 20억+ / 36개월 완전관측", "mc": 10000, "adtv": 20, "obs": 0.90},
        {"name": "시총 3,000억+ / 거래대금 10억+ / 신규상장 허용(관측제한 없음)", "mc": 3000, "adtv": 10, "obs": 0.05},
    ]

    latest_q = schedule[-1]
    base_date = schedule[0]["determination_date"]

    df_latest_all = all_cross_sections[latest_q["rebalance_id"]]
    base_top50_latest = df_latest_all[df_latest_all['is_eligible_pure']].sort_values('intensity_pct', ascending=False).head(50)
    base_codes_latest = set(base_top50_latest['code'])

    results = []
    for sc in scenarios:
        h_by_q = {}
        latest_eligible_cnt = 0
        latest_avg_intensity = 0.0
        latest_med_marcap = 0.0
        overlap_with_base = 0

        for q in schedule:
            qid = q["rebalance_id"]
            df_all = all_cross_sections[qid]
            min_days = int(np.floor(q["window_mkt_days"] * sc["obs"]))
            cond = (
                (df_all['net_buy_val'] > 0) &
                (df_all['end_marcap_eok'] >= sc["mc"]) &
                (df_all['adtv_60d_eok'] >= sc["adtv"]) &
                (df_all['trading_days'] >= min_days)
            )
            elig = df_all[cond].sort_values('intensity_pct', ascending=False)
            p_top50 = elig.head(50).copy()
            p_top50['rank'] = range(1, len(p_top50) + 1)
            p_top50['weight'] = 1.0 / len(p_top50)
            h_by_q[qid] = p_top50

            if qid == latest_q["rebalance_id"]:
                latest_eligible_cnt = int(cond.sum())
                latest_avg_intensity = round(float(p_top50['intensity_pct'].mean()), 2)
                latest_med_marcap = round(float(p_top50['end_marcap_eok'].median()), 0)
                overlap_with_base = len(set(p_top50['code']) & base_codes_latest)

        ts_sc = compute_index_series(trades, schedule, h_by_q, base_date=base_date, base_val=1000.0)
        m_sc = pd.merge(ts_sc, bench_merged[['date', 'KOSPI_ret', 'KOSDAQ_ret']], on='date', how='inner')
        perf = calc_performance_metrics(
            m_sc['index_value'].values,
            m_sc['daily_return_pct'].values,
            m_sc['KOSPI_ret'].values,
            m_sc['KOSDAQ_ret'].values
        )

        results.append({
            "scenario": sc["name"],
            "min_marcap_eok": sc["mc"],
            "min_adtv_eok": sc["adtv"],
            "min_obs_ratio": sc["obs"],
            "is_baseline": sc.get("is_baseline", False),
            "eligible_pool_count": latest_eligible_cnt,
            "top50_avg_intensity_pct": latest_avg_intensity,
            "top50_median_marcap_eok": latest_med_marcap,
            "overlap_with_baseline_count": overlap_with_base,
            "overlap_with_baseline_pct": round(overlap_with_base / 50.0 * 100.0, 1),
            "final_index": perf["current"],
            "total_return_pct": perf["total_return_pct"],
            "mdd_pct": perf["mdd_pct"],
            "ann_volatility_pct": perf["ann_volatility_pct"],
            "corr_kospi": perf["corr_kospi"],
            "corr_kosdaq": perf["corr_kosdaq"],
        })
        print(f"  - [{sc['name']}] 적격={latest_eligible_cnt}개 | 평균강도={latest_avg_intensity}% | 중위시총={latest_med_marcap:,.0f}억 | 수익률={perf['total_return_pct']:+.2f}% | KOSPI상관={perf['corr_kospi']:.3f} | KOSDAQ상관={perf['corr_kosdaq']:.3f}")

    return results


def main():
    universe, trades, bench = prepare_ledger_with_marcap()
    universe_map = universe.set_index('Code').to_dict(orient='index')

    trading_dates = sorted(trades['date'].unique().tolist())
    max_date = trading_dates[-1]
    schedule = get_rebalance_schedule(trading_dates)
    print(f"[2/6] 총 {len(schedule)}개 분기({schedule[0]['rebalance_id']} ~ {schedule[-1]['rebalance_id']}) GAEMI 50 PURE 및 비교지수 종목 선정 중...")

    pure_holdings = {}
    abs_holdings = {}
    all_cross_sections = {}
    rebalance_history = []

    prev_pure_codes = set()
    prev_pure_rank_map = {}
    # 종목별 최초 편입 분기 및 편입 시점 기준일 기록
    first_entry_info = {}  # code -> {"quarter": q_id, "entry_det_date": det_date, "entry_eff_date": eff_start, "entry_price": prc}

    for q in schedule:
        q_id = q["rebalance_id"]
        det_date = q["determination_date"]
        eff_start = q["effective_start"]

        df_all, pure_top50, abs_top50 = evaluate_cross_section_at_date(
            trades, universe_map, q,
            min_marcap_eok=3000.0, min_adtv_60d_eok=10.0, min_obs_ratio=0.90
        )

        # 전 분기 대비 순위 변화(rank_change) 계산
        def calc_rank_delta(row):
            c = row['code']
            curr_r = int(row['rank'])
            if not prev_pure_rank_map:
                return "초기편입"
            if c not in prev_pure_rank_map:
                return "NEW"
            diff = prev_pure_rank_map[c] - curr_r
            if diff > 0:
                return f"▲ +{diff}"
            elif diff < 0:
                return f"▼ {diff}"
            return "-"

        pure_top50['prev_quarter_rank'] = pure_top50['code'].map(lambda c: prev_pure_rank_map.get(c, None))
        pure_top50['rank_change_str'] = pure_top50.apply(calc_rank_delta, axis=1)

        # 최초 편입 시점 기록
        for _, row in pure_top50.iterrows():
            c = row['code']
            if c not in first_entry_info:
                first_entry_info[c] = {
                    "quarter": q_id,
                    "det_date": det_date,
                    "eff_start": eff_start,
                    "entry_close": int(row['last_close'])
                }

        pure_holdings[q_id] = pure_top50
        abs_holdings[q_id] = abs_top50
        all_cross_sections[q_id] = df_all

        curr_pure_codes = set(pure_top50['code'])
        curr_abs_codes = set(abs_top50['code'])

        if prev_pure_codes:
            p_added = sorted(list(curr_pure_codes - prev_pure_codes))
            p_removed = sorted(list(prev_pure_codes - curr_pure_codes))
        else:
            p_added = []
            p_removed = []

        pure_abs_common = sorted(list(curr_pure_codes & curr_abs_codes))

        # 삼성전자(005930), SK하이닉스(000660) 해당 분기 상태 추출
        def get_giant_status(ticker):
            r = df_all[df_all['code'] == ticker]
            if r.empty:
                return None
            row = r.iloc[0]
            return {
                "code": ticker,
                "name": str(row['name']),
                "net_buy_val": int(row['net_buy_val']),
                "net_buy_eok": float(row['net_buy_eok']),
                "avg_marcap_36m_eok": float(row['avg_marcap_36m_eok']),
                "end_marcap_eok": float(row['end_marcap_eok']),
                "intensity_pct": float(row['intensity_pct']),
                "abs_rank": int(row['abs_rank_all']),
                "pure_rank": int(row['pure_rank_eligible']) if pd.notna(row['pure_rank_eligible']) else None,
                "selected_in_pure50": bool(ticker in curr_pure_codes),
                "selected_in_abs50": bool(ticker in curr_abs_codes),
            }

        rebalance_history.append({
            **q,
            "pure_abs_common_count": len(pure_abs_common),
            "pure_abs_common_pct": round(len(pure_abs_common) / 50.0 * 100.0, 1),
            "pure_avg_intensity_pct": round(float(pure_top50['intensity_pct'].mean()), 2),
            "abs_avg_intensity_pct": round(float(abs_top50['intensity_pct'].mean()), 2),
            "pure_added": [
                {
                    "code": c,
                    "name": universe_map.get(c, {}).get("Name", c),
                    "rank": int(pure_top50[pure_top50['code'] == c]['rank'].iloc[0]),
                    "intensity_pct": float(pure_top50[pure_top50['code'] == c]['intensity_pct'].iloc[0]),
                    "net_buy_val": int(pure_top50[pure_top50['code'] == c]['net_buy_val'].iloc[0]),
                }
                for c in p_added
            ],
            "pure_removed": [
                {
                    "code": c,
                    "name": universe_map.get(c, {}).get("Name", c),
                    "new_pure_rank": int(df_all[df_all['code'] == c]['pure_rank_eligible'].iloc[0])
                    if (not df_all[df_all['code'] == c].empty and pd.notna(df_all[df_all['code'] == c]['pure_rank_eligible'].iloc[0]))
                    else None,
                    "reason": str(df_all[df_all['code'] == c]['eligibility_note'].iloc[0])
                    if not df_all[df_all['code'] == c].empty else "순위권 외"
                }
                for c in p_removed
            ],
            "samsung_status": get_giant_status("005930"),
            "hynix_status": get_giant_status("000660"),
        })

        prev_pure_codes = curr_pure_codes
        prev_pure_rank_map = pure_top50.set_index('code')['rank'].to_dict()

        top1 = pure_top50.iloc[0]
        print(f"  [{q_id}] 기준일={det_date} | PURE #1={top1['name']}(강도 {top1['intensity_pct']:.2f}%, 순매수 {top1['net_buy_eok']:,.0f}억 / 평균시총 {top1['avg_marcap_36m_eok']:,.0f}억) | 절대금액Top50과 공통={len(pure_abs_common)}/50개")

    # 지수 시계열 산출
    base_date = schedule[0]["determination_date"]
    df_pure_ts = compute_index_series(trades, schedule, pure_holdings, base_date=base_date, base_val=1000.0)
    df_abs_ts = compute_index_series(trades, schedule, abs_holdings, base_date=base_date, base_val=1000.0)

    # 기존 GAEMI 50 NOW 시계열도 로드하여 병합 보존
    old_ts = pd.read_csv(os.path.join(DATA_DIR, "index_timeseries.csv"))
    merged = pd.merge(
        df_pure_ts.rename(columns={"index_value": "GAEMI_50_PURE", "daily_return_pct": "GAEMI_50_PURE_ret"}),
        df_abs_ts[['date', 'index_value', 'daily_return_pct']].rename(columns={"index_value": "GAEMI_50_ABS", "daily_return_pct": "GAEMI_50_ABS_ret"}),
        on='date',
        how='inner'
    )
    if 'GAEMI_50_NOW' in old_ts.columns:
        merged = pd.merge(merged, old_ts[['date', 'GAEMI_50_NOW', 'GAEMI_50_NOW_ret']], on='date', how='left')

    merged = pd.merge(merged, bench, on='date', how='left')
    merged['KOSPI'] = merged['KOSPI'].ffill().bfill()
    merged['KOSDAQ'] = merged['KOSDAQ'].ffill().bfill()

    kospi_base = float(merged.loc[merged['date'] == base_date, 'KOSPI'].iloc[0])
    kosdaq_base = float(merged.loc[merged['date'] == base_date, 'KOSDAQ'].iloc[0])
    merged['KOSPI_norm'] = (merged['KOSPI'] / kospi_base * 1000.0).round(2)
    merged['KOSDAQ_norm'] = (merged['KOSDAQ'] / kosdaq_base * 1000.0).round(2)
    merged['KOSPI_ret'] = (merged['KOSPI'].pct_change().fillna(0.0) * 100.0).round(4)
    merged['KOSDAQ_ret'] = (merged['KOSDAQ'].pct_change().fillna(0.0) * 100.0).round(4)

    # 호환성을 위해 GAEMI_50 컬럼도 유지
    merged['GAEMI_50'] = merged['GAEMI_50_ABS']
    merged['GAEMI_50_ret'] = merged['GAEMI_50_ABS_ret']

    merged.to_csv(os.path.join(DATA_DIR, "index_timeseries.csv"), index=False, encoding="utf-8-sig")
    merged.to_parquet(os.path.join(DATA_DIR, "index_timeseries.parquet"), index=False)

    # 민감도 분석 실행
    sensitivity_results = run_sensitivity_analysis(trades, all_cross_sections, schedule, merged)
    with open(os.path.join(DATA_DIR, "sensitivity_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(sensitivity_results, f, ensure_ascii=False, indent=2)

    # [4/6] 최신 분기(2026 Q4) 구성 종목의 편입 시점, 편입 이후 수익률, 분기 수익률, 현재 비중 계산
    print("[4/6] 종목별 편입 시점·편입 이후 수익률 및 기존 지수 대비 8대 비교 검증 산출 중...")
    latest_q = schedule[-1]
    latest_qid = latest_q["rebalance_id"]
    eff_start = latest_q["effective_start"]

    latest_pure = pure_holdings[latest_qid].copy()
    latest_abs = abs_holdings[latest_qid].copy()
    latest_all_df = all_cross_sections[latest_qid].copy()

    # 각 종목의 기준일~최신일 누적 gross_ret 테이블
    sub_since_2024 = trades[trades['date'] >= base_date].copy()
    ret_pivot_all = sub_since_2024.pivot(index='date', columns='code', values='gross_ret').fillna(1.0)
    latest_price_map = trades[trades['date'] == max_date].set_index('code')['reg_close'].to_dict()

    # 현재 분기(eff_start ~ max_date) 수익률
    q_dates = [d for d in ret_pivot_all.index if eff_start <= d <= max_date]
    q_cum_ret = ret_pivot_all.loc[q_dates].prod(axis=0).to_dict()

    def enrich_holdings(df_h, is_pure=True):
        df_h['q_gross_ret'] = df_h['code'].map(lambda c: float(q_cum_ret.get(c, 1.0)))
        df_h['q_return_pct'] = ((df_h['q_gross_ret'] - 1.0) * 100.0).round(2)
        tot_w = (df_h['weight'] * df_h['q_gross_ret']).sum()
        df_h['current_weight_pct'] = ((df_h['weight'] * df_h['q_gross_ret']) / tot_w * 100.0).round(2)
        df_h['current_price'] = df_h['code'].map(lambda c: int(latest_price_map.get(c, 0)))

        entry_quarters = []
        entry_dates = []
        since_entry_rets = []
        consec_quarters = []

        for _, row in df_h.iterrows():
            c = row['code']
            # 몇 개 분기 편입되었는지 계산
            q_in_list = [q["rebalance_id"] for q in schedule if c in set(pure_holdings[q["rebalance_id"]]['code'])] if is_pure else [q["rebalance_id"] for q in schedule if c in set(abs_holdings[q["rebalance_id"]]['code'])]
            consec_quarters.append(len(q_in_list))

            if is_pure and c in first_entry_info:
                info = first_entry_info[c]
                eq = info["quarter"]
                ed = info["eff_start"]
                e_dates = [d for d in ret_pivot_all.index if ed <= d <= max_date]
                if e_dates and c in ret_pivot_all.columns:
                    g_prod = float(ret_pivot_all.loc[e_dates, c].prod())
                    s_ret = round((g_prod - 1.0) * 100.0, 2)
                else:
                    s_ret = 0.0
                entry_quarters.append(eq)
                entry_dates.append(ed)
                since_entry_rets.append(s_ret)
            else:
                entry_quarters.append(latest_qid)
                entry_dates.append(eff_start)
                since_entry_rets.append(float(row['q_return_pct']))

        df_h['entry_quarter'] = entry_quarters
        df_h['entry_date'] = entry_dates
        df_h['since_entry_return_pct'] = since_entry_rets
        df_h['quarters_included_count'] = consec_quarters
        return df_h

    latest_pure = enrich_holdings(latest_pure, is_pure=True)
    latest_abs = enrich_holdings(latest_abs, is_pure=False)

    latest_pure.to_csv(os.path.join(DATA_DIR, "gaemi50_pure_constituents.csv"), index=False, encoding="utf-8-sig")
    latest_abs.to_csv(os.path.join(DATA_DIR, "gaemi50_abs_constituents.csv"), index=False, encoding="utf-8-sig")

    # 전체 분기별 GAEMI 50 PURE 이력 저장
    all_pure_q_rows = []
    for q in schedule:
        qid = q["rebalance_id"]
        tmp = pure_holdings[qid].copy()
        tmp['index_name'] = 'GAEMI_50_PURE'
        tmp['rebalance_id'] = qid
        tmp['determination_date'] = q['determination_date']
        all_pure_q_rows.append(tmp)
    pd.concat(all_pure_q_rows, ignore_index=True).to_csv(
        os.path.join(DATA_DIR, "historical_pure_constituents_all_quarters.csv"), index=False, encoding="utf-8-sig"
    )

    # [5/6] Section 4: 기존 지수(절대금액 Top 50)와 새 지수(순매수 강도 Top 50)의 8대 비교 검증 데이터 생성
    pure_codes = set(latest_pure['code'])
    abs_codes = set(latest_abs['code'])
    common_codes = pure_codes & abs_codes
    newly_included_codes = pure_codes - abs_codes  # PURE에만 편입된 종목
    excluded_from_abs_codes = abs_codes - pure_codes  # 기존 절대금액 Top 50에서 탈락한 종목

    # 4-4. 새롭게 편입되는 종목 (PURE 50에는 있으나 기존 절대금액 50에는 없던 종목)
    newly_included_df = latest_pure[latest_pure['code'].isin(newly_included_codes)].sort_values('rank')
    # 4-5. 제외되는 종목 (기존 절대금액 50에는 있었으나 PURE 50에서 제외된 종목)
    excluded_from_abs_df = latest_abs[latest_abs['code'].isin(excluded_from_abs_codes)].sort_values('rank')

    # 4-6. 업종별 구성 변화
    ind_pure = latest_pure['industry'].replace('', '기타').value_counts()
    ind_abs = latest_abs['industry'].replace('', '기타').value_counts()
    all_inds = sorted(list(set(ind_pure.index) | set(ind_abs.index)), key=lambda x: -(ind_pure.get(x, 0) - ind_abs.get(x, 0)))
    industry_comparison = []
    for ind in all_inds:
        p_cnt = int(ind_pure.get(ind, 0))
        a_cnt = int(ind_abs.get(ind, 0))
        industry_comparison.append({
            "industry": ind,
            "pure_count": p_cnt,
            "pure_weight_pct": round(p_cnt * 2.0, 1),
            "abs_count": a_cnt,
            "abs_weight_pct": round(a_cnt * 2.0, 1),
            "diff_count": p_cnt - a_cnt,
            "diff_weight_pct": round((p_cnt - a_cnt) * 2.0, 1),
        })

    # 4-7. 시가총액 규모별 구성 변화
    size_order = ["초대형주 (10조 이상)", "대형주 (1조~10조)", "중형주 (3,000억~1조)", "소형주 (3,000억 미만)"]
    sz_pure = latest_pure['size_bucket'].value_counts()
    sz_abs = latest_abs['size_bucket'].value_counts()
    size_comparison = []
    for sb in size_order:
        p_cnt = int(sz_pure.get(sb, 0))
        a_cnt = int(sz_abs.get(sb, 0))
        size_comparison.append({
            "size_bucket": sb,
            "pure_count": p_cnt,
            "pure_weight_pct": round(p_cnt * 2.0, 1),
            "abs_count": a_cnt,
            "abs_weight_pct": round(a_cnt * 2.0, 1),
            "diff_count": p_cnt - a_cnt,
            "diff_weight_pct": round((p_cnt - a_cnt) * 2.0, 1),
        })

    # 시장별(KOSPI vs KOSDAQ) 구성 변화
    mkt_pure = latest_pure['market'].value_counts()
    mkt_abs = latest_abs['market'].value_counts()
    market_comparison = [
        {
            "market": mkt,
            "pure_count": int(mkt_pure.get(mkt, 0)),
            "pure_weight_pct": round(int(mkt_pure.get(mkt, 0)) * 2.0, 1),
            "abs_count": int(mkt_abs.get(mkt, 0)),
            "abs_weight_pct": round(int(mkt_abs.get(mkt, 0)) * 2.0, 1),
            "diff_count": int(mkt_pure.get(mkt, 0)) - int(mkt_abs.get(mkt, 0)),
        }
        for mkt in ["KOSPI", "KOSDAQ"]
    ]

    # 4-8. 삼성전자·SK하이닉스의 선정 여부와 순위 (최신 분기 및 전 분기 추이)
    samsung_latest = rebalance_history[-1]["samsung_status"]
    hynix_latest = rebalance_history[-1]["hynix_status"]
    giants_quarterly = [
        {
            "rebalance_id": h["rebalance_id"],
            "determination_date": h["determination_date"],
            "samsung": h["samsung_status"],
            "hynix": h["hynix_status"],
        }
        for h in rebalance_history
    ]

    # 성과 및 상관계수 계산
    metrics = {
        "GAEMI_50_PURE": calc_performance_metrics(
            merged['GAEMI_50_PURE'].values, merged['GAEMI_50_PURE_ret'].values,
            merged['KOSPI_ret'].values, merged['KOSDAQ_ret'].values
        ),
        "GAEMI_50_ABS": calc_performance_metrics(
            merged['GAEMI_50_ABS'].values, merged['GAEMI_50_ABS_ret'].values,
            merged['KOSPI_ret'].values, merged['KOSDAQ_ret'].values
        ),
        "KOSPI": calc_performance_metrics(
            merged['KOSPI_norm'].values, merged['KOSPI_ret'].values,
            merged['KOSPI_ret'].values, merged['KOSDAQ_ret'].values
        ),
        "KOSDAQ": calc_performance_metrics(
            merged['KOSDAQ_norm'].values, merged['KOSDAQ_ret'].values,
            merged['KOSPI_ret'].values, merged['KOSDAQ_ret'].values
        ),
        "KOSPI_raw": round(float(merged['KOSPI'].iloc[-1]), 2),
        "KOSDAQ_raw": round(float(merged['KOSDAQ'].iloc[-1]), 2),
    }
    if 'GAEMI_50_NOW' in merged.columns:
        metrics["GAEMI_50_NOW"] = calc_performance_metrics(
            merged['GAEMI_50_NOW'].values, merged['GAEMI_50_NOW_ret'].values,
            merged['KOSPI_ret'].values, merged['KOSDAQ_ret'].values
        )

    # PURE와 ABS 간의 일간 수익률 상관계수
    corr_pure_abs = float(np.corrcoef(merged['GAEMI_50_PURE_ret'].values[1:], merged['GAEMI_50_ABS_ret'].values[1:])[0, 1])
    metrics["GAEMI_50_PURE"]["corr_abs50"] = round(corr_pure_abs, 4)

    comparison_report = {
        "as_of_quarter": latest_qid,
        "determination_date": latest_q["determination_date"],
        "window_36m_start": latest_q["window_36m_start"],
        "common_count": len(common_codes),
        "common_pct": round(len(common_codes) / 50.0 * 100.0, 1),
        "newly_included_count": len(newly_included_codes),
        "excluded_count": len(excluded_from_abs_codes),
        "common_stocks": latest_pure[latest_pure['code'].isin(common_codes)][
            ['rank', 'code', 'name', 'market', 'industry', 'intensity_pct', 'net_buy_eok', 'avg_marcap_36m_eok', 'end_marcap_eok', 'abs_rank_all']
        ].to_dict(orient="records"),
        "newly_included_stocks": newly_included_df[
            ['rank', 'code', 'name', 'market', 'industry', 'size_bucket', 'intensity_pct', 'net_buy_eok', 'avg_marcap_36m_eok', 'end_marcap_eok', 'abs_rank_all', 'entry_quarter', 'since_entry_return_pct']
        ].to_dict(orient="records"),
        "excluded_from_abs_stocks": excluded_from_abs_df[
            ['rank', 'code', 'name', 'market', 'industry', 'size_bucket', 'intensity_pct', 'net_buy_eok', 'avg_marcap_36m_eok', 'end_marcap_eok', 'pure_rank_eligible', 'raw_intensity_rank', 'eligibility_note']
        ].to_dict(orient="records"),
        "industry_comparison": industry_comparison,
        "size_comparison": size_comparison,
        "market_comparison": market_comparison,
        "giants_focus": {
            "samsung_latest": samsung_latest,
            "hynix_latest": hynix_latest,
            "quarterly_history": giants_quarterly,
        },
        "performance_comparison": metrics,
    }

    with open(os.path.join(DATA_DIR, "pure_vs_abs_comparison.json"), "w", encoding="utf-8") as f:
        json.dump(comparison_report, f, ensure_ascii=False, indent=2)

    # [6/6] 종목별 상세 추이(순매수대금, 시가총액, 순매수 강도, 주가) 데이터 생성
    print("[6/6] 웹사이트용 종목별 상세 데이터 및 JSON/JS 번들 생성 중...")
    union_codes = sorted(list(pure_codes | abs_codes | {"005930", "000660"}))
    w36_start = latest_q["window_36m_start"]
    sub_top = trades[(trades['code'].isin(union_codes)) & (trades['date'] >= w36_start)].sort_values(['code', 'date']).copy()
    sub_top['cum_net_buy_eok'] = (sub_top.groupby('code')['krx_ind_net_val'].cumsum() / 1e8).round(1)
    sub_top['cum_total_net_buy_eok'] = (sub_top.groupby('code')['total_ind_net_val'].cumsum() / 1e8).round(1)
    sub_top['marcap_eok'] = (sub_top['daily_marcap'] / 1e8).round(0)
    sub_top['ym_week'] = pd.to_datetime(sub_top['date']).dt.to_period('W').astype(str)
    weekly_top = sub_top.groupby(['code', 'ym_week'], as_index=False).last()

    # 종목별 상세 메타 정보 매핑
    pure_meta_map = latest_pure.set_index('code').to_dict(orient='index')
    abs_meta_map = latest_abs.set_index('code').to_dict(orient='index')
    all_meta_map = latest_all_df.set_index('code').to_dict(orient='index')

    stock_trajectories = {}
    for c in union_codes:
        c_df = weekly_top[weekly_top['code'] == c].sort_values('date')
        m_all = all_meta_map.get(c, {})
        m_pure = pure_meta_map.get(c, {})
        m_abs = abs_meta_map.get(c, {})

        # 편입 이력 분기 리스트
        in_quarters = [q["rebalance_id"] for q in schedule if c in set(pure_holdings[q["rebalance_id"]]['code'])]
        f_info = first_entry_info.get(c, None)
        if f_info:
            ed = f_info["eff_start"]
            e_dates = [d for d in ret_pivot_all.index if ed <= d <= max_date]
            s_ret = round((float(ret_pivot_all.loc[e_dates, c].prod()) - 1.0) * 100.0, 2) if (e_dates and c in ret_pivot_all.columns) else 0.0
        else:
            s_ret = None

        stock_trajectories[c] = {
            "code": c,
            "name": m_all.get("name", universe_map.get(c, {}).get("Name", c)),
            "market": m_all.get("market", universe_map.get(c, {}).get("MarketName", "")),
            "industry": m_all.get("industry", universe_map.get(c, {}).get("Industry", "")),
            "size_bucket": m_all.get("size_bucket", ""),
            "net_buy_36m_eok": float(m_all.get("net_buy_eok", 0)),
            "avg_marcap_36m_eok": float(m_all.get("avg_marcap_36m_eok", 0)),
            "end_marcap_eok": float(m_all.get("end_marcap_eok", 0)),
            "intensity_pct": float(m_all.get("intensity_pct", 0)),
            "pure_rank": int(m_all["pure_rank_eligible"]) if pd.notna(m_all.get("pure_rank_eligible")) else None,
            "abs_rank": int(m_all.get("abs_rank_all", 0)),
            "rank_change_str": m_pure.get("rank_change_str", "편입 외"),
            "prev_quarter_rank": int(m_pure["prev_quarter_rank"]) if pd.notna(m_pure.get("prev_quarter_rank")) else None,
            "in_pure50": bool(c in pure_codes),
            "in_abs50": bool(c in abs_codes),
            "entry_quarter": f_info["quarter"] if f_info else "미편입",
            "entry_date": f_info["eff_start"] if f_info else "-",
            "since_entry_return_pct": s_ret,
            "included_quarters": in_quarters,
            "eligibility_note": m_all.get("eligibility_note", ""),
            "dates": c_df['date'].tolist(),
            "prices": [int(x) for x in c_df['reg_close'].tolist()],
            "marcap_eok": [float(x) for x in c_df['marcap_eok'].tolist()],
            "cum_net_buy_eok": [float(x) for x in c_df['cum_net_buy_eok'].tolist()],
            "cum_total_net_buy_eok": [float(x) for x in c_df['cum_total_net_buy_eok'].tolist()],
        }

    summary = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_as_of": max_date,
        "base_date": base_date,
        "base_value": 1000.0,
        "representative_index": "GAEMI 50 PURE",
        "selection_formula": "순매수 강도(%) = (36개월 개인 누적 순매수대금 / 36개월 평균 시가총액) × 100",
        "eligibility_criteria": {
            "min_marcap_eok": 3000,
            "min_adtv_60d_eok": 10,
            "min_observation_ratio": 0.90,
            "positive_net_buy_only": True,
            "universe": "KOSPI·KOSDAQ 상장 일반 보통주 (ETF·ETN·SPAC·우선주·리츠·외국기업·인프라펀드 제외)"
        },
        "index_type": "Price Return Index (가격지수, 배당 미포함·자본금변동 기준가 보정)",
        "current_rebalance": rebalance_history[-1],
        "rebalance_history": rebalance_history,
        "metrics": metrics,
    }

    with open(os.path.join(DATA_DIR, "index_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    web_payload = {
        "summary": summary,
        "audit": json.load(open(os.path.join(DATA_DIR, "audit_summary.json"), encoding="utf-8")),
        "comparison": comparison_report,
        "sensitivity": sensitivity_results,
        "timeseries": merged.to_dict(orient="records"),
        "gaemi50_pure_constituents": latest_pure.to_dict(orient="records"),
        "gaemi50_abs_constituents": latest_abs.to_dict(orient="records"),
        "stock_trajectories": stock_trajectories,
    }

    web_data_dir = os.path.join(BASE_DIR, "docs", "data")
    os.makedirs(web_data_dir, exist_ok=True)
    with open(os.path.join(web_data_dir, "gaemi_data.json"), "w", encoding="utf-8") as f:
        json.dump(web_payload, f, ensure_ascii=False)
    with open(os.path.join(web_data_dir, "gaemi_data.js"), "w", encoding="utf-8") as f:
        f.write("window.GAEMI_DATA = ")
        json.dump(web_payload, f, ensure_ascii=False)
        f.write(";\n")

    print("\n=== GAEMI 50 PURE vs 기존 지수 및 벤치마크 비교 요약 ===")
    for k in ["GAEMI_50_PURE", "GAEMI_50_ABS", "KOSPI", "KOSDAQ"]:
        m = metrics[k]
        print(f"  {k:15s}: 현재={m['current']:8.2f} ({m['daily_change_pct']:+.2f}%) | 누적={m['total_return_pct']:+.2f}% | MDD={m['mdd_pct']:.2f}% | 변동성={m['ann_volatility_pct']:.2f}% | KOSPI상관={m['corr_kospi']:.3f} | KOSDAQ상관={m['corr_kosdaq']:.3f}")


if __name__ == "__main__":
    main()
