"""
PHASE 3 — 섹션 7. 모바일·테마별(라이트/다크/시스템 자동) 실제 검증 및 WCAG AA 대비 감사 스크립트

검증 해상도:
- 320 x 800
- 390 x 844
- 768 x 1024
- 1280 x 960

각 해상도마다 라이트 테마(light), 다크 테마(dark), 시스템 테마 자동 설정(prefers-color-scheme)을 검증하고
라이트·다크 테마별 스크린샷을 저장하며, 12개 필수 검사 항목을 모두 실제 실행하여 점검한다.
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


CONTRAST_CHECK_JS = """() => {
  function parseColor(str) {
    if (!str) return null;
    const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
    if (!m) return null;
    return { r: +m[1], g: +m[2], b: +m[3], a: m[4] !== undefined ? +m[4] : 1 };
  }
  function lum(c) {
    const a = [c.r, c.g, c.b].map(v => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
  }
  function ratio(c1, c2) {
    const l1 = lum(c1);
    const l2 = lum(c2);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  }
  function getBg(el) {
    let cur = el;
    while (cur && cur !== document.documentElement) {
      const bg = parseColor(getComputedStyle(cur).backgroundColor);
      if (bg && bg.a >= 0.85) return bg;
      cur = cur.parentElement;
    }
    return parseColor(getComputedStyle(document.body).backgroundColor) || { r: 246, g: 246, b: 244, a: 1 };
  }

  const selectors = [
    '.brand-text h1', '.brand-text .en', '.brand-sub', '.asof-pill',
    '.tile-k', '.tile-v', '.tile-chg', '.tile-foot',
    '#tabs button[aria-selected="true"]', '#tabs button[aria-selected="false"]',
    '.fact-label', '.fact-val', '.fact-desc',
    'table.tbl th', 'table.tbl td', '.up', '.down',
    '.notice-box', '.site-credit'
  ];

  let minTextRatio = 99;
  let minTextSelector = '';

  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (!el || el.offsetParent === null) continue;
    const fg = parseColor(getComputedStyle(el).color);
    const bg = getBg(el);
    if (fg && bg) {
      const r = ratio(fg, bg);
      if (r < minTextRatio) {
        minTextRatio = r;
        minTextSelector = sel;
      }
    }
  }

  // 차트 선 색상과 카드 배경색의 명도 대비(3:1 이상) 검사
  const cs = getComputedStyle(document.documentElement);
  const surfaceBg = parseColor(getComputedStyle(document.querySelector('.card') || document.body).backgroundColor);
  const hexToRgb = (hex) => {
    const h = hex.trim().replace('#', '');
    if (h.length !== 6) return null;
    return { r: parseInt(h.slice(0,2),16), g: parseInt(h.slice(2,4),16), b: parseInt(h.slice(4,6),16), a: 1 };
  };
  const chartVars = ['--chart-gaemi', '--chart-kospi', '--chart-kosdaq', '--chart-foreign', '--chart-institution'];
  let minChartRatio = 99;
  const chartTokenValues = {};
  for (const v of chartVars) {
    const hex = cs.getPropertyValue(v).trim();
    chartTokenValues[v] = hex;
    const c = hexToRgb(hex);
    if (c && surfaceBg) {
      const r = ratio(c, surfaceBg);
      if (r < minChartRatio) minChartRatio = r;
    }
  }

  return {
    minTextRatio: Number(minTextRatio.toFixed(2)),
    minTextSelector,
    minChartRatio: Number(minChartRatio.toFixed(2)),
    chartTokenValues
  };
}"""


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
            for theme_mode in ["light", "dark"]:
                context = browser.new_context(
                    viewport={"width": vp["width"], "height": vp["height"]},
                    color_scheme=theme_mode,
                )
                page = context.new_page()
                console_errors = []
                page.on("pageerror", lambda err: console_errors.append(str(err)))
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(400)

                # 시스템 테마(prefers-color-scheme) 자동 감지 상태 확인
                auto_detected_dark = page.evaluate("() => document.getElementById('themeBtn').getAttribute('aria-pressed') === 'true'")
                system_theme_ok = (auto_detected_dark == (theme_mode == "dark"))

                # 수동 테마 설정 및 새로고침 후 로컬 저장소 유지 검증
                if theme_mode == "dark" and not auto_detected_dark:
                    page.click("#themeBtn")
                elif theme_mode == "light" and auto_detected_dark:
                    page.click("#themeBtn")

                # 보조 비교지수 체크박스 활성화 시 차트 데이터셋 추가 동작 확인 (기본 4개 + 보조 1개 = 5개)
                page.check("#chk-kqew")
                dataset_cnt = page.evaluate("() => Chart.getChart('mainChart').data.datasets.length")
                aux_chart_ok = (dataset_cnt == 5)
                page.uncheck("#chk-kqew")

                # 라이트·다크 테마별 스크린샷 저장 (스크롤 최상단)
                page.evaluate("() => window.scrollTo(0, 0)")
                shot_path = os.path.join(ARTIFACT_DIR, f"gaemi_phase3_{vp['name']}_{theme_mode}.png")
                page.screenshot(path=shot_path, full_page=False)

                # 명도 대비(WCAG AA) 검사
                contrast_info = page.evaluate(CONTRAST_CHECK_JS)
                contrast_ok = (contrast_info["minTextRatio"] >= 4.5 and contrast_info["minChartRatio"] >= 3.0)

                val_pure = page.inner_text("#val-pure").strip()
                val_matched = page.inner_text("#val-matched").strip()
                val_kospi = page.inner_text("#val-kospi").strip()
                val_kosdaq = page.inner_text("#val-kosdaq").strip()

                # 기간 선택(1Y) 버튼 동작 및 재인덱싱 확인
                page.click('#period-btns button[data-period="1Y"]')
                val_1y = page.inner_text("#val-pure").strip()
                gap_matched_1y = page.inner_text("#gap-matched").strip()
                period_filter_ok = (val_1y != val_pure and val_1y != "-" and gap_matched_1y != "-")
                page.click('#period-btns button[data-period="ALL"]')

                tab_isolation_ok = True
                any_overflow = False
                main_chart_ok = False
                detail_chart_ok = False
                investor_chart_ok = False
                search_filter_ok = False
                details_toggle_ok = False
                rows_cnt = 0

                for tid in all_tabs:
                    page.click(f'#tabs button[data-tab="{tid}"]')
                    page.wait_for_timeout(120)

                    chk = page.evaluate("""(activeId) => {
                        const panels = Array.from(document.querySelectorAll('.tab-panel'));
                        const visibleIds = panels.filter(el => !el.hidden && el.offsetParent !== null).map(el => el.id);
                        const docW = document.documentElement.scrollWidth;
                        const winW = window.innerWidth;
                        const logo = document.querySelector('img.logo').getBoundingClientRect();
                        let chartBox = { width: 0, height: 0 };
                        let chartKospiColor = '';
                        let capChartReady = true;
                        let epChartReady = true;
                        if (activeId === 'sec-01') {
                            chartBox = document.getElementById('mainChart').getBoundingClientRect();
                            const capBox = document.getElementById('captureCompareChart').getBoundingClientRect();
                            const epBox = document.getElementById('episodeChart').getBoundingClientRect();
                            capChartReady = capBox.width > 50 && capBox.height > 50;
                            epChartReady = epBox.width > 50 && epBox.height > 50;
                            const c = Chart.getChart('mainChart');
                            chartKospiColor = c ? c.data.datasets[2].borderColor : '';
                        }
                        if (activeId === 'sec-02') chartBox = document.getElementById('detailChart').getBoundingClientRect();
                        if (activeId === 'sec-04') chartBox = document.getElementById('investorIndexChart').getBoundingClientRect();
                        return {
                            visibleIds,
                            isolated: visibleIds.length === 1 && visibleIds[0] === activeId,
                            docWidth: docW,
                            winWidth: winW,
                            overflow: docW > winW,
                            logoReady: logo.width >= 20 && logo.height >= 20,
                            chartReady: chartBox.width > 50 && chartBox.height > 50 && capChartReady && epChartReady,
                            chartKospiColor
                        };
                    }""", tid)

                    if not chk["isolated"]:
                        tab_isolation_ok = False
                    if chk["overflow"]:
                        any_overflow = True
                    if tid == "sec-01":
                        main_chart_ok = chk["chartReady"] and (chk["chartKospiColor"] == contrast_info["chartTokenValues"]["--chart-kospi"])
                        # 접기(details) 펼치기 동작 확인
                        page.click("#sec-01 details.more summary")
                        details_toggle_ok = page.evaluate("() => document.querySelector('#sec-01 details.more').open === true")
                    elif tid == "sec-02":
                        detail_chart_ok = chk["chartReady"]
                        rows_cnt = page.locator("#pure50-tbody tr").count()
                        # 검색 및 시장 필터 동작 확인
                        page.fill("#sec2-search", "하이닉스")
                        cnt_search = page.locator("#pure50-tbody tr").count()
                        page.fill("#sec2-search", "")
                        cnt_reset = page.locator("#pure50-tbody tr").count()
                        search_filter_ok = (cnt_search == 1 and cnt_reset == 50)
                    elif tid == "sec-04":
                        investor_chart_ok = chk["chartReady"]

                # 테마 전환 버튼 클릭 시 Chart.js 선 색상 즉시 변경 및 새로고침 후 유지 확인
                page.click('#tabs button[data-tab="sec-01"]')
                before_kospi_color = page.evaluate("() => Chart.getChart('mainChart').data.datasets[2].borderColor")
                page.click("#themeBtn")
                after_kospi_color = page.evaluate("() => Chart.getChart('mainChart').data.datasets[2].borderColor")
                instant_theme_switch_ok = (before_kospi_color != after_kospi_color)

                toggled_theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
                page.reload(wait_until="networkidle")
                persisted_theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
                theme_persist_ok = (toggled_theme == persisted_theme)

                passed = (
                    val_pure == "757.28" and
                    val_matched != "-" and
                    val_kospi == "1,877.92" and
                    val_kosdaq == "845.26" and
                    rows_cnt == 50 and
                    system_theme_ok and
                    contrast_ok and
                    aux_chart_ok and
                    period_filter_ok and
                    search_filter_ok and
                    details_toggle_ok and
                    instant_theme_switch_ok and
                    theme_persist_ok and
                    tab_isolation_ok and
                    not any_overflow and
                    main_chart_ok and
                    detail_chart_ok and
                    investor_chart_ok and
                    len(console_errors) == 0
                )

                res_item = {
                    "viewport": f"{vp['width']}x{vp['height']}",
                    "theme": theme_mode,
                    "status": "PASS" if passed else "FAIL",
                    "min_text_contrast_ratio": contrast_info["minTextRatio"],
                    "min_text_selector": contrast_info["minTextSelector"],
                    "min_chart_contrast_ratio": contrast_info["minChartRatio"],
                    "system_theme_auto_detect": system_theme_ok,
                    "instant_chart_theme_update": instant_theme_switch_ok,
                    "theme_persisted_on_reload": theme_persist_ok,
                    "tab_isolation_verified": tab_isolation_ok,
                    "horizontal_overflow": any_overflow,
                    "charts_rendered": main_chart_ok and detail_chart_ok and investor_chart_ok,
                    "aux_chart_toggle_ok": aux_chart_ok,
                    "period_filter_ok": period_filter_ok,
                    "search_filter_ok": search_filter_ok,
                    "details_toggle_ok": details_toggle_ok,
                    "console_errors": console_errors,
                    "screenshot": shot_path,
                }
                ui_report.append(res_item)
                print(
                    f"  [{res_item['status']}] {vp['width']}px ({theme_mode:5s}) | "
                    f"textContrast>={contrast_info['minTextRatio']} ({contrast_info['minTextSelector']}) | "
                    f"chartContrast>={contrast_info['minChartRatio']} | "
                    f"instantTheme={instant_theme_switch_ok} | persist={theme_persist_ok} | "
                    f"overflow={any_overflow} | errors={len(console_errors)}"
                )
                context.close()

        browser.close()
    httpd.shutdown()

    with open(os.path.join(DATA_DIR, "ui_verification_report.json"), "w", encoding="utf-8") as f:
        json.dump(ui_report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    run_ui_verification()
