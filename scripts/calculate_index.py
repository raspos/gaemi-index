"""
PHASE 3 & 4: GAEMI 50 및 GAEMI 50 NOW 지수 산출 엔진 및 과거 시계열 검증
- 산출 방식: 분기별 정기 리밸런싱 (3·6·9·12월 마지막 거래일 기준 데이터 집계 -> 익분기 첫 거래일 동일가중 2% 적용)
- 지수 유형: 가격지수 (Price Return Index, 배당 미포함 / 액면분할·감자·증자 등 자본금 변동은 KRX 기준가 대비 종가 수익률로 보정)
- 기준일 및 기준값: 2024-09-30 (2024년 3분기 말, 36개월 원자료가 완전히 확보된 첫 분기말) = 1,000.00 pt
  (2024-10-02 첫 거래일부터 새 포트폴리오 수익률 반영)
- 비교 벤치마크: KOSPI, KOSDAQ (동일 기준일 1,000.00 환산 비교 및 원지수 병기)
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


def load_data():
    universe = pd.read_parquet(os.path.join(DATA_DIR, "universe.parquet"))
    trades = pd.read_parquet(os.path.join(DATA_DIR, "daily_investor_trades.parquet"))
    bench = pd.read_parquet(os.path.join(DATA_DIR, "benchmarks.parquet"))
    return universe, trades, bench


def get_rebalance_schedule(trading_dates, min_data_date="2021-09-30"):
    """
    3, 6, 9, 12월의 마지막 거래일을 리밸런싱 기준일(determination_date)로 식별.
    36개월(3년) 원자료가 확보되는 시점 이후의 리밸런싱 스케줄 반환.
    """
    s_dates = pd.Series(sorted(trading_dates))
    df_dt = pd.DataFrame({'date': s_dates})
    df_dt['ym'] = df_dt['date'].str.slice(0, 7)
    df_dt['month'] = df_dt['date'].str.slice(5, 7).astype(int)

    # 각 연월의 마지막 거래일
    month_ends = df_dt.groupby('ym')['date'].max().reset_index()
    month_ends['month'] = month_ends['ym'].str.slice(5, 7).astype(int)
    q_ends = month_ends[month_ends['month'].isin([3, 6, 9, 12])].sort_values('date').reset_index(drop=True)

    # 36개월(3년) 전 데이터가 존재하는 분기말만 선택 (2024-09-30 이후)
    valid_q = q_ends[q_ends['date'] >= '2024-09-30'].reset_index(drop=True)
    schedule = []
    all_dates_list = sorted(trading_dates)

    for i in range(len(valid_q)):
        det_date = valid_q.loc[i, 'date']
        # effective start date: next trading day after det_date
        later_dates = [d for d in all_dates_list if d > det_date]
        if not later_dates:
            continue
        eff_start = later_dates[0]
        if i + 1 < len(valid_q):
            eff_end = valid_q.loc[i + 1, 'date']
            next_det = eff_end
        else:
            eff_end = all_dates_list[-1]
            next_det = None

        dt_obj = datetime.strptime(det_date, "%Y-%m-%d")
        q_num = (dt_obj.month - 1) // 3 + 1
        # 적용 분기 라벨 (예: 2024-09-30 기준 -> 2024 Q4 적용)
        if q_num == 4:
            apply_label = f"{dt_obj.year + 1} Q1"
        else:
            apply_label = f"{dt_obj.year} Q{q_num + 1}"

        # 36개월 시작일, 12개월 시작일 계산
        start_36m = (dt_obj - relativedelta(months=36) + relativedelta(days=1)).strftime("%Y-%m-%d")
        start_12m = (dt_obj - relativedelta(months=12) + relativedelta(days=1)).strftime("%Y-%m-%d")

        schedule.append({
            "rebalance_id": apply_label,
            "determination_date": det_date,
            "effective_start": eff_start,
            "effective_end": eff_end,
            "window_36m_start": start_36m,
            "window_12m_start": start_12m,
        })
    return schedule


def select_top50_at_date(trades, universe_map, det_date, window_start, top_n=50, market_basis="krx"):
    """
    특정 기준일(det_date) 시점에 실제 거래 가능한 상장 보통주 중에서
    [window_start, det_date] 기간의 개인 순매수대금(매수대금 - 매도대금) 상위 50개 종목 추출.
    - 생존자 편향 방지: det_date 당시 상장되어 있었고, det_date에 유효 종가가 존재하는 종목 대상
    """
    sub = trades[(trades['date'] >= window_start) & (trades['date'] <= det_date)]
    if sub.empty:
        return pd.DataFrame()

    # det_date 당일(또는 직전 5거래일 내) 실제 상장·거래 기록이 있는 종목 확인 (상장폐지 종목이 이미 폐지된 후면 제외)
    recent_cut = (datetime.strptime(det_date, "%Y-%m-%d") - relativedelta(days=15)).strftime("%Y-%m-%d")
    active_at_det = set(sub[(sub['date'] >= recent_cut) & (sub['reg_close'] > 0)]['code'].unique())

    # 상장폐지일이 det_date 이전이거나 당일인 종목 제외
    valid_codes = set()
    for c in active_at_det:
        u_info = universe_map.get(c)
        if not u_info:
            continue
        del_dt = u_info.get('DelistingDate')
        if pd.notna(del_dt) and str(del_dt)[:10] <= det_date:
            continue
        valid_codes.add(c)

    sub_valid = sub[sub['code'].isin(valid_codes)]

    val_col = 'krx_ind_net_val' if market_basis == 'krx' else 'total_ind_net_val'
    buy_col = 'krx_ind_buy_val'
    sell_col = 'krx_ind_sell_val'
    vol_col = 'krx_ind_net_vol'

    agg = sub_valid.groupby('code', as_index=False).agg(
        net_buy_val=(val_col, 'sum'),
        buy_val=(buy_col, 'sum'),
        sell_val=(sell_col, 'sum'),
        net_buy_vol=(vol_col, 'sum'),
        krx_net_buy_val=('krx_ind_net_val', 'sum'),
        nxt_net_buy_val=('nxt_ind_net_val', 'sum'),
        total_net_buy_val=('total_ind_net_val', 'sum'),
        trading_days=('date', 'count'),
        last_close=('reg_close', 'last')
    )

    # 순매수대금 상위 50개 추출
    top50 = agg.sort_values('net_buy_val', ascending=False).head(top_n).copy()
    top50['rank'] = range(1, len(top50) + 1)
    top50['weight'] = 1.0 / len(top50)
    top50['name'] = top50['code'].map(lambda c: universe_map.get(c, {}).get('Name', c))
    top50['market'] = top50['code'].map(lambda c: universe_map.get(c, {}).get('MarketName', ''))
    top50['industry'] = top50['code'].map(lambda c: universe_map.get(c, {}).get('Industry', ''))
    top50['status'] = top50['code'].map(lambda c: universe_map.get(c, {}).get('Status', 'ACTIVE'))
    return top50.reset_index(drop=True)


def compute_index_series(trades, schedule, holdings_by_q, base_date="2024-09-30", base_val=1000.0):
    """
    분기별 리밸런싱과 일별 수익률(정규장종가 / KRX기준가)을 이용해 연속 지수 시계열 산출.
    - 분기 리밸런싱 시점 동일가중(2.0%)
    - 분기 중 주가 변동에 따른 비중 변화 허용(Buy-and-Hold Drift)
    - 리밸런싱 시 체인링킹(Chain-linking)으로 지수 연속성 보장
    """
    # 필요한 종목들의 일별 수익률 피벗 생성
    all_constituent_codes = set()
    for q_id, df_h in holdings_by_q.items():
        all_constituent_codes.update(df_h['code'].tolist())

    sub_trades = trades[
        (trades['code'].isin(all_constituent_codes)) &
        (trades['date'] >= base_date)
    ].copy()

    # 일별 수익률: base_price > 0 and reg_close > 0 이면 reg_close / base_price, 아니면 1.0
    valid_prc = (sub_trades['base_price'] > 0) & (sub_trades['reg_close'] > 0)
    sub_trades['gross_ret'] = np.where(
        valid_prc,
        sub_trades['reg_close'].astype(float) / sub_trades['base_price'].astype(float),
        1.0
    )
    # 이상치 방어 (상·하한가 ±30% 범위; 신규상장일 등 최대 400%)
    sub_trades['gross_ret'] = sub_trades['gross_ret'].clip(0.3, 4.0)

    ret_pivot = sub_trades.pivot(index='date', columns='code', values='gross_ret').fillna(1.0)
    all_dates = sorted(ret_pivot.index.tolist())

    series_rows = []
    current_index_val = base_val

    # 기준일(2024-09-30) 초기 포인트 기록
    series_rows.append({
        "date": base_date,
        "index_value": round(current_index_val, 2),
        "daily_return_pct": 0.0,
        "rebalance_id": schedule[0]["rebalance_id"],
        "is_rebalance_date": True
    })

    prev_index_val = current_index_val

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

        # 분기 시작 시 각 종목의 상대가치 = 1.0 (동일가중 2%)
        rel_wealth = np.ones(n_stocks, dtype=float)
        q_base_index = current_index_val

        for d_idx, dt in enumerate(q_dates):
            day_gross = np.array([ret_pivot.at[dt, c] if c in ret_pivot.columns else 1.0 for c in codes], dtype=float)
            rel_wealth = rel_wealth * day_gross
            port_rel_val = float(np.sum(init_w * rel_wealth))
            new_index_val = q_base_index * port_rel_val
            daily_ret = (new_index_val / prev_index_val - 1.0) * 100.0

            series_rows.append({
                "date": dt,
                "index_value": round(new_index_val, 2),
                "daily_return_pct": round(daily_ret, 4),
                "rebalance_id": q_id,
                "is_rebalance_date": (d_idx == 0)
            })
            prev_index_val = new_index_val
            current_index_val = new_index_val

    return pd.DataFrame(series_rows)


def main():
    print("데이터 로드 중...")
    universe, trades, bench = load_data()
    universe_map = universe.set_index('Code').to_dict(orient='index')

    trading_dates = sorted(trades['date'].unique().tolist())
    max_date = trading_dates[-1]
    min_date = trading_dates[0]
    print(f"원천 데이터 거래일 범위: {min_date} ~ {max_date} (총 {len(trading_dates)} 거래일)")

    schedule = get_rebalance_schedule(trading_dates)
    print(f"산출 리밸런싱 구간 수: {len(schedule)}개 분기 ({schedule[0]['rebalance_id']} ~ {schedule[-1]['rebalance_id']})")

    gaemi50_holdings = {}
    gaemi50_now_holdings = {}
    rebalance_history = []

    prev_g50_codes = set()
    prev_now_codes = set()

    for q in schedule:
        q_id = q["rebalance_id"]
        det_date = q["determination_date"]
        w36 = q["window_36m_start"]
        w12 = q["window_12m_start"]

        top50_36m = select_top50_at_date(trades, universe_map, det_date, w36, top_n=50, market_basis="krx")
        top50_12m = select_top50_at_date(trades, universe_map, det_date, w12, top_n=50, market_basis="krx")

        gaemi50_holdings[q_id] = top50_36m
        gaemi50_now_holdings[q_id] = top50_12m

        curr_g50_codes = set(top50_36m['code'])
        curr_now_codes = set(top50_12m['code'])

        # 신규 편입 및 퇴출 종목 계산
        if prev_g50_codes:
            g50_added = sorted(list(curr_g50_codes - prev_g50_codes))
            g50_removed = sorted(list(prev_g50_codes - curr_g50_codes))
        else:
            g50_added = []
            g50_removed = []

        if prev_now_codes:
            now_added = sorted(list(curr_now_codes - prev_now_codes))
            now_removed = sorted(list(prev_now_codes - curr_now_codes))
        else:
            now_added = []
            now_removed = []

        overlap_codes = sorted(list(curr_g50_codes & curr_now_codes))
        overlap_rate = len(overlap_codes) / 50.0 * 100.0

        rebalance_history.append({
            **q,
            "gaemi50_Overlap_now_count": len(overlap_codes),
            "gaemi50_overlap_now_pct": round(overlap_rate, 1),
            "gaemi50_added": [
                {"code": c, "name": universe_map.get(c, {}).get("Name", c),
                 "rank": int(top50_36m[top50_36m['code'] == c]['rank'].iloc[0]),
                 "net_buy_val": int(top50_36m[top50_36m['code'] == c]['net_buy_val'].iloc[0])}
                for c in g50_added
            ],
            "gaemi50_removed": [
                {"code": c, "name": universe_map.get(c, {}).get("Name", c)}
                for c in g50_removed
            ],
            "gaemi50_now_added": [
                {"code": c, "name": universe_map.get(c, {}).get("Name", c),
                 "rank": int(top50_12m[top50_12m['code'] == c]['rank'].iloc[0]),
                 "net_buy_val": int(top50_12m[top50_12m['code'] == c]['net_buy_val'].iloc[0])}
                for c in now_added
            ],
            "gaemi50_now_removed": [
                {"code": c, "name": universe_map.get(c, {}).get("Name", c)}
                for c in now_removed
            ],
        })
        prev_g50_codes = curr_g50_codes
        prev_now_codes = curr_now_codes
        print(f"  [{q_id}] 기준일={det_date} | GAEMI50 #1={top50_36m.iloc[0]['name']}({top50_36m.iloc[0]['net_buy_val']/1e8:,.0f}억) | NOW #1={top50_12m.iloc[0]['name']}({top50_12m.iloc[0]['net_buy_val']/1e8:,.0f}억) | 중복률={overlap_rate:.1f}% | 편입/퇴출={len(g50_added)}/{len(g50_removed)}")

    # 지수 시계열 산출
    base_date = schedule[0]["determination_date"]
    df_g50 = compute_index_series(trades, schedule, gaemi50_holdings, base_date=base_date, base_val=1000.0)
    df_now = compute_index_series(trades, schedule, gaemi50_now_holdings, base_date=base_date, base_val=1000.0)

    # 벤치마크 병합 및 1,000 포인트 환산
    merged = pd.merge(
        df_g50.rename(columns={"index_value": "GAEMI_50", "daily_return_pct": "GAEMI_50_ret"}),
        df_now[['date', 'index_value', 'daily_return_pct']].rename(columns={"index_value": "GAEMI_50_NOW", "daily_return_pct": "GAEMI_50_NOW_ret"}),
        on='date',
        how='inner'
    )
    merged = pd.merge(merged, bench, on='date', how='left')
    merged['KOSPI'] = merged['KOSPI'].ffill().bfill()
    merged['KOSDAQ'] = merged['KOSDAQ'].ffill().bfill()

    kospi_base = float(merged.loc[merged['date'] == base_date, 'KOSPI'].iloc[0])
    kosdaq_base = float(merged.loc[merged['date'] == base_date, 'KOSDAQ'].iloc[0])
    merged['KOSPI_norm'] = (merged['KOSPI'] / kospi_base * 1000.0).round(2)
    merged['KOSDAQ_norm'] = (merged['KOSDAQ'] / kosdaq_base * 1000.0).round(2)
    merged['KOSPI_ret'] = (merged['KOSPI'].pct_change().fillna(0.0) * 100.0).round(4)
    merged['KOSDAQ_ret'] = (merged['KOSDAQ'].pct_change().fillna(0.0) * 100.0).round(4)

    merged.to_csv(os.path.join(DATA_DIR, "index_timeseries.csv"), index=False, encoding="utf-8-sig")
    merged.to_parquet(os.path.join(DATA_DIR, "index_timeseries.parquet"), index=False)

    # 현재 적용 중인 분기(마지막 분기)의 구성종목 및 현재 드리프트 비중 계산
    latest_q = schedule[-1]
    latest_qid = latest_q["rebalance_id"]
    latest_g50 = gaemi50_holdings[latest_qid].copy()
    latest_now = gaemi50_now_holdings[latest_qid].copy()

    # 최신 거래일(max_date) 기준 Rolling 36개월 / 12개월 순위도 함께 산출 (최신 데이터 비교용)
    dt_max = datetime.strptime(max_date, "%Y-%m-%d")
    rolling_36m = select_top50_at_date(
        trades, universe_map, max_date,
        (dt_max - relativedelta(months=36) + relativedelta(days=1)).strftime("%Y-%m-%d"),
        top_n=50, market_basis="krx"
    )
    rolling_12m = select_top50_at_date(
        trades, universe_map, max_date,
        (dt_max - relativedelta(months=12) + relativedelta(days=1)).strftime("%Y-%m-%d"),
        top_n=50, market_basis="krx"
    )

    # 현재 분기 시작 이후 각 종목의 수익률 및 현재 비중 계산
    eff_start = latest_q["effective_start"]
    q_sub = trades[(trades['date'] >= eff_start) & (trades['date'] <= max_date)].copy()
    valid_p = (q_sub['base_price'] > 0) & (q_sub['reg_close'] > 0)
    q_sub['g_ret'] = np.where(valid_p, q_sub['reg_close'] / q_sub['base_price'], 1.0).clip(0.3, 4.0)
    cum_ret_by_code = q_sub.groupby('code')['g_ret'].prod().to_dict()
    latest_price_by_code = trades[trades['date'] == max_date].set_index('code')['reg_close'].to_dict()

    for df_curr in [latest_g50, latest_now]:
        df_curr['q_gross_ret'] = df_curr['code'].map(lambda c: float(cum_ret_by_code.get(c, 1.0)))
        df_curr['q_return_pct'] = ((df_curr['q_gross_ret'] - 1.0) * 100.0).round(2)
        total_w = (df_curr['weight'] * df_curr['q_gross_ret']).sum()
        df_curr['current_weight_pct'] = ((df_curr['weight'] * df_curr['q_gross_ret']) / total_w * 100.0).round(2)
        df_curr['current_price'] = df_curr['code'].map(lambda c: int(latest_price_by_code.get(c, 0)))

    latest_g50.to_csv(os.path.join(DATA_DIR, "gaemi50_constituents.csv"), index=False, encoding="utf-8-sig")
    latest_now.to_csv(os.path.join(DATA_DIR, "gaemi50_now_constituents.csv"), index=False, encoding="utf-8-sig")
    rolling_36m.to_csv(os.path.join(DATA_DIR, "rolling_36m_top50.csv"), index=False, encoding="utf-8-sig")
    rolling_12m.to_csv(os.path.join(DATA_DIR, "rolling_12m_top50.csv"), index=False, encoding="utf-8-sig")

    # 전체 분기별 구성종목 이력 저장
    all_q_rows = []
    for q in schedule:
        qid = q["rebalance_id"]
        for idx_name, df_h in [("GAEMI_50", gaemi50_holdings[qid]), ("GAEMI_50_NOW", gaemi50_now_holdings[qid])]:
            tmp = df_h.copy()
            tmp['index_name'] = idx_name
            tmp['rebalance_id'] = qid
            tmp['determination_date'] = q['determination_date']
            all_q_rows.append(tmp)
    df_all_q = pd.concat(all_q_rows, ignore_index=True)
    df_all_q.to_csv(os.path.join(DATA_DIR, "historical_constituents_all_quarters.csv"), index=False, encoding="utf-8-sig")

    # 상위 종목들의 월별/주별 개인 누적 순매수 및 주가 추이 데이터 생성 (웹사이트 인터랙티브 차트 ⑦번용)
    top_union_codes = sorted(list(set(latest_g50['code']) | set(latest_now['code'])))
    w36_start = latest_q["window_36m_start"]
    sub_top = trades[(trades['code'].isin(top_union_codes)) & (trades['date'] >= w36_start)].sort_values(['code', 'date']).copy()

    # 주간(금요일/주말 마지막 거래일) 단위로 압축하여 정적 JSON 경량화 + 정확도 유지
    sub_top['cum_net_buy_eok'] = (sub_top.groupby('code')['krx_ind_net_val'].cumsum() / 1e8).round(1)
    sub_top['cum_total_net_buy_eok'] = (sub_top.groupby('code')['total_ind_net_val'].cumsum() / 1e8).round(1)
    sub_top['ym_week'] = pd.to_datetime(sub_top['date']).dt.to_period('W').astype(str)
    weekly_top = sub_top.groupby(['code', 'ym_week'], as_index=False).last()

    stock_trajectories = {}
    for c in top_union_codes:
        c_df = weekly_top[weekly_top['code'] == c].sort_values('date')
        u_info = universe_map.get(c, {})
        stock_trajectories[c] = {
            "code": c,
            "name": u_info.get("Name", c),
            "market": u_info.get("MarketName", ""),
            "industry": u_info.get("Industry", ""),
            "dates": c_df['date'].tolist(),
            "prices": [int(x) for x in c_df['reg_close'].tolist()],
            "cum_net_buy_eok": [float(x) for x in c_df['cum_net_buy_eok'].tolist()],
            "cum_total_net_buy_eok": [float(x) for x in c_df['cum_total_net_buy_eok'].tolist()],
        }

    # 성과 요약 지표 계산
    last_row = merged.iloc[-1]
    prev_row = merged.iloc[-2]

    def calc_stats(col_val, col_ret):
        vals = merged[col_val].values
        rets = merged[col_ret].values[1:] / 100.0
        total_ret = (vals[-1] / vals[0] - 1.0) * 100.0
        peak = np.maximum.accumulate(vals)
        dd = (vals / peak - 1.0) * 100.0
        mdd = float(np.min(dd))
        ann_vol = float(np.std(rets, ddof=1) * np.sqrt(250) * 100.0) if len(rets) > 1 else 0.0
        return {
            "current": round(float(vals[-1]), 2),
            "daily_change_pt": round(float(vals[-1] - vals[-2]), 2),
            "daily_change_pct": round(float((vals[-1] / vals[-2] - 1.0) * 100.0), 2),
            "total_return_pct": round(float(total_ret), 2),
            "mdd_pct": round(mdd, 2),
            "ann_volatility_pct": round(ann_vol, 2),
            "high": round(float(np.max(vals)), 2),
            "high_date": str(merged.loc[merged[col_val].idxmax(), 'date']),
            "low": round(float(np.min(vals)), 2),
            "low_date": str(merged.loc[merged[col_val].idxmin(), 'date']),
        }

    summary = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_as_of": max_date,
        "base_date": base_date,
        "base_value": 1000.0,
        "index_type": "Price Return Index (가격지수, 배당 미포함·자본금변동 기준가 보정)",
        "market_basis_note": "KRX 정규장 개인 순매수 기준 (2025.03.04 출범한 넥스트레이드 NXT 개인 순매수 별도 병기·비교 제공, 중복 합산 없음)",
        "current_rebalance": rebalance_history[-1],
        "rebalance_history": rebalance_history,
        "metrics": {
            "GAEMI_50": calc_stats("GAEMI_50", "GAEMI_50_ret"),
            "GAEMI_50_NOW": calc_stats("GAEMI_50_NOW", "GAEMI_50_NOW_ret"),
            "KOSPI": calc_stats("KOSPI_norm", "KOSPI_ret"),
            "KOSDAQ": calc_stats("KOSDAQ_norm", "KOSDAQ_ret"),
            "KOSPI_raw": round(float(last_row['KOSPI']), 2),
            "KOSDAQ_raw": round(float(last_row['KOSDAQ']), 2),
        }
    }

    with open(os.path.join(DATA_DIR, "index_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # 웹사이트용 통합 JSON 번들 생성 (정적 사이트에서 즉시 로드 가능하도록)
    web_payload = {
        "summary": summary,
        "audit": json.load(open(os.path.join(DATA_DIR, "audit_summary.json"), encoding="utf-8")),
        "timeseries": merged.to_dict(orient="records"),
        "gaemi50_constituents": latest_g50.to_dict(orient="records"),
        "gaemi50_now_constituents": latest_now.to_dict(orient="records"),
        "rolling_36m_top50": rolling_36m.to_dict(orient="records"),
        "rolling_12m_top50": rolling_12m.to_dict(orient="records"),
        "stock_trajectories": stock_trajectories,
    }
    web_data_dir = os.path.join(BASE_DIR, "docs", "data")
    os.makedirs(web_data_dir, exist_ok=True)
    with open(os.path.join(web_data_dir, "gaemi_data.json"), "w", encoding="utf-8") as f:
        json.dump(web_payload, f, ensure_ascii=False)
    # 또한 글로벌 변수 JS 파일로도 저장하여 file:// 로컬 열람 및 GitHub Pages 모두에서 CORS 없이 즉시 동작하도록 지원
    with open(os.path.join(web_data_dir, "gaemi_data.js"), "w", encoding="utf-8") as f:
        f.write("window.GAEMI_DATA = ")
        json.dump(web_payload, f, ensure_ascii=False)
        f.write(";\n")

    print("\n=== 지수 산출 결과 요약 ===")
    for k in ["GAEMI_50", "GAEMI_50_NOW", "KOSPI", "KOSDAQ"]:
        m = summary["metrics"][k]
        print(f"  {k:14s}: 현재={m['current']:8.2f} ({m['daily_change_pct']:+.2f}%) | 누적수익률={m['total_return_pct']:+.2f}% | MDD={m['mdd_pct']:.2f}% | 변동성={m['ann_volatility_pct']:.2f}%")


if __name__ == "__main__":
    main()
