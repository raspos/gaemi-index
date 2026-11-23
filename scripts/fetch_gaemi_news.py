"""
scripts/fetch_gaemi_news.py

개미 지수(GAEMI INDEX) 47개 언론사 화이트리스트 기반 뉴스 수집 및 일별 매핑 모듈
- 47개 언론사(종합지, 경제지, 지상파, 종편, 통신사, IT/경제전문) 화이트리스트 검증
- 네이버 뉴스 검색 API HUB 및 백업 RSS 수집
- 개인투자자 수급(개인 순매수, 개미투자자, 수급 집중 등), 주요 순매수 상위 종목, 업종별 키워드 매칭
- 중복 제거 (URL 기준, 정규화 제목 기준)
- 거래일 및 변곡점 날짜별 기사 인덱싱 (by_date)
- 독립적 실행 및 안전한 예외 처리 (뉴스 수집 실패 시에도 지수 파이프라인 중단 방지)
"""

import os
import re
import sys
import json
import time
import html
import hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import requests
import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DATA_DIR = os.path.join(BASE_DIR, "data")
DOCS_DATA_DIR = os.path.join(BASE_DIR, "docs", "data")
OUTPUT_JSON = os.path.join(DATA_DIR, "gaemi_news.json")
OUTPUT_JS = os.path.join(DOCS_DATA_DIR, "gaemi_news.js")

KST = timezone(timedelta(hours=9))

def now_kst():
    return datetime.now(KST)

def load_env():
    env_candidates = [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(os.path.dirname(BASE_DIR), "joongang-bokwatch", "joongang-bokwatch", ".env")
    ]
    for env_path in env_candidates:
        if os.path.exists(env_path):
            with open(env_path, encoding='utf-8-sig') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        k, v = line.split('=', 1)
                        k, v = k.strip(), v.strip('"\' ')
                        if not os.environ.get(k):
                            os.environ[k] = v

