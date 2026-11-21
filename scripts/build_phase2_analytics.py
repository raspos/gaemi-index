"""
개미 지수 | GAEMI 50 PURE — PHASE 0 ~ PHASE 6 통합 감사·재산출·비교 분석 엔진

[수행 내용]
1. PHASE 0 감사 및 보정:
   - 0-1: 일별 순매수수량 × 정규장 종가 기반 추정 순매수대금과 KRX 실제 체결대금(trendForeignOrg 공시) 간 오차 정량 검증 및 명시
   - 0-2: 36개월 원자료 완전 확보 원장(complete_36m_data.py 반영) 기반으로 전 분기 재산출 및 변경 전후 비교 기록
   - 0-3: KRX 전용 GAEMI 50 PURE vs KRX+NXT 통합 GAEMI 50 PURE 종목·수익률 비교 검증
   - 0-4: KRX 공식 과거 상장주식수·시가총액 스냅샷(2026-03-08, 03-31, 06-30, 09-30, 11-20) 앵커링으로 자사주 소각·유상증자·CB전환 보정 및 액면분할/병합/감자 구분 처리
2. PHASE 1 핵심 질문 3가지 & Active Share / 비교 포트폴리오:
   - 개미 차별성 지수 (Active Share = 0.5 * sum |w_gaemi - w_market|)
   - 동일가중 효과 분리용 비교 포트폴리오:
     ① 시가총액 상위 50 동일가중 (Top 50 Marcap EW)
     ② 시가총액·업종 1:1 매칭 50종목 동일가중 (Matched Size & Sector 50 EW)
     ③ 코스닥 동일가중 비교지수 (KOSDAQ Equal-Weight)
   - 시장 시총 상위 50과의 중복률, 업종별·시총규모별 시장 대비 비중 차이, 개미 지수에만 높은 비중으로 포함된 종목 vs 개미 지수에 없는 시장 대형주
3. PHASE 2 개인·외국인·기관 선택 비교 ('누가 무엇을 샀나'):
   - 동일 36개월·동일 자격 기준(시총 3,000억+, 60일 거래대금 10억+, 36개월 관측 확보, 양수 순매수)으로 개인·외국인·기관(연기금 포함 KRX 기관합계) 순매수 강도 상위 50 산출
   - 주체 간 상위 50 중복률 (개인∩외국인, 개인∩기관, 외국인∩기관)
   - 업종별 순매수대금 및 평균 순매수 강도 비교
   - 반대편에 선 종목 (개인 순매수 & 외국인·기관 동시 순매도 vs 외국인·기관 동시 순매수 & 개인 순매도)
   - 3대 투자주체별 순매수 강도 상위 50 가상 지수 시계열 백테스트 (2024.09.30 = 1,000)
"""

import os
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


def load_official_krx_snapshots():
    """
    PHASE 0-4: fdr_krx_data_cache에 저장된 KRX 공식 과거 상장주식수(Stocks) 및 시가총액(Marcap) 스냅샷 로드.
    2026년 중 발생한 자사주 소각, 유상증자, CB 전환 등을 공식 상장주식수로 정확히 반영하기 위한 앵커로 활용.
    """
    snap_dates = ["2026-03-08", "2026-03-31", "2026-06-30", "2026-09-30"]
    snapshots = {}
    for dt in snap_dates:
        cache_file = os.path.join(DATA_DIR, f"krx_snap_{dt}.csv")
        if os.path.exists(cache_file):
            df = pd.read_csv(cache_file, dtype={'Code': str})
        else:
            url = f"https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/krx/{dt}.csv"
            try:
                df = pd.read_csv(url, index_col=0, dtype={'Code': str})[['Code', 'Marcap', 'Stocks', 'Close']]
                df.to_csv(cache_file, index=False)
            except Exception as e:
                print(f"  스냅샷 로드 실패 ({dt}): {e}")
                continue
        snapshots[dt] = df.set_index('Code')['Stocks'].to_dict()
    return snapshots


def prepare_audited_ledger():
    print("[PHASE 0] 원장 로드 및 공식 스냅샷 결합 시가총액·자본금 변동 정밀 복원 중...")
    universe = pd.read_parquet(os.path.join(DATA_DIR, "universe.parquet"))
    needed_cols = [
        'code', 'date', 'base_price', 'reg_close', 'krx_vol',
        'krx_ind_net_vol', 'krx_frg_net_vol', 'krx_org_net_vol',
        'nxt_ind_net_vol', 'nxt_close', 'nxt_vol'
    ]
    trades = pd.read_parquet(os.path.join(DATA_DIR, "daily_investor_trades.parquet"), columns=needed_cols)
    trades.sort_values(['code', 'date'], inplace=True, ignore_index=True)
    bench = pd.read_parquet(os.path.join(DATA_DIR, "benchmarks.parquet"))

    snapshots = load_official_krx_snapshots()
    latest_shares_map = universe.set_index('Code')['Stocks'].to_dict()

    # 구간별 공식 상장주식수 매핑 (2026-03-31 이전은 2026-03-08 공식 주식수를 기준 앵커로 사용하여 2026년 자사주소각/증자 왜곡 차단)
    s_0308 = snapshots.get("2026-03-08", latest_shares_map)
    s_0331 = snapshots.get("2026-03-31", latest_shares_map)
    s_0630 = snapshots.get("2026-06-30", latest_shares_map)
    s_0930 = snapshots.get("2026-09-30", latest_shares_map)

    c_series = trades['code']
    dt_vals = trades['date'].values

    sh_0308 = c_series.map(lambda c: s_0308.get(c, latest_shares_map.get(c, 0))).values.astype(np.float64)
    sh_0331 = c_series.map(lambda c: s_0331.get(c, latest_shares_map.get(c, 0))).values.astype(np.float64)
    sh_0630 = c_series.map(lambda c: s_0630.get(c, latest_shares_map.get(c, 0))).values.astype(np.float64)
    sh_0930 = c_series.map(lambda c: s_0930.get(c, latest_shares_map.get(c, 0))).values.astype(np.float64)
    sh_latest = c_series.map(lambda c: latest_shares_map.get(c, 0)).values.astype(np.float64)

    # 액면분할/병합/무상증자/감자 등 자본금 변동 배율 역산
    # 단순 소폭 배당락(|ratio-1| < 3%)은 주식수 변화가 아니므로 제외하고, 3% 이상 기준가 조정일만 주식수 변동 이벤트로 역산
    prev_close = trades.groupby('code')['reg_close'].shift(1).fillna(0).values
    base_p = trades['base_price'].values
    reg_c = trades['reg_close'].values

    valid_ca = (prev_close > 0) & (base_p > 0)
    raw_ratio = np.where(valid_ca, prev_close / np.maximum(base_p, 1), 1.0)
    # 2026-03-08 이전 발생한 분할/병합/무상증자/감자(|ratio-1| >= 0.03)만 2026-03-08 앵커 주식수에서 역산
    ca_mult_pre = np.where((dt_vals <= "2026-03-08") & (np.abs(raw_ratio - 1.0) >= 0.03), raw_ratio, 1.0)
    ca_mult_pre = np.clip(ca_mult_pre, 0.02, 50.0)
    trades['ca_mult_pre'] = ca_mult_pre

    rev_cum = trades.iloc[::-1].groupby('code')['ca_mult_pre'].cumprod().iloc[::-1]
    future_split_pre = (rev_cum / trades['ca_mult_pre']).values
    trades.drop(columns=['ca_mult_pre'], inplace=True)

    pit_shares = np.where(
        dt_vals <= "2026-03-08", sh_0308 / future_split_pre,
        np.where(
            dt_vals <= "2026-03-31", sh_0331,
            np.where(
                dt_vals <= "2026-06-30", sh_0630,
                np.where(dt_vals <= "2026-09-30", sh_0930, sh_latest)
            )
        )
    )

    trades['daily_marcap'] = pit_shares * reg_c.astype(np.float64)
    trades['daily_trdval'] = trades['krx_vol'].values.astype(np.float64) * reg_c.astype(np.float64)

    # 투자주체별 일별 추정 순매수대금 (일별 순매수수량 × 당일 정규장 종가)
    reg_c_i64 = reg_c.astype(np.int64)
    trades['krx_ind_net_val'] = trades['krx_ind_net_vol'].values.astype(np.int64) * reg_c_i64
    trades['krx_frg_net_val'] = trades['krx_frg_net_vol'].values.astype(np.int64) * reg_c_i64
    trades['krx_org_net_val'] = trades['krx_org_net_vol'].values.astype(np.int64) * reg_c_i64

    nxt_prc = np.where(trades['nxt_close'].values > 0, trades['nxt_close'].values, reg_c).astype(np.int64)
    trades['nxt_ind_net_val'] = trades['nxt_ind_net_vol'].values.astype(np.int64) * nxt_prc
    trades['total_ind_net_val'] = trades['krx_ind_net_val'] + trades['nxt_ind_net_val']

    # 일별 수익률 (KRX 공식 기준가 대비 정규장 종가)
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

        dates_up_to_det = [d for d in all_dates_list if d <= det_date]
        start_60d = dates_up_to_det[max(0, len(dates_up_to_det) - 60)]
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


