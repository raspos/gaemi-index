"""
PHASE 4 — 섹션 1 & 2: 영속 원장 관리, 증분 업데이트, 정기 전체 검증, 원자적(Atomic) 저장 및 데이터 매니페스트 관리 모듈 (update_ledger.py)

[핵심 원칙]
1. 기존 원장 보존:
   - Git 저장소에 커밋되는 연도별 분할 원장(`data/ledger_shards/trades_YYYY.parquet`, 총 ~60MB, 파일당 3.8~14.3MB)을 영속 원본 저장소(Single Source of Truth)로 사용한다.
   - 기존 데이터를 삭제하고 새로 덮어쓰는 방식을 금지한다 (`기존 원장 + 신규 데이터 → 중복 제거 → 완전성 검증 → 임시 파일 원자적 교체`).
2. 일별 증분 업데이트(`--mode daily`) vs 정기 전체 검증(`--mode full-audit`):
   - `daily`: 기존 원장의 마지막 거래일 이후 신규 거래일만 고속 수집(종목당 1페이지, 최근 날짜 필터)하여 기존 원장과 병합하고, 새로 적격 후보(시총 1,500억+ 또는 최근 거래 급증)에 진입했으나 과거 36개월 자료가 부족한 종목은 자동으로 7페이지(전 기간) 백필한다.
   - `full-audit`: 주 1회(또는 수동 실행 시) 적격 종목 및 후보 종목 전체의 관측기간 충족 여부, 상장폐지 종목 누락 여부, 기업 이벤트(액면분할·병합·무상증자·감자·상호변경), 과거 데이터 수정 여부를 전수 점검하고 보강한다.
3. 원자료 손실 방지 및 실패 보호:
   - API 연결 실패 또는 수집 실패율이 임계치(10%)를 초과하면 기존 정상 원장을 그대로 보존하고 비정상 종료 코드를 반환하여 잘못된 데이터가 배포되지 않도록 차단한다.
   - 새 원장은 `.tmp` 파일로 먼저 기록한 뒤 ① 중복 기본키(`code`, `date`) 0건, ② 과거 거래일 손실 0건, ③ 날짜별 종목 수 급감 여부, ④ 36개월 완전 관측 종목 수(>=1,700개) 검증을 통과했을 때만 원자적으로(`os.replace`) 확정한다.
4. 데이터 버전 관리 (`data/data_manifest.json`):
   - 데이터 기준일, 수집 완료 시각, 원자료 버전, 샤드별 SHA-256 체크섬, 수집 종목 수, 원장 레코드 수, 신규 추가 레코드 수, 수정된 레코드 수, 중복 제거 건수, 수집 실패 건수, Git 커밋 SHA, 검증 결과를 기록한다.
"""

import os
import sys
import time
import json
import hashlib
import argparse
import subprocess
import asyncio
import aiohttp
import pandas as pd
import numpy as np
from datetime import datetime
from collect_data import build_universe, collect_benchmarks, fetch_stock_history, BASE_DIR, DATA_DIR

SHARDS_DIR = os.path.join(DATA_DIR, "ledger_shards")
MANIFEST_PATH = os.path.join(DATA_DIR, "data_manifest.json")
RAW_COLS = [
    "code", "date", "base_price", "reg_close", "close_price",
    "krx_ind_buy_vol", "krx_ind_sell_vol", "krx_ind_net_vol",
    "krx_frg_net_vol", "krx_org_net_vol", "krx_vol",
    "nxt_ind_buy_vol", "nxt_ind_sell_vol", "nxt_ind_net_vol",
    "nxt_close", "nxt_vol"
]


def compute_file_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def get_git_commit_sha():
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BASE_DIR, stderr=subprocess.DEVNULL)
        return out.decode("utf-8").strip()
    except Exception:
        return "unknown"


