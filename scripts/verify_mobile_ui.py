"""
PHASE 6: 웹사이트 렌더링 및 모바일 반응형(320px, 390px, 768px, 1280px) 자동 검증 스크립트
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
            page.wait_for_timeout(800)

            # 1. 지수 값 렌더링 확인
            val_pure = page.inner_text("#val-pure").strip()
            val_abs = page.inner_text("#val-abs").strip()
            rows_cnt = page.locator("#constituent-tbody tr").count()

            # 2. 가로 스크롤 오버플로우 여부 확인
            overflow_info = page.evaluate("""() => {
                const docW = document.documentElement.scrollWidth;
                const winW = window.innerWidth;
                const c1 = document.getElementById('mainIndexChart').getBoundingClientRect();
                const c2 = document.getElementById('sizeComparisonChart').getBoundingClientRect();
                const c3 = document.getElementById('stockTrajectoryChart').getBoundingClientRect();
                return {
                    docWidth: docW,
                    winWidth: winW,
                    hasHorizontalOverflow: docW > winW,
                    mainChartReady: c1.width > 50 && c1.height > 50,
                    sizeChartReady: c2.width > 50 && c2.height > 50,
                    trajChartReady: c3.width > 50 && c3.height > 50
                };
            }""")

            shot_path = os.path.join(ARTIFACT_DIR, f"gaemi_pure_ui_{vp['name']}.png")
            page.screenshot(path=shot_path, full_page=False)

            passed = (
                val_pure == "826.55" and
                val_abs == "936.98" and
                rows_cnt == 50 and
                not overflow_info["hasHorizontalOverflow"] and
                overflow_info["mainChartReady"] and
                overflow_info["sizeChartReady"] and
                overflow_info["trajChartReady"] and
                len(console_errors) == 0
            )

            res_item = {
                "viewport": f"{vp['width']}x{vp['height']}",
                "status": "PASS" if passed else "FAIL",
                "val_pure": val_pure,
                "val_abs": val_abs,
                "table_rows": rows_cnt,
                "doc_scroll_width": overflow_info["docWidth"],
                "window_inner_width": overflow_info["winWidth"],
                "horizontal_overflow": overflow_info["hasHorizontalOverflow"],
                "charts_rendered": (
                    overflow_info["mainChartReady"] and
                    overflow_info["sizeChartReady"] and
                    overflow_info["trajChartReady"]
                ),
                "console_errors": console_errors,
                "screenshot": shot_path,
            }
            ui_report.append(res_item)
            print(f"  [{res_item['status']}] Viewport {vp['width']}px | docWidth={overflow_info['docWidth']}px | PURE={val_pure} | ABS={val_abs} | rows={rows_cnt} | errors={len(console_errors)}")
            context.close()

        browser.close()
    httpd.shutdown()

    with open(os.path.join(DATA_DIR, "ui_verification_report.json"), "w", encoding="utf-8") as f:
        json.dump(ui_report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    run_ui_verification()
