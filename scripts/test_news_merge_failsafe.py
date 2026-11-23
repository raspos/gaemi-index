"""
scripts/test_news_merge_failsafe.py

개미 지수 뉴스 수집 영속성, 증분 병합, 중복 제거, 변곡점 보존, 실패 방어(Circuit Breaker) 전수 테스트
"""

import os
import sys
import json
import shutil
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import scripts.fetch_gaemi_news as news_mod

class TestNewsMergeAndFailsafe(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory to test file operations safely
        self.temp_dir = tempfile.mkdtemp()
        self.orig_json = news_mod.OUTPUT_JSON
        self.orig_js = news_mod.OUTPUT_JS
        self.test_json = os.path.join(self.temp_dir, "gaemi_news.json")
        self.test_js = os.path.join(self.temp_dir, "gaemi_news.js")
        news_mod.OUTPUT_JSON = self.test_json
        news_mod.OUTPUT_JS = self.test_js

    def tearDown(self):
        news_mod.OUTPUT_JSON = self.orig_json
        news_mod.OUTPUT_JS = self.orig_js
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_incremental_merge(self):
        """기존 기사가 있을 때 신규 기사가 덮어쓰지 않고 병합되는지 검증"""
        initial_data = {
            "last_updated": "2026-11-20T18:00:00+09:00",
            "last_success_at": "2026-11-20T18:00:00+09:00",
            "total_articles": 1,
            "articles": [
                {
                    "id": "item1",
                    "title": "과거 보존 기사: 개인투자자 코스피 대규모 순매수",
                    "summary": "과거 기사 요약",
                    "link": "https://www.yna.co.kr/view/AKR2026112000001",
                    "outlet_id": "yna",
                    "outlet_name": "연합뉴스",
                    "date": "2026-11-20",
                    "published": "2026-11-20T18:00:00+09:00",
                    "is_inflection": False
                }
            ],
            "by_date": {
                "2026-11-20": ["item1"]
            }
        }
        with open(self.test_json, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, ensure_ascii=False)

        # Mock naver fetch returning 1 new article
        orig_fetch = news_mod.fetch_from_naver
        try:
            news_mod.fetch_from_naver = lambda cid, sec, q, display=50: ([{
                "title": "신규 기사: 삼성전자 개인 순매수 급증",
                "description": "삼성전자 반도체 순매수 요약",
                "originallink": "https://www.sedaily.com/NewsView/TEST001",
                "pubDate": "Mon, 23 Nov 2026 10:00:00 +0900"
            }], None)

            news_mod.main()

            with open(self.test_json, "r", encoding="utf-8") as f:
                res = json.load(f)

            # Both old article and new article must exist
            links = [a["link"] for a in res["articles"]]
            self.assertIn("https://www.yna.co.kr/view/AKR2026112000001", links)
            self.assertIn("https://www.sedaily.com/NewsView/TEST001", links)
            self.assertGreaterEqual(res["total_articles"], 2)
            print("  [PASS] Test 1: 증분 병합 (과거 기사 유지 + 신규 기사 추가 성공)")
        finally:
            news_mod.fetch_from_naver = orig_fetch

    def test_02_deduplication(self):
        """동일 URL 및 정규화된 동일 제목의 중복 제거 검증"""
        initial_data = {
            "last_updated": "2026-11-23T09:00:00+09:00",
            "total_articles": 1,
            "articles": [
                {
                    "id": "dup1",
                    "title": "[속보] 개인 순매수 1조 돌파",
                    "summary": "기존 요약",
                    "link": "https://www.edaily.co.kr/news/read?newsId=0001",
                    "outlet_id": "edaily",
                    "outlet_name": "이데일리",
                    "date": "2026-11-23",
                    "published": "2026-11-23T09:00:00+09:00",
                    "is_inflection": False
                }
            ],
            "by_date": {"2026-11-23": ["dup1"]}
        }
        with open(self.test_json, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, ensure_ascii=False)

        orig_fetch = news_mod.fetch_from_naver
        try:
            # Return duplicate by URL, and duplicate by title
            news_mod.fetch_from_naver = lambda cid, sec, q, display=50: ([
                {
                    "title": "[속보] 개인 순매수 1조 돌파", # Same title
                    "description": "다른 링크지만 제목 동일",
                    "originallink": "https://www.edaily.co.kr/news/read?newsId=0002",
                    "pubDate": "Mon, 23 Nov 2026 09:05:00 +0900"
                },
                {
                    "title": "완전히 다른 제목",
                    "description": "같은 링크",
                    "originallink": "https://www.edaily.co.kr/news/read?newsId=0001", # Same link
                    "pubDate": "Mon, 23 Nov 2026 09:10:00 +0900"
                }
            ], None)

            news_mod.main()

            with open(self.test_json, "r", encoding="utf-8") as f:
                res = json.load(f)

            # Neither duplicate should be added
            edaily_arts = [a for a in res["articles"] if a.get("outlet_id") == "edaily"]
            self.assertEqual(len(edaily_arts), 1)
            print("  [PASS] Test 2: 2중 중복 제거 (URL 중복 및 정규화 제목 중복 완벽 차단)")
        finally:
            news_mod.fetch_from_naver = orig_fetch

    def test_03_inflection_point_protection(self):
        """변곡점 연결 기사는 800건 초과 시에도 영구 보존되는지 검증"""
        # Create an inflection article on 2024-08-05
        inflection_art = {
            "id": "inf_bm",
            "title": "2024-08-05 블랙먼데이 개미 1.6조원 매수",
            "summary": "역대급 변곡점 기사",
            "link": "https://www.yna.co.kr/view/AKR2024080599999",
            "outlet_id": "yna",
            "outlet_name": "연합뉴스",
            "date": "2024-08-05",
            "published": "2024-08-05T16:00:00+09:00",
            "is_inflection": True
        }
        # And 850 dummy old normal articles
        dummy_arts = [inflection_art]
        for i in range(850):
            dummy_arts.append({
                "id": f"dummy_{i}",
                "title": f"일반 과거 기사 {i} 개인 순매수 동향",
                "summary": "일반 기사",
                "link": f"https://www.sedaily.com/NewsView/DUMMY_{i}",
                "outlet_id": "sedaily",
                "outlet_name": "서울경제",
                "date": "2025-01-01",
                "published": f"2025-01-01T{i%24:02d}:00:00+09:00",
                "is_inflection": False
            })

        initial_data = {
            "last_updated": "2026-11-20T18:00:00+09:00",
            "total_articles": len(dummy_arts),
            "articles": dummy_arts,
            "by_date": {"2024-08-05": ["inf_bm"]}
        }
        with open(self.test_json, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, ensure_ascii=False)

        orig_fetch = news_mod.fetch_from_naver
        try:
            news_mod.fetch_from_naver = lambda cid, sec, q, display=50: ([], None)
            news_mod.main()

            with open(self.test_json, "r", encoding="utf-8") as f:
                res = json.load(f)

            # Inflection article must STILL be in articles and in by_date
            links = [a["link"] for a in res["articles"]]
            self.assertIn("https://www.yna.co.kr/view/AKR2024080599999", links)
            self.assertIn("2024-08-05", res["by_date"])
            print("  [PASS] Test 3: 변곡점 기사 영구 보존 (800건 초과 시에도 2024-08-05 변곡점 기사 100% 보존)")
        finally:
            news_mod.fetch_from_naver = orig_fetch

    def test_04_circuit_breaker_on_api_failure(self):
        """API 오류 또는 인증 실패 시 기존 정상 데이터가 100% 보존되는지 검증"""
        initial_data = {
            "last_updated": "2026-11-23T08:00:00+09:00",
            "last_success_at": "2026-11-23T08:00:00+09:00",
            "last_status": "success",
            "total_articles": 1,
            "articles": [
                {
                    "id": "safe1",
                    "title": "보호되어야 할 정상 기사",
                    "summary": "요약",
                    "link": "https://www.donga.com/news/1",
                    "outlet_id": "donga",
                    "outlet_name": "동아일보",
                    "date": "2026-11-23",
                    "published": "2026-11-23T08:00:00+09:00"
                }
            ],
            "by_date": {"2026-11-23": ["safe1"]}
        }
        with open(self.test_json, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, ensure_ascii=False)

        orig_fetch = news_mod.fetch_from_naver
        try:
            # Simulate API error 401 Unauthorized
            news_mod.fetch_from_naver = lambda cid, sec, q, display=50: ([], "HTTP 401 Unauthorized")
            news_mod.main()

            with open(self.test_json, "r", encoding="utf-8") as f:
                res = json.load(f)

            # Data must NOT be empty! Original article must still exist!
            links = [a["link"] for a in res["articles"]]
            self.assertIn("https://www.donga.com/news/1", links)
            self.assertEqual(res["last_status"], "warning_retained_existing")
            self.assertEqual(res["last_success_at"], "2026-11-23T08:00:00+09:00")
            print("  [PASS] Test 4: 실패 방어 Circuit Breaker (API 401 오류 시 기존 기사 100% 보존 및 상태 기록)")
        finally:
            news_mod.fetch_from_naver = orig_fetch

    def test_05_display_vs_storage_separation(self):
        """저장 기사 수가 120건으로 조기 삭제되지 않고 180건 이상 풀로 보존되는지 검증"""
        with open(self.orig_json, "r", encoding="utf-8") as f:
            real_data = json.load(f)
        total = real_data.get("total_articles", 0)
        stored_count = len(real_data.get("articles", []))
        self.assertGreater(stored_count, 120)
        self.assertEqual(total, stored_count)
        print(f"  [PASS] Test 5: 저장-표시 분리 (현재 저장 기사: {stored_count}건 > 120건, 표시와 별도로 영속 유지)")

def run_tests():
    print("=== GAEMI INDEX 뉴스 영속성 및 실패방어 테스트 시작 ===")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestNewsMergeAndFailsafe)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()

if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
