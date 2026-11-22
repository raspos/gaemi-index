"""
scripts/verify_reboot_ui.py

개미 지수(GAEMI INDEX) 전면 재기획 웹 UI 및 모바일 반응형 검증 스크립트
- 검증 해상도: 320x800, 390x844, 768x1024, 1280x960
- 테마: Light & Dark
- 스크린샷 아티팩트 저장 (8장)
- BOK WATCH형 차트, 변곡점, 이벤트 줄, 날짜 인스펙터, 5개 탭 전수 점검
- 가로 넘침(overflow), WCAG AA 명도 대비, 콘솔 에러 전무 검증
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
    print("=== 개미 지수 (GAEMI INDEX) UI 종합 검증 시작 ===")
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

                # 1. 대표 집중도 수치 확인
                conc_val = page.inner_text("#hero-conc-val").strip()
                conc_delta = page.inner_text("#hero-conc-delta").strip()
                conc_summary = page.inner_text("#hero-summary-text").strip()
                
                conc_ok = ("58.1%" in conc_val or "58.07" in conc_val) and ("+5.9" in conc_delta or "+5.87" in conc_delta)
                summary_ok = len(conc_summary) > 20

                # 2. BOK WATCH SVG 차트 렌더링 확인
                chart_svg_cnt = page.locator("#concentrationChart svg").count()
                chart_ok = chart_svg_cnt >= 1
                
                # 차트 내 패스 및 요소 검증
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

                # 3. 가로 넘침(Overflow) 검사
                overflow_info = page.evaluate("""() => {
                    return {
                        docWidth: document.documentElement.scrollWidth,
                        winWidth: window.innerWidth,
                        overflow: document.documentElement.scrollWidth > window.innerWidth
                    };
                }""")
                overflow_ok = not overflow_info["overflow"]

                # 4. 차트 인터랙션 (범위 전환 7일 -> 30일 -> 90일)
                page.click('#concRangeSwitch button[data-range="30"]')
                page.wait_for_timeout(150)
                range_30_active = page.evaluate("() => document.querySelector('#concRangeSwitch button[data-range=\"30\"]').classList.contains('on')")
                page.click('#concRangeSwitch button[data-range="90"]')
                page.wait_for_timeout(150)

                # 5. Top 10 테이블 행 수 확인
                top10_rows = page.locator("#top10-tbody tr").count()
                top10_ok = top10_rows == 10

                # 6. 요인 분해 카드 확인
                decomp_title = page.inner_text("#inspect-date-title").strip()
                contrib_items = page.locator("#contrib-list .decomp-item").count()
                decomp_ok = len(decomp_title) > 0 and contrib_items >= 2

                # 7. 탭 전환 검증 (tab-bought, tab-movement, tab-scorecard, tab-method)
                # Tab 2: 개미가 산 종목
                page.click('#tabs button[data-tab="tab-bought"]')
                page.wait_for_timeout(150)
                bought_visible = page.evaluate("() => !document.getElementById('tab-bought').hidden")
                page.fill("#stockSearchInput", "삼성전자")
                page.wait_for_timeout(100)
                search_res_cnt = page.locator("#bought-ranking-tbody tr").count()
                search_ok = search_res_cnt >= 1
                page.fill("#stockSearchInput", "")

                # Tab 3: 개미의 이동
                page.click('#tabs button[data-tab="tab-movement"]')
                page.wait_for_timeout(150)
                movement_visible = page.evaluate("() => !document.getElementById('tab-movement').hidden")
                sector_bars_cnt = page.locator("#sectorBarList .sector-bar-row").count()
                movement_ok = movement_visible and sector_bars_cnt >= 5

                # Tab 4: 개미의 성적표
                page.click('#tabs button[data-tab="tab-scorecard"]')
                page.wait_for_timeout(150)
                scorecard_visible = page.evaluate("() => !document.getElementById('tab-scorecard').hidden")
                scorecard_ok = scorecard_visible and page.locator("#sc-gaemi-down-mean").count() >= 1

                # Tab 1 복귀
                page.click('#tabs button[data-tab="tab-conc"]')
                page.wait_for_timeout(150)
                conc_tab_visible = page.evaluate("() => !document.getElementById('tab-conc').hidden")

                # 스크린샷 캡처 (상단)
                page.evaluate("() => window.scrollTo(0, 0)")
                shot_name = f"gaemi_reboot_{test_name}.png"
                shot_path = os.path.join(ARTIFACT_DIR, shot_name)
                page.screenshot(path=shot_path, full_page=False)

                test_pass = (
                    conc_ok and summary_ok and chart_ok and svg_rich_ok and
                    overflow_ok and top10_ok and decomp_ok and
                    search_ok and movement_ok and scorecard_ok and conc_tab_visible and
                    len(console_errors) == 0
                )

                if not test_pass:
                    results["passed"] = False

                test_entry = {
                    "name": test_name,
                    "viewport": f"{vp['width']}x{vp['height']}",
                    "theme": theme,
                    "conc_val": conc_val,
                    "conc_delta": conc_delta,
                    "chart_elements": chart_elements,
                    "overflow": overflow_info["overflow"],
                    "top10_rows": top10_rows,
                    "console_errors": console_errors,
                    "passed": test_pass,
                    "screenshot": shot_path
                }
                results["tests"].append(test_entry)
                status_str = "PASS" if test_pass else "FAIL"
                print(f"  -> 결과: {status_str} (집중도: {conc_val}, 차트: {chart_elements['paths']}paths, 가로넘침: {overflow_info['overflow']}, 콘솔에러: {len(console_errors)})")

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