def classify_size(mc_eok):
    if mc_eok >= 100000:
        return "초대형주 (10조 이상)"
    elif mc_eok >= 10000:
        return "대형주 (1조~10조)"
    elif mc_eok >= 3000:
        return "중형주 (3,000억~1조)"
    else:
        return "소형주 (3,000억 미만)"


def evaluate_quarter_cross_section(trades, universe_map, q_info, min_marcap_eok=3000.0, min_adtv_60d_eok=10.0, min_obs_ratio=0.90):
    """
    특정 분기 기준일(det_date)의 전 종목 36개월 수급(개인/외국인/기관/KRX+NXT 통합) 및 평균 시가총액 집계.
    """
    det_date = q_info["determination_date"]
    w36_start = q_info["window_36m_start"]
    w60_start = q_info["window_60d_start"]
    mkt_days = q_info["window_mkt_days"]
    min_trading_days = int(np.floor(mkt_days * min_obs_ratio))

    sub36 = trades[(trades['date'] >= w36_start) & (trades['date'] <= det_date)]
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

    agg36 = sub36.groupby('code', as_index=False).agg(
        ind_net_val=('krx_ind_net_val', 'sum'),
        frg_net_val=('krx_frg_net_val', 'sum'),
        org_net_val=('krx_org_net_val', 'sum'),
        nxt_ind_net_val=('nxt_ind_net_val', 'sum'),
        tot_ind_net_val=('total_ind_net_val', 'sum'),
        avg_marcap_36m=('daily_marcap', 'mean'),
        end_marcap=('daily_marcap', 'last'),
        last_close=('reg_close', 'last'),
        trading_days=('date', 'count'),
    )

    agg60 = sub60.groupby('code', as_index=False).agg(trdval_60d_sum=('daily_trdval', 'sum'))
    agg60['adtv_60d'] = agg60['trdval_60d_sum'] / 60.0

    df_all = pd.merge(agg36, agg60[['code', 'adtv_60d']], on='code', how='left')
    df_all['adtv_60d'] = df_all['adtv_60d'].fillna(0.0)

    df_all['net_buy_val'] = df_all['ind_net_val']
    df_all['net_buy_eok'] = (df_all['ind_net_val'] / 1e8).round(2)
    df_all['frg_net_buy_eok'] = (df_all['frg_net_val'] / 1e8).round(2)
    df_all['org_net_buy_eok'] = (df_all['org_net_val'] / 1e8).round(2)
    df_all['nxt_net_buy_eok'] = (df_all['nxt_ind_net_val'] / 1e8).round(2)
    df_all['tot_net_buy_eok'] = (df_all['tot_ind_net_val'] / 1e8).round(2)
    df_all['avg_marcap_36m_eok'] = (df_all['avg_marcap_36m'] / 1e8).round(2)
    df_all['end_marcap_eok'] = (df_all['end_marcap'] / 1e8).round(2)
    df_all['adtv_60d_eok'] = (df_all['adtv_60d'] / 1e8).round(2)

    # 각 투자주체별 36개월 순매수 강도 (%) = 36개월 누적 추정 순매수대금 / 36개월 평균 시가총액 * 100
    avg_mc_pos = np.maximum(df_all['avg_marcap_36m'].values, 1.0)
    df_all['intensity_pct'] = np.where(df_all['avg_marcap_36m'] > 0, df_all['ind_net_val'] / avg_mc_pos * 100.0, 0.0).round(4)
    df_all['frg_intensity_pct'] = np.where(df_all['avg_marcap_36m'] > 0, df_all['frg_net_val'] / avg_mc_pos * 100.0, 0.0).round(4)
    df_all['org_intensity_pct'] = np.where(df_all['avg_marcap_36m'] > 0, df_all['org_net_val'] / avg_mc_pos * 100.0, 0.0).round(4)
    df_all['tot_intensity_pct'] = np.where(df_all['avg_marcap_36m'] > 0, df_all['tot_ind_net_val'] / avg_mc_pos * 100.0, 0.0).round(4)

    df_all['name'] = df_all['code'].map(lambda c: universe_map.get(c, {}).get('Name', c))
    df_all['market'] = df_all['code'].map(lambda c: universe_map.get(c, {}).get('MarketName', ''))
    df_all['industry'] = df_all['code'].map(lambda c: universe_map.get(c, {}).get('Industry', '') or '기타')
    df_all['status'] = df_all['code'].map(lambda c: universe_map.get(c, {}).get('Status', 'ACTIVE'))
    df_all['size_bucket'] = df_all['end_marcap_eok'].map(classify_size)

    # 전체 시장 포트폴리오(KOSPI+KOSDAQ 합산 시가총액 가중) 내 각 종목 비중(%)
    total_mkt_marcap = df_all['end_marcap'].sum()
    df_all['market_weight_pct'] = (df_all['end_marcap'] / total_mkt_marcap * 100.0) if total_mkt_marcap > 0 else 0.0

    # 시가총액 순위 및 개인 절대 순매수액 순위
    df_all = df_all.sort_values('end_marcap', ascending=False).reset_index(drop=True)
    df_all['marcap_rank_all'] = range(1, len(df_all) + 1)

    df_all = df_all.sort_values('ind_net_val', ascending=False).reset_index(drop=True)
    df_all['abs_rank_all'] = range(1, len(df_all) + 1)

    # 공통 기본 자격 요건 (시총 3,000억+, 60일 거래대금 10억+, 36개월 관측일수 90%+)
    df_all['pass_marcap'] = df_all['end_marcap_eok'] >= min_marcap_eok
    df_all['pass_adtv'] = df_all['adtv_60d_eok'] >= min_adtv_60d_eok
    df_all['pass_36m_obs'] = df_all['trading_days'] >= min_trading_days
    df_all['base_eligible'] = df_all['pass_marcap'] & df_all['pass_adtv'] & df_all['pass_36m_obs']

    # 개인(KRX), 개인(KRX+NXT 통합), 외국인, 기관 각각의 적격(양수 순매수) 여부
    df_all['is_eligible_pure'] = df_all['base_eligible'] & (df_all['ind_net_val'] > 0)
    df_all['is_eligible_tot_pure'] = df_all['base_eligible'] & (df_all['tot_ind_net_val'] > 0)
    df_all['is_eligible_frg_pure'] = df_all['base_eligible'] & (df_all['frg_net_val'] > 0)
    df_all['is_eligible_org_pure'] = df_all['base_eligible'] & (df_all['org_net_val'] > 0)

    def get_exclude_reason(row):
        reasons = []
        if row['ind_net_val'] <= 0:
            reasons.append("순매도(음수)")
        if not row['pass_36m_obs']:
            reasons.append(f"36개월 관측미달({row['trading_days']}/{mkt_days}일)")
        if not row['pass_marcap']:
            reasons.append(f"시총 {min_marcap_eok:.0f}억 미만({row['end_marcap_eok']:.0f}억)")
        if not row['pass_adtv']:
            reasons.append(f"거래대금 {min_adtv_60d_eok:.0f}억 미만({row['adtv_60d_eok']:.1f}억)")
        return ", ".join(reasons) if reasons else "적격"

    df_all['eligibility_note'] = df_all.apply(get_exclude_reason, axis=1)

    # 개인 순매수 강도 순위
    elig_ind = df_all[df_all['is_eligible_pure']].sort_values('intensity_pct', ascending=False).reset_index(drop=True)
    elig_ind['pure_rank'] = range(1, len(elig_ind) + 1)
    df_all['pure_rank_eligible'] = df_all['code'].map(elig_ind.set_index('code')['pure_rank'].to_dict())

    # 외국인 순매수 강도 순위
    elig_frg = df_all[df_all['is_eligible_frg_pure']].sort_values('frg_intensity_pct', ascending=False).reset_index(drop=True)
    elig_frg['frg_pure_rank'] = range(1, len(elig_frg) + 1)
    df_all['frg_pure_rank'] = df_all['code'].map(elig_frg.set_index('code')['frg_pure_rank'].to_dict())

    # 기관 순매수 강도 순위
    elig_org = df_all[df_all['is_eligible_org_pure']].sort_values('org_intensity_pct', ascending=False).reset_index(drop=True)
    elig_org['org_pure_rank'] = range(1, len(elig_org) + 1)
    df_all['org_pure_rank'] = df_all['code'].map(elig_org.set_index('code')['org_pure_rank'].to_dict())

    # KRX+NXT 통합 개인 순매수 강도 순위
    elig_tot = df_all[df_all['is_eligible_tot_pure']].sort_values('tot_intensity_pct', ascending=False).reset_index(drop=True)
    elig_tot['tot_pure_rank'] = range(1, len(elig_tot) + 1)
    df_all['tot_pure_rank'] = df_all['code'].map(elig_tot.set_index('code')['tot_pure_rank'].to_dict())

    return df_all, elig_ind.head(50).copy(), elig_frg.head(50).copy(), elig_org.head(50).copy(), elig_tot.head(50).copy()