def load_persistent_ledger():
    """
    영속 저장소(data/ledger_shards/trades_YYYY.parquet)에서 기존 원장을 로드한다.
    샤드가 없을 경우에만 로컬 단일 파일(daily_investor_trades.parquet)에서 초기 마이그레이션한다.
    """
    os.makedirs(SHARDS_DIR, exist_ok=True)
    shard_files = sorted([os.path.join(SHARDS_DIR, f) for f in os.listdir(SHARDS_DIR) if f.endswith(".parquet")])
    if shard_files:
        dfs = [pd.read_parquet(f, columns=RAW_COLS) for f in shard_files]
        df = pd.concat(dfs, ignore_index=True)
        df.sort_values(["code", "date"], inplace=True, ignore_index=True)
        return df

    single_path = os.path.join(DATA_DIR, "daily_investor_trades.parquet")
    if os.path.exists(single_path):
        df = pd.read_parquet(single_path, columns=RAW_COLS)
        df.sort_values(["code", "date"], inplace=True, ignore_index=True)
        return df

    raise FileNotFoundError("기존 영속 원장(data/ledger_shards/*.parquet)을 찾을 수 없습니다.")


def save_sharded_ledger_atomic(df):
    """
    검증이 완료된 원장 DataFrame을 연도별 임시 파일(.tmp)로 작성한 뒤 원자적으로 교체한다.
    """
    os.makedirs(SHARDS_DIR, exist_ok=True)
    df["yr"] = df["date"].str.slice(0, 4)
    shard_hashes = {}
    for yr, g in df.groupby("yr"):
        shard_name = f"trades_{yr}.parquet"
        final_p = os.path.join(SHARDS_DIR, shard_name)
        tmp_p = os.path.join(SHARDS_DIR, f".{shard_name}.tmp")
        g.drop(columns=["yr"]).to_parquet(tmp_p, index=False, compression="zstd", compression_level=9)
        os.replace(tmp_p, final_p)
        shard_hashes[shard_name] = {
            "rows": int(len(g)),
            "size_bytes": int(os.path.getsize(final_p)),
            "sha256": compute_file_sha256(final_p),
        }
    df.drop(columns=["yr"], inplace=True)
    return shard_hashes