class PressMatcher:
    def __init__(self):
        yaml_path = os.path.join(DATA_DIR, "press.yaml")
        verified_path = os.path.join(DATA_DIR, "press_verified.json")
        
        self.outlets = {}
        if os.path.exists(yaml_path):
            with open(yaml_path, encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
                for o in cfg.get('outlets', []):
                    self.outlets[o['id']] = o

        self.verified_domains = {}
        if os.path.exists(verified_path):
            with open(verified_path, encoding='utf-8') as f:
                vdata = json.load(f)
                self.verified_domains = vdata.get('domains', {})

        # Domain to outlet mapping
        self.domain_to_outlet = {}
        for domain, info in self.verified_domains.items():
            if info.get('verified') and info.get('outlet') in self.outlets:
                self.domain_to_outlet[domain.lower()] = self.outlets[info['outlet']]

        # Fallback aliases
        self.alias_to_outlet = {}
        for oid, o in self.outlets.items():
            for a in [o['name'], o.get('name_en', ''), *o.get('aliases', [])]:
                clean_a = re.sub(r"[\s\-_·.\[\]()]", "", a).lower()
                if clean_a:
                    self.alias_to_outlet[clean_a] = o

    def extract_domain(self, url):
        m = re.match(r"https?://([^/:?#]+)", url or "")
        h = m.group(1).lower() if m else ""
        return re.sub(r"^(www|m|mobile)\.", "", h)

    def match(self, url, title="", press_hint=""):
        host = self.extract_domain(url)
        # 1. Match verified domain
        parts = host.split(".")
        for i in range(len(parts) - 1):
            cand = ".".join(parts[i:])
            if cand in self.domain_to_outlet:
                return self.domain_to_outlet[cand]

        # 2. Match press_hint or alias
        for raw in [press_hint, host]:
            clean_k = re.sub(r"[\s\-_·.\[\]()]", "", raw or "").lower()
            if clean_k in self.alias_to_outlet:
                return self.alias_to_outlet[clean_k]

        return None

def clean_html(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())

def norm_title(title):
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|[\"'“”‘’…·,.!?]", "", title or "")
    return re.sub(r"\s+", "", t)[:35]

# Top stocks to recognize
WATCHED_STOCKS = [
    ("삼성전자", "반도체"),
    ("SK하이닉스", "반도체"),
    ("삼성전기", "전자부품/IT"),
    ("두산에너빌리티", "기계/중공업"),
    ("대덕전자", "전자부품/IT"),
    ("한화솔루션", "화학/소재"),
    ("삼성SDI", "2차전지"),
    ("심텍", "전자부품/IT"),
    ("주성엔지니어링", "반도체"),
    ("이수페타시스", "전자부품/IT"),
    ("SK이노베이션", "2차전지"),
    ("LG에너지솔루션", "2차전지"),
    ("에코프로", "2차전지"),
    ("에코프로비엠", "2차전지"),
    ("포스코홀딩스", "철강/금속"),
    ("POSCO홀딩스", "철강/금속"),
    ("현대차", "자동차/부품"),
    ("기아", "자동차/부품"),
    ("카카오", "플랫폼/소프트웨어"),
    ("NAVER", "플랫폼/소프트웨어"),
    ("셀트리온", "바이오/제약"),
    ("삼성바이오로직스", "바이오/제약"),
    ("알테오젠", "바이오/제약"),
    ("HLB", "바이오/제약"),
    ("한미반도체", "반도체")
]

SECTOR_KEYWORDS = {
    "반도체": ["반도체", "HBM", "D램", "파운드리"],
    "2차전지": ["2차전지", "이차전지", "배터리", "양극재"],
    "바이오/제약": ["바이오", "제약", "임상", "신약"],
    "자동차/부품": ["자동차", "완성차", "현대차", "전기차"],
    "전자부품/IT": ["전자부품", "기판", "PCB", "적층세라믹"],
    "기계/중공업": ["원전", "원자력", "조선", "방산", "중공업"]
}

def tag_article(title, summary):
    full_text = f"{title} {summary}"
    stocks_found = []
    sectors_found = set()
    
    for s_name, s_sec in WATCHED_STOCKS:
        if s_name in full_text:
            stocks_found.append(s_name)
            sectors_found.add(s_sec)

    for sec, kws in SECTOR_KEYWORDS.items():
        if any(kw in full_text for kw in kws):
            sectors_found.add(sec)

    keywords = []
    if any(k in full_text for k in ["순매수", "매수세", "사들인", "매집"]):
        keywords.append("순매수")
    if any(k in full_text for k in ["개미", "개인투자자", "개인"]):
        keywords.append("개인")
    if any(k in full_text for k in ["외국인", "외인"]):
        keywords.append("외국인")
    if any(k in full_text for k in ["기관"]):
        keywords.append("기관")
    if any(k in full_text for k in ["급락", "폭락", "하락장", "약세"]):
        keywords.append("하락장")
    if any(k in full_text for k in ["급등", "상승장", "반등"]):
        keywords.append("상승장")

    return stocks_found, sorted(list(sectors_found)), keywords

def fetch_from_naver(cid, sec, query, display=50):
    url = "https://naverapihub.apigw.ntruss.com/search/v1/news"
    headers = {
        "X-NCP-APIGW-API-KEY-ID": cid,
        "X-NCP-APIGW-API-KEY": sec
    }
    params = {
        "query": query,
        "display": min(display, 100),
        "sort": "date"
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=7)
        if r.status_code == 200:
            return r.json().get("items", [])
        else:
            print(f"  [Naver API Error] query '{query}': {r.status_code} {r.text[:100]}")
            return []
    except Exception as e:
        print(f"  [Naver API Exception] query '{query}': {e}")
        return []

def main():
    load_env()
    t0 = time.time()
    print("=== [GAEMI INDEX] 47개 언론사 뉴스 수집 및 연동 시작 ===")

    matcher = PressMatcher()
    print(f"  등록된 47개 언론사 중 검증 도메인 {len(matcher.domain_to_outlet)}개 로드 완료")

    cid = os.environ.get("NAVER_CLIENT_ID")
    sec = os.environ.get("NAVER_CLIENT_SECRET")

    raw_items = []

    # 1. 네이버 뉴스 API 수집
    if cid and sec:
        queries = [
            "개인 순매수",
            "개미투자자 순매수",
            "삼성전자 개인 순매수",
            "삼성전기 개인 순매수",
            "두산에너빌리티 순매수",
            "반도체 개인 순매수",
            "2차전지 개인 순매수",
            "개인 매수세 코스피",
            "개인 순매도 외국인"
        ]
        print(f"  네이버 검색 API 호출 ({len(queries)}개 쿼리)...")
        for q in queries:
            items = fetch_from_naver(cid, sec, q, display=50)
            for it in items:
                it['query'] = q
            raw_items.extend(items)
            time.sleep(0.15)
        print(f"  네이버 API 수집 원본: {len(raw_items)}건")
    else:
        print("  [알림] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 없음 -> 기존 아카이브 사용")

    # 2. 로컬 백업 naver.jsonl이 있으면 병합
    backup_path = os.path.join(os.path.dirname(BASE_DIR), "joongang-bokwatch", "joongang-bokwatch", "site", "data", "naver.jsonl")
    if os.path.exists(backup_path):
        print(f"  기존 뉴스 아카이브 로드: {backup_path}...")
        with open(backup_path, encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    obj = json.loads(line)
                    t = obj.get("title", "")
                    s = obj.get("summary", "")
                    if any(k in t or k in s for k in ["순매수", "개미", "개인투자자", "삼성전자", "수급"]):
                        raw_items.append({
                            'title': t,
                            'description': s,
                            'originallink': obj.get("link"),
                            'link': obj.get("naver_link") or obj.get("link"),
                            'pubDate': obj.get("published"),
                            'press_hint': obj.get("press"),
                            'query': 'archive'
                        })
                except Exception:
                    pass

    # 3. 47개 화이트리스트 필터링 및 정규화
    processed_articles = []
    seen_links = set()
    seen_titles = set()
    collected_outlets = set()

    for it in raw_items:
        orig_link = it.get("originallink") or it.get("link") or ""
        if not orig_link:
            continue
        if orig_link in seen_links:
            continue

        raw_title = clean_html(it.get("title", ""))
        n_title = norm_title(raw_title)
        if not n_title or n_title in seen_titles:
            continue

        summary = clean_html(it.get("description", ""))
        press_hint = it.get("press_hint", "")

        outlet_info = matcher.match(orig_link, raw_title, press_hint)
        if not outlet_info:
            continue # 화이트리스트 47개 언론사에 속하지 않으면 제외

        # 파싱된 날짜
        pub_raw = it.get("pubDate", "")
        ts = None
        if pub_raw:
            try:
                ts = parsedate_to_datetime(pub_raw).astimezone(KST)
            except Exception:
                try:
                    ts = datetime.fromisoformat(pub_raw).astimezone(KST)
                except Exception:
                    ts = now_kst()
        else:
            ts = now_kst()

        date_str = ts.strftime("%Y-%m-%d")
        time_str = ts.strftime("%H:%M")
        iso_str = ts.isoformat()

        stocks_found, sectors_found, keywords = tag_article(raw_title, summary)

        # 수급 관련성 최소 요건 확인: 키워드 또는 종목이 존재해야 함
        is_relevant = len(keywords) > 0 or len(stocks_found) > 0 or len(sectors_found) > 0
        if not is_relevant:
            continue

        seen_links.add(orig_link)
        seen_titles.add(n_title)
        collected_outlets.add(outlet_info['name'])

        art_id = hashlib.sha1(orig_link.encode()).hexdigest()[:12]
        processed_articles.append({
            'id': art_id,
            'title': raw_title,
            'summary': summary[:250],
            'link': orig_link,
            'outlet_id': outlet_info['id'],
            'outlet_name': outlet_info['name'],
            'outlet_type': outlet_info.get('type', '언론사'),
            'date': date_str,
            'time': time_str,
            'published': iso_str,
            'stocks': stocks_found,
            'sectors': sectors_found,
            'keywords': keywords
        })

    # 최신순 정렬
    processed_articles.sort(key=lambda x: x['published'], reverse=True)

    # 4. 날짜별 인덱스 (by_date)
    by_date = {}
    for art in processed_articles:
        d = art['date']
        if d not in by_date:
            by_date[d] = []
        if len(by_date[d]) < 15: # 날짜당 최대 15개
            by_date[d].append(art)

    print(f"  화이트리스트 통과 및 정제 완료 기사: {len(processed_articles)}건")
    print(f"  수집 성공 언론사: {len(collected_outlets)} / 47곳")
    print(f"  언론사 목록: {', '.join(sorted(collected_outlets))}")

    # 최종 결과 페이로드
    payload = {
        'last_updated': now_kst().isoformat(),
        'total_articles': len(processed_articles),
        'outlets_monitored_count': 47,
        'outlets_collected_count': len(collected_outlets),
        'outlets_collected_names': sorted(list(collected_outlets)),
        'articles': processed_articles[:120], # 최신 120건 보존
        'by_date': by_date
    }

    print(f"  JSON 저장: {OUTPUT_JSON}...")
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"  JS 번들 저장: {OUTPUT_JS}...")
    js_code = f"window.GAEMI_NEWS = {json.dumps(payload, ensure_ascii=False)};\n"
    with open(OUTPUT_JS, 'w', encoding='utf-8') as f:
        f.write(js_code)

    print(f"=== 뉴스 수집 완료 (소요시간: {time.time()-t0:.2f}초) ===")
    return 0

if __name__ == '__main__':
    main()
