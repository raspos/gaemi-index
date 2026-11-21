"""
PHASE 6 & 7: 웹사이트 렌더링, 카테고리 탭 격리(선택한 탭만 표시) 및 모바일 반응형(320px, 390px, 768px, 1280px) 자동 검증 스크립트
"""

import os
import json
import threading
import http.server
import socketserver
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
DATA_DIR = os.path.join(BASE_DIR, "data")
ARTIFACT_DIR = r"C:\Users\kimwo\.gemini\antigravity\brain\b8de2d09-6563-4cc5-9e7f-5158b4af6818"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DOCS_DIR, **kwargs)

    def log_message(self, format, *args):
        pass


def run_ui_verification():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/index.html"
    print(f"테스트 서버 시작: {url}")

    viewports = [
        {"name": "mobile_320", "width": 320, "height": 800},
        {"name": "mobile_390", "width": 390, "height": 844},
        {"name": "tablet_768", "width": 768, "height": 1024},
        {"name": "desktop_1280", "width": 1280, "height": 960},
    ]

    all_tabs = ["sec-01", "sec-02", "sec-03", "sec-04", "sec-05", "sec-footer"]
    ui_report = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH, headless=True)
        for vp in viewports:
            context = browser.new_context(viewport={"width": vp["width"], "height": vp["height"]})
            page = context.new_page()
            console_errors = []
            page.on("pageerror", lambda err: console_errors.append(str(err)))
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(500)

            val_pure = page.inner_text("#val-pure").strip()
            val_kospi = page.inner_text("#val-kospi").strip()
            val_kosdaq = page.inner_text("#val-kosdaq").strip()

            # 기본 탭(sec-01) 확인 및 스크린샷
            shot_path = os.path.join(ARTIFACT_DIR, f"gaemi_pure_ui_{vp['name']}.png")
            page.screenshot(path=shot_path, full_page=False)

            tab_isolation_ok = True
            any_overflow = False
            main_chart_ok = False
            detail_chart_ok = False
            investor_chart_ok = False
            rows_cnt = 0

            for tid in all_tabs:
                page.click(f'#tabs button[data-tab="{tid}"]')
                page.wait_for_timeout(150)

                chk = page.evaluate("""(activeId) => {
                    const panels = Array.from(document.querySelectorAll('.tab-panel'));
                    const visibleIds = panels.filter(el => !el.hidden && el.offsetParent !== null).map(el => el.id);
                    const docW = document.documentElement.scrollWidth;
                    const winW = window.innerWidth;
                    const logo = document.querySelector('img.logo').getBoundingClientRect();
                    let chartBox = { width: 0, height: 0 };
                    if (activeId === 'sec-01') chartBox = document.getElementById('mainChart').getBoundingClientRect();
                    if (activeId === 'sec-02') chartBox = document.getElementById('detailChart').getBoundingClientRect();
                    if (activeId === 'sec-04') chartBox = document.getElementById('investorIndexChart').getBoundingClientRect();
                    return {
                        visibleIds,
                        isolated: visibleIds.length === 1 && visibleIds[0] === activeId,
                        docWidth: docW,
                        winWidth: winW,
                        overflow: docW > winW,
                        logoReady: logo.width >= 20 && logo.height >= 20,
                        chartReady: chartBox.width > 50 && chartBox.height > 50
                    };
                }""", tid)

                if not chk["isolated"]:
                    tab_isolation_ok = False
                if chk["overflow"]:
                    any_overflow = True
                if tid == "sec-01":
                    main_chart_ok = chk["chartReady"]
                elif tid == "sec-02":
                    detail_chart_ok = chk["chartReady"]
                    rows_cnt = page.locator("#pure50-tbody tr").count()
                elif tid == "sec-04":
                    investor_chart_ok = chk["chartReady"]

            passed = (
                val_pure == "757.28" and
                val_kospi == "1,877.92" and
                val_kosdaq == "845.26" and
                rows_cnt == 50 and
                tab_isolation_ok and
                not any_overflow and
                main_chart_ok and
                detail_chart_ok and
                investor_chart_ok and
                len(console_errors) == 0
            )

            res_item = {
                "viewport": f"{vp['width']}x{vp['height']}",
                "status": "PASS" if passed else "FAIL",
                "val_pure": val_pure,
                "val_kospi": val_kospi,
                "val_kosdaq": val_kosdaq,
                "table_rows": rows_cnt,
                "tab_isolation_verified": tab_isolation_ok,
                "horizontal_overflow": any_overflow,
                "charts_rendered": main_chart_ok and detail_chart_ok and investor_chart_ok,
                "console_errors": console_errors,
                "screenshot": shot_path,
            }
            ui_report.append(res_item)
            print(f"  [{res_item['status']}] Viewport {vp['width']}px | tabIsolation={tab_isolation_ok} | overflow={any_overflow} | charts={res_item['charts_rendered']} | rows={rows_cnt} | errors={len(console_errors)}")
            context.close()

        browser.close()
    httpd.shutdown()

    with open(os.path.join(DATA_DIR, "ui_verification_report.json"), "w", encoding="utf-8") as f:
        json.dump(ui_report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    run_ui_verification()