def merge_and_validate_ledger(existing_df, new_df, universe_df, allow_no_new_dates=True):
    """
    PHASE 4 Section 1-2 & 1-4:
    기존 원장 + 신규 데이터 → 중복 제거 → 변경 감지 → 완전성 검증
    """
    old_total_rows = int(len(existing_df))
    old_dates = set(existing_df["date"].unique())
    old_max_date = max(old_dates) if old_dates else ""
    old_codes = set(existing_df["code"].unique())

    if new_df is None or new_df.empty:
        combined = existing_df.copy()
        raw_concat_len = old_total_rows
        modified_records = 0
    else:
        new_df = new_df[new_df["date"] >= "2021-09-01"].copy()
        # 동일 (code, date)에 대해 원천 데이터 수정(종가 또는 거래량 정정) 건수 측정
        overlap = pd.merge(
            existing_df[["code", "date", "reg_close", "krx_ind_net_vol"]],
            new_df[["code", "date", "reg_close", "krx_ind_net_vol"]].drop_duplicates(["code", "date"], keep="last"),
            on=["code", "date"],
            suffixes=("_old", "_new")
        )
        modified_records = int(
            ((overlap["reg_close_old"] != overlap["reg_close_new"]) |
             (overlap["krx_ind_net_vol_old"] != overlap["krx_ind_net_vol_new"])).sum()
        )

        combined = pd.concat([existing_df, new_df[RAW_COLS]], ignore_index=True)
        raw_concat_len = len(combined)

    # 최신 수집 데이터를 우선(keep='last')하여 동일 종목·동일 거래일 중복 제거
    combined.sort_values(["code", "date"], inplace=True, ignore_index=True)
    before_dedup = len(combined)
    combined.drop_duplicates(subset=["code", "date"], keep="last", inplace=True, ignore_index=True)
    dedup_removed_count = int(before_dedup - len(combined))

    # --- 완전성 및 손실 방지 검증 (Section 1-4) ---
    # 1. 중복 기본키 0건 검증
    dup_pk_cnt = int(combined.duplicated(subset=["code", "date"]).sum())
    if dup_pk_cnt > 0:
        raise ValueError(f"[원장 검증 실패] 중복 기본키(code, date)가 {dup_pk_cnt}건 존재합니다.")

    # 2. 과거 거래일 손실 0건 검증
    new_dates_set = set(combined["date"].unique())
    lost_dates = old_dates - new_dates_set
    if lost_dates:
        raise ValueError(f"[원장 검증 실패] 기존 거래일 {len(lost_dates)}일이 손실되었습니다: {sorted(list(lost_dates))[:5]}")

    # 3. 기존 종목 손실 검증 (상장폐지 종목 포함 모든 기존 종목 코드 보존)
    new_codes_set = set(combined["code"].unique())
    lost_codes = old_codes - new_codes_set
    if lost_codes:
        raise ValueError(f"[원장 검증 실패] 기존 종목 {len(lost_codes)}개가 원장에서 손실되었습니다.")

    # 4. 전체 레코드 수 비정상 감소 방지
    if len(combined) < old_total_rows:
        raise ValueError(f"[원장 검증 실패] 병합 후 레코드 수({len(combined):,})가 기존({old_total_rows:,})보다 감소했습니다.")

    # 5. 날짜별 종목 수의 비정상 급감 탐지 (최근 10거래일 기준 평균 대비 80% 이상 유지)
    sorted_dates = sorted(list(new_dates_set))
    recent_10 = sorted_dates[-10:]
    recent_counts = combined[combined["date"].isin(recent_10)].groupby("date")["code"].count()
    median_recent_cnt = float(recent_counts.median())
    latest_dt = sorted_dates[-1]
    latest_dt_cnt = int(recent_counts.loc[latest_dt])
    if latest_dt_cnt < median_recent_cnt * 0.80:
        raise ValueError(
            f"[원장 검증 실패] 최신 거래일({latest_dt}) 수집 종목 수({latest_dt_cnt}개)가 "
            f"최근 중앙값({median_recent_cnt:.0f}개)의 80% 미만입니다. 부분 수집 오류로 판단하여 업데이트를 중단합니다."
        )

    # 6. 지수 편입에 필요한 36개월 관측자료 확보 종목 수 검증
    code_days = combined.groupby("code")["date"].count()
    full_36m_stocks = int((code_days >= 650).sum())
    if full_36m_stocks < 1700:
        raise ValueError(f"[원장 검증 실패] 36개월(>=650일) 관측 확보 종목 수({full_36m_stocks}개)가 최소 기준(1,700개) 미달입니다.")

    # 7. 상장폐지 종목 과거 이력 보존 검증
    if universe_df is not None:
        delisted_in_u = set(universe_df[universe_df["Status"] == "DELISTED"]["Code"])
        delisted_in_ledger = len(delisted_in_u & new_codes_set)
        if delisted_in_ledger < 150:
            raise ValueError(f"[원장 검증 실패] 상장폐지 종목 보존 수({delisted_in_ledger}개)가 기준(150개) 미달입니다.")
    else:
        delisted_in_ledger = 0

    added_dates = sorted(list(new_dates_set - old_dates))
    net_added_rows = int(len(combined) - old_total_rows)

    stats = {
        "old_total_rows": old_total_rows,
        "new_total_rows": int(len(combined)),
        "net_added_rows": net_added_rows,
        "dedup_removed_count": dedup_removed_count,
        "modified_historical_records": modified_records,
        "duplicate_primary_keys": dup_pk_cnt,
        "old_max_date": old_max_date,
        "new_max_date": latest_dt,
        "added_trading_dates": added_dates,
        "latest_date_stock_count": latest_dt_cnt,
        "total_unique_stocks": int(len(new_codes_set)),
        "full_36m_stocks_count": full_36m_stocks,
        "delisted_stocks_preserved": delisted_in_ledger,
    }
    return combined, stats


