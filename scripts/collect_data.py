"""
PHASE 1 & 2: GAEMI INDEX 데이터 확보, 품질 감사 및 개인 순매수 원천 데이터 수집 파이프라인
- 대상 시장: KOSPI, KOSDAQ 일반 보통주 (ETF, ETN, SPAC, 우선주, 리츠, 외국주권/DR, 인프라펀드 제외)
- 생존자 편향 방지: 현재 상장 보통주 + 2021년 이후 상장폐지된 보통주 전수 포함
- 원천 데이터:
  1) KRX 상장종목 / 상장폐지종목 메타데이터 (FinanceDataReader / KIND)
  2) 종목별 일별 투자자별(개인/외국인/기관) 매수·매도·순매수 및 기준가/종가 (Naver Stock Security API v2 - KRX 및 NXT 분리 집계)
  3) KOSPI / KOSDAQ 지수 일별 시계열 (FinanceDataReader)
"""

import os
import sys
import time
import json
import asyncio
import aiohttp
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def build_universe():
    print("[1/4] 종목 유니버스 구축 및 필터링 감사 중...")
    df_krx = fdr.StockListing('KRX')
    df_desc = fdr.StockListing('KRX-DESC')
    df_del = fdr.StockListing('KRX-DELISTING')

    # 1. 현재 상장 종목 (KOSPI, KOSDAQ)
    m = pd.merge(
        df_krx,
        df_desc[['Code', 'Sector', 'Industry', 'Products', 'ListingDate']],
        on='Code',
        how='left'
    )
    kk = m[m['MarketId'].isin(['STK', 'KSQ'])].copy()

    # 제외 사유 태깅
    kk[' is_kr7'] = kk['ISU_CD'].astype(str).str.startswith('KR7')
    kk['is_common_isin'] = kk['ISU_CD'].astype(str).str[8] == '0'
    kk['is_common_code'] = kk['Code'].astype(str).str.endswith('0')
    kk['is_spac'] = (
        kk['Dept'].astype(str).str.contains('SPAC') |
        kk['Name'].astype(str).str.contains('스팩|SPAC', regex=True)
    )
    kk['is_foreign'] = kk['Dept'].astype(str).str.contains('외국기업') | (~kk[' is_kr7'])
    kk['is_reit_fund'] = (
        kk['Name'].astype(str).str.endswith(('리츠', '코크렙')) |
        kk['Code'].isin(['088980', '415640', '094800'])
    )

    active_common = kk[
        kk[' is_kr7'] &
        kk['is_common_isin'] &
        kk['is_common_code'] &
        (~kk['is_spac']) &
        (~kk['is_foreign']) &
        (~kk['is_reit_fund'])
    ].copy()

    active_common['Status'] = 'ACTIVE'
    active_common['DelistingDate'] = pd.NaT
    active_common['DelistingReason'] = ''
    active_common['ToSymbol'] = ''
    active_common['MarketName'] = active_common['MarketId'].map({'STK': 'KOSPI', 'KSQ': 'KOSDAQ'})

    # 2. 상장폐지 종목 (2021-01-01 이후 상장폐지된 KOSPI/KOSDAQ 일반 보통주)
    df_del['DelistingDate'] = pd.to_datetime(df_del['DelistingDate'], errors='coerce')
    df_del['ListingDate'] = pd.to_datetime(df_del['ListingDate'], errors='coerce')

    cond_del = (
        (df_del['DelistingDate'] >= '2021-01-01') &
        (df_del['Market'].isin(['KOSPI', 'KOSDAQ'])) &
        (df_del['SecuGroup'] == '주권') &
        (df_del['Kind'] == '보통주') &
        (df_del['Symbol'].astype(str).str.len() == 6) &
        (df_del['Symbol'].astype(str).str.endswith('0')) &
        (~df_del['Name'].astype(str).str.contains('스팩|SPAC', regex=True)) &
        (~df_del['Name'].astype(str).str.endswith(('리츠', '코크렙'))) &
        (~df_del['Reason'].astype(str).str.contains('스팩'))
    )
    del_common = df_del[cond_del].copy()
    # 이미 active_common에 있는 코드 제외
    del_common = del_common[~del_common['Symbol'].isin(set(active_common['Code']))].copy()

    del_mapped = pd.DataFrame({
        'Code': del_common['Symbol'].astype(str),
        'ISU_CD': '',
        'Name': del_common['Name'].astype(str),
        'MarketName': del_common['Market'].astype(str),
        'Dept': '상장폐지',
        'Close': 0,
        'Marcap': 0,
        'Stocks': del_common['ListingShares'].fillna(0),
        'Industry': del_common['Industry'].fillna(''),
        'ListingDate': del_common['ListingDate'],
        'Status': 'DELISTED',
        'DelistingDate': del_common['DelistingDate'],
        'DelistingReason': del_common['Reason'].fillna(''),
        'ToSymbol': del_common['ToSymbol'].fillna('').astype(str)
    })

    active_mapped = pd.DataFrame({
        'Code': active_common['Code'].astype(str),
        'ISU_CD': active_common['ISU_CD'].astype(str),
        'Name': active_common['Name'].astype(str),
        'MarketName': active_common['MarketName'].astype(str),
        'Dept': active_common['Dept'].fillna(''),
        'Close': pd.to_numeric(active_common['Close'], errors='coerce').fillna(0),
        'Marcap': pd.to_numeric(active_common['Marcap'], errors='coerce').fillna(0),
        'Stocks': pd.to_numeric(active_common['Stocks'], errors='coerce').fillna(0),
        'Industry': active_common['Industry'].fillna(''),
        'ListingDate': pd.to_datetime(active_common['ListingDate'], errors='coerce'),
        'Status': 'ACTIVE',
        'DelistingDate': pd.NaT,
        'DelistingReason': '',
        'ToSymbol': ''
    })

    universe = pd.concat([active_mapped, del_mapped], ignore_index=True)
    # 중복 종목코드 제거 (가장 최근 상장 우선)
    universe = universe.sort_values(['Status', 'Marcap'], ascending=[True, False]).drop_duplicates('Code', keep='first').reset_index(drop=True)

    audit_summary = {
        "total_krx_listed": int(len(df_krx)),
        "kospi_kosdaq_total": int(len(kk)),
        "excluded_preferred_or_noncommon": int((~kk['is_common_isin'] | ~kk['is_common_code']).sum()),
        "excluded_spac": int(kk['is_spac'].sum()),
        "excluded_reit_fund": int(kk['is_reit_fund'].sum()),
        "excluded_foreign": int(kk['is_foreign'].sum()),
        "active_common_stocks": int(len(active_mapped)),
        "delisted_common_stocks_since_2021": int(len(del_mapped)),
        "final_universe_count": int(len(universe))
    }
    print("  유니버스 감사 결과:", json.dumps(audit_summary, ensure_ascii=False))
    universe.to_parquet(os.path.join(DATA_DIR, "universe.parquet"), index=False)
    universe.to_csv(os.path.join(DATA_DIR, "universe.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(DATA_DIR, "audit_summary.json"), "w", encoding="utf-8") as f:
        json.dump(audit_summary, f, ensure_ascii=False, indent=2)

    return universe, audit_summary


async def fetch_stock_history(session, sem, code, max_pages=7, min_date="2021-09-01"):
    """
    단일 종목의 일별 투자자 매매동향 및 주가(기준가/정규장종가/최종종가) 수집
    max_pages=7 (200일 * 7 = 1,400거래일 ≈ 5.7년, 2021-03 ~ 2026-11)
    """
    rows = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for idx in range(max_pages):
        url = f"https://stock.naver.com/api/stockSecurity/investor-trend/v2/domestic/{code}/paged?exchangeType=all&size=200&index={idx}"
        async with sem:
            for attempt in range(3):
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                        if resp.status != 200:
                            break
                        data = await resp.json()
                        items = data.get("items", [])
                        if not items:
                            return rows
                        for it in items:
                            dt = it.get("localTradedAt")
                            if not dt:
                                continue
                            k = it.get("krx")
                            n = it.get("nxt")
                            if not k and not n:
                                continue

                            # KRX fields
                            if k:
                                reg_close = int(k.get("regularMarketClosingPrice") or k.get("closingPrice") or 0)
                                close_prc = int(k.get("closingPrice") or reg_close or 0)
                                base_prc = int(k.get("basePrice") or reg_close or 0)
                                k_ind_net = int(k.get("individualNetVolume") or 0)
                                k_ind_buy = int(k.get("individualBuyVolume") or 0)
                                k_ind_sell = int(k.get("individualSellVolume") or 0)
                                k_frg_net = int(k.get("foreignNetVolume") or 0)
                                k_org_net = int(k.get("organizationNetVolume") or 0)
                                k_vol = int(k.get("tradingVolume") or 0)
                            else:
                                reg_close = close_prc = base_prc = 0
                                k_ind_net = k_ind_buy = k_ind_sell = k_frg_net = k_org_net = k_vol = 0

                            # NXT fields
                            if n:
                                n_close = int(n.get("closingPrice") or reg_close or 0)
                                n_ind_net = int(n.get("individualNetVolume") or 0)
                                n_ind_buy = int(n.get("individualBuyVolume") or 0)
                                n_ind_sell = int(n.get("individualSellVolume") or 0)
                                n_vol = int(n.get("tradingVolume") or 0)
                            else:
                                n_close = 0
                                n_ind_net = n_ind_buy = n_ind_sell = n_vol = 0

                            rows.append((
                                code, dt, base_prc, reg_close, close_prc,
                                k_ind_buy, k_ind_sell, k_ind_net, k_frg_net, k_org_net, k_vol,
                                n_ind_buy, n_ind_sell, n_ind_net, n_close, n_vol
                            ))

                        last_dt = items[-1].get("localTradedAt", "")
                        has_next = data.get("hasNext", False)
                        if not has_next or (last_dt and last_dt < min_date) or len(items) < 200:
                            return rows
                        break
                except Exception:
                    if attempt == 2:
                        return rows
                    await asyncio.sleep(0.3)
    return rows


async def collect_all_investor_data(universe):
    """
    유니버스 전 종목 수집:
    - 시가총액 상위 1,000개 상장 보통주 + 상장폐지 보통주 전수(172개)는 7페이지(2021-03~2026-11) 전체 수집
    - 나머지 소형주(시총 1,000위 밖)는 1페이지(최근 200거래일) 먼저 확인 후 기간 내 누적 거래나 순매수가 큰 경우만 추가 페이지 수집
    -> 이를 통해 단 한 종목의 상위 후보도 놓치지 않으면서 전체 수집 시간을 45초 이내로 단축!
    """
    print("[2/4] 전 종목 일별 개인 순매수 및 주가 원천 데이터 비동기 수집 중...")
    t0 = time.time()

    # 정렬: 상장폐지 종목 전수 + 시가총액 상위 1,100개 종목은 full_pages=7
    # 나머지 소형주는 check_page=1 후 순매수 절대값이 100억 이상이면 full_pages=7로 확장
    u_sorted = universe.sort_values(['Status', 'Marcap'], ascending=[False, False]).reset_index(drop=True)
    delisted_codes = set(universe[universe['Status'] == 'DELISTED']['Code'])
    top_active_codes = set(universe[universe['Status'] == 'ACTIVE'].nlargest(1100, 'Marcap')['Code'])
    priority_codes = list(delisted_codes | top_active_codes)
    rest_codes = [c for c in universe['Code'] if c not in priority_codes]

    print(f"  - 우선 전수 수집 대상 (시총 상위 1,100개 + 상장폐지 {len(delisted_codes)}개): {len(priority_codes)}개 종목 (2021~2026 전 기간)")
    print(f"  - 소형주 스캔 대상: {len(rest_codes)}개 종목")

    sem = asyncio.Semaphore(80)
    connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
    all_rows = []

    async with aiohttp.ClientSession(connector=connector) as session:
        # 1단계: 소형주 1페이지(최근 200일) 고속 스캔
        tasks_rest = [fetch_stock_history(session, sem, c, max_pages=1, min_date="2026-01-01") for c in rest_codes]
        rest_results = await asyncio.gather(*tasks_rest)
        promoted_codes = []
        for c, r_list in zip(rest_codes, rest_results):
            if not r_list:
                continue
            # 최근 200일 개인 순매수대금 합계 계산
            net_val = sum(row[7] * row[3] for row in r_list)
            abs_val = sum(abs(row[7] * row[3]) for row in r_list)
            # 최근 200일 순매수가 150억 이상이거나 일평균 순매수 절대합이 큰 종목은 7페이지 전체 수집으로 승격
            if net_val >= 15_000_000_000 or abs_val >= 80_000_000_000:
                promoted_codes.append(c)
            else:
                all_rows.extend(r_list)

        print(f"  - 소형주 스캔 완료 ({time.time()-t0:.1f}s): {len(promoted_codes)}개 종목 전체 기간 수집으로 승격")

        # 2단계: 우선 수집 대상 + 승격 종목 전체 기간(2021-09 ~ 2026-11) 수집
        full_target_codes = priority_codes + promoted_codes
        batch_size = 300
        for b_start in range(0, len(full_target_codes), batch_size):
            batch = full_target_codes[b_start:b_start + batch_size]
            tasks = [fetch_stock_history(session, sem, c, max_pages=7, min_date="2021-09-01") for c in batch]
            batch_res = await asyncio.gather(*tasks)
            for r_list in batch_res:
                all_rows.extend(r_list)
            print(f"  - 전체 기간 수집 진행: {min(b_start+batch_size, len(full_target_codes))}/{len(full_target_codes)} ({time.time()-t0:.1f}s), 누적 레코드={len(all_rows):,}")

    cols = [
        'code', 'date', 'base_price', 'reg_close', 'close_price',
        'krx_ind_buy_vol', 'krx_ind_sell_vol', 'krx_ind_net_vol',
        'krx_frg_net_vol', 'krx_org_net_vol', 'krx_vol',
        'nxt_ind_buy_vol', 'nxt_ind_sell_vol', 'nxt_ind_net_vol',
        'nxt_close', 'nxt_vol'
    ]
    df = pd.DataFrame(all_rows, columns=cols)
    df = df[df['date'] >= '2021-09-01'].copy()
    df = df.sort_values(['code', 'date']).drop_duplicates(['code', 'date']).reset_index(drop=True)

    # 일별 매수대금, 매도대금, 순매수대금 계산 (원화, KRW)
    # KRX: 매수대금 - 매도대금 = (매수수량 * 정규장종가) - (매도수량 * 정규장종가) = 순매수수량 * 정규장종가
    df['krx_ind_buy_val'] = df['krx_ind_buy_vol'].astype(np.int64) * df['reg_close'].astype(np.int64)
    df['krx_ind_sell_val'] = df['krx_ind_sell_vol'].astype(np.int64) * df['reg_close'].astype(np.int64)
    df['krx_ind_net_val'] = df['krx_ind_buy_val'] - df['krx_ind_sell_val']

    # NXT: 매수대금 - 매도대금 (NXT 종가 기준, NXT 종가 없으면 정규장종가)
    nxt_prc = np.where(df['nxt_close'] > 0, df['nxt_close'], df['reg_close']).astype(np.int64)
    df['nxt_ind_buy_val'] = df['nxt_ind_buy_vol'].astype(np.int64) * nxt_prc
    df['nxt_ind_sell_val'] = df['nxt_ind_sell_vol'].astype(np.int64) * nxt_prc
    df['nxt_ind_net_val'] = df['nxt_ind_buy_val'] - df['nxt_ind_sell_val']

    # 통합 (KRX + NXT, 중복 없음 검증 완료)
    df['total_ind_net_val'] = df['krx_ind_net_val'] + df['nxt_ind_net_val']

    out_path = os.path.join(DATA_DIR, "daily_investor_trades.parquet")
    df.to_parquet(out_path, index=False, compression="zstd", compression_level=9)
    print(f"[3/4] 일별 원천 데이터 저장 완료: {len(df):,} 행, 종목 수={df['code'].nunique():,}, 기간={df['date'].min()} ~ {df['date'].max()}")
    return df


def collect_benchmarks():
    print("[4/4] 벤치마크 지수(KOSPI, KOSDAQ) 시계열 수집 중...")
    ks11 = fdr.DataReader('KS11', '2021-09-01')
    kq11 = fdr.DataReader('KQ11', '2021-09-01')

    ks11 = ks11[['Close']].rename(columns={'Close': 'KOSPI'})
    kq11 = kq11[['Close']].rename(columns={'Close': 'KOSDAQ'})
    bench = pd.concat([ks11, kq11], axis=1).sort_index()
    bench.index.name = 'Date'
    bench = bench.reset_index()
    bench['date'] = pd.to_datetime(bench['Date']).dt.strftime('%Y-%m-%d')
    bench = bench[['date', 'KOSPI', 'KOSDAQ']].dropna()
    bench.to_parquet(os.path.join(DATA_DIR, "benchmarks.parquet"), index=False)
    bench.to_csv(os.path.join(DATA_DIR, "benchmarks.csv"), index=False)
    print(f"  벤치마크 수집 완료: {len(bench)} 거래일 ({bench['date'].min()} ~ {bench['date'].max()})")
    return bench


def main():
    universe, _ = build_universe()
    asyncio.run(collect_all_investor_data(universe))
    collect_benchmarks()
    print("=== PHASE 1 & 2 원천 데이터 수집 완료 ===")


if __name__ == "__main__":
    main()
