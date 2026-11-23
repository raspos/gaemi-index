#!/usr/bin/env python3
"""Two-date KOSPI/KOSDAQ shared-listed cohort export; no edits to GAEMI production data."""
from __future__ import annotations
import csv, datetime, hashlib, os, pathlib, urllib.request
import duckdb

ROOT=pathlib.Path("comparison_export")
ROOT.mkdir(exist_ok=True)
BASE="https://raw.githubusercontent.com/FinanceData/marcap/master/data"
DATES={2025:"2025-06-02",2026:"2026-11-20"}

def download(y):
    dst=ROOT/f"marcap-{y}.parquet"
    url=f"{BASE}/marcap-{y}.parquet"
    if not dst.exists():
        print("DOWNLOAD",url,flush=True)
        req=urllib.request.Request(url,headers={"User-Agent":"GAEMI-data-audit/1.0"})
        with urllib.request.urlopen(req,timeout=300) as src, open(dst,"wb") as out:
            while True:
                block=src.read(1024*1024)
                if not block: break
                out.write(block)
    print("SIZE",y,dst.stat().st_size,flush=True)
    return dst,url

con=duckdb.connect()
snapshots={}
sources={}
for year, day in DATES.items():
    file,url=download(year)
    sources[year]=url
    schema=con.execute("DESCRIBE SELECT * FROM read_parquet(?)",[str(file)]).fetchall()
    print("SCHEMA",year,[(r[0],r[1]) for r in schema],flush=True)
    # Fetch only the requested trading date, never interpolate missing-date observations.
    qry = """
      SELECT CAST(Code AS VARCHAR) AS code,
             CAST(Name AS VARCHAR) AS name,
             CAST(Market AS VARCHAR) AS market,
             TRY_CAST(Close AS DOUBLE) AS close,
             TRY_CAST(Marcap AS DOUBLE) AS marcap,
             TRY_CAST(Stocks AS DOUBLE) AS shares
      FROM read_parquet(?)
      WHERE CAST(Date AS DATE) = CAST(? AS DATE)
        AND Market IN ('KOSPI', 'KOSDAQ')
    """
    rows=con.execute(qry,[str(file),day]).fetchall()
    print("DATE",day,"ROWS",len(rows),"MARKETS",con.execute("""
      SELECT Market, count(*) FROM read_parquet(?)
      WHERE CAST(Date AS DATE) = CAST(? AS DATE)
      GROUP BY Market ORDER BY Market
    """,[str(file),day]).fetchall(),flush=True)
    if len(rows) < 2000:
        raise RuntimeError(f"Too few snapshot entries on {day}: {len(rows)}; verify source dates and schema.")
    dat={}
    for code,name,market,close,cap,shares in rows:
        code=str(code).strip().zfill(6)
        if code in dat:
            raise RuntimeError(f"duplicate code {code} on {day}")
        dat[code]=(name,market,close,cap,shares)
    snapshots[year]=dat

c25,c26=snapshots[2025],snapshots[2026]
matched=sorted(set(c25)&set(c26))
only25=sorted(set(c25)-set(c26))
only26=sorted(set(c26)-set(c25))
print("MATCHED",len(matched),"ONLY2025",len(only25),"ONLY2026",len(only26),flush=True)
if len(matched)<1800:
    raise RuntimeError("Too few shared-listed tickers; inspect Market coding.")
allcols=["종목코드","종목명_2025","종목명_2026","시장_2025","시장_2026","종가_20250602_원","종가_20261120_원","주가변화_원","원시주가수익률_pct","상승하락_원시","상장주식수_2025","상장주식수_2026","주식수증감률_pct","주식수변화_검토","시총원장값_2025","시총원장값_2026","시총원장값_증감","종목명변경","시장변경","원자료_2025","원자료_2026"]
out=ROOT/"matched_stocks.csv"
with open(out,"w",encoding="utf-8-sig",newline="") as f:
    w=csv.writer(f)
    w.writerow(allcols)
    for c in matched:
        n0,m0,p0,v0,s0=c25[c]; n1,m1,p1,v1,s1=c26[c]
        valid=(p0 is not None and p1 is not None and p0>0 and p1>0)
        chg=(p1-p0) if valid else ""
        ret=100*(p1/p0-1) if valid else ""
        direction=("상승" if chg>0 else "하락" if chg<0 else "보합") if valid else "가격없음"
        sc=100*(s1/s0-1) if s0 and s1 else ""
        changed= "검토필요" if sc!="" and abs(sc)>1 else ""
        w.writerow([c,n0,n1,m0,m1,p0,p1,chg,ret,direction,s0,s1,sc,changed,v0,v1,(v1-v0 if v0 is not None and v1 is not None else ""),"예" if n0!=n1 else "","예" if m0!=m1 else "",sources[2025],sources[2026]])

def excl(path,codes,lookup,year):
    with open(ROOT/path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow(["종목코드",f"종목명_{year}",f"시장_{year}",f"종가_{year}_원",f"상장주식수_{year}",f"시총원장값_{year}"])
        for c in codes:
            n,m,p,v,s=lookup[c];w.writerow([c,n,m,p,s,v])
excl("only_2025.csv",only25,c25,2025)
excl("only_2026.csv",only26,c26,2026)

stats={}
for market in ("KOSPI","KOSDAQ"):
    group=[c for c in matched if c26[c][1]==market]
    up=down=flat=missing=flag=0
    for c in group:
        p0,p1=c25[c][2],c26[c][2]
        s0,s1=c25[c][4],c26[c][4]
        if s0 and s1 and abs(s1/s0-1)>0.01: flag+=1
        if not p0 or not p1:missing+=1
        elif p1>p0: up+=1
        elif p1<p0:down+=1
        else:flat+=1
    stats[market]=(len(group),up,down,flat,missing,flag)
print("STATS",stats,flush=True)
with open(ROOT/"audit_summary.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.writer(f);w.writerow(["시장_2026","두날짜공통상장수","원시주가_상승","원시주가_하락","원시주가_보합","가격없음","주식수변화1pct초과_검토필요","데이터출처","주의사항"])
    for m,v in stats.items():
        w.writerow([m,*v,"FinanceData/marcap; 원천 KRX","원시종가 비교. 액면분할·병합·증자 등 기업행동 보정 전. 검토필요 행은 기사 확정 집계에 그대로 사용 금지."])
print("EXPORT_READY",out,flush=True)
