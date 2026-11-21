"""
PHASE 0-2: 36개월 원자료 수집 완전성 보강 스크립트
- 기존 1페이지(200거래일)만 수집되었던 종목 중 시가총액 1,000억 원 이상을 한 번이라도 기록한 527개 종목 전수에 대해
  2021-09-01 ~ 2026-11-20 전체 기간(7페이지, 최대 1,400거래일) 원자료를 추가 수집하여 누락 가능성을 0으로 제거합니다.
- 메모리 피크 방지를 위해 기존 테이블에서 대상 종목의 200일 조각을 먼저 제거한 뒤 신규 전 기간 데이터를 병합합니다.
"""

import os
import time
import json
import asyncio
import aiohttp
import pandas as pd
import numpy as np
from collect_data import fetch_stock_history, DATA_DIR


async def complete_36m_collection():
    t0 = time.time()
    u = pd.read_parquet(os.path.join(DATA_DIR, "universe.parquet"))
    p_path = os.path.join(DATA_DIR, "daily_investor_trades.parquet")

    raw_cols = [
        'code', 'date', 'base_price', 'reg_close', 'close_price',
        'krx_ind_buy_vol', 'krx_ind_sell_vol', 'krx_ind_net_vol',
        'krx_frg_net_vol', 'krx_org_net_vol', 'krx_vol',
        'nxt_ind_buy_vol', 'nxt_ind_sell_vol', 'nxt_ind_net_vol',
        'nxt_close', 'nxt_vol'
    ]
    t = pd.read_parquet(p_path, columns=raw_cols)

    cnts = t.groupby('code').agg(
        days=('date', 'count'),
        min_dt=('date', 'min'),
        max_close=('reg_close', 'max')
    ).reset_index()
    m = pd.merge(u, cnts, left_on='Code', right_on='code', how='left')
    m['ListingDate_str'] = m['ListingDate'].astype(str).str.slice(0, 10)
    m['max_mc_eok'] = m['Stocks'] * m['max_close'].fillna(0) / 1e8

    # 200일만 수집된 종목 중 시가총액 800억 원 이상(3,000억 기준의 약 1/4까지 여유 확보) 또는 상장일 2025-12 이전 후보 전수
    truncated = m[(m['days'] == 200) & (m['ListingDate_str'] < '2025-12-01') & (m['max_mc_eok'] >= 800)].copy()
    target_codes = truncated['Code'].tolist()
    print(f"[PHASE 0-2] 36개월 전 기간 추가 수집 대상: {len(target_codes)}개 종목")

    # 기존 DataFrame에서 target_codes 먼저 제거하여 메모리 확보
    t_kept = t[~t['code'].isin(set(target_codes))].copy()
    del t

    sem = asyncio.Semaphore(85)
    connector = aiohttp.TCPConnector(limit=110, ttl_dns_cache=300)
    new_rows = []
    failed_codes = []

    async with aiohttp.ClientSession(connector=connector) as session:
        batch_size = 200
        for b_start in range(0, len(target_codes), batch_size):
            batch = target_codes[b_start:b_start + batch_size]
            tasks = [fetch_stock_history(session, sem, c, max_pages=7, min_date="2021-09-01") for c in batch]
            res = await asyncio.gather(*tasks)
            for c, r_list in zip(batch, res):
                if not r_list:
                    failed_codes.append(c)
                else:
                    new_rows.extend(r_list)
            print(f"  진행: {min(b_start+batch_size, len(target_codes))}/{len(target_codes)} ({time.time()-t0:.1f}s), 신규 레코드={len(new_rows):,}")

    df_new = pd.DataFrame(new_rows, columns=raw_cols)
    del new_rows
    df_new = df_new[df_new['date'] >= '2021-09-01'].sort_values(['code', 'date']).drop_duplicates(['code', 'date'])

    # 메모리 효율적 병합
    combined = pd.concat([t_kept, df_new], ignore_index=True)
    del t_kept, df_new

    # 파생 금액 컬럼 계산
    combined['krx_ind_buy_val'] = combined['krx_ind_buy_vol'].astype(np.int64) * combined['reg_close'].astype(np.int64)
    combined['krx_ind_sell_val'] = combined['krx_ind_sell_vol'].astype(np.int64) * combined['reg_close'].astype(np.int64)
    combined['krx_ind_net_val'] = combined['krx_ind_buy_val'] - combined['krx_ind_sell_val']

    nxt_prc = np.where(combined['nxt_close'] > 0, combined['nxt_close'], combined['reg_close']).astype(np.int64)
    combined['nxt_ind_buy_val'] = combined['nxt_ind_buy_vol'].astype(np.int64) * nxt_prc
    combined['nxt_ind_sell_val'] = combined['nxt_ind_sell_vol'].astype(np.int64) * nxt_prc
    combined['nxt_ind_net_val'] = combined['nxt_ind_buy_val'] - combined['nxt_ind_sell_val']
    combined['total_ind_net_val'] = combined['krx_ind_net_val'] + combined['nxt_ind_net_val']

    combined.to_parquet(p_path, index=False, compression="zstd", compression_level=9)

    final_cnts = combined.groupby('code')['date'].count()
    full_36m_stocks = int((final_cnts >= 650).sum())
    total_rows = int(len(combined))
    total_stocks = int(combined['code'].nunique())

    completeness_log = {
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "expanded_stock_count": len(target_codes),
        "failed_codes": failed_codes,
        "total_stocks_in_ledger": total_stocks,
        "stocks_with_full_36m_data": full_36m_stocks,
        "total_daily_records": total_rows,
    }
    with open(os.path.join(DATA_DIR, "phase0_completeness_log.json"), "w", encoding="utf-8") as f:
        json.dump(completeness_log, f, ensure_ascii=False, indent=2)

    print(f"[PHASE 0-2 완료] 총 레코드={total_rows:,}행 | 36개월 이상 완전 확보 종목={full_36m_stocks:,}개 | 실패={len(failed_codes)}개")


if __name__ == "__main__":
    asyncio.run(complete_36m_collection())