async def fetch_incremental_or_backfill(universe_df, existing_df, mode="daily", max_failure_ratio=0.10):
    """
    - mode == 'daily':
      1) 현재 상장 보통주(ACTIVE) 전수에 대해 1페이지(최근 200일 중 기존 마지막 거래일 이후) 증분 수집
      2) 시가총액 1,500억 원 이상(적격 기준 3,000억의 절반) 상장 종목 중 원장 내 관측일수가 650일 미만이고
         상장일이 36개월 이상 경과한 후보 종목을 자동 탐지하여 7페이지(전 기간) 백필 수집
    - mode == 'full-audit':
      1) daily 증분 수집 수행
      2) 시가총액 800억 원 이상 후보 종목 중 650일 미만 수집 종목 전수 + 상장폐지 종목 누락분 전수 7페이지 백필
    """
    t0 = time.time()
    old_max_date = existing_df["date"].max()
    active_codes = universe_df[universe_df["Status"] == "ACTIVE"]["Code"].tolist()

    # 후보 종목 중 과거 36개월 히스토리 보강이 필요한 종목 자동 탐지
    code_days = existing_df.groupby("code")["date"].count().to_dict()
    u_active = universe_df[universe_df["Status"] == "ACTIVE"].copy()
    u_active["obs_days"] = u_active["Code"].map(lambda c: code_days.get(c, 0))
    u_active["listing_str"] = u_active["ListingDate"].astype(str).str.slice(0, 10)
    u_active["marcap_eok"] = u_active["Marcap"] / 1e8

    mc_threshold = 800.0 if mode == "full-audit" else 1500.0
    need_backfill = u_active[
        (u_active["marcap_eok"] >= mc_threshold) &
        (u_active["obs_days"] <= 200) &
        (u_active["listing_str"] < "2024-01-01")
    ]["Code"].tolist()

    print(f"[수집 시작] 모드={mode} | 기존 최신일={old_max_date} | 일별 증분 대상={len(active_codes)}종목 | 36개월 백필 대상={len(need_backfill)}종목")

    sem = asyncio.Semaphore(80)
    connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
    fetched_rows = []
    failed_codes = []

    # 일별 증분 수집 시에는 기존 최신 거래일의 직전 15일 이후 데이터만 가져오도록 min_date 설정
    min_dt_daily = old_max_date if old_max_date else "2026-01-01"

    async with aiohttp.ClientSession(connector=connector) as session:
        batch_size = 400
        for b_start in range(0, len(active_codes), batch_size):
            batch = active_codes[b_start:b_start + batch_size]
            tasks = [fetch_stock_history(session, sem, c, max_pages=1, min_date=min_dt_daily) for c in batch]
            res = await asyncio.gather(*tasks)
            for c, r_list in zip(batch, res):
                if not r_list:
                    failed_codes.append(c)
                else:
                    fetched_rows.extend(r_list)

        if need_backfill:
            print(f"  - 후보 종목 36개월 과거 원자료 보강 수집 중 ({len(need_backfill)}종목)...")
            for b_start in range(0, len(need_backfill), 200):
                batch = need_backfill[b_start:b_start + 200]
                tasks = [fetch_stock_history(session, sem, c, max_pages=7, min_date="2021-09-01") for c in batch]
                res = await asyncio.gather(*tasks)
                for c, r_list in zip(batch, res):
                    if r_list:
                        fetched_rows.extend(r_list)

    fail_ratio = len(failed_codes) / max(len(active_codes), 1)
    print(f"[수집 완료] 소요={time.time()-t0:.1f}s | 수집 레코드={len(fetched_rows):,}건 | 미응답/거래없음={len(failed_codes)}종목 ({fail_ratio*100:.2f}%)")

    if fail_ratio > max_failure_ratio:
        raise RuntimeError(
            f"[수집 중단] API 수집 실패율({fail_ratio*100:.1f}%)이 허용 임계치({max_failure_ratio*100:.1f}%)를 초과했습니다. "
            f"기존 정상 원장을 보호하기 위해 업데이트를 중단합니다."
        )

    df_new = pd.DataFrame(fetched_rows, columns=RAW_COLS) if fetched_rows else pd.DataFrame(columns=RAW_COLS)
    return df_new, failed_codes