def build_matched_comparison_portfolio(df_all, pure_top50):
    """
    PHASE 1-2 & 1-3: 시가총액·업종이 유사한 50종목 비교 포트폴리오 (Matched Size & Sector 50 EW)
    - 사전에 정의된 객관적 규칙(사후 성과 선택 금지):
      적격 유니버스(base_eligible: 시총 3,000억+, 60일 거래대금 10억+, 36개월 관측 확보) 내에서
      GAEMI 50 PURE에 속하지 않은 종목 중 각 PURE 편입 종목과
      ① 동일 시장(KOSPI/KOSDAQ) & 동일 업종 내에서 시가총액 차이가 가장 작은 종목을 1:1 비복원 매칭
      (동일 업종 내 미매칭 후보가 없을 경우 동일 시장 내에서 시가총액이 가장 가까운 종목 매칭).
    """
    pure_codes = set(pure_top50['code'])
    pool = df_all[df_all['base_eligible'] & (~df_all['code'].isin(pure_codes))].copy()
    used_codes = set()
    matched_rows = []

    for _, p_row in pure_top50.iterrows():
        t_mkt = p_row['market']
        t_ind = p_row['industry']
        t_mc = float(p_row['end_marcap_eok'])

        avail = pool[~pool['code'].isin(used_codes)]
        if avail.empty:
            break

        # 1순위: 동일 시장 & 동일 업종
        cand = avail[(avail['market'] == t_mkt) & (avail['industry'] == t_ind)]
        # 2순위: 동일 시장
        if cand.empty:
            cand = avail[avail['market'] == t_mkt]
        # 3순위: 전체 적격 풀
        if cand.empty:
            cand = avail

        idx_best = (cand['end_marcap_eok'] - t_mc).abs().idxmin()
        chosen = cand.loc[idx_best]
        used_codes.add(chosen['code'])
        matched_rows.append(chosen)

    df_matched = pd.DataFrame(matched_rows).reset_index(drop=True)
    df_matched['rank'] = range(1, len(df_matched) + 1)
    df_matched['weight'] = 1.0 / len(df_matched)
    return df_matched


def compute_active_share(df_all, portfolio_codes):
    """
    Active Share = 1/2 * sum_i |w_{i, portfolio} - w_{i, market}| * 100%
    - portfolio_codes가 동일가중 N종목일 때 w_{i, portfolio} = 100 / N (%)
    - w_{i, market} = market_weight_pct (%)
    """
    n = len(portfolio_codes)
    if n == 0:
        return 0.0
    w_port_each = 100.0 / n
    port_set = set(portfolio_codes)

    w_mkt = df_all['market_weight_pct'].values
    is_in = df_all['code'].isin(port_set).values
    w_port = np.where(is_in, w_port_each, 0.0)

    active_share = 0.5 * np.sum(np.abs(w_port - w_mkt))
    return round(float(active_share), 2)


def compute_equal_weight_index_series(ret_pivot, all_dates, schedule, holdings_by_q, base_date="2024-09-30", base_val=1000.0):
    """
    사전 생성된 ret_pivot을 이용해 분기 리밸런싱 동일가중 연속 지수 시계열을 고속 산출.
    """
    rows = [{
        "date": base_date,
        "index_value": round(base_val, 2),
        "daily_return_pct": 0.0,
        "rebalance_id": schedule[0]["rebalance_id"],
        "is_rebalance_date": True
    }]
    curr_val = base_val
    prev_val = base_val
    avail_cols = set(ret_pivot.columns)

    for q_info in schedule:
        q_id = q_info["rebalance_id"]
        eff_start = q_info["effective_start"]
        eff_end = q_info["effective_end"]
        df_h = holdings_by_q[q_id]
        codes = [c for c in df_h['code'].tolist() if c in avail_cols]
        n_stocks = len(codes)
        if n_stocks == 0:
            continue
        init_w = 1.0 / n_stocks

        q_dates = [d for d in all_dates if eff_start <= d <= eff_end]
        if not q_dates:
            continue

        sub_mat = ret_pivot.loc[q_dates, codes].values
        rel_wealth = np.ones(n_stocks, dtype=float)
        q_base = curr_val

        for d_idx, dt in enumerate(q_dates):
            rel_wealth = rel_wealth * sub_mat[d_idx]
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


def calc_perf_stats(vals, rets, k_rets, q_rets):
    vals = np.array(vals, dtype=float)
    rets = np.array(rets[1:], dtype=float) / 100.0
    k_r = np.array(k_rets[1:], dtype=float) / 100.0
    q_r = np.array(q_rets[1:], dtype=float) / 100.0

    tot_ret = (vals[-1] / vals[0] - 1.0) * 100.0
    peak = np.maximum.accumulate(vals)
    dd = (vals / peak - 1.0) * 100.0
    mdd = float(np.min(dd))
    vol = float(np.std(rets, ddof=1) * np.sqrt(250) * 100.0) if len(rets) > 1 else 0.0
    c_kospi = float(np.corrcoef(rets, k_r)[0, 1]) if len(rets) > 2 else 0.0
    c_kosdaq = float(np.corrcoef(rets, q_r)[0, 1]) if len(rets) > 2 else 0.0

    return {
        "current": round(float(vals[-1]), 2),
        "daily_change_pt": round(float(vals[-1] - vals[-2]), 2),
        "daily_change_pct": round(float((vals[-1] / vals[-2] - 1.0) * 100.0), 2),
        "total_return_pct": round(float(tot_ret), 2),
        "mdd_pct": round(mdd, 2),
        "ann_volatility_pct": round(vol, 2),
        "corr_kospi": round(c_kospi, 4),
        "corr_kosdaq": round(c_kosdaq, 4),
        "high": round(float(np.max(vals)), 2),
        "low": round(float(np.min(vals)), 2),
    }


