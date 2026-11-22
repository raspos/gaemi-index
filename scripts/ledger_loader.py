"""
공통 영속 원장 로더 (scripts/ledger_loader.py)

[PHASE 8 섹션 1]
- 영속 샤드 원장(data/ledger_shards/trades_*.parquet)을 최우선으로 로드한다.
- 단일 파일(data/daily_investor_trades.parquet)은 샤드가 전혀 없는 레거시 호환 목적으로만 사용한다.
- 무결성 검증:
  1) data_manifest.json 존재 시 샤드별 SHA-256 체크섬 검증
  2) 데이터 기준일(max(date) == manifest['data_as_of']) 일치 확인
  3) (code, date) 기본키 중복 검사
  4) 원장 부재 시 명확한 FileNotFoundError 출력
"""

import os
import json
import hashlib
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SHARDS_DIR = os.path.join(DATA_DIR, "ledger_shards")
MANIFEST_PATH = os.path.join(DATA_DIR, "data_manifest.json")


def _sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def load_raw_ledger(needed_cols=None, verify_integrity=True, sort_by_code_date=False):
    """
    영속 샤드 원장 우선 로드 및 무결성/체크섬/기준일/중복 검사.
    """
    shard_files = []
    if os.path.exists(SHARDS_DIR):
        shard_files = sorted(
            [os.path.join(SHARDS_DIR, f) for f in os.listdir(SHARDS_DIR) if f.endswith(".parquet") and not f.startswith(".")]
        )

    if shard_files:
        # 1) 체크섬 및 매니페스트 검증
        manifest = None
        if verify_integrity and os.path.exists(MANIFEST_PATH):
            with open(MANIFEST_PATH, encoding="utf-8") as f:
                manifest = json.load(f)
            exp_shards = manifest.get("shards", {})
            for fp in shard_files:
                fname = os.path.basename(fp)
                if fname in exp_shards:
                    actual_sha = _sha256_file(fp)
                    exp_sha = exp_shards[fname].get("sha256")
                    if exp_sha and actual_sha != exp_sha:
                        raise ValueError(
                            f"[원장 무결성 오류] 샤드 체크섬 불일치: {fname} "
                            f"(기대={exp_sha[:12]}..., 실제={actual_sha[:12]}...)"
                        )

        # 2) 샤드 로드 (code, date는 중복·기준일 검증을 위해 최소 확보)
        read_cols = None
        if needed_cols is not None:
            read_cols = list(dict.fromkeys(["code", "date"] + list(needed_cols)))
        dfs = [pd.read_parquet(f, columns=read_cols) for f in shard_files]
        trades = pd.concat(dfs, ignore_index=True)

        if verify_integrity:
            # 3) 기본키 중복 검사
            dup_cnt = int(trades.duplicated(subset=["code", "date"]).sum())
            if dup_cnt > 0:
                raise ValueError(f"[원장 무결성 오류] (code, date) 중복 레코드 {dup_cnt}건 발견")

            # 4) 기준일 일치 확인
            if manifest and manifest.get("data_as_of"):
                actual_max_dt = str(trades["date"].max())
                exp_max_dt = str(manifest["data_as_of"])
                if actual_max_dt != exp_max_dt:
                    raise ValueError(
                        f"[원장 무결성 오류] 데이터 기준일 불일치: 원장={actual_max_dt} vs 매니페스트={exp_max_dt}"
                    )

        if needed_cols is not None:
            trades = trades[list(needed_cols)]

        if sort_by_code_date:
            trades.sort_values(["code", "date"], inplace=True, ignore_index=True)
        return trades

    # 레거시 단일 파일 fallback (샤드가 없을 때만 호환용으로 사용)
    single_path = os.path.join(DATA_DIR, "daily_investor_trades.parquet")
    if os.path.exists(single_path):
        trades = pd.read_parquet(single_path, columns=needed_cols)
        if verify_integrity and "code" in trades.columns and "date" in trades.columns:
            dup_cnt = int(trades.duplicated(subset=["code", "date"]).sum())
            if dup_cnt > 0:
                raise ValueError(f"[원장 무결성 오류] 단일 원장 (code, date) 중복 {dup_cnt}건 발견")
        if sort_by_code_date and "code" in trades.columns and "date" in trades.columns:
            trades.sort_values(["code", "date"], inplace=True, ignore_index=True)
        return trades

    raise FileNotFoundError(
        f"[원장 부재 오류] 영속 샤드 원장({SHARDS_DIR}/*.parquet) 및 "
        f"레거시 단일 원장({single_path})을 모두 찾을 수 없습니다."
    )