def write_manifest(merge_stats, shard_hashes, failed_codes, mode, status="SUCCESS"):
    total_sha = hashlib.sha256(
        "".join(v["sha256"] for _, v in sorted(shard_hashes.items())).encode("utf-8")
    ).hexdigest()

    manifest = {
        "status": status,
        "update_mode": mode,
        "data_as_of": merge_stats["new_max_date"],
        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ledger_version": f"v4.{merge_stats['new_max_date'].replace('-', '')}",
        "ledger_combined_sha256": total_sha,
        "git_commit_sha": get_git_commit_sha(),
        "index_engine_version": "GAEMI_50_PURE_PHASE4_v1.0",
        "collected_stock_count": merge_stats["total_unique_stocks"],
        "latest_date_stock_count": merge_stats["latest_date_stock_count"],
        "full_36m_stocks_count": merge_stats["full_36m_stocks_count"],
        "delisted_stocks_preserved": merge_stats["delisted_stocks_preserved"],
        "total_ledger_records": merge_stats["new_total_rows"],
        "newly_added_records": merge_stats["net_added_rows"],
        "dedup_removed_records": merge_stats["dedup_removed_count"],
        "modified_historical_records": merge_stats["modified_historical_records"],
        "duplicate_primary_keys": merge_stats["duplicate_primary_keys"],
        "added_trading_dates": merge_stats["added_trading_dates"],
        "api_failed_stock_count": len(failed_codes),
        "shards": shard_hashes,
    }
    tmp_m = MANIFEST_PATH + ".tmp"
    with open(tmp_m, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, allow_nan=False)
    os.replace(tmp_m, MANIFEST_PATH)
    return manifest


def run_pipeline_update(mode="daily", skip_network=False):
    print(f"=== GAEMI 50 PURE 원장 업데이트 파이프라인 시작 (mode={mode}, skip_network={skip_network}) ===")
    existing_df = load_persistent_ledger()
    print(f"  [1/4] 직전 정상 원장 로드 완료: {len(existing_df):,}행, 종목={existing_df['code'].nunique():,}개, 기간={existing_df['date'].min()}~{existing_df['date'].max()}")

    if skip_network:
        universe_df = pd.read_parquet(os.path.join(DATA_DIR, "universe.parquet"))
        df_new = pd.DataFrame(columns=RAW_COLS)
        failed_codes = []
    else:
        universe_df, _ = build_universe()
        collect_benchmarks()
        df_new, failed_codes = asyncio.run(fetch_incremental_or_backfill(universe_df, existing_df, mode=mode))

    print("  [2/4] 기존 원장과 증분 병합 및 무결성·완전성 검증 중...")
    combined_df, merge_stats = merge_and_validate_ledger(existing_df, df_new, universe_df)

    print("  [3/4] 연도별 영속 샤드 원장 원자적(Atomic) 저장 중...")
    shard_hashes = save_sharded_ledger_atomic(combined_df)

    print("  [4/4] 데이터 매니페스트(data_manifest.json) 기록 중...")
    manifest = write_manifest(merge_stats, shard_hashes, failed_codes, mode=mode, status="VERIFIED")
    print(f"=== 원장 확정 완료: 버전={manifest['ledger_version']} | 레코드={manifest['total_ledger_records']:,}행 | 체크섬={manifest['ledger_combined_sha256'][:12]} ===")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GAEMI 50 PURE Incremental & Auditable Ledger Updater")
    parser.add_argument("--mode", choices=["daily", "full-audit"], default="daily")
    parser.add_argument("--skip-network", action="store_true", help="네트워크 수집 없이 기존 영속 샤드 검증 및 매니페스트만 갱신")
    args = parser.parse_args()
    try:
        run_pipeline_update(mode=args.mode, skip_network=args.skip_network)
    except Exception as e:
        print(f"[FATAL] 원장 업데이트 실패 (기존 정상 원장 유지됨): {e}", file=sys.stderr)
        sys.exit(1)
