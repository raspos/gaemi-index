"""
scripts/verify_reboot_ui.py

개미 지수 (GAEMI INDEX) UI·UX 전면 재설계 종합 검증 스크립트
- 검증 해상도: 320x800, 390x844, 768x1024, 1280x960
- 테마: Light & Dark
- 스크린샷 아티팩트 저장 (8장)
- 3개 대메뉴 [ 지금 ] [ 종목 ] [ 리서치 ] 및 리서치 4개 서브탭, 모달 전수 점검
- 가로 넘침(overflow) 전무, 콘솔 에러 전무 검증
"""

import os
import sys
import json
import time
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACT_DIR = r"C:\Users\kimwo\.gemini\antigravity\brain\b8de2d09-6563-4cc5-9e7f-5158b4af6818"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
URL = "http://localhost:8080"


def run_verification():
    print("=== 개미 지수 (GAEMI INDEX) 전면 재설계 UI 종합 검증 시작 ===")
    viewports = [
        {"name": "mobile_320", "width": 320, "height": 800},
        {"name": "mobile_390", "width": 390, "height": 844},
        {"name": "tablet_768", "width": 768, "height": 1024},
        {"name": "desktop_1280", "width": 1280, "height": 960},
    ]

    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tests": [],
        "passed": True
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
            headless=True
        )

        for vp in viewports:
            for theme in ["light", "dark"]:
                test_name = f"{vp['name']}_{theme}"
                print(f"\n[검증 진행] {test_name} ({vp['width']}x{vp['height']})...")

                context = browser.new_context(
                    viewport={"width": vp["width"], "height": vp["height"]},
                    color_scheme=theme
                )
                page = context.new_page()

                console_errors = []
                page.on("pageerror", lambda err: console_errors.append(str(err)))
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

                page.goto(URL, wait_until="networkidle")
                page.wait_for_timeout(300)

                # 테마 동기화 확인 및 전환
                is_dark = page.evaluate("() => document.getElementById('themeBtn').getAttribute('aria-pressed') === 'true'")
                if theme == "dark" and not is_dark:
                    page.click("#themeBtn")
                    page.wait_for_timeout(100)
                elif theme == "light" and is_dark:
                    page.click("#themeBtn")
                    page.wait_for_timeout(100)

                # ========================================================
                # 1. 메인 화면 [ 지금 ] (tab-now) 3대 핵심 영역 검증
                # ========================================================
                # SECTION 01: 개미들은 무엇을 사고 있나
                conc_val = page.inner_text("#hero-conc-val").strip()
                conc_delta = page.inner_text("#hero-conc-delta").strip()
                top5_rows_cnt = page.locator("#main-top5-tbody tr").count()
                now_sec1_ok = ("58." in conc_val) and ("%" in conc_delta) and (top5_rows_cnt == 5)

                # SECTION 02: 한국 증시, 얼마나 떨어졌나
                d30_val = page.inner_text("#dd-d30-val").strip()
                idx_dd_val = page.inner_text("#dd-idx-val").strip()
                med_dd_val = page.inner_text("#dd-median-val").strip()
                now_sec2_kospi_ok = ("76." in d30_val) and ("-45." in idx_dd_val) and ("-45." in med_dd_val)

                # KOSDAQ 시장 전환 테스트
                page.click('#ddMarketSwitch button[data-mkt="KOSDAQ"]')
                page.wait_for_timeout(100)
                kq_d30_val = page.inner_text("#dd-d30-val").strip()
                kq_med_val = page.inner_text("#dd-median-val").strip()
                now_sec2_kosdaq_ok = ("84." in kq_d30_val) and ("-55." in kq_med_val)

                # KOSPI 복귀
                page.click('#ddMarketSwitch button[data-mkt="KOSPI"]')
                page.wait_for_timeout(100)

                # SECTION 03: 개미가 사는 종목은 얼마나 떨어졌나 (비교 막대)
                bar_r_val = page.inner_text("#main-val-retail").strip()
                now_sec3_ok = ("-55." in bar_r_val)

                # 관련 뉴스 (최소화: 2건 텍스트 리스트)
                main_news_cnt = page.locator("#main-news-list .main-news-item").count()
                news_pill = page.inner_text("#news-outlets-pill").strip()
                now_news_ok = (main_news_cnt == 2) and ("개사" in news_pill)

                # 가로 넘침(Overflow) 검사 (메인 화면 기준)
                overflow_info = page.evaluate("""() => {
                    return {
                        docWidth: document.documentElement.scrollWidth,
                        winWidth: window.innerWidth,
                        overflow: document.documentElement.scrollWidth > window.innerWidth
                    };
                }""")
                overflow_ok = not overflow_info["overflow"]

                # ========================================================
                # 2. [ 종목 ] 탭 (tab-stocks) 검증
                # ========================================================
                page.click('#tabs button[data-tab="tab-stocks"]')
                page.wait_for_timeout(150)
                stocks_visible = page.evaluate("() => !document.getElementById('tab-stocks').hidden")
                
                # 종목 검색 테스트
                page.fill("#stockSearchInput", "삼성전자")
                page.wait_for_timeout(100)
                search_res_cnt = page.locator("#bought-ranking-tbody tr").count()
                search_ok = search_res_cnt >= 1
                page.fill("#stockSearchInput", "")
                page.wait_for_timeout(100)

                # 업종 이동 바 및 증감 테이블
                sector_bars_cnt = page.locator("#sectorBarList .sector-bar-row").count()
                sector_shift_cnt = page.locator("#sector-shift-tbody tr").count()
                stocks_tab_ok = stocks_visible and search_ok and (sector_bars_cnt >= 5) and (sector_shift_cnt >= 1)

                # ========================================================
                # 3. [ 리서치 ] 탭 (tab-research) 및 4개 서브탭 검증
                # ========================================================
                page.click('#tabs button[data-tab="tab-research"]')
                page.wait_for_timeout(150)
                research_visible = page.evaluate("() => !document.getElementById('tab-research').hidden")

                # 서브탭 1: 집중도 (BOK WATCH 차트 및 요인 분해)
                chart_svg_cnt = page.locator("#concentrationChart svg").count()
                chart_elements = page.evaluate("""() => {
                    const svg = document.querySelector('#concentrationChart svg');
                    if (!svg) return { paths: 0, lines: 0, texts: 0, width: 0 };
                    const rect = svg.getBoundingClientRect();
                    return {
                        paths: svg.querySelectorAll('path').length,
                        lines: svg.querySelectorAll('line').length,
                        texts: svg.querySelectorAll('text').length,
                        circles: svg.querySelectorAll('circle').length,
                        width: rect.width,
                        height: rect.height
                    };
                }""")
                expected_min_w = min(vp["width"], 1180) - 90
                svg_rich_ok = chart_elements["paths"] >= 2 and chart_elements["texts"] >= 5 and chart_elements["width"] >= expected_min_w
                top10_rows = page.locator("#top10-tbody tr").count()
                top10_ok = top10_rows == 10
                decomp_title = page.inner_text("#inspect-date-title").strip()
                decomp_ok = len(decomp_title) > 0

                # 서브탭 2: 낙폭 (구간 분포, 3단 비교 카드, 일별 시계열)
                page.click('#researchSubTabs button[data-rtab="res-drawdown"]')
                page.wait_for_timeout(150)
                dist_rows_cnt = page.locator("#distBarList .dist-row").count()
                dist_bar_ok = dist_rows_cnt == 5
                page.click('#distBarList .dist-row[data-bidx="4"]')
                page.wait_for_timeout(100)
                bucket_visible = page.evaluate("() => !document.getElementById('bucketStocksWrap').hidden")
                page.click("#closeBucketStocksBtn")
                page.wait_for_timeout(100)

                retail_box_cnt = page.locator("#comp-box-retail").count()
                retail_top10_cnt = page.locator("#retail-top10-drawdown-tbody tr").count()
                retail_top50_ok = retail_box_cnt >= 1 and retail_top10_cnt == 10
                ts_chart_cnt = page.locator("#ddTimeseriesChart").count()
                ts_chart_ok = ts_chart_cnt >= 1

                # 서브탭 3: 시장 관계 (상관관계 분석)
                page.click('#researchSubTabs button[data-rtab="res-market"]')
                page.wait_for_timeout(150)
                mkt_kospi_corr = page.inner_text("#m-kospi-corr").strip()
                mkt_kosdaq_corr = page.inner_text("#m-kosdaq-corr").strip()
                market_ok = ("-0.28" in mkt_kospi_corr or "-0.29" in mkt_kospi_corr) and ("-0.10" in mkt_kosdaq_corr)
                page.click('#marketPeriodSwitch button[data-mperiod="60D"]')
                page.wait_for_timeout(100)
                mkt_60d_corr = page.inner_text("#m-kospi-corr").strip()
                corr_period_switch_ok = ("-0.23" in mkt_60d_corr or "-0.24" in mkt_60d_corr or "-0.25" in mkt_60d_corr)

                # 서브탭 4: 성적표 (하락장 성적표)
                page.click('#researchSubTabs button[data-rtab="res-scorecard"]')
                page.wait_for_timeout(150)
                scorecard_ok = page.locator("#sc-gaemi-down-mean").count() >= 1

                # ========================================================
                # 4. 모달 기능 점검 (전체 기사 모달 & 데이터·산출 방법 모달)
                # ========================================================
                # 메인으로 복귀 후 모달 테스트
                page.click('#tabs button[data-tab="tab-now"]')
                page.wait_for_timeout(150)

                # 전체 기사 모달
                page.click("#openFullNewsBtn")
                page.wait_for_timeout(100)
                news_modal_visible = page.evaluate("() => !document.getElementById('fullNewsModal').hidden")
                page.click("#closeFullNewsModalBtn")
                page.wait_for_timeout(100)
                news_modal_hidden = page.evaluate("() => document.getElementById('fullNewsModal').hidden")
                news_modal_ok = news_modal_visible and news_modal_hidden

                # 데이터·산출 방법 모달
                page.click("#openMethodModalBtn")
                page.wait_for_timeout(100)
                method_modal_visible = page.evaluate("() => !document.getElementById('methodModal').hidden")
                page.click("#closeMethodModalBtn")
                page.wait_for_timeout(100)
                method_modal_hidden = page.evaluate("() => document.getElementById('methodModal').hidden")
                method_modal_ok = method_modal_visible and method_modal_hidden

                # 스크린샷 캡처 (메인 화면)
                page.evaluate("() => window.scrollTo(0, 0)")
                shot_name = f"gaemi_reboot_{test_name}.png"
                shot_path = os.path.join(ARTIFACT_DIR, shot_name)
                page.screenshot(path=shot_path, full_page=False)

                checks = {
                    "now_sec1_ok": now_sec1_ok,
                    "now_sec2_kospi_ok": now_sec2_kospi_ok,
                    "now_sec2_kosdaq_ok": now_sec2_kosdaq_ok,
                    "now_sec3_ok": now_sec3_ok,
                    "now_news_ok": now_news_ok,
                    "overflow_ok": overflow_ok,
                    "stocks_tab_ok": stocks_tab_ok,
                    "research_visible": research_visible,
                    "svg_rich_ok": svg_rich_ok,
                    "top10_ok": top10_ok,
                    "decomp_ok": decomp_ok,
                    "dist_bar_ok": dist_bar_ok,
                    "bucket_visible": bucket_visible,
                    "retail_top50_ok": retail_top50_ok,
                    "ts_chart_ok": ts_chart_ok,
                    "market_ok": market_ok,
                    "corr_period_switch_ok": corr_period_switch_ok,
                    "scorecard_ok": scorecard_ok,
                    "news_modal_ok": news_modal_ok,
                    "method_modal_ok": method_modal_ok,
                    "no_console_errors": len(console_errors) == 0,
                }
                failed_checks = [k for k, v in checks.items() if not v]
                test_pass = len(failed_checks) == 0

                if not test_pass:
                    results["passed"] = False
                    print(f"  [!] Failed checks: {failed_checks}")

                test_entry = {
                    "name": test_name,
                    "viewport": f"{vp['width']}x{vp['height']}",
                    "theme": theme,
                    "conc_val": conc_val,
                    "conc_delta": conc_delta,
                    "overflow": overflow_info["overflow"],
                    "console_errors": console_errors,
                    "passed": test_pass,
                    "screenshot": shot_path
                }
                results["tests"].append(test_entry)
                status_str = "PASS" if test_pass else "FAIL"
                print(f"  -> 결과: {status_str} (집중도: {conc_val}, 상위5행: {top5_rows_cnt}, 가로넘침: {overflow_info['overflow']}, 콘솔에러: {len(console_errors)})")

                context.close()

        browser.close()

    report_path = os.path.join(BASE_DIR, "data", "reboot_ui_verification_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n=== 전체 검증 결과 요약 ===")
    all_ok = results["passed"]
    print(f"최종 판정: {'SUCCESS (ALL PASS)' if all_ok else 'FAILURE'}")
    print(f"보고서 저장: {report_path}")
    return all_ok


if __name__ == "__main__":
    ok = run_verification()
    sys.exit(0 if ok else 1)