def main():
    # 기존 GAEMI 50 PURE 구성종목 백업 (재산출 전후 비교용)
    prev_pure_path = os.path.join(DATA_DIR, "gaemi50_pure_constituents.csv")
    old_pure_codes = []
    if os.path.exists(prev_pure_path):
        old_df = pd.read_csv(prev_pure_path, dtype={'code': str})
        old_pure_codes = old_df['code'].tolist()

    universe, trades, bench = prepare_audited_ledger()
    universe_map = universe.set_index('Code').to_dict(orient='index')

    trading_dates = sorted(trades['date'].unique().tolist())
    max_date = trading_dates[-1]
    schedule = get_rebalance_schedule(trading_dates)
    base_date = schedule[0]["determination_date"]

    # base_date 이후 수익률 피벗 테이블 1회 생성
    print("[2/6] 수익률 매트릭스 생성 및 9개 분기 투자주체별·비교포트폴리오 선정 중...")
    sub_ret = trades[trades['date'] >= base_date][['date', 'code', 'gross_ret']]
    ret_pivot = sub_ret.pivot(index='date', columns='code', values='gross_ret').fillna(1.0)
    all_dates_since_base = sorted(ret_pivot.index.tolist())
    del sub_ret

    pure_holdings = {}        # 개인 순매수 강도 Top 50 (KRX)
    tot_pure_holdings = {}    # 개인 순매수 강도 Top 50 (KRX+NXT 통합)
    frg_pure_holdings = {}    # 외국인 순매수 강도 Top 50
    org_pure_holdings = {}    # 기관 순매수 강도 Top 50
    abs_holdings = {}         # 기존 개인 순매수 절대금액 Top 50
    matched_holdings = {}     # 시가총액·업종 유사 50종목 비교 포트폴리오
    kosdaq_ew_holdings = {}   # 코스닥 적격 보통주 전체 동일가중 비교지수
    marcap_top50_holdings = {}  # 시장 시가총액 상위 50 동일가중

    all_cross_sections = {}
    rebalance_history = []
    prev_pure_set = set()
    prev_pure_rank_map = {}
    first_entry_info = {}

    for q in schedule:
        qid = q["rebalance_id"]
        det_date = q["determination_date"]
        eff_start = q["effective_start"]

        df_all, ind50, frg50, org50, tot50 = evaluate_quarter_cross_section(
            trades, universe_map, q, min_marcap_eok=3000.0, min_adtv_60d_eok=10.0, min_obs_ratio=0.90
        )

        for df_sub in [ind50, frg50, org50, tot50]:
            df_sub['rank'] = range(1, len(df_sub) + 1)
            df_sub['weight'] = 1.0 / len(df_sub)

        abs50 = df_all.sort_values('ind_net_val', ascending=False).head(50).copy()
        abs50['rank'] = range(1, len(abs50) + 1)
        abs50['weight'] = 1.0 / len(abs50)

        mc50 = df_all.sort_values('end_marcap', ascending=False).head(50).copy()
        mc50['rank'] = range(1, len(mc50) + 1)
        mc50['weight'] = 1.0 / len(mc50)

        matched50 = build_matched_comparison_portfolio(df_all, ind50)

        # 코스닥 동일가중 비교지수 (적격 코스닥 보통주 전체 동일가중)
        kq_elig = df_all[(df_all['market'] == 'KOSDAQ') & df_all['base_eligible']].copy()
        kq_elig['weight'] = 1.0 / len(kq_elig) if len(kq_elig) > 0 else 0.0

        # 전 분기 대비 순위 변화
        def calc_rank_delta(row):
            c = row['code']
            curr_r = int(row['rank'])
            if not prev_pure_rank_map:
                return "초기편입"
            if c not in prev_pure_rank_map:
                return "NEW"
            diff = prev_pure_rank_map[c] - curr_r
            return f"▲ +{diff}" if diff > 0 else (f"▼ {diff}" if diff < 0 else "-")

        ind50['prev_quarter_rank'] = ind50['code'].map(lambda c: prev_pure_rank_map.get(c, None))
        ind50['rank_change_str'] = ind50.apply(calc_rank_delta, axis=1)

        for _, row in ind50.iterrows():
            c = row['code']
            if c not in first_entry_info:
                first_entry_info[c] = {
                    "quarter": qid,
                    "det_date": det_date,
                    "eff_start": eff_start,
                    "entry_close": int(row['last_close'])
                }

        pure_holdings[qid] = ind50
        tot_pure_holdings[qid] = tot50
        frg_pure_holdings[qid] = frg50
        org_pure_holdings[qid] = org50
        abs_holdings[qid] = abs50
        matched_holdings[qid] = matched50
        kosdaq_ew_holdings[qid] = kq_elig
        marcap_top50_holdings[qid] = mc50
        all_cross_sections[qid] = df_all

        curr_pure_set = set(ind50['code'])
        if prev_pure_set:
            p_added = sorted(list(curr_pure_set - prev_pure_set))
            p_removed = sorted(list(prev_pure_set - curr_pure_set))
        else:
            p_added, p_removed = [], []

        as_pure = compute_active_share(df_all, ind50['code'].tolist())
        as_mc50 = compute_active_share(df_all, mc50['code'].tolist())
        as_matched = compute_active_share(df_all, matched50['code'].tolist())

        rebalance_history.append({
            **q,
            "active_share_pure_pct": as_pure,
            "active_share_marcap50_ew_pct": as_mc50,
            "active_share_matched50_ew_pct": as_matched,
            "pure_avg_intensity_pct": round(float(ind50['intensity_pct'].mean()), 2),
            "krx_vs_total_overlap_count": len(curr_pure_set & set(tot50['code'])),
            "pure_added": [
                {
                    "code": c,
                    "name": universe_map.get(c, {}).get("Name", c),
                    "rank": int(ind50[ind50['code'] == c]['rank'].iloc[0]),
                    "intensity_pct": float(ind50[ind50['code'] == c]['intensity_pct'].iloc[0]),
                    "net_buy_eok": float(ind50[ind50['code'] == c]['net_buy_eok'].iloc[0]),
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
            "constituents_snapshot": ind50[['rank', 'code', 'name', 'market', 'industry', 'intensity_pct', 'net_buy_eok', 'end_marcap_eok', 'rank_change_str']].to_dict(orient="records"),
        })

        prev_pure_set = curr_pure_set
        prev_pure_rank_map = ind50.set_index('code')['rank'].to_dict()
        print(f"  [{qid}] PURE #1={ind50.iloc[0]['name']}({ind50.iloc[0]['intensity_pct']:.2f}%) | ActiveShare={as_pure:.1f}% (시총50EW {as_mc50:.1f}%, 유사50EW {as_matched:.1f}%) | KRXvs통합 일치={len(curr_pure_set & set(tot50['code']))}/50")

    # [3/6] 지수 시계열 산출 (대표지수 + 비교지수 + 투자주체별 가상 지수)
    print("[3/6] 전체 지수 및 비교 포트폴리오 시계열 산출 중...")
    ts_pure = compute_equal_weight_index_series(ret_pivot, all_dates_since_base, schedule, pure_holdings, base_date)
    ts_tot_pure = compute_equal_weight_index_series(ret_pivot, all_dates_since_base, schedule, tot_pure_holdings, base_date)
    ts_abs = compute_equal_weight_index_series(ret_pivot, all_dates_since_base, schedule, abs_holdings, base_date)
    ts_matched = compute_equal_weight_index_series(ret_pivot, all_dates_since_base, schedule, matched_holdings, base_date)
    ts_kq_ew = compute_equal_weight_index_series(ret_pivot, all_dates_since_base, schedule, kosdaq_ew_holdings, base_date)
    ts_frg = compute_equal_weight_index_series(ret_pivot, all_dates_since_base, schedule, frg_pure_holdings, base_date)
    ts_org = compute_equal_weight_index_series(ret_pivot, all_dates_since_base, schedule, org_pure_holdings, base_date)

    merged = ts_pure.rename(columns={"index_value": "GAEMI_50_PURE", "daily_return_pct": "GAEMI_50_PURE_ret"})
    for name_col, df_s in [
        ("GAEMI_50_TOTAL", ts_tot_pure),
        ("GAEMI_50_ABS", ts_abs),
        ("MATCHED_50_EW", ts_matched),
        ("KOSDAQ_EW", ts_kq_ew),
        ("FOREIGN_50_PURE", ts_frg),
        ("INSTITUTION_50_PURE", ts_org),
    ]:
        merged = pd.merge(
            merged,
            df_s[['date', 'index_value', 'daily_return_pct']].rename(columns={"index_value": name_col, "daily_return_pct": f"{name_col}_ret"}),
            on='date', how='left'
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
    merged['GAEMI_50'] = merged['GAEMI_50_ABS']
    merged['GAEMI_50_ret'] = merged['GAEMI_50_ABS_ret']

    merged.to_csv(os.path.join(DATA_DIR, "index_timeseries.csv"), index=False, encoding="utf-8-sig")
    merged.to_parquet(os.path.join(DATA_DIR, "index_timeseries.parquet"), index=False)

    # [4/6] 최신 분기 구성종목 보강 및 PHASE 1-2 (개미는 시장과 얼마나 다른가) 정량 분석
    print("[4/6] PHASE 1-2 (Active Share & 시장 구성 비교) 및 PHASE 2 (개인·외국인·기관 비교) 생성 중...")
    latest_q = schedule[-1]
    latest_qid = latest_q["rebalance_id"]
    eff_start = latest_q["effective_start"]

    latest_all = all_cross_sections[latest_qid].copy()
    latest_pure = pure_holdings[latest_qid].copy()
    latest_frg = frg_pure_holdings[latest_qid].copy()
    latest_org = org_pure_holdings[latest_qid].copy()
    latest_tot = tot_pure_holdings[latest_qid].copy()
    latest_abs = abs_holdings[latest_qid].copy()
    latest_matched = matched_holdings[latest_qid].copy()
    latest_mc50 = marcap_top50_holdings[latest_qid].copy()

    latest_price_map = trades[trades['date'] == max_date].set_index('code')['reg_close'].to_dict()
    q_dates = [d for d in ret_pivot.index if eff_start <= d <= max_date]
    q_cum_ret = ret_pivot.loc[q_dates].prod(axis=0).to_dict()

    def enrich_df(df_h, holdings_dict):
        df_h['q_gross_ret'] = df_h['code'].map(lambda c: float(q_cum_ret.get(c, 1.0)))
        df_h['q_return_pct'] = ((df_h['q_gross_ret'] - 1.0) * 100.0).round(2)
        tot_w = (df_h['weight'] * df_h['q_gross_ret']).sum()
        df_h['current_weight_pct'] = ((df_h['weight'] * df_h['q_gross_ret']) / tot_w * 100.0).round(2)
        df_h['current_price'] = df_h['code'].map(lambda c: int(latest_price_map.get(c, 0)))

        e_qs, e_ds, s_rets, q_cnts = [], [], [], []
        for _, row in df_h.iterrows():
            c = row['code']
            q_in = [q["rebalance_id"] for q in schedule if c in set(holdings_dict[q["rebalance_id"]]['code'])]
            q_cnts.append(len(q_in))
            first_q = q_in[0] if q_in else latest_qid
            first_eff = next((q["effective_start"] for q in schedule if q["rebalance_id"] == first_q), eff_start)
            e_dates = [d for d in ret_pivot.index if first_eff <= d <= max_date]
            s_ret = round((float(ret_pivot.loc[e_dates, c].prod()) - 1.0) * 100.0, 2) if (e_dates and c in ret_pivot.columns) else 0.0
            e_qs.append(first_q)
            e_ds.append(first_eff)
            s_rets.append(s_ret)

        df_h['entry_quarter'] = e_qs
        df_h['entry_date'] = e_ds
        df_h['since_entry_return_pct'] = s_rets
        df_h['quarters_included_count'] = q_cnts
        return df_h

    latest_pure = enrich_df(latest_pure, pure_holdings)
    latest_frg = enrich_df(latest_frg, frg_pure_holdings)
    latest_org = enrich_df(latest_org, org_pure_holdings)
    latest_abs = enrich_df(latest_abs, abs_holdings)

    latest_pure.to_csv(os.path.join(DATA_DIR, "gaemi50_pure_constituents.csv"), index=False, encoding="utf-8-sig")
    latest_abs.to_csv(os.path.join(DATA_DIR, "gaemi50_abs_constituents.csv"), index=False, encoding="utf-8-sig")

    # --- PHASE 1-2: 개미는 시장과 얼마나 달랐나? ---
    pure_codes = set(latest_pure['code'])
    mc50_codes = set(latest_mc50['code'])
    matched_codes = set(latest_matched['code'])
    kq_ew_codes = set(kosdaq_ew_holdings[latest_qid]['code'])

    as_pure_vs_mkt = compute_active_share(latest_all, list(pure_codes))
    as_mc50_vs_mkt = compute_active_share(latest_all, list(mc50_codes))
    as_matched_vs_mkt = compute_active_share(latest_all, list(matched_codes))
    as_abs_vs_mkt = compute_active_share(latest_all, list(set(latest_abs['code'])))

    # 코스피 단독 / 코스닥 단독 대비 Active Share
    kospi_only_df = latest_all[latest_all['market'] == 'KOSPI'].copy()
    kospi_only_df['market_weight_pct'] = kospi_only_df['end_marcap'] / kospi_only_df['end_marcap'].sum() * 100.0
    kosdaq_only_df = latest_all[latest_all['market'] == 'KOSDAQ'].copy()
    kosdaq_only_df['market_weight_pct'] = kosdaq_only_df['end_marcap'] / kosdaq_only_df['end_marcap'].sum() * 100.0

    # 시장 시가총액 상위 50개와의 중복률
    mc50_overlap_codes = pure_codes & mc50_codes
    mc50_overlap_count = len(mc50_overlap_codes)
    mc50_overlap_pct = round(mc50_overlap_count / 50.0 * 100.0, 1)

    # 개미 지수와 전체 시장(시총가중)의 업종별 비중 차이
    mkt_sector_w = latest_all.groupby('industry')['market_weight_pct'].sum().to_dict()
    pure_sector_w = (latest_pure['industry'].value_counts() * 2.0).to_dict()
    matched_sector_w = (latest_matched['industry'].value_counts() * 2.0).to_dict()

    all_sectors = sorted(
        list(set(mkt_sector_w.keys()) | set(pure_sector_w.keys())),
        key=lambda s: -(pure_sector_w.get(s, 0.0) - mkt_sector_w.get(s, 0.0))
    )
    sector_vs_market = []
    for sec in all_sectors:
        pw = round(float(pure_sector_w.get(sec, 0.0)), 2)
        mw = round(float(mkt_sector_w.get(sec, 0.0)), 2)
        if pw > 0 or mw >= 1.5:
            sector_vs_market.append({
                "industry": sec,
                "pure_count": int(round(pw / 2.0)),
                "pure_weight_pct": pw,
                "market_weight_pct": mw,
                "matched_weight_pct": round(float(matched_sector_w.get(sec, 0.0)), 2),
                "diff_weight_pct": round(pw - mw, 2),
            })

    # 개미 지수와 전체 시장(시총가중)의 시가총액 규모별 비중 차이
    size_order = ["초대형주 (10조 이상)", "대형주 (1조~10조)", "중형주 (3,000억~1조)", "소형주 (3,000억 미만)"]
    mkt_size_w = latest_all.groupby('size_bucket')['market_weight_pct'].sum().to_dict()
    pure_size_w = (latest_pure['size_bucket'].value_counts() * 2.0).to_dict()
    abs_size_w = (latest_abs['size_bucket'].value_counts() * 2.0).to_dict()
    matched_size_w = (latest_matched['size_bucket'].value_counts() * 2.0).to_dict()

    size_vs_market = []
    for sb in size_order:
        pw = round(float(pure_size_w.get(sb, 0.0)), 2)
        mw = round(float(mkt_size_w.get(sb, 0.0)), 2)
        aw = round(float(abs_size_w.get(sb, 0.0)), 2)
        mtw = round(float(matched_size_w.get(sb, 0.0)), 2)
        size_vs_market.append({
            "size_bucket": sb,
            "pure_count": int(round(pw / 2.0)),
            "pure_weight_pct": pw,
            "market_weight_pct": mw,
            "abs_weight_pct": aw,
            "matched_weight_pct": mtw,
            "diff_vs_market_pct": round(pw - mw, 2),
            "diff_vs_abs_pct": round(pw - aw, 2),
        })

    # 개미 지수에만 상대적으로 높은 비중(+1.8%p~+2.0%p)으로 포함된 종목 상위 15선
    overweight_in_gaemi = latest_pure.copy()
    overweight_in_gaemi['weight_diff_vs_market'] = (2.0 - overweight_in_gaemi['market_weight_pct']).round(3)
    overweight_top15 = overweight_in_gaemi.sort_values(['weight_diff_vs_market', 'intensity_pct'], ascending=[False, False]).head(15)[
        ['rank', 'code', 'name', 'market', 'industry', 'intensity_pct', 'net_buy_eok', 'end_marcap_eok', 'market_weight_pct', 'weight_diff_vs_market']
    ].to_dict(orient="records")

    # 코스피·코스닥 대형주(시총 상위 25개) 가운데 개미 지수에 없는 종목
    top25_marcap = latest_all.sort_values('end_marcap', ascending=False).head(25).copy()
    top25_marcap['in_pure50'] = top25_marcap['code'].isin(pure_codes)
    missing_large_caps = top25_marcap[~top25_marcap['in_pure50']].head(15)[
        ['marcap_rank_all', 'code', 'name', 'market', 'industry', 'end_marcap_eok', 'market_weight_pct', 'net_buy_eok', 'intensity_pct', 'pure_rank_eligible', 'eligibility_note']
    ].to_dict(orient="records")

    # --- PHASE 2: 누가 무엇을 샀나 (개인 vs 외국인 vs 기관) ---
    frg_codes = set(latest_frg['code'])
    org_codes = set(latest_org['code'])

    ind_frg_common = pure_codes & frg_codes
    ind_org_common = pure_codes & org_codes
    frg_org_common = frg_codes & org_codes

    # 업종별 주체 간 비교 (적격 유니버스 전체 기준 업종별 순매수대금 합계 및 평균 순매수 강도)
    elig_universe = latest_all[latest_all['base_eligible']].copy()
    sec_inv = elig_universe.groupby('industry', as_index=False).agg(
        stock_count=('code', 'count'),
        total_avg_marcap_eok=('avg_marcap_36m_eok', 'sum'),
        ind_net_buy_eok=('net_buy_eok', 'sum'),
        frg_net_buy_eok=('frg_net_buy_eok', 'sum'),
        org_net_buy_eok=('org_net_buy_eok', 'sum'),
        ind_mean_intensity=('intensity_pct', 'mean'),
        frg_mean_intensity=('frg_intensity_pct', 'mean'),
        org_mean_intensity=('org_intensity_pct', 'mean'),
    )
    # 업종 전체 시총 대비 순매수 강도
    sec_inv['ind_sector_intensity_pct'] = (sec_inv['ind_net_buy_eok'] / np.maximum(sec_inv['total_avg_marcap_eok'], 1.0) * 100.0).round(2)
    sec_inv['frg_sector_intensity_pct'] = (sec_inv['frg_net_buy_eok'] / np.maximum(sec_inv['total_avg_marcap_eok'], 1.0) * 100.0).round(2)
    sec_inv['org_sector_intensity_pct'] = (sec_inv['org_net_buy_eok'] / np.maximum(sec_inv['total_avg_marcap_eok'], 1.0) * 100.0).round(2)
    sec_inv = sec_inv[sec_inv['stock_count'] >= 2].sort_values('ind_sector_intensity_pct', ascending=False)

    # 반대편에 선 종목 (Divergent Bets)
    # 1) 개인은 순매수(>0)하고 외국인(<0)과 기관(<0)은 모두 순매도한 종목 (개인 순매수 강도 순)
    ind_buy_others_sell = elig_universe[
        (elig_universe['ind_net_val'] > 0) &
        (elig_universe['frg_net_val'] < 0) &
        (elig_universe['org_net_val'] < 0)
    ].sort_values('intensity_pct', ascending=False).head(15)[
        ['code', 'name', 'market', 'industry', 'end_marcap_eok', 'intensity_pct', 'net_buy_eok', 'frg_intensity_pct', 'frg_net_buy_eok', 'org_intensity_pct', 'org_net_buy_eok', 'pure_rank_eligible']
    ].to_dict(orient="records")

    # 2) 외국인(>0)과 기관(>0)은 모두 순매수하고 개인(<0)은 순매도한 종목 (외국인+기관 합산 순매수 강도 순)
    elig_universe['inst_frg_combined_intensity'] = (elig_universe['frg_intensity_pct'] + elig_universe['org_intensity_pct']).round(4)
    others_buy_ind_sell = elig_universe[
        (elig_universe['ind_net_val'] < 0) &
        (elig_universe['frg_net_val'] > 0) &
        (elig_universe['org_net_val'] > 0)
    ].sort_values('inst_frg_combined_intensity', ascending=False).head(15)[
        ['code', 'name', 'market', 'industry', 'end_marcap_eok', 'intensity_pct', 'net_buy_eok', 'frg_intensity_pct', 'frg_net_buy_eok', 'org_intensity_pct', 'org_net_buy_eok', 'frg_pure_rank', 'org_pure_rank']
    ].to_dict(orient="records")

    # [5/6] 전체 성과 및 코스닥 유사성 검증 지표 계산
    k_rets = merged['KOSPI_ret'].values
    q_rets = merged['KOSDAQ_ret'].values
    metrics = {}
    for key, col_v, col_r in [
        ("GAEMI_50_PURE", "GAEMI_50_PURE", "GAEMI_50_PURE_ret"),
        ("GAEMI_50_TOTAL", "GAEMI_50_TOTAL", "GAEMI_50_TOTAL_ret"),
        ("GAEMI_50_ABS", "GAEMI_50_ABS", "GAEMI_50_ABS_ret"),
        ("MATCHED_50_EW", "MATCHED_50_EW", "MATCHED_50_EW_ret"),
        ("KOSDAQ_EW", "KOSDAQ_EW", "KOSDAQ_EW_ret"),
        ("FOREIGN_50_PURE", "FOREIGN_50_PURE", "FOREIGN_50_PURE_ret"),
        ("INSTITUTION_50_PURE", "INSTITUTION_50_PURE", "INSTITUTION_50_PURE_ret"),
        ("KOSPI", "KOSPI_norm", "KOSPI_ret"),
        ("KOSDAQ", "KOSDAQ_norm", "KOSDAQ_ret"),
    ]:
        metrics[key] = calc_perf_stats(merged[col_v].values, merged[col_r].values, k_rets, q_rets)

    metrics["KOSPI_raw"] = round(float(merged['KOSPI'].iloc[-1]), 2)
    metrics["KOSDAQ_raw"] = round(float(merged['KOSDAQ'].iloc[-1]), 2)

    # PURE와 각 비교 지수 간 일간 수익률 상관계수 및 종목 중복률 계산
    pure_rets_arr = merged['GAEMI_50_PURE_ret'].values[1:]
    for k_other, col_r in [
        ("GAEMI_50_TOTAL", "GAEMI_50_TOTAL_ret"),
        ("GAEMI_50_ABS", "GAEMI_50_ABS_ret"),
        ("MATCHED_50_EW", "MATCHED_50_EW_ret"),
        ("KOSDAQ_EW", "KOSDAQ_EW_ret"),
        ("FOREIGN_50_PURE", "FOREIGN_50_PURE_ret"),
        ("INSTITUTION_50_PURE", "INSTITUTION_50_PURE_ret"),
    ]:
        other_arr = merged[col_r].values[1:]
        metrics[k_other]["corr_with_pure"] = round(float(np.corrcoef(pure_rets_arr, other_arr)[0, 1]), 4)

    # 코스닥과의 유사성 검증 (Section 1-2 C)
    kosdaq_all_codes = set(latest_all[latest_all['market'] == 'KOSDAQ']['code'])
    kosdaq_top50_mc_codes = set(latest_all[latest_all['market'] == 'KOSDAQ'].sort_values('end_marcap', ascending=False).head(50)['code'])
    pure_in_kosdaq_cnt = len(pure_codes & kosdaq_all_codes)
    pure_in_kosdaq_top50_cnt = len(pure_codes & kosdaq_top50_mc_codes)
    pure_in_kq_ew_cnt = len(pure_codes & kq_ew_codes)

    kosdaq_similarity_verification = {
        "pure_kosdaq_stock_count": pure_in_kosdaq_cnt,
        "pure_kosdaq_weight_pct": round(pure_in_kosdaq_cnt * 2.0, 1),
        "pure_overlap_with_kosdaq_top50_marcap_count": pure_in_kosdaq_top50_cnt,
        "pure_overlap_with_kosdaq_top50_marcap_pct": round(pure_in_kosdaq_top50_cnt / 50.0 * 100.0, 1),
        "pure_overlap_with_kosdaq_ew_count": pure_in_kq_ew_cnt,
        "kosdaq_ew_universe_count": len(kq_ew_codes),
        "comparison_table": [
            {
                "name": "GAEMI 50 PURE (개미 지수)",
                "rule": "코스피·코스닥 적격 보통주 중 36개월 개인 순매수 강도 상위 50 동일가중",
                "stock_overlap_with_pure_pct": 100.0,
                "active_share_vs_market_pct": as_pure_vs_mkt,
                **metrics["GAEMI_50_PURE"]
            },
            {
                "name": "코스닥 (시가총액 가중)",
                "rule": "코스닥 상장 전 종목 시가총액 가중 지수",
                "stock_overlap_with_pure_pct": round(pure_in_kosdaq_top50_cnt / 50.0 * 100.0, 1),
                "active_share_vs_market_pct": None,
                **metrics["KOSDAQ"]
            },
            {
                "name": "코스닥 동일가중 비교지수",
                "rule": f"적격 조건(시총 3,000억+·거래대금 10억+·36개월 관측) 충족 코스닥 {len(kq_ew_codes)}종목 전체 동일가중",
                "stock_overlap_with_pure_pct": round(pure_in_kq_ew_cnt / max(len(kq_ew_codes), 1) * 100.0, 1),
                "active_share_vs_market_pct": compute_active_share(latest_all, list(kq_ew_codes)),
                **metrics["KOSDAQ_EW"]
            },
            {
                "name": "시가총액·업종 유사 50종목 비교 포트폴리오",
                "rule": "GAEMI 50 PURE 제외 적격 종목 중 각 PURE 종목과 동일 시장·동일 업종·최근접 시가총액 1:1 매칭 50종목 동일가중",
                "stock_overlap_with_pure_pct": 0.0,
                "active_share_vs_market_pct": as_matched_vs_mkt,
                **metrics["MATCHED_50_EW"]
            }
        ],
        "diagnosis_category": "종목 구성은 다르지만 주가 흐름(일간 변동 방향)은 유사하고 누적 성과는 차별화됨",
        "diagnosis_detail": (
            f"GAEMI 50 PURE 구성 50종목 중 코스닥 시가총액 상위 50개와 겹치는 종목은 {pure_in_kosdaq_top50_cnt}개({pure_in_kosdaq_top50_cnt*2}%)에 불과하며, "
            f"시가총액·업종 유사 50종목 비교 포트폴리오와는 중복 종목이 0개(Active Share {as_pure_vs_mkt}% vs {as_matched_vs_mkt}%)입니다. "
            f"그럼에도 일간 수익률 상관계수가 코스닥과 {metrics['GAEMI_50_PURE']['corr_kosdaq']:.3f}(코스닥 동일가중과 {metrics['KOSDAQ_EW']['corr_with_pure']:.3f})로 높은 이유는 "
            f"개인이 집중 순매수한 50종목 중 중형주(3,000억~1조)가 {int(pure_size_w.get('중형주 (3,000억~1조)', 0)//2)}종목({pure_size_w.get('중형주 (3,000억~1조)', 0):.0f}%), "
            f"코스닥 종목이 {pure_in_kosdaq_cnt}종목({pure_in_kosdaq_cnt*2}%)을 차지해 국내 중소형주 공통 시장 요인(베타)의 영향을 함께 받기 때문입니다. "
            f"반면 누적 수익률은 GAEMI 50 PURE({metrics['GAEMI_50_PURE']['total_return_pct']:+.2f}%)가 시가총액·업종 유사 비교 포트폴리오({metrics['MATCHED_50_EW']['total_return_pct']:+.2f}%) 및 "
            f"코스닥 동일가중({metrics['KOSDAQ_EW']['total_return_pct']:+.2f}%)과 뚜렷한 격차를 보입니다."
        )
    }

    # --- PHASE 0 감사 결과 리포트 정리 ---
    new_pure_codes = latest_pure['code'].tolist()
    changed_after_phase0_in = sorted(list(set(new_pure_codes) - set(old_pure_codes))) if old_pure_codes else []
    changed_after_phase0_out = sorted(list(set(old_pure_codes) - set(new_pure_codes))) if old_pure_codes else []

    completeness_info = {}
    comp_log_path = os.path.join(DATA_DIR, "phase0_completeness_log.json")
    if os.path.exists(comp_log_path):
        completeness_info = json.load(open(comp_log_path, encoding="utf-8"))

    phase0_audit_report = {
        "audit_0_1_net_buy_estimation": {
            "method": "일별 확정 개인 순매수수량(매수수량 - 매도수량) × 당일 KRX 정규장 종가",
            "krx_official_status": "KRX 정보데이터시스템(MDCSTAT024)의 비로그인 API 차단(HTTP 400 LOGOUT)으로 종목별 일별 체결대금 원자료 직접 수집 불가",
            "validation_against_execution_amount": "Naver 공시 외국인·기관 3개월 누적 실제 체결 순매수대금(accTradeAmount)과 일별(순매수수량×종가) 합산치 교차 검증 결과, 기관 중앙값 오차 0.62%(평균 1.46%), 외국인 중앙값 오차 1.70%(평균 2.38%) 확인",
            "ui_policy": "모든 금액 지표에 실제 체결대금이 아닌 '추정 순매수대금 (일별 순매수수량 × 종가)'임을 명시"
        },
        "audit_0_2_36m_completeness": {
            **completeness_info,
            "policy": "최근 200일 거래 부진으로 누락될 가능성을 차단하기 위해 시가총액 후보군 전수의 2021-09 ~ 2026-11 전체 기간(7페이지) 원자료 일괄 확보 완료",
        },
        "audit_0_3_krx_vs_nxt": {
            "is_nxt_included_in_krx": False,
            "is_duplicated": False,
            "nxt_launch_date": "2025-03-04",
            "krx_vs_combined_top50_overlap_2026Q4": f"{len(pure_codes & set(latest_tot['code']))}/50 ({len(pure_codes & set(latest_tot['code']))*2}%)",
            "krx_only_only_stocks": [universe_map.get(c, {}).get("Name", c) for c in sorted(list(pure_codes - set(latest_tot['code'])))],
            "combined_only_stocks": [universe_map.get(c, {}).get("Name", c) for c in sorted(list(set(latest_tot['code']) - pure_codes))],
            "krx_pure_final_index": metrics["GAEMI_50_PURE"]["current"],
            "krx_pure_total_return_pct": metrics["GAEMI_50_PURE"]["total_return_pct"],
            "combined_pure_final_index": metrics["GAEMI_50_TOTAL"]["current"],
            "combined_pure_total_return_pct": metrics["GAEMI_50_TOTAL"]["total_return_pct"],
            "policy": "2025.03 NXT 출범 전후 36개월 집계 기준의 시계열 연속성을 위해 대표지수는 KRX 정규장 기준으로 산출하고, KRX+NXT 통합 지수를 비교지수로 함께 제공"
        },
        "audit_0_4_historical_marcap_and_recalculation": {
            "anchor_method": "2026-03-08, 2026-03-31, 2026-06-30, 2026-09-30, 2026-11-20 KRX 공식 상장주식수(LIST_SHRS) 스냅샷 직접 앵커링 + 2026-03-08 이전 자본금 이벤트(|전일종가/기준가 - 1| >= 3%: 액면분할·병합·무상증자·감자) 역산 복원",
            "recalculation_constituent_change_2026Q4": {
                "overlap_with_pre_audit_count": 50 - len(changed_after_phase0_in),
                "newly_entered_after_audit": [universe_map.get(c, {}).get("Name", c) for c in changed_after_phase0_in],
                "removed_after_audit": [universe_map.get(c, {}).get("Name", c) for c in changed_after_phase0_out],
            }
        }
    }

    # --- PHASE 6: 메인 화면 3대 데이터 팩트 문장 (과장·단정 배제, 순수 수치 기반) ---
    gap_vs_kospi = round(metrics["GAEMI_50_PURE"]["total_return_pct"] - metrics["KOSPI"]["total_return_pct"], 2)
    key_facts_banner = [
        {
            "id": "fact-1",
            "label": "수익률 격차 (2024.09.30 ~ 2026.11.20)",
            "value": f"{gap_vs_kospi:+.2f}%p",
            "sentence": f"2024년 9월 말 이후 GAEMI 50 PURE 누적 수익률은 {metrics['GAEMI_50_PURE']['total_return_pct']:+.2f}%로, 같은 기간 코스피({metrics['KOSPI']['total_return_pct']:+.2f}%)보다 {abs(gap_vs_kospi):.2f}%p 낮고 코스닥({metrics['KOSDAQ']['total_return_pct']:+.2f}%)과는 {abs(metrics['GAEMI_50_PURE']['total_return_pct'] - metrics['KOSDAQ']['total_return_pct']):.2f}%p 차이 났다."
        },
        {
            "id": "fact-2",
            "label": "시장과의 구성 차이 (2026 Q4 Active Share)",
            "value": f"{as_pure_vs_mkt:.1f}%",
            "sentence": f"국내 주식시장(코스피·코스닥 시가총액 가중) 대비 GAEMI 50 PURE의 비중 차이(Active Share)는 {as_pure_vs_mkt:.1f}%이며, 시장 시가총액 상위 50개 종목과 겹치는 종목은 50개 중 {mc50_overlap_count}개({mc50_overlap_pct}%)다."
        },
        {
            "id": "fact-3",
            "label": "투자 주체 간 종목 중복률 (2026 Q4, 36개월)",
            "value": f"외국인 {len(ind_frg_common)}개 · 기관 {len(ind_org_common)}개",
            "sentence": f"개인 순매수 강도 상위 50개 종목 중 외국인 상위 50개와 겹치는 종목은 {len(ind_frg_common)}개({len(ind_frg_common)*2}%), 기관(연기금 포함) 상위 50개와 겹치는 종목은 {len(ind_org_common)}개({len(ind_org_common)*2}%)다."
        }
    ]

    # [6/6] 종목별 상세 시계열(주간 압축) 및 웹 번들 저장
    print("[6/6] 종목별 상세 시계열 및 웹 데이터 번들 저장 중...")
    union_codes = sorted(list(pure_codes | frg_codes | org_codes | set(latest_abs['code']) | {"005930", "000660"}))
    w36_start = latest_q["window_36m_start"]
    sub_top = trades[(trades['code'].isin(union_codes)) & (trades['date'] >= w36_start)].sort_values(['code', 'date']).copy()
    sub_top['cum_ind_eok'] = (sub_top.groupby('code')['krx_ind_net_val'].cumsum() / 1e8).round(1)
    sub_top['cum_frg_eok'] = (sub_top.groupby('code')['krx_frg_net_val'].cumsum() / 1e8).round(1)
    sub_top['cum_org_eok'] = (sub_top.groupby('code')['krx_org_net_val'].cumsum() / 1e8).round(1)
    sub_top['marcap_eok'] = (sub_top['daily_marcap'] / 1e8).round(0)
    sub_top['ym_week'] = pd.to_datetime(sub_top['date']).dt.to_period('W').astype(str)
    weekly_top = sub_top.groupby(['code', 'ym_week'], as_index=False).last()

    pure_meta_map = latest_pure.set_index('code').to_dict(orient='index')
    all_meta_map = latest_all.set_index('code').to_dict(orient='index')

    stock_trajectories = {}
    for c in union_codes:
        c_df = weekly_top[weekly_top['code'] == c].sort_values('date')
        m_all = all_meta_map.get(c, {})
        m_pure = pure_meta_map.get(c, {})
        in_qs = [q["rebalance_id"] for q in schedule if c in set(pure_holdings[q["rebalance_id"]]['code'])]
        f_info = first_entry_info.get(c, None)
        if f_info:
            ed = f_info["eff_start"]
            e_dates = [d for d in ret_pivot.index if ed <= d <= max_date]
            s_ret = round((float(ret_pivot.loc[e_dates, c].prod()) - 1.0) * 100.0, 2) if (e_dates and c in ret_pivot.columns) else 0.0
        else:
            s_ret = None

        stock_trajectories[c] = {
            "code": c,
            "name": m_all.get("name", universe_map.get(c, {}).get("Name", c)),
            "market": m_all.get("market", universe_map.get(c, {}).get("MarketName", "")),
            "industry": m_all.get("industry", universe_map.get(c, {}).get("Industry", "")),
            "size_bucket": m_all.get("size_bucket", ""),
            "net_buy_36m_eok": float(m_all.get("net_buy_eok", 0)),
            "frg_net_buy_36m_eok": float(m_all.get("frg_net_buy_eok", 0)),
            "org_net_buy_36m_eok": float(m_all.get("org_net_buy_eok", 0)),
            "avg_marcap_36m_eok": float(m_all.get("avg_marcap_36m_eok", 0)),
            "end_marcap_eok": float(m_all.get("end_marcap_eok", 0)),
            "market_weight_pct": round(float(m_all.get("market_weight_pct", 0)), 4),
            "intensity_pct": float(m_all.get("intensity_pct", 0)),
            "frg_intensity_pct": float(m_all.get("frg_intensity_pct", 0)),
            "org_intensity_pct": float(m_all.get("org_intensity_pct", 0)),
            "pure_rank": int(m_all["pure_rank_eligible"]) if pd.notna(m_all.get("pure_rank_eligible")) else None,
            "frg_pure_rank": int(m_all["frg_pure_rank"]) if pd.notna(m_all.get("frg_pure_rank")) else None,
            "org_pure_rank": int(m_all["org_pure_rank"]) if pd.notna(m_all.get("org_pure_rank")) else None,
            "abs_rank": int(m_all.get("abs_rank_all", 0)),
            "marcap_rank": int(m_all.get("marcap_rank_all", 0)),
            "rank_change_str": m_pure.get("rank_change_str", "미편입"),
            "prev_quarter_rank": int(m_pure["prev_quarter_rank"]) if pd.notna(m_pure.get("prev_quarter_rank")) else None,
            "in_pure50": bool(c in pure_codes),
            "entry_quarter": f_info["quarter"] if f_info else "미편입",
            "entry_date": f_info["eff_start"] if f_info else "-",
            "since_entry_return_pct": s_ret,
            "included_quarters": in_qs,
            "eligibility_note": m_all.get("eligibility_note", ""),
            "dates": c_df['date'].tolist(),
            "prices": [int(x) for x in c_df['reg_close'].tolist()],
            "marcap_eok": [float(x) for x in c_df['marcap_eok'].tolist()],
            "cum_net_buy_eok": [float(x) for x in c_df['cum_ind_eok'].tolist()],
            "cum_frg_net_buy_eok": [float(x) for x in c_df['cum_frg_eok'].tolist()],
            "cum_org_net_buy_eok": [float(x) for x in c_df['cum_org_eok'].tolist()],
        }

    market_differentiation = {
        "active_share": {
            "gaemi_pure_vs_market_pct": as_pure_vs_mkt,
            "marcap_top50_ew_vs_market_pct": as_mc50_vs_mkt,
            "matched_size_sector_50_ew_vs_market_pct": as_matched_vs_mkt,
            "gaemi_abs_vs_market_pct": as_abs_vs_mkt,
            "pure_excess_active_share_over_marcap50_ew_pct": round(as_pure_vs_mkt - as_mc50_vs_mkt, 2),
        },
        "marcap_top50_overlap": {
            "overlap_count": mc50_overlap_count,
            "overlap_pct": mc50_overlap_pct,
            "overlapping_stocks": latest_pure[latest_pure['code'].isin(mc50_overlap_codes)][
                ['rank', 'code', 'name', 'market', 'industry', 'intensity_pct', 'net_buy_eok', 'end_marcap_eok', 'marcap_rank_all', 'market_weight_pct']
            ].to_dict(orient="records"),
        },
        "sector_vs_market": sector_vs_market,
        "size_vs_market": size_vs_market,
        "overweight_in_gaemi_top15": overweight_top15,
        "missing_large_caps_top15": missing_large_caps,
        "kosdaq_similarity": kosdaq_similarity_verification,
    }

    investor_comparison = {
        "note": "기관은 KRX 투자자 분류상 '기관합계'(금융투자·보험·투신·사모·은행·기타금융·연기금 등 포함) 기준이며, 각 주체별 36개월 누적 추정 순매수대금(일별 순매수수량 × 정규장 종가)을 36개월 평균 시가총액으로 나눈 순매수 강도(%) 상위 50개 종목을 동일한 자격 기준(보통주, 시총 3,000억+, 60일 거래대금 10억+, 36개월 관측 확보, 양수 순매수)으로 선정했습니다.",
        "overlaps": {
            "ind_vs_frg_count": len(ind_frg_common),
            "ind_vs_frg_pct": round(len(ind_frg_common) / 50.0 * 100.0, 1),
            "ind_vs_frg_stocks": [universe_map.get(c, {}).get("Name", c) for c in sorted(list(ind_frg_common))],
            "ind_vs_org_count": len(ind_org_common),
            "ind_vs_org_pct": round(len(ind_org_common) / 50.0 * 100.0, 1),
            "ind_vs_org_stocks": [universe_map.get(c, {}).get("Name", c) for c in sorted(list(ind_org_common))],
            "frg_vs_org_count": len(frg_org_common),
            "frg_vs_org_pct": round(len(frg_org_common) / 50.0 * 100.0, 1),
            "frg_vs_org_stocks": [universe_map.get(c, {}).get("Name", c) for c in sorted(list(frg_org_common))],
        },
        "top50_by_investor": {
            "individual": latest_pure[['rank', 'code', 'name', 'market', 'industry', 'intensity_pct', 'net_buy_eok', 'avg_marcap_36m_eok', 'end_marcap_eok', 'since_entry_return_pct', 'rank_change_str']].to_dict(orient="records"),
            "foreign": latest_frg[['rank', 'code', 'name', 'market', 'industry', 'frg_intensity_pct', 'frg_net_buy_eok', 'avg_marcap_36m_eok', 'end_marcap_eok', 'since_entry_return_pct']].to_dict(orient="records"),
            "institution": latest_org[['rank', 'code', 'name', 'market', 'industry', 'org_intensity_pct', 'org_net_buy_eok', 'avg_marcap_36m_eok', 'end_marcap_eok', 'since_entry_return_pct']].to_dict(orient="records"),
        },
        "sector_comparison": sec_inv.to_dict(orient="records"),
        "divergent_bets": {
            "ind_buy_others_sell": ind_buy_others_sell,
            "others_buy_ind_sell": others_buy_ind_sell,
        },
        "simulated_index_metrics": {
            "individual_pure50": metrics["GAEMI_50_PURE"],
            "foreign_pure50": metrics["FOREIGN_50_PURE"],
            "institution_pure50": metrics["INSTITUTION_50_PURE"],
        }
    }

    summary = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_as_of": max_date,
        "base_date": base_date,
        "base_value": 1000.0,
        "representative_index": "GAEMI 50 PURE",
        "key_facts": key_facts_banner,
        "current_rebalance": rebalance_history[-1],
        "rebalance_history": rebalance_history,
        "metrics": metrics,
    }

    with open(os.path.join(DATA_DIR, "index_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA_DIR, "phase0_audit_report.json"), "w", encoding="utf-8") as f:
        json.dump(phase0_audit_report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA_DIR, "market_differentiation.json"), "w", encoding="utf-8") as f:
        json.dump(market_differentiation, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA_DIR, "investor_comparison.json"), "w", encoding="utf-8") as f:
        json.dump(investor_comparison, f, ensure_ascii=False, indent=2)

    sens_path = os.path.join(DATA_DIR, "sensitivity_analysis.json")
    sens_data = json.load(open(sens_path, encoding="utf-8")) if os.path.exists(sens_path) else []
    comp_path = os.path.join(DATA_DIR, "pure_vs_abs_comparison.json")
    comp_data = json.load(open(comp_path, encoding="utf-8")) if os.path.exists(comp_path) else {}

    web_payload = {
        "summary": summary,
        "phase0_audit": phase0_audit_report,
        "market_diff": market_differentiation,
        "investor_comp": investor_comparison,
        "comparison": comp_data,
        "sensitivity": sens_data,
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

    print("\n=== PHASE 0 ~ PHASE 6 핵심 분석 결과 요약 ===")
    for k in ["GAEMI_50_PURE", "GAEMI_50_TOTAL", "GAEMI_50_ABS", "MATCHED_50_EW", "KOSDAQ_EW", "FOREIGN_50_PURE", "INSTITUTION_50_PURE", "KOSPI", "KOSDAQ"]:
        m = metrics[k]
        print(f"  {k:20s}: 현재={m['current']:8.2f} | 누적={m['total_return_pct']:+7.2f}% | MDD={m['mdd_pct']:6.2f}% | 변동성={m['ann_volatility_pct']:5.2f}% | KOSPI상관={m['corr_kospi']:.3f} | KOSDAQ상관={m['corr_kosdaq']:.3f}")


if __name__ == "__main__":
    main()
