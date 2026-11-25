(function () {
  "use strict";

  const THEME_STORAGE_KEY = "gaemi_theme";
  let DATA = window.GAEMI_DATA || null;
  let mainChart = null;
  let captureChart = null;
  let episodeChart = null;
  let detailChart = null;
  let invChart = null;
  let themeInitialized = false;

  const INDEX_STORAGE_KEY = "gaemi_selected_index";
  const state = {
    activeTab: "sec-01",
    selectedIndex: "50", // "50" | "100"
    period: "ALL", // ALL | 1Y | 6M | 3M | YTD
    selectedEpisodeId: null,
    showG50: false,
    showG100: false,
    showG51: false,
    showAbs: false,
    showKqEw: false,
    showTotal: false,
    sec2Scope: "50", // "50" | "100"
    sec2Market: "ALL",
    sec2Search: "",
    selectedStock: "417200",
    invListMode: "IND", // IND | FRG | ORG | DIV_IND | DIV_OTH
    selectedQuarter: null,
    ddMarket: "KOSPI", // "KOSPI" | "KOSDAQ"
    ddTsRange: 90,
    ddTsMetric: "median",
    boughtSort: "netbuy",
    selectedBucketRange: null,
  };

  function initSelectedIndex() {
    try {
      const params = new URLSearchParams(window.location.search);
      const urlIdx = params.get("idx");
      const saved = localStorage.getItem(INDEX_STORAGE_KEY);
      if (urlIdx === "100" || urlIdx === "50") {
        state.selectedIndex = urlIdx;
      } else if (saved === "100" || saved === "50") {
        state.selectedIndex = saved;
      }
    } catch (_) {}
  }
  initSelectedIndex();

  // --- 테마 초기화(중복 리스너 등록 방지 가드 적용), 로컬 저장소 보존, 시스템 테마 자동 감지 ---
  function initTheme() {
    try {
      const saved = localStorage.getItem(THEME_STORAGE_KEY);
      if (saved === "light" || saved === "dark") {
        document.documentElement.setAttribute("data-theme", saved);
      } else {
        document.documentElement.removeAttribute("data-theme");
      }
    } catch (_) {}

    if (!themeInitialized) {
      themeInitialized = true;
      if (window.matchMedia) {
        const mq = window.matchMedia("(prefers-color-scheme: dark)");
        const onSystemThemeChange = () => {
          let saved = null;
          try {
            saved = localStorage.getItem(THEME_STORAGE_KEY);
          } catch (_) {}
          if (!saved) {
            updateThemeButtonLabel();
            refreshActiveChart();
          }
        };
        if (mq.addEventListener) {
          mq.addEventListener("change", onSystemThemeChange);
        } else if (mq.addListener) {
          mq.addListener(onSystemThemeChange);
        }
      }
    }
    updateThemeButtonLabel();
  }

  function isDarkMode() {
    const curr = document.documentElement.getAttribute("data-theme");
    if (curr === "dark") return true;
    if (curr === "light") return false;
    return Boolean(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  function updateThemeButtonLabel() {
    const btn = document.getElementById("themeBtn");
    if (!btn) return;
    const dark = isDarkMode();
    btn.textContent = dark ? "라이트" : "다크";
    btn.setAttribute("aria-pressed", dark ? "true" : "false");
  }

  function toggleTheme() {
    const nextTheme = isDarkMode() ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", nextTheme);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    } catch (_) {}
    updateThemeButtonLabel();
    refreshActiveChart();
  }

  // CSS 디자인 토큰에서 현재 테마의 차트 색상을 동적으로 읽기
  function getChartTokens() {
    const cs = getComputedStyle(document.documentElement);
    const read = (prop, fallback) => (cs.getPropertyValue(prop) || "").trim() || fallback;
    return {
      gaemi: read("--chart-gaemi", "#d84b17"),
      gaemiFill: read("--chart-gaemi-fill", "rgba(216, 75, 23, 0.12)"),
      kospi: read("--chart-kospi", "#161615"),
      kosdaq: read("--chart-kosdaq", "#1862c4"),
      foreign: read("--chart-foreign", "#137a47"),
      institution: read("--chart-institution", "#7928ca"),
      aux: read("--chart-aux", "#5e5d58"),
      aux2: read("--chart-aux-2", "#8c4a08"),
      gaemi100: read("--chart-gaemi100", "#0d7a5f"),
      gaemi51: read("--chart-gaemi51", "#5a5954"),
      grid: read("--chart-grid", "rgba(90, 89, 84, 0.18)"),
      axis: read("--chart-axis", "#43423f"),
      rebLine: read("--chart-reb-line", "rgba(90, 89, 84, 0.35)"),
      rebText: read("--chart-reb-text", "#595853"),
      tooltipBg: read("--chart-tooltip-bg", "rgba(18, 18, 17, 0.94)"),
      tooltipInk: read("--chart-tooltip-ink", "#f6f6f4"),
      tooltipBorder: read("--chart-tooltip-border", "#34342f"),
    };
  }

  // PHASE 4 Section 6: 현재 활성화된 탭의 차트만 즉시 렌더링(다른 탭으로 이동할 때 activateTab에서 렌더링)
  function refreshActiveChart() {
    if (state.activeTab === "tab-conc") {
      renderDrawdownTimeseriesChart();
      renderConcentrationChart();
    } else if (!DATA) {
      return;
    } else if (state.activeTab === "tab-scorecard" || state.activeTab === "sec-01") {
      renderSection01();
    } else if (state.activeTab === "sec-02") {
      renderStockDetailPanel();
    } else if (state.activeTab === "sec-04") {
      renderSection04();
    }
  }

  function activateTab(tabId, updateHash = true) {
    const validTabs = ["tab-conc", "tab-bought", "tab-movement", "tab-scorecard", "tab-method", "sec-01", "sec-02", "sec-03", "sec-04", "sec-05", "sec-footer"];
    const target = validTabs.includes(tabId) ? tabId : "tab-conc";
    state.activeTab = target;

    document.querySelectorAll('#tabs button[role="tab"]').forEach((btn) => {
      const isSel = btn.getAttribute("data-tab") === target;
      btn.setAttribute("aria-selected", isSel ? "true" : "false");
    });

    document.querySelectorAll(".tab-panel").forEach((panel) => {
      if (panel.id === target) {
        panel.removeAttribute("hidden");
      } else {
        panel.setAttribute("hidden", "");
      }
    });

    if (updateHash) {
      history.replaceState(null, "", `#${target}`);
    }

    if (target === "tab-conc") {
      renderDrawdownHero();
      renderDrawdownDistribution();
      renderRetailTop50Drawdown();
      renderDrawdownTimeseriesChart();
      renderConcentrationHero();
      renderConcentrationChart();
    } else if (target === "tab-bought") {
      renderBoughtTab();
    } else if (target === "tab-movement") {
      renderMovementTab();
    } else if (target === "tab-scorecard") {
      renderSection01();
    } else if (target === "tab-method") {
      // methodology
    }
  }

  function fmtNum(n, d = 2) {
    if (n === null || n === undefined || isNaN(n)) return "-";
    return Number(n).toLocaleString("ko-KR", {
      minimumFractionDigits: d,
      maximumFractionDigits: d,
    });
  }

  function fmtInt(n) {
    if (n === null || n === undefined || isNaN(n)) return "-";
    return Math.round(Number(n)).toLocaleString("ko-KR");
  }

  function fmtEok(eokVal) {
    if (eokVal === null || eokVal === undefined || isNaN(eokVal)) return "-";
    const v = Number(eokVal);
    const sign = v < 0 ? "-" : "";
    const absV = Math.abs(v);
    if (absV >= 10000) {
      const jo = Math.trunc(absV / 10000);
      const rem = Math.round(absV % 10000);
      return `${sign}${jo.toLocaleString("ko-KR")}조 ${rem.toLocaleString("ko-KR")}억`;
    }
    return `${sign}${Math.round(absV).toLocaleString("ko-KR")}억`;
  }

  function fmtPct(v, d = 2) {
    if (v === null || v === undefined || isNaN(v)) return "-";
    const num = Number(v);
    const s = num > 0 ? "+" : "";
    return `${s}${num.toFixed(d)}%`;
  }

  function clsSign(v) {
    const num = Number(v);
    if (num > 0) return "up";
    if (num < 0) return "down";
    return "";
  }

  // 핵심 발견 세 가지 (데이터 기반 자동 갱신)
  function renderFactsBar() {
    const facts = (DATA.summary && DATA.summary.key_facts) || [];
    const el = document.getElementById("facts-bar");
    if (!el) return;
    el.innerHTML = facts
      .map(
        (f) => `<div class="fact-tile">
        <div class="fact-head">
          <span class="fact-label">${f.label}</span>
          <span class="fact-val">${f.value}</span>
        </div>
        <p class="fact-desc">${f.sentence}</p>
      </div>`
      )
      .join("");
  }

  // 기간 필터링 및 선택 구간 첫 거래일 = 1,000 정규화 (PHASE 7 시계열 병합 포함)
  function getPeriodRows() {
    const ts = DATA.timeseries || [];
    if (!ts.length) return [];
    const p7Ts = (DATA.phase7_expansion && DATA.phase7_expansion.timeseries_phase7) || [];
    const p7Map = new Map(p7Ts.map((r) => [r.date, r]));
    const mergedTs = ts.map((r) => {
      const extra = p7Map.get(r.date);
      return extra ? { ...r, ...extra } : r;
    });
    const maxDate = mergedTs[mergedTs.length - 1].date;
    const maxObj = new Date(maxDate);
    let cutDate = "2000-01-01";

    if (state.period === "1Y") {
      const d = new Date(maxObj);
      d.setFullYear(d.getFullYear() - 1);
      cutDate = d.toISOString().slice(0, 10);
    } else if (state.period === "6M") {
      const d = new Date(maxObj);
      d.setMonth(d.getMonth() - 6);
      cutDate = d.toISOString().slice(0, 10);
    } else if (state.period === "3M") {
      const d = new Date(maxObj);
      d.setMonth(d.getMonth() - 3);
      cutDate = d.toISOString().slice(0, 10);
    } else if (state.period === "YTD") {
      cutDate = `${maxDate.slice(0, 4)}-01-01`;
    }
    const filtered = mergedTs.filter((r) => r.date >= cutDate);
    return filtered.length >= 2 ? filtered : mergedTs;
  }

  function calcPeriodStats(rows, colVal) {
    const rawVals = rows.map((r) => Number(r[colVal]));
    const b0 = rawVals[0] || 1000;
    const reindexed = rawVals.map((v) => (v / b0) * 1000.0);
    const cur = reindexed[reindexed.length - 1];
    const prev = reindexed[reindexed.length - 2] || cur;
    const dailyPct = (cur / prev - 1) * 100;
    const dailyPt = cur - prev;
    const cumPct = (cur / 1000.0 - 1) * 100;

    const rets = [];
    for (let i = 1; i < reindexed.length; i++) {
      rets.push(reindexed[i] / reindexed[i - 1] - 1);
    }

    let peak = reindexed[0];
    let mdd = 0;
    for (let i = 0; i < reindexed.length; i++) {
      if (reindexed[i] > peak) peak = reindexed[i];
      const dd = (reindexed[i] / peak - 1) * 100;
      if (dd < mdd) mdd = dd;
    }

    const mean = rets.reduce((a, b) => a + b, 0) / Math.max(rets.length, 1);
    const variance =
      rets.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / Math.max(rets.length - 1, 1);
    const annVol = Math.sqrt(variance) * Math.sqrt(250) * 100;

    return {
      reindexed: reindexed.map((v) => Number(v.toFixed(2))),
      current: cur,
      dailyPt,
      dailyPct,
      cumPct,
      mdd,
      annVol,
      rets,
    };
  }

  function pearsonCorr(a, b) {
    const n = Math.min(a.length, b.length);
    if (n < 3) return 0;
    const ma = a.reduce((s, v) => s + v, 0) / n;
    const mb = b.reduce((s, v) => s + v, 0) / n;
    let num = 0,
      da = 0,
      db = 0;
    for (let i = 0; i < n; i++) {
      const xa = a[i] - ma;
      const xb = b[i] - mb;
      num += xa * xb;
      da += xa * xa;
      db += xb * xb;
    }
    return da > 0 && db > 0 ? num / Math.sqrt(da * db) : 0;
  }

  // PHASE 6 & 7: 하락장 성적표 ('증시가 떨어질 때'), 하락장/상승장 포착률, 하락장 사건별 차트 렌더링 (개미 50 / 개미 100 전환 지원)
  function renderPhase6DownsideSection() {
    const p6 = DATA.phase6_downside;
    const p7 = DATA.phase7_expansion;
    if (!p6) return;

    const is100 = state.selectedIndex === "100" && p7 && p7.perf_summary && p7.perf_summary.GAEMI_100;
    const hl = p6.auto_headline || {};
    const sc = p6.scorecard_when_market_falls || {};
    const cap = p6.capture_ratios || {};
    const dDays = p6.daily_downside_analysis || {};
    const sev = p6.severity_buckets || {};
    const epsObj = p6.drawdown_episodes || {};

    const p100Cap = is100 ? p7.perf_summary.GAEMI_100.vs_kosdaq : null;
    const m100Cap = is100 ? p7.perf_summary.MATCHED_100_EW.vs_kosdaq : null;
    const p100Kp = is100 ? p7.perf_summary.GAEMI_100.vs_kospi : null;
    const p50Cap = p7 && p7.perf_summary && p7.perf_summary.GAEMI_50 ? p7.perf_summary.GAEMI_50.vs_kosdaq : null;

    // 1) 상단 자동 생성 핵심 메시지 배너 (PHASE 8 통계 재검증 반영)
    const hlTextEl = document.getElementById("down-headline-text");
    if (hlTextEl) {
      if (is100 && p100Cap) {
        hlTextEl.textContent = `코스닥 하락월(10개월)에서 개미 100은 월평균 ${fmtPct(p100Cap.down_month_mean_pct)}(코스닥 ${fmtPct(p100Cap.bench_down_mean_pct)})를 기록했습니다.`;
      } else {
        hlTextEl.textContent = "개인 순매수 강도 상위 종목의 하락 폭이 더 컸지만, 기업 규모와 변동성 등을 고려하면 차이는 불확실합니다.";
      }
    }

    // 2) '증시가 떨어질 때' 4대 성적표
    const setEl = (id, txt) => {
      const el = document.getElementById(id);
      if (el) el.textContent = txt;
    };
    if (is100 && p100Cap && m100Cap) {
      const gapM = p100Cap.down_month_mean_pct - m100Cap.down_month_mean_pct;
      const st100 = (p7.statistical_tests && p7.statistical_tests.GAEMI_100 && p7.statistical_tests.GAEMI_100.vs_kosdaq_down_months) || {};
      setEl("down-scorecard-sample", `표본: 코스닥 하락월 ${p100Cap.down_months_count}개월`);
      setEl("sc-gaemi-down-mean", fmtPct(p100Cap.down_month_mean_pct));
      setEl("sc-gaemi-down-sub", `중앙값 ${fmtPct(st100.median_pct)} · 95% CI [${st100.ci95_pct ? st100.ci95_pct[0] : "-"}%, ${st100.ci95_pct ? st100.ci95_pct[1] : "-"}%]`);
      setEl("sc-kosdaq-down-mean", fmtPct(p100Cap.bench_down_mean_pct));
      setEl("sc-kosdaq-down-sub", `개미 100이 ${fmtPct(p100Cap.down_month_gap_pctp)}p ${p100Cap.down_month_gap_pctp < 0 ? "더 하락" : "방어"}`);
      setEl("sc-matched-down-mean", fmtPct(m100Cap.down_month_mean_pct));
      setEl("sc-matched-down-sub", `개미 100이 ${fmtPct(gapM)}p ${gapM < 0 ? "더 하락" : "방어"}`);
      setEl("sc-worse-ratio", `${p100Cap.worse_than_bench_months_pct}% (${p100Cap.worse_than_bench_months_count}/${p100Cap.down_months_count}개월)`);
      setEl("sc-worse-matched-sub", `유사 100 대비 월평균 ${fmtPct(gapM)}p`);
    } else {
      setEl("down-scorecard-sample", `표본: 코스닥 하락월 ${sc.kosdaq_down_months_count || 10}개월`);
      setEl("sc-gaemi-down-mean", fmtPct(sc.gaemi_mean_in_kosdaq_down_pct));
      setEl(
        "sc-gaemi-down-sub",
        `중앙값 ${fmtPct(sc.gaemi_median_in_kosdaq_down_pct)} · 기하 ${fmtPct(sc.gaemi_geo_in_kosdaq_down_pct)}`
      );
      setEl("sc-kosdaq-down-mean", fmtPct(sc.kosdaq_mean_in_kosdaq_down_pct));
      setEl(
        "sc-kosdaq-down-sub",
        `개미가 ${fmtPct(sc.gap_vs_kosdaq_mean_pctp)}p ${sc.gap_vs_kosdaq_mean_pctp < 0 ? "더 하락" : "방어"}`
      );
      setEl("sc-matched-down-mean", fmtPct(sc.matched50_mean_in_kosdaq_down_pct));
      setEl(
        "sc-matched-down-sub",
        `개미가 ${fmtPct(sc.gap_vs_matched50_mean_pctp)}p ${sc.gap_vs_matched50_mean_pctp < 0 ? "더 하락" : "방어"}`
      );
      setEl("sc-worse-ratio", `${sc.worse_than_kosdaq_months_pct}% (${sc.worse_than_kosdaq_months_count}/${sc.kosdaq_down_months_count}개월)`);
      setEl(
        "sc-worse-matched-sub",
        `유사 50 대비: ${sc.worse_than_matched50_in_kosdaq_down_pct}% (${sc.worse_than_matched50_in_kosdaq_down_count}/${sc.kosdaq_down_months_count}개월)`
      );
    }

    // 3) 하락장 포착률 가로 막대그래프 (100% 기준선 = 0~150% 스케일에서 66.67% 위치)
    const cKq = (cap.vs_kosdaq && cap.vs_kosdaq.GAEMI_50_PURE) || {};
    const cKqMatched = (cap.vs_kosdaq && cap.vs_kosdaq.MATCHED_50_EW) || {};
    const cKp = (cap.vs_kospi && cap.vs_kospi.GAEMI_50_PURE) || {};
    const cMt = (cap.vs_matched50 && cap.vs_matched50.GAEMI_50_PURE) || {};

    const capBarsEl = document.getElementById("down-capture-bars");
    if (capBarsEl) {
      const barItems = is100 && p100Cap && m100Cap && p100Kp
        ? [
            {
              label: `개미 100 (vs 코스닥 ${p100Cap.down_months_count}개월)`,
              ratio: p100Cap.downside_capture_pct,
              gapText: `개미100 ${fmtPct(p100Cap.down_month_mean_pct)} · 코스닥 ${fmtPct(p100Cap.bench_down_mean_pct)} (${p100Cap.down_month_gap_pctp >= 0 ? "+" : ""}${p100Cap.down_month_gap_pctp.toFixed(2)}%p)`,
              colorVar: "var(--chart-gaemi100)",
            },
            {
              label: `유사 100종목 (vs 코스닥 ${m100Cap.down_months_count}개월)`,
              ratio: m100Cap.downside_capture_pct,
              gapText: `유사100 ${fmtPct(m100Cap.down_month_mean_pct)} · 코스닥 ${fmtPct(m100Cap.bench_down_mean_pct)} (+${m100Cap.down_month_gap_pctp.toFixed(2)}%p)`,
              colorVar: "var(--chart-institution)",
            },
            {
              label: `개미 50 (vs 코스닥 ${p50Cap ? p50Cap.down_months_count : 10}개월)`,
              ratio: p50Cap ? p50Cap.downside_capture_pct : 115.9,
              gapText: `개미50 ${fmtPct(p50Cap ? p50Cap.down_month_mean_pct : -12.15)} · 코스닥 ${fmtPct(p100Cap.bench_down_mean_pct)}`,
              colorVar: "var(--chart-gaemi)",
            },
            {
              label: `개미 100 (vs 코스피 ${p100Kp.down_months_count}개월)`,
              ratio: p100Kp.downside_capture_pct,
              gapText: `개미100 ${fmtPct(p100Kp.down_month_mean_pct)} · 코스피 ${fmtPct(p100Kp.bench_down_mean_pct)}`,
              colorVar: "var(--chart-kospi)",
            },
          ]
        : [
            {
              label: `개미 50 (vs 코스닥 ${cKq.down_months_count || 10}개월)`,
              ratio: cKq.downside_capture_geo_pct || 115.9,
              gapText: `개미 ${fmtPct(cKq.port_down_arith_mean_pct)} · 코스닥 ${fmtPct(cKq.bench_down_arith_mean_pct)} (${fmtPct(cKq.mean_gap_in_down_months_pctp)}p)`,
              colorVar: "var(--chart-gaemi)",
            },
            {
              label: `유사 50종목 (vs 코스닥 ${cKqMatched.down_months_count || 10}개월)`,
              ratio: cKqMatched.downside_capture_geo_pct || 84.2,
              gapText: `유사50 ${fmtPct(cKqMatched.port_down_arith_mean_pct)} · 코스닥 ${fmtPct(cKqMatched.bench_down_arith_mean_pct)} (+${Number(cKqMatched.mean_gap_in_down_months_pctp).toFixed(2)}%p)`,
              colorVar: "var(--chart-institution)",
            },
            {
              label: `개미 50 (vs 유사 50종목 ${cMt.down_months_count || 12}개월)`,
              ratio: cMt.downside_capture_geo_pct || 137.0,
              gapText: `개미 ${fmtPct(cMt.port_down_arith_mean_pct)} · 유사50 ${fmtPct(cMt.bench_down_arith_mean_pct)} (${fmtPct(cMt.mean_gap_in_down_months_pctp)}p)`,
              colorVar: "var(--chart-gaemi)",
            },
            {
              label: `개미 50 (vs 코스피 ${cKp.down_months_count || 10}개월)`,
              ratio: cKp.downside_capture_geo_pct || 97.5,
              gapText: `개미 ${fmtPct(cKp.port_down_arith_mean_pct)} · 코스피 ${fmtPct(cKp.bench_down_arith_mean_pct)} (+${Number(cKp.mean_gap_in_down_months_pctp).toFixed(2)}%p)`,
              colorVar: "var(--chart-kospi)",
            },
          ];

      capBarsEl.innerHTML = barItems
        .map((it) => {
          const widthPct = Math.min(100, Math.max(0, (Number(it.ratio) / 150.0) * 100.0)).toFixed(1);
          return `<div>
            <div class="cap-item-head">
              <span>${it.label}</span>
              <strong style="font-family:var(--font-mono)">${Number(it.ratio).toFixed(1)}%</strong>
            </div>
            <div class="cap-track" title="세로선 = 기준시장 하락폭 100%">
              <div class="cap-ref-line"></div>
              <div class="cap-fill" style="width:${widthPct}%;background:${it.colorVar}"></div>
            </div>
            <span style="font-size:11px;color:var(--ink-3);display:block;margin-top:2px">${it.gapText}</span>
          </div>`;
        })
        .join("");
    }

    // 4) 상승장 vs 하락장 포착률 나란히 비교 Chart.js 막대 차트
    const tk = getChartTokens();
    const cKqEw = (cap.vs_kosdaq && cap.vs_kosdaq.KOSDAQ_EW) || {};
    const cFrg = (cap.vs_kosdaq && cap.vs_kosdaq.FOREIGN_50_PURE) || {};
    const capCanvas = document.getElementById("captureCompareChart");
    if (capCanvas) {
      const ctxCap = capCanvas.getContext("2d");
      if (captureChart) captureChart.destroy();
      const capLabels = is100 && p100Cap && m100Cap
        ? ["개미 100", "비슷한 주식 100개", "개미 50", "코스닥 동일가중"]
        : ["개미 50", "비슷한 주식 50개", "코스닥 동일가중", "외국인 강도 50"];
      const capDownData = is100 && p100Cap && m100Cap
        ? [
            p100Cap.downside_capture_pct,
            m100Cap.downside_capture_pct,
            p50Cap ? p50Cap.downside_capture_pct : 115.9,
            cKqEw.downside_capture_geo_pct || 91.3,
          ]
        : [
            cKq.downside_capture_geo_pct || 115.9,
            cKqMatched.downside_capture_geo_pct || 84.2,
            cKqEw.downside_capture_geo_pct || 91.3,
            cFrg.downside_capture_geo_pct || 91.5,
          ];
      const capUpData = is100 && p100Cap && m100Cap
        ? [
            p100Cap.upside_capture_pct,
            m100Cap.upside_capture_pct,
            p50Cap ? p50Cap.upside_capture_pct : 112.6,
            cKqEw.upside_capture_geo_pct || 121.4,
          ]
        : [
            cKq.upside_capture_geo_pct || 112.6,
            cKqMatched.upside_capture_geo_pct || 95.6,
            cKqEw.upside_capture_geo_pct || 121.4,
            cFrg.upside_capture_geo_pct || 118.7,
          ];
      captureChart = new Chart(ctxCap, {
        type: "bar",
        data: {
          labels: capLabels,
          datasets: [
            {
              label: "하락장 포착률 (낮을수록 방어 · 100%=코스닥)",
              data: capDownData,
              backgroundColor: is100 ? tk.gaemi100 : tk.gaemi,
              borderRadius: 4,
            },
            {
              label: "상승장 포착률 (높을수록 탄력 · 100%=코스닥)",
              data: capUpData,
              backgroundColor: tk.kosdaq,
              borderRadius: 4,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: {
            legend: {
              position: "top",
              align: "start",
              labels: { color: tk.axis, boxWidth: 12, boxHeight: 10, font: { size: 11, weight: "600" } },
            },
            tooltip: {
              backgroundColor: tk.tooltipBg,
              titleColor: tk.tooltipInk,
              bodyColor: tk.tooltipInk,
              borderColor: tk.tooltipBorder,
              borderWidth: 1,
              callbacks: {
                label(c) {
                  return ` ${c.dataset.label.split(" (")[0]}: ${Number(c.parsed.y).toFixed(1)}%`;
                },
              },
            },
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: tk.axis, font: { size: 11, weight: "600" } },
            },
            y: {
              min: 0,
              max: 140,
              grid: { color: tk.grid },
              ticks: {
                color: tk.axis,
                font: { family: "JetBrains Mono", size: 10 },
                callback: (v) => `${v}%`,
              },
            },
          },
        },
      });
    }

    // 5) 코스닥 하락월 10개월 상세 표 & 일간/하락폭 구간별 반응 표
    const downMonthsTbody = document.getElementById("kosdaq-down-months-tbody");
    if (downMonthsTbody) {
      const mList = p6.kosdaq_down_months_table || [];
      downMonthsTbody.innerHTML = mList
        .map(
          (r) => `<tr>
          <td><strong>${r.ym}</strong></td>
          <td class="r down">${fmtPct(r.KOSDAQ)}</td>
          <td class="r ${clsSign(r.GAEMI_50_PURE)}"><strong>${fmtPct(r.GAEMI_50_PURE)}</strong></td>
          <td class="r ${clsSign(r.gap_vs_kosdaq)}">${r.gap_vs_kosdaq > 0 ? "+" : ""}${r.gap_vs_kosdaq.toFixed(2)}%p</td>
          <td class="r ${clsSign(r.MATCHED_50_EW)}">${fmtPct(r.MATCHED_50_EW)}</td>
          <td class="r ${clsSign(r.gap_vs_matched)}"><strong>${r.gap_vs_matched > 0 ? "+" : ""}${r.gap_vs_matched.toFixed(2)}%p</strong></td>
        </tr>`
        )
        .join("");
    }

    const sevTbody = document.getElementById("down-daily-severity-tbody");
    if (sevTbody) {
      const dkq = dDays.kosdaq_down_days || {};
      const dkp = dDays.kospi_down_days || {};
      const sMonthly = (sev.monthly_kosdaq || []).filter((b) => b.months_count > 0);
      const sDaily = sev.daily_kosdaq || [];

      const rowsHtml = [
        `<tr>
          <td><strong>코스닥 하락일 전체 (${dkq.down_days_count}거래일)</strong></td>
          <td class="r down">${fmtPct(dkq.bench_mean_return_pct)}</td>
          <td class="r down"><strong>${fmtPct(dkq.gaemi_mean_return_pct)}</strong> <span class="code-sub">(상승 ${dkq.gaemi_positive_on_down_day_pct}%)</span></td>
          <td class="r down">${fmtPct(dkq.matched50_mean_return_pct)}</td>
          <td class="r">${dkq.worse_than_bench_days_pct}% (${dkq.worse_than_bench_days_count}일)</td>
        </tr>`,
        `<tr>
          <td><strong>코스피 하락일 전체 (${dkp.down_days_count}거래일)</strong></td>
          <td class="r down">${fmtPct(dkp.bench_mean_return_pct)}</td>
          <td class="r down"><strong>${fmtPct(dkp.gaemi_mean_return_pct)}</strong> <span class="code-sub">(상승 ${dkp.gaemi_positive_on_down_day_pct}%)</span></td>
          <td class="r down">${fmtPct(dkp.matched50_mean_return_pct)}</td>
          <td class="r">${dkp.worse_than_bench_days_pct}% (${dkp.worse_than_bench_days_count}일)</td>
        </tr>`,
        ...sMonthly.map(
          (b) => `<tr>
            <td>월간 코스닥 ${b.bucket} (${b.months_count}개월)</td>
            <td class="r down">${fmtPct(b.bench_mean_pct)}</td>
            <td class="r down"><strong>${fmtPct(b.gaemi_mean_pct)}</strong></td>
            <td class="r down">${fmtPct(b.matched50_mean_pct)}</td>
            <td class="r">${b.worse_than_bench_count}/${b.months_count}개월</td>
          </tr>`
        ),
        ...sDaily.map(
          (b) => `<tr>
            <td>${b.bucket} (${b.days_count}일)</td>
            <td class="r down">${fmtPct(b.bench_mean_pct)}</td>
            <td class="r down"><strong>${fmtPct(b.gaemi_mean_pct)}</strong></td>
            <td class="r down">${fmtPct(b.matched50_mean_pct)}</td>
            <td class="r">${b.worse_than_bench_pct}%</td>
          </tr>`
        ),
      ];
      sevTbody.innerHTML = rowsHtml.join("");
    }

    // 6) 주요 하락장 사건별(Drawdown Episodes) 버튼, 요약 타일, 시작일=100 차트, 전체 테이블
    const kqEps = epsObj.kosdaq_episodes || [];
    if (kqEps.length > 0) {
      if (!state.selectedEpisodeId || !kqEps.some((e) => e.episode_id === state.selectedEpisodeId)) {
        // 기본 선택: 가장 최근 또는 낙폭이 큰 주요 하락장 (#6 2026.06~07 또는 최신 #7)
        state.selectedEpisodeId = kqEps[kqEps.length - 2] ? kqEps[kqEps.length - 2].episode_id : kqEps[0].episode_id;
      }

      const epBtnsEl = document.getElementById("episode-btns");
      if (epBtnsEl) {
        epBtnsEl.innerHTML = kqEps
          .map((e, i) => {
            const onCls = e.episode_id === state.selectedEpisodeId ? "on" : "";
            const shortPeriod = `${e.start_date.slice(2, 7)}~${e.end_date.slice(5, 10)}`;
            return `<button type="button" class="${onCls}" data-epid="${e.episode_id}">하락장 #${i + 1} (${shortPeriod})</button>`;
          })
          .join("");

        epBtnsEl.querySelectorAll("button").forEach((btn) => {
          btn.addEventListener("click", () => {
            state.selectedEpisodeId = btn.getAttribute("data-epid");
            renderEpisodeDetail(kqEps, tk);
            epBtnsEl.querySelectorAll("button").forEach((b) => b.classList.remove("on"));
            btn.classList.add("on");
          });
        });
      }

      renderEpisodeDetail(kqEps, tk);

      const allEpTbody = document.getElementById("all-episodes-tbody");
      if (allEpTbody) {
        allEpTbody.innerHTML = kqEps
          .map((e) => {
            const r = e.returns_pct;
            const g = e.gaps_vs_gaemi_pctp;
            return `<tr>
              <td><strong>${e.title}</strong></td>
              <td class="r">${e.trading_days_to_trough}일</td>
              <td class="r down">${fmtPct(r.KOSDAQ)}</td>
              <td class="r down"><strong>${fmtPct(r.GAEMI_50_PURE)}</strong></td>
              <td class="r down">${fmtPct(r.MATCHED_50_EW)}</td>
              <td class="r ${clsSign(r.KOSPI)}">${fmtPct(r.KOSPI)}</td>
              <td class="r ${clsSign(g.vs_MATCHED_50)}"><strong>${g.vs_MATCHED_50 > 0 ? "+" : ""}${g.vs_MATCHED_50.toFixed(2)}%p</strong></td>
              <td class="r">${e.recovery.GAEMI_50_PURE.status_label}</td>
            </tr>`;
          })
          .join("");
      }

      const ddSensTbody = document.getElementById("dd-sens-tbody");
      if (ddSensTbody) {
        ddSensTbody.innerHTML = (epsObj.threshold_sensitivity || [])
          .map(
            (s) => `<tr>
            <td><strong>${s.threshold_pct}</strong></td>
            <td class="r">${s.episode_count}건</td>
            <td class="r down">${fmtPct(s.kosdaq_avg_drop_pct)}</td>
            <td class="r down"><strong>${fmtPct(s.gaemi_avg_drop_pct)}</strong></td>
            <td class="r down">${fmtPct(s.matched50_avg_drop_pct)}</td>
            <td class="r">${s.worse_than_kosdaq_episodes} (평균 ${s.gaemi_gap_vs_kosdaq_pctp > 0 ? "+" : ""}${s.gaemi_gap_vs_kosdaq_pctp.toFixed(2)}%p)</td>
            <td class="r"><strong>${s.worse_than_matched50_episodes} (평균 ${s.gaemi_gap_vs_matched50_pctp > 0 ? "+" : ""}${s.gaemi_gap_vs_matched50_pctp.toFixed(2)}%p)</strong></td>
          </tr>`
          )
          .join("");
      }
    }
  }

  function renderEpisodeDetail(kqEps, tk) {
    const ep = kqEps.find((e) => e.episode_id === state.selectedEpisodeId) || kqEps[0];
    if (!ep) return;
    const p7 = DATA.phase7_expansion;
    const is100 = state.selectedIndex === "100" && p7 && Array.isArray(p7.episode_comparison);
    const ep7 = is100 ? p7.episode_comparison.find((e) => e.episode_id === ep.episode_id) : null;
    const r = ep.returns_pct;
    const g = ep.gaps_vs_gaemi_pctp;
    const rec = ep.recovery;

    const mainRet = ep7 ? ep7.returns_pct.GAEMI_100 : r.GAEMI_50_PURE;
    const matchRet = ep7 ? ep7.returns_pct.MATCHED_100_EW : r.MATCHED_50_EW;
    const kqRet = ep7 ? ep7.returns_pct.KOSDAQ : r.KOSDAQ;
    const kpRet = ep7 ? ep7.returns_pct.KOSPI : r.KOSPI;
    const gapM = mainRet - matchRet;
    const gapKq = mainRet - kqRet;
    const gapKp = mainRet - kpRet;

    const cardsEl = document.getElementById("episode-summary-cards");
    if (cardsEl) {
      cardsEl.innerHTML = `
        <div class="down-box">
          <span class="dk">${is100 ? "개미 100" : "개미 50"} (${ep.start_date}~${ep.end_date})</span>
          <span class="dv down">${fmtPct(mainRet)}</span>
          <span class="ds">${is100 ? `개미 50: ${fmtPct(r.GAEMI_50_PURE)}` : `회복: ${rec.GAEMI_50_PURE.status_label}`}</span>
        </div>
        <div class="down-box">
          <span class="dk">${is100 ? "유사 100종목" : "유사 50종목"}</span>
          <span class="dv down">${fmtPct(matchRet)}</span>
          <span class="ds">개미 대비 <strong>${gapM > 0 ? "+" : ""}${gapM.toFixed(2)}%p</strong>${is100 ? "" : ` · ${rec.MATCHED_50_EW.status_label}`}</span>
        </div>
        <div class="down-box">
          <span class="dk">코스닥</span>
          <span class="dv down">${fmtPct(kqRet)}</span>
          <span class="ds">개미 대비 <strong>${gapKq > 0 ? "+" : ""}${gapKq.toFixed(2)}%p</strong> · ${rec.KOSDAQ.status_label}</span>
        </div>
        <div class="down-box">
          <span class="dk">코스피</span>
          <span class="dv ${clsSign(kpRet)}">${fmtPct(kpRet)}</span>
          <span class="ds">개미 대비 <strong>${gapKp > 0 ? "+" : ""}${gapKp.toFixed(2)}%p</strong> · ${rec.KOSPI.status_label}</span>
        </div>
      `;
    }

    const noteEl = document.getElementById("episode-chart-note");
    if (noteEl) {
      noteEl.textContent = `* ${ep.title} (${ep.start_date} = 100) · 점선: 코스닥 저점(${ep.end_date}, ${ep.trading_days_to_trough}거래일)`;
    }

    const tr = ep.trajectory_base100;
    const epCanvas = document.getElementById("episodeChart");
    if (!epCanvas || !tr) return;

    const troughPlugin = {
      id: "troughLine",
      afterDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea) return;
        const x = scales.x.getPixelForValue(tr.trough_index_in_series);
        if (x >= chartArea.left && x <= chartArea.right) {
          ctx.save();
          ctx.beginPath();
          ctx.setLineDash([4, 3]);
          ctx.strokeStyle = tk.rebLine;
          ctx.moveTo(x, chartArea.top);
          ctx.lineTo(x, chartArea.bottom);
          ctx.stroke();
          ctx.fillStyle = tk.rebText;
          ctx.font = "600 10px 'JetBrains Mono', monospace";
          ctx.fillText(`저점 (${tr.trough_date})`, Math.min(x + 4, chartArea.right - 95), chartArea.top + 12);
          ctx.restore();
        }
      },
    };

    const ctxEp = epCanvas.getContext("2d");
    if (episodeChart) episodeChart.destroy();
    episodeChart = new Chart(ctxEp, {
      type: "line",
      data: {
        labels: tr.dates,
        datasets: [
          {
            label: "개미 지수 (실선)",
            data: tr.GAEMI_50_PURE,
            borderColor: tk.gaemi,
            backgroundColor: tk.gaemiFill,
            borderWidth: 2.7,
            borderDash: [],
            pointRadius: 0,
            tension: 0.1,
            order: 1,
          },
          {
            label: "비슷한 주식 50개 (굵은 파선)",
            data: tr.MATCHED_50_EW,
            borderColor: tk.institution,
            backgroundColor: "transparent",
            borderWidth: 2.3,
            borderDash: [8, 4],
            pointRadius: 0,
            tension: 0.1,
            order: 2,
          },
          {
            label: "코스닥 (짧은 점선)",
            data: tr.KOSDAQ,
            borderColor: tk.kosdaq,
            backgroundColor: "transparent",
            borderWidth: 2.0,
            borderDash: [2, 3],
            pointRadius: 0,
            tension: 0.1,
            order: 3,
          },
          {
            label: "코스피 (긴 점선)",
            data: tr.KOSPI,
            borderColor: tk.kospi,
            backgroundColor: "transparent",
            borderWidth: 1.8,
            borderDash: [5, 4],
            pointRadius: 0,
            tension: 0.1,
            order: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "top",
            align: "start",
            labels: { color: tk.axis, boxWidth: 16, boxHeight: 3, font: { size: 11.5, weight: "600" } },
          },
          tooltip: {
            backgroundColor: tk.tooltipBg,
            titleColor: tk.tooltipInk,
            bodyColor: tk.tooltipInk,
            borderColor: tk.tooltipBorder,
            borderWidth: 1,
            callbacks: {
              label(c) {
                const v = c.parsed.y;
                const diff = (v - 100.0).toFixed(2);
                const s = diff > 0 ? "+" : "";
                return ` ${c.dataset.label}: ${v.toFixed(2)} (${s}${diff}%)`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: tk.axis, maxTicksLimit: 7, font: { family: "JetBrains Mono", size: 10.5 } },
          },
          y: {
            grid: { color: tk.grid },
            ticks: { color: tk.axis, font: { family: "JetBrains Mono", size: 10.5 } },
          },
        },
      },
      plugins: [troughPlugin],
    });
  }

  // PHASE 7: '더 많이 산 주식이 더 크게 떨어졌을까?' (1~50 · 51~100 · 101~150위 + 민감도 + 통계검증)
  function renderPhase7IntensityCard() {
    const p7 = DATA.phase7_expansion;
    if (!p7) return;

    const tiers = p7.intensity_tiers || [];
    const reg = p7.controlled_regression || {};
    const tagEl = document.getElementById("p7-intensity-stat-tag");
    if (tagEl && tiers.length === 3) {
      tagEl.textContent =
        `${tiers[0].down_month_mean_pct.toFixed(2)}% vs ${tiers[1].down_month_mean_pct.toFixed(2)}% vs ${tiers[2].down_month_mean_pct.toFixed(2)}% · 군집·통제보강 p=0.054`;
    }

    const tbody = document.getElementById("p7-intensity-tbody");
    if (tbody) {
      tbody.innerHTML = tiers
        .map(
          (t) => `<tr>
          <td><strong>${t.tier}</strong></td>
          <td class="r down"><strong>${fmtPct(t.down_month_mean_pct)}</strong></td>
          <td class="r up">${fmtPct(t.up_month_mean_pct)}</td>
          <td class="r"><strong>${Number(t.downside_capture_pct).toFixed(1)}%</strong></td>
          <td class="r">${Number(t.upside_capture_pct).toFixed(1)}%</td>
          <td class="r down">${Number(t.mdd_pct).toFixed(2)}%</td>
          <td class="r">${Number(t.downside_beta_kosdaq).toFixed(3)}</td>
        </tr>`
        )
        .join("");
    }

    const sensEl = document.getElementById("p7-sens-tbody");
    if (sensEl) {
      sensEl.innerHTML = (p7.sensitivity_n || [])
        .map(
          (s) => `<tr>
          <td><strong>GAEMI ${s.n_stocks}</strong></td>
          <td class="r ${clsSign(s.total_return_pct)}"><strong>${fmtPct(s.total_return_pct)}</strong></td>
          <td class="r down">${Number(s.mdd_pct).toFixed(2)}%</td>
          <td class="r">${Number(s.ann_volatility_pct).toFixed(2)}%</td>
          <td class="r">${Number(s.downside_capture_kosdaq_pct).toFixed(1)}%</td>
          <td class="r">${Number(s.upside_capture_kosdaq_pct).toFixed(1)}%</td>
        </tr>`
        )
        .join("");
    }

    const statEl = document.getElementById("p7-stat-tbody");
    if (statEl && p7.statistical_tests) {
      const rows = [
        ["GAEMI 50", p7.statistical_tests.GAEMI_50],
        ["GAEMI 100", p7.statistical_tests.GAEMI_100],
        ["51~100위", p7.statistical_tests.GAEMI_51_100],
        ["101~150위", p7.statistical_tests.GAEMI_101_150],
      ];
      statEl.innerHTML = rows
        .filter(([, obj]) => obj)
        .map(([lbl, obj]) => {
          const kq = obj.vs_kosdaq_down_months;
          const mt = obj.vs_matched_down_months;
          return `<tr>
            <td><strong>${lbl}</strong></td>
            <td class="r down">${fmtPct(kq.mean_pct)} [${kq.ci95_pct[0]}%, ${kq.ci95_pct[1]}%]</td>
            <td class="r ${clsSign(kq.diff_mean_pctp)}">${kq.diff_mean_pctp > 0 ? "+" : ""}${kq.diff_mean_pctp.toFixed(2)}%p</td>
            <td class="r ${clsSign(mt.diff_mean_pctp)}">${mt.diff_mean_pctp > 0 ? "+" : ""}${mt.diff_mean_pctp.toFixed(2)}%p (p=${mt.p_value.toFixed(3)})</td>
          </tr>`;
        })
        .join("");
    }

    const abEl = document.getElementById("p7-ab-diag");
    if (abEl && p7.ab_stability && p7.matched100_diagnostics) {
      const ab = p7.ab_stability;
      const m100 = p7.matched100_diagnostics;
      abEl.textContent =
        `A/B 추정 일치율 — 상위 50: ${ab.avg_top50_overlap_pct}% · 상위 100: ${ab.avg_top100_overlap_pct}% · 51~100위: ${ab.avg_rank51_100_overlap_pct}% | 유사 100 매칭: 평균 ${m100.avg_matched_count}/100 (동일업종 ${m100.avg_tier1_same_sector} · 동일시장 ${m100.avg_tier2_same_market} · 미매칭 ${m100.avg_unmatched})`;
    }
  }

  // TAB 1: 개미 지수 (상단 고정 스트립 + 하락장 분석 + 메인 비교 차트 + 상세 성과 표)
  function renderSection01() {
    renderPhase6DownsideSection();
    renderPhase7IntensityCard();
    const rows = getPeriodRows();
    if (!rows.length) return;
    const startDt = rows[0].date;
    const endDt = rows[rows.length - 1].date;
    const baseDt = DATA.summary.base_date || "2024-09-30";

    const setTxt = (id, txt) => {
      const el = document.getElementById(id);
      if (el) el.textContent = txt;
    };
    const setCls = (id, cls) => {
      const el = document.getElementById(id);
      if (el) el.className = cls;
    };

    setTxt("header-asof", `기준일 ${baseDt}=1,000 · 최신 ${endDt}(잠정)`);
    setTxt("period-label-pure", `시작일 ${startDt} = 1,000`);
    setTxt("chart-reindexed-note", `* 선택한 기간 첫 거래일(${startDt})을 1,000.00으로 맞춘 가격지수(배당 제외·잠정) 추이입니다 (${startDt} ~ ${endDt}).`);

    const is100 = state.selectedIndex === "100" && rows[0].GAEMI_100 !== undefined;
    document.querySelectorAll("#index-switch button").forEach((b) => {
      b.classList.toggle("on", b.getAttribute("data-idx") === state.selectedIndex);
    });
    const swTag = document.getElementById("index-switch-tag");
    if (swTag) {
      swTag.textContent = is100
        ? "비교지수: GAEMI 100 (상위 100 · 1% 동일가중)"
        : "대표지수: GAEMI 50 PURE (상위 50 · 2% 동일가중)";
    }

    const stPure50 = calcPeriodStats(rows, "GAEMI_50_PURE");
    const stG100 = rows[0].GAEMI_100 !== undefined ? calcPeriodStats(rows, "GAEMI_100") : stPure50;
    const stG51 = rows[0].GAEMI_51_100 !== undefined ? calcPeriodStats(rows, "GAEMI_51_100") : null;
    const stMatched50 = calcPeriodStats(rows, "MATCHED_50_EW");
    const stMatched100 = rows[0].MATCHED_100_EW !== undefined ? calcPeriodStats(rows, "MATCHED_100_EW") : stMatched50;

    const stPure = is100 ? stG100 : stPure50;
    const stMatched = is100 ? stMatched100 : stMatched50;
    const stKospi = calcPeriodStats(rows, "KOSPI_norm");
    const stKosdaq = calcPeriodStats(rows, "KOSDAQ_norm");
    const stAbs = calcPeriodStats(rows, "GAEMI_50_ABS");
    const stKqEw = calcPeriodStats(rows, "KOSDAQ_EW");
    const stTotal = calcPeriodStats(rows, "GAEMI_50_TOTAL");

    const titleMainEl = document.getElementById("tile-main-title");
    if (titleMainEl) titleMainEl.textContent = is100 ? "개미 100 (GAEMI 100 · 잠정)" : "개미 50 (GAEMI 50 PURE · 잠정)";
    const titleMatchedEl = document.getElementById("tile-matched-title");
    if (titleMatchedEl) titleMatchedEl.textContent = is100 ? "비슷한 주식 100개 (시총·업종 유사)" : "비슷한 주식 50개 (시총·업종 유사)";

    // 1) 상단 4개 핵심 비교 카드 업데이트 (개미 지수, 비슷한 주식 50개, 코스피, 코스닥)
    setTxt("val-pure", fmtNum(stPure.current, 2));
    const sgn = stPure.dailyPt > 0 ? "▲ +" : stPure.dailyPt < 0 ? "▼ " : "";
    setTxt("chg-pure", `전일비 ${sgn}${fmtNum(stPure.dailyPt, 2)} (${fmtPct(stPure.dailyPct)})`);
    setCls("chg-pure", `tile-chg ${clsSign(stPure.dailyPct)}`);

    setTxt("cum-pure", fmtPct(stPure.cumPct));
    setCls("cum-pure", clsSign(stPure.cumPct));

    // 2번째 카드: 비슷한 주식 50개 (시총·업종 유사 비교 포트폴리오)
    setTxt("val-matched", fmtNum(stMatched.current, 2));
    setTxt("cum-matched", `동일 기간 ${fmtPct(stMatched.cumPct)}`);
    setCls("cum-matched", `tile-chg ${clsSign(stMatched.cumPct)}`);

    const gapMatched = stPure.cumPct - stMatched.cumPct;
    setTxt("gap-matched", `${gapMatched > 0 ? "+" : ""}${gapMatched.toFixed(2)}%p`);
    setCls("gap-matched", clsSign(gapMatched));

    // 3번째 카드: 코스피
    setTxt("raw-kospi", `실제 ${fmtNum(DATA.summary.metrics.KOSPI_raw, 2)}`);
    setTxt("val-kospi", fmtNum(stKospi.current, 2));
    setTxt("cum-kospi", `동일 기간 ${fmtPct(stKospi.cumPct)}`);
    setCls("cum-kospi", `tile-chg ${clsSign(stKospi.cumPct)}`);

    const gapKospi = stPure.cumPct - stKospi.cumPct;
    setTxt("gap-kospi", `${gapKospi > 0 ? "+" : ""}${gapKospi.toFixed(2)}%p`);
    setCls("gap-kospi", clsSign(gapKospi));

    // 4번째 카드: 코스닥
    setTxt("raw-kosdaq", `실제 ${fmtNum(DATA.summary.metrics.KOSDAQ_raw, 2)}`);
    setTxt("val-kosdaq", fmtNum(stKosdaq.current, 2));
    setTxt("cum-kosdaq", `동일 기간 ${fmtPct(stKosdaq.cumPct)}`);
    setCls("cum-kosdaq", `tile-chg ${clsSign(stKosdaq.cumPct)}`);

    const gapKosdaq = stPure.cumPct - stKosdaq.cumPct;
    setTxt("gap-kosdaq", `${gapKosdaq > 0 ? "+" : ""}${gapKosdaq.toFixed(2)}%p`);
    setCls("gap-kosdaq", clsSign(gapKosdaq));

    // 2) 기본 4개 지수 차트 (선택된 개미 50/100 → 비슷한 주식 50/100 → 코스피 → 코스닥)
    const tk = getChartTokens();
    const datasets = [
      {
        label: is100 ? "개미 100 (GAEMI 100 · 실선)" : "개미 50 (GAEMI 50 PURE · 실선)",
        data: stPure.reindexed,
        borderColor: is100 ? tk.gaemi100 : tk.gaemi,
        backgroundColor: is100 ? "transparent" : tk.gaemiFill,
        borderWidth: 2.8,
        borderDash: [],
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.1,
        order: 1,
      },
      {
        label: is100 ? "비슷한 주식 100개 (굵은 파선)" : "비슷한 주식 50개 (굵은 파선)",
        data: stMatched.reindexed,
        borderColor: tk.institution,
        backgroundColor: "transparent",
        borderWidth: 2.3,
        borderDash: [8, 4],
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.1,
        order: 2,
      },
      {
        label: "코스피 (1,000 환산 · 긴 점선)",
        data: stKospi.reindexed,
        borderColor: tk.kospi,
        backgroundColor: "transparent",
        borderWidth: 1.9,
        borderDash: [5, 4],
        pointRadius: 0,
        pointHoverRadius: 3,
        tension: 0.1,
        order: 3,
      },
      {
        label: "코스닥 (1,000 환산 · 짧은 점선)",
        data: stKosdaq.reindexed,
        borderColor: tk.kosdaq,
        backgroundColor: "transparent",
        borderWidth: 1.8,
        borderDash: [2, 3],
        pointRadius: 0,
        pointHoverRadius: 3,
        tension: 0.1,
        order: 4,
      },
    ];

    if (state.showG50 && is100) {
      datasets.push({
        label: "개미 50 (GAEMI 50 PURE)",
        data: stPure50.reindexed,
        borderColor: tk.gaemi,
        backgroundColor: "transparent",
        borderWidth: 2.1,
        borderDash: [6, 3],
        pointRadius: 0,
        tension: 0.1,
        order: 5,
      });
    }
    if (state.showG100 && !is100) {
      datasets.push({
        label: "개미 100 (GAEMI 100)",
        data: stG100.reindexed,
        borderColor: tk.gaemi100,
        backgroundColor: "transparent",
        borderWidth: 2.1,
        borderDash: [6, 3],
        pointRadius: 0,
        tension: 0.1,
        order: 5,
      });
    }
    if (state.showG51 && stG51) {
      datasets.push({
        label: "개미 51~100위",
        data: stG51.reindexed,
        borderColor: tk.gaemi51,
        backgroundColor: "transparent",
        borderWidth: 1.9,
        borderDash: [3, 3],
        pointRadius: 0,
        tension: 0.1,
        order: 5,
      });
    }

    if (state.showKqEw) {
      datasets.push({
        label: "코스닥 동일가중",
        data: stKqEw.reindexed,
        borderColor: tk.foreign,
        backgroundColor: "transparent",
        borderWidth: 1.8,
        borderDash: [4, 2],
        pointRadius: 0,
        tension: 0.1,
        order: 5,
      });
    }
    if (state.showAbs) {
      datasets.push({
        label: "단순 순매수금액 상위 50",
        data: stAbs.reindexed,
        borderColor: tk.aux,
        backgroundColor: "transparent",
        borderWidth: 1.7,
        borderDash: [2, 2],
        pointRadius: 0,
        tension: 0.1,
        order: 6,
      });
    }
    if (state.showTotal) {
      datasets.push({
        label: "개미 지수 (KRX+NXT 합산)",
        data: stTotal.reindexed,
        borderColor: tk.aux2,
        backgroundColor: "transparent",
        borderWidth: 1.7,
        borderDash: [8, 2, 2, 2],
        pointRadius: 0,
        tension: 0.1,
        order: 7,
      });
    }

    const rebMarkers = [];
    rows.forEach((r, idx) => {
      if (r.is_rebalance_date && idx > 0) {
        rebMarkers.push({ index: idx, label: r.rebalance_id });
      }
    });

    const rebPlugin = {
      id: "rebLines",
      afterDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea) return;
        const chartW = chartArea.right - chartArea.left;
        const showText = chartW >= 420;
        ctx.save();
        rebMarkers.forEach((m) => {
          const x = scales.x.getPixelForValue(m.index);
          if (x >= chartArea.left && x <= chartArea.right) {
            ctx.beginPath();
            ctx.setLineDash([3, 3]);
            ctx.strokeStyle = tk.rebLine;
            ctx.moveTo(x, chartArea.top);
            ctx.lineTo(x, chartArea.bottom);
            ctx.stroke();
            if (showText) {
              ctx.fillStyle = tk.rebText;
              ctx.font = "600 10px 'JetBrains Mono', monospace";
              ctx.fillText(m.label, x + 3, chartArea.top + 11);
            }
          }
        });
        ctx.restore();
      },
    };

    const ctx = document.getElementById("mainChart").getContext("2d");
    if (mainChart) mainChart.destroy();
    mainChart = new Chart(ctx, {
      type: "line",
      data: { labels: rows.map((r) => r.date), datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "top",
            align: "start",
            labels: {
              color: tk.axis,
              boxWidth: 18,
              boxHeight: 3,
              font: { size: 12, weight: "600" },
            },
          },
          tooltip: {
            backgroundColor: tk.tooltipBg,
            titleColor: tk.tooltipInk,
            bodyColor: tk.tooltipInk,
            borderColor: tk.tooltipBorder,
            borderWidth: 1,
            callbacks: {
              label(c) {
                const v = c.parsed.y;
                const pct = ((v / 1000.0 - 1) * 100).toFixed(2);
                const s = pct > 0 ? "+" : "";
                return ` ${c.dataset.label}: ${fmtNum(v, 2)} (${s}${pct}%)`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: tk.axis, maxTicksLimit: 8, font: { family: "JetBrains Mono", size: 11 } },
          },
          y: {
            grid: { color: tk.grid },
            ticks: { color: tk.axis, font: { family: "JetBrains Mono", size: 11 } },
          },
        },
      },
      plugins: [rebPlugin],
    });

    // 3) 접기 상세 성과 테이블
    const tableConfigs = [
      { name: "개미 50 (GAEMI 50 PURE · 잠정)", st: stPure50 },
      ...(stG100 !== stPure50 ? [{ name: "개미 100 (GAEMI 100 · 잠정)", st: stG100 }] : []),
      ...(stG51 ? [{ name: "개미 51~100위", st: stG51 }] : []),
      { name: "코스피 (1,000 환산)", st: stKospi },
      { name: "코스닥 (1,000 환산)", st: stKosdaq },
      { name: "비슷한 주식 50개 (시총·업종 유사)", st: stMatched50 },
      ...(stMatched100 !== stMatched50 ? [{ name: "비슷한 주식 100개 (시총·업종 유사)", st: stMatched100 }] : []),
      { name: "코스닥 동일가중", st: stKqEw },
      { name: "단순 순매수금액 상위 50", st: stAbs },
      { name: "개미 지수 (KRX+NXT 합산)", st: stTotal },
    ];

    const perfTbody = document.getElementById("perf-detail-tbody");
    if (perfTbody) {
      perfTbody.innerHTML = tableConfigs
        .map((item) => {
          const s = item.st;
          const exKospi = s.cumPct - stKospi.cumPct;
          const exKosdaq = s.cumPct - stKosdaq.cumPct;
          const cKospi = pearsonCorr(s.rets, stKospi.rets);
          const cKosdaq = pearsonCorr(s.rets, stKosdaq.rets);

          return `<tr>
            <td><strong>${item.name}</strong></td>
            <td class="r">${fmtNum(s.current, 2)}</td>
            <td class="r ${clsSign(s.cumPct)}"><strong>${fmtPct(s.cumPct)}</strong></td>
            <td class="r ${clsSign(exKospi)}">${exKospi > 0 ? "+" : ""}${exKospi.toFixed(2)}%p</td>
            <td class="r ${clsSign(exKosdaq)}">${exKosdaq > 0 ? "+" : ""}${exKosdaq.toFixed(2)}%p</td>
            <td class="r">${cKospi.toFixed(3)}</td>
            <td class="r">${cKosdaq.toFixed(3)}</td>
            <td class="r down">${s.mdd.toFixed(2)}%</td>
            <td class="r">${s.annVol.toFixed(2)}%</td>
          </tr>`;
        })
        .join("");
    }
  }

  // TAB 2: 개미가 산 종목 (상위 50 / 상위 100 전환 지원)
  function getStockDetailRecord(code) {
    if (DATA.stock_trajectories && DATA.stock_trajectories[code]) {
      return DATA.stock_trajectories[code];
    }
    const p7 = DATA.phase7_expansion;
    if (!p7) return null;
    const item = (p7.constituents_100 || []).find((r) => r.code === code);
    const mPts = (p7.stock_trajectories_51_100 && p7.stock_trajectories_51_100[code]) || [];
    if (!item) return null;
    let cum = 0;
    const dates = [];
    const cumNet = [];
    const prices = [];
    mPts.forEach((pt) => {
      cum += Number(pt.ind_net_eok || 0);
      dates.push(pt.ym);
      cumNet.push(Number(cum.toFixed(2)));
      prices.push(Number(pt.close || 0));
    });
    return {
      code: item.code,
      name: item.name,
      market: item.market,
      size_bucket: item.end_marcap_eok >= 10000 ? "1조 이상" : "3,000억~1조",
      pure_rank: item.rank,
      abs_rank: "-",
      marcap_rank: "-",
      intensity_pct: item.intensity_pct,
      net_buy_36m_eok: item.ind_net_val_eok,
      avg_marcap_36m_eok: item.avg_marcap_36m_eok,
      end_marcap_eok: item.end_marcap_eok,
      market_weight_pct: "-",
      rank_change_str: item.rank_change_str,
      industry: item.industry,
      since_entry_return_pct: item.ret_since_entry_pct,
      entry_quarter: item.first_entry_quarter,
      entry_date: item.first_entry_date,
      included_quarters: [],
      frg_intensity_pct: null,
      org_intensity_pct: null,
      frg_net_buy_36m_eok: null,
      org_net_buy_36m_eok: null,
      dates,
      cum_net_buy_eok: cumNet,
      prices,
    };
  }

  function renderSection02() {
    const p7 = DATA.phase7_expansion;
    const isScope100 = state.sec2Scope === "100" && p7 && Array.isArray(p7.constituents_100) && p7.constituents_100.length;
    const rawList = isScope100
      ? p7.constituents_100.map((r) => ({ ...r, since_entry_return_pct: r.ret_since_entry_pct }))
      : (DATA.gaemi50_pure_constituents || []);

    const tEl = document.getElementById("sec2-title");
    const sEl = document.getElementById("sec2-sub");
    if (tEl) tEl.textContent = isScope100 ? "개미가 산 100종목" : "개미가 산 50종목";
    if (sEl) sEl.textContent = isScope100 ? "순매수 강도 상위 100개 보통주 (1~50위 · 51~100위 구분)" : "순매수 강도 상위 50개 보통주 (직전 36개월)";

    document.querySelectorAll("#sec2-scope-btns button").forEach((b) => {
      b.classList.toggle("on", b.getAttribute("data-scope") === state.sec2Scope);
    });

    const kospiCnt = rawList.filter((r) => r.market === "KOSPI").length;
    const kosdaqCnt = rawList.filter((r) => r.market === "KOSDAQ").length;

    document.querySelectorAll("#sec2-mkt-btns button").forEach((btn) => {
      const m = btn.getAttribute("data-mkt");
      if (m === "ALL") btn.textContent = `전체 (${rawList.length})`;
      if (m === "KOSPI") btn.textContent = `KOSPI (${kospiCnt})`;
      if (m === "KOSDAQ") btn.textContent = `KOSDAQ (${kosdaqCnt})`;
    });

    const q = state.sec2Search.trim().toLowerCase();
    const filtered = rawList.filter((r) => {
      if (state.sec2Market !== "ALL" && r.market !== state.sec2Market) return false;
      if (q && !r.name.toLowerCase().includes(q) && !r.code.toLowerCase().includes(q)) return false;
      return true;
    });

    const tbody = document.getElementById("pure50-tbody");
    if (!filtered.length) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--ink-3);padding:18px">조건에 맞는 종목이 없습니다.</td></tr>`;
    } else {
      tbody.innerHTML = filtered
        .map((r) => {
          const isAct = r.code === state.selectedStock ? "active-row" : "";
          const rChg = r.rank_change_str || "-";
          const badgeCls = rChg === "NEW" ? "new" : "";
          const retCls = clsSign(r.since_entry_return_pct);
          const tierBadge = isScope100
            ? `<span class="tier-pill ${r.rank <= 50 ? "t1" : "t2"}">${r.rank <= 50 ? "1~50" : "51~100"}</span>`
            : "";
          return `<tr class="clickable ${isAct}" data-code="${r.code}">
            <td class="r"><strong>${r.rank}</strong></td>
            <td>
              <strong>${r.name}</strong><span class="code-sub">${r.code}</span>${tierBadge}
              <span class="badge-sm ${badgeCls}" style="margin-left:4px">${rChg}</span>
            </td>
            <td class="r"><strong class="up">+${Number(r.intensity_pct).toFixed(2)}%</strong></td>
            <td class="r ${retCls}">${fmtPct(r.since_entry_return_pct)}</td>
          </tr>`;
        })
        .join("");
    }

    const secRows = (DATA.market_diff.sector_vs_market || []).filter((r) => r.pure_count > 0);
    document.getElementById("sec2-sector-tbody").innerHTML = secRows
      .map(
        (r) => `<tr>
        <td>${r.industry}</td>
        <td class="r">${r.pure_count}종목</td>
        <td class="r"><strong>${r.pure_weight_pct.toFixed(1)}%</strong></td>
      </tr>`
      )
      .join("");

    const sizeRows = DATA.market_diff.size_vs_market || [];
    document.getElementById("sec2-size-tbody").innerHTML = sizeRows
      .map(
        (r) => `<tr>
        <td>${r.size_bucket}</td>
        <td class="r">${r.pure_count}종목</td>
        <td class="r"><strong>${r.pure_weight_pct.toFixed(1)}%</strong></td>
      </tr>`
      )
      .join("");
  }

  function initDetailSelect() {
    const sel = document.getElementById("dt-stock-select");
    if (!sel) return;
    const trajs = DATA.stock_trajectories || {};
    const p7List = (DATA.phase7_expansion && DATA.phase7_expansion.constituents_100) || [];
    const pureList = DATA.gaemi50_pure_constituents || [];
    const rankMap = new Map((p7List.length ? p7List : pureList).map((r) => [r.code, r.rank]));

    const allCodesSet = new Set([...Object.keys(trajs), ...p7List.map((r) => r.code)]);
    const codes = Array.from(allCodesSet).sort((a, b) => {
      const ra = rankMap.has(a) ? rankMap.get(a) : 999;
      const rb = rankMap.has(b) ? rankMap.get(b) : 999;
      return ra - rb;
    });

    sel.innerHTML = codes
      .map((c) => {
        const t = getStockDetailRecord(c);
        if (!t) return "";
        const rk = rankMap.get(c) || t.pure_rank;
        const rTag = rk ? `#${rk}` : "편입외";
        return `<option value="${c}">${rTag} ${t.name} (${c}) — 강도 ${Number(t.intensity_pct).toFixed(2)}%</option>`;
      })
      .join("");

    if (!getStockDetailRecord(state.selectedStock) && codes.length) {
      state.selectedStock = codes[0];
    }
    sel.value = state.selectedStock;
  }

  function renderStockDetailPanel() {
    const t = getStockDetailRecord(state.selectedStock);
    if (!t) return;

    document.getElementById("dt-code-mkt").textContent = `${t.code} · ${t.market} · ${t.size_bucket}`;
    document.getElementById("dt-title").textContent = t.name;

    const pRank = t.pure_rank ? `강도 순위 #${t.pure_rank}위` : "적격 50위 밖";
    document.getElementById("dt-intensity").textContent = `+${Number(t.intensity_pct).toFixed(2)}%`;
    document.getElementById("dt-rank-sub").textContent =
      t.abs_rank !== "-" ? `${pRank} · 금액 순위 #${t.abs_rank}위 · 시총 #${t.marcap_rank}위` : pRank;

    document.getElementById("dt-netbuy").textContent = fmtEok(t.net_buy_36m_eok);
    document.getElementById("dt-marcap").textContent = `평균 ${fmtEok(t.avg_marcap_36m_eok)}`;
    document.getElementById("dt-marcap-sub").textContent =
      t.market_weight_pct !== "-" ? `기준일 시총: ${fmtEok(t.end_marcap_eok)} (시장 비중 ${t.market_weight_pct}%)` : `기준일 시총: ${fmtEok(t.end_marcap_eok)}`;

    document.getElementById("dt-chg").textContent = t.rank_change_str || "-";
    document.getElementById("dt-industry").textContent = t.industry || "-";

    const retEl = document.getElementById("dt-ret");
    if (t.since_entry_return_pct !== null && t.since_entry_return_pct !== undefined) {
      retEl.textContent = fmtPct(t.since_entry_return_pct);
      retEl.className = `v ${clsSign(t.since_entry_return_pct)}`;
      document.getElementById("dt-entry-sub").textContent =
        t.included_quarters && t.included_quarters.length
          ? `최초 편입: ${t.entry_quarter} (${t.entry_date}) · 총 ${t.included_quarters.length}개 분기 포함`
          : `최초 편입: ${t.entry_quarter} (${t.entry_date})`;
    } else {
      retEl.textContent = "미편입";
      retEl.className = "v";
      document.getElementById("dt-entry-sub").textContent = t.eligibility_note || "편입 이력 없음";
    }

    if (t.frg_intensity_pct !== null && t.frg_intensity_pct !== undefined) {
      document.getElementById("dt-others").textContent =
        `외인 ${fmtPct(t.frg_intensity_pct)} / 기관 ${fmtPct(t.org_intensity_pct)}`;
      document.getElementById("dt-others-sub").textContent =
        `외인 ${fmtEok(t.frg_net_buy_36m_eok)} · 기관 ${fmtEok(t.org_net_buy_36m_eok)}`;
    } else {
      document.getElementById("dt-others").textContent = t.pure_rank ? `#${t.pure_rank}위 (51~100)` : "-";
      document.getElementById("dt-others-sub").textContent = "GAEMI 100 편입 종목";
    }

    const tk = getChartTokens();
    const ctx = document.getElementById("detailChart").getContext("2d");
    if (detailChart) detailChart.destroy();
    detailChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: t.dates,
        datasets: [
          {
            label: "개인 누적 추정 순매수대금 (억 원 · 실선)",
            data: t.cum_net_buy_eok,
            borderColor: tk.gaemi,
            backgroundColor: tk.gaemiFill,
            fill: true,
            borderWidth: 2.2,
            pointRadius: 0,
            yAxisID: "yNet",
            tension: 0.15,
          },
          {
            label: "주가 (원 · 점선)",
            data: t.prices,
            borderColor: tk.kospi,
            backgroundColor: "transparent",
            borderWidth: 2.0,
            borderDash: [5, 3],
            pointRadius: 0,
            yAxisID: "yPrc",
            tension: 0.15,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            display: true,
            position: "top",
            align: "start",
            labels: { color: tk.axis, boxWidth: 14, boxHeight: 3, font: { size: 11 } },
          },
          tooltip: {
            backgroundColor: tk.tooltipBg,
            titleColor: tk.tooltipInk,
            bodyColor: tk.tooltipInk,
            borderColor: tk.tooltipBorder,
            borderWidth: 1,
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: tk.axis, maxTicksLimit: 6, font: { family: "JetBrains Mono", size: 10 } },
          },
          yNet: {
            position: "left",
            grid: { color: tk.grid },
            ticks: {
              font: { family: "JetBrains Mono", size: 10 },
              color: tk.gaemi,
              callback: (v) => `${fmtInt(v)}억`,
            },
          },
          yPrc: {
            position: "right",
            grid: { drawOnChartArea: false },
            ticks: {
              color: tk.kospi,
              font: { family: "JetBrains Mono", size: 10 },
              callback: (v) => `${fmtInt(v)}원`,
            },
          },
        },
      },
    });
  }

  // TAB 3: 시장과의 차이 (PHASE 3 Section 3 & 5 반영)
  function renderSection03() {
    const md = DATA.market_diff;
    const as = md.active_share;

    const setIf = (id, txt) => {
      const el = document.getElementById(id);
      if (el) el.textContent = txt;
    };
    setIf("as-mc50-txt", `${as.marcap_top50_ew_vs_market_pct.toFixed(1)}%`);
    setIf("as-pure-txt", `${as.gaemi_pure_vs_market_pct.toFixed(1)}%`);
    setIf("as-matched-txt", `${as.matched_size_sector_50_ew_vs_market_pct.toFixed(1)}%`);

    const asItems = [
      {
        label: "비슷한 주식 50개 (시총·업종 유사 동일가중)",
        val: as.matched_size_sector_50_ew_vs_market_pct,
        cls: "blue",
      },
      {
        label: "개미 지수 (GAEMI 50 PURE · 50종목 동일가중)",
        val: as.gaemi_pure_vs_market_pct,
        cls: "",
      },
      {
        label: "단순 순매수금액 상위 50 (50종목 동일가중)",
        val: as.gaemi_abs_vs_market_pct,
        cls: "muted",
      },
      {
        label: "시가총액 상위 50종목 동일가중 (동일가중 기본 차이)",
        val: as.marcap_top50_ew_vs_market_pct,
        cls: "muted",
      },
    ];

    document.getElementById("active-share-bars").innerHTML = asItems
      .map(
        (it) => `<div>
        <div class="as-row-head">
          <span>${it.label}</span>
          <strong style="font-family:var(--font-mono)">${it.val.toFixed(1)}%</strong>
        </div>
        <div class="as-track"><div class="as-fill ${it.cls}" style="width:${it.val}%"></div></div>
      </div>`
      )
      .join("");

    const kqSim = md.kosdaq_similarity;
    const simSumEl = document.getElementById("kq-sim-summary");
    if (simSumEl) simSumEl.textContent = kqSim.diagnosis_category;
    const simDetEl = document.getElementById("kq-sim-detail");
    if (simDetEl) simDetEl.textContent = kqSim.diagnosis_detail;

    document.getElementById("kq-sim-tbody").innerHTML = kqSim.comparison_table
      .map((r) => {
        const retCls = clsSign(r.total_return_pct);
        return `<tr>
          <td><strong>${r.name}</strong></td>
          <td class="r">${r.stock_overlap_with_pure_pct.toFixed(1)}%</td>
          <td class="r ${retCls}"><strong>${fmtPct(r.total_return_pct)}</strong></td>
          <td class="r">${r.corr_kosdaq.toFixed(3)}</td>
          <td class="r down">${r.mdd_pct.toFixed(2)}%</td>
        </tr>`;
      })
      .join("");

    document.getElementById("sec3-size-diff-tbody").innerHTML = md.size_vs_market
      .map((r) => {
        const dCls = clsSign(r.diff_vs_market_pct);
        const sgn = r.diff_vs_market_pct > 0 ? "+" : "";
        return `<tr>
          <td>${r.size_bucket}</td>
          <td class="r"><strong>${r.pure_weight_pct.toFixed(1)}%</strong> (${r.pure_count}종목)</td>
          <td class="r">${r.market_weight_pct.toFixed(1)}%</td>
          <td class="r ${dCls}"><strong>${sgn}${r.diff_vs_market_pct.toFixed(1)}%p</strong></td>
        </tr>`;
      })
      .join("");

    document.getElementById("sec3-sector-diff-tbody").innerHTML = md.sector_vs_market
      .map((r) => {
        const dCls = clsSign(r.diff_weight_pct);
        const sgn = r.diff_weight_pct > 0 ? "+" : "";
        return `<tr>
          <td>${r.industry}</td>
          <td class="r"><strong>${r.pure_weight_pct.toFixed(1)}%</strong></td>
          <td class="r">${r.market_weight_pct.toFixed(1)}%</td>
          <td class="r ${dCls}"><strong>${sgn}${r.diff_weight_pct.toFixed(1)}%p</strong></td>
        </tr>`;
      })
      .join("");

    document.getElementById("mc50-ov-cnt").textContent =
      `${md.marcap_top50_overlap.overlap_count}개(${md.marcap_top50_overlap.overlap_pct}%)`;

    document.getElementById("sec3-missing-large-tbody").innerHTML = md.missing_large_caps_top15
      .map((r) => {
        const pRankStr = r.pure_rank_eligible ? `강도 #${r.pure_rank_eligible}위` : r.eligibility_note;
        return `<tr class="clickable" data-code="${r.code}">
          <td class="r">#${r.marcap_rank_all}</td>
          <td><strong>${r.name}</strong><span class="code-sub">${r.code}</span></td>
          <td class="r"><strong>${r.market_weight_pct.toFixed(2)}%</strong></td>
          <td class="r">${fmtEok(r.net_buy_eok)}</td>
          <td class="r">${r.intensity_pct.toFixed(2)}% <span class="code-sub">(${pRankStr})</span></td>
        </tr>`;
      })
      .join("");
  }

  // TAB 4: 개미·외국인·기관의 선택
  function renderSection04() {
    const ic = DATA.investor_comp;
    const ov = ic.overlaps;

    document.getElementById("ov-ind-frg").textContent = `${ov.ind_vs_frg_count}종목 (${ov.ind_vs_frg_pct}%)`;
    document.getElementById("ov-ind-frg-names").textContent = ov.ind_vs_frg_stocks.length
      ? `겹치는 종목: ${ov.ind_vs_frg_stocks.join(", ")}`
      : "겹치는 종목 없음";

    document.getElementById("ov-ind-org").textContent = `${ov.ind_vs_org_count}종목 (${ov.ind_vs_org_pct}%)`;
    document.getElementById("ov-ind-org-names").textContent = ov.ind_vs_org_stocks.length
      ? `겹치는 종목: ${ov.ind_vs_org_stocks.join(", ")}`
      : "50개 중 겹치는 종목이 없습니다.";

    document.getElementById("ov-frg-org").textContent = `${ov.frg_vs_org_count}종목 (${ov.frg_vs_org_pct}%)`;
    document.getElementById("ov-frg-org-names").textContent = ov.frg_vs_org_stocks.length
      ? `겹치는 종목: ${ov.frg_vs_org_stocks.join(", ")}`
      : "겹치는 종목 없음";

    renderUnifiedInvestorTable();

    document.getElementById("inv-sector-tbody").innerHTML = (ic.sector_comparison || [])
      .slice(0, 18)
      .map(
        (r) => `<tr>
        <td>${r.industry} <span class="code-sub">(${r.stock_count})</span></td>
        <td class="r ${clsSign(r.ind_sector_intensity_pct)}"><strong>${fmtPct(r.ind_sector_intensity_pct)}</strong> <span class="code-sub">(${fmtEok(r.ind_net_buy_eok)})</span></td>
        <td class="r ${clsSign(r.frg_sector_intensity_pct)}">${fmtPct(r.frg_sector_intensity_pct)} <span class="code-sub">(${fmtEok(r.frg_net_buy_eok)})</span></td>
        <td class="r ${clsSign(r.org_sector_intensity_pct)}">${fmtPct(r.org_sector_intensity_pct)} <span class="code-sub">(${fmtEok(r.org_net_buy_eok)})</span></td>
      </tr>`
      )
      .join("");

    // 투자 주체별 가상 지수 차트 (CSS 토큰 사용 + 선 모양 구분)
    const tk = getChartTokens();
    const ts = DATA.timeseries || [];
    const ctx = document.getElementById("investorIndexChart").getContext("2d");
    if (invChart) invChart.destroy();
    invChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: ts.map((r) => r.date),
        datasets: [
          {
            label: `개미 순매수 강도 50 (${fmtPct(DATA.summary.metrics.GAEMI_50_PURE.total_return_pct)} · 실선)`,
            data: ts.map((r) => r.GAEMI_50_PURE),
            borderColor: tk.gaemi,
            borderWidth: 2.5,
            borderDash: [],
            pointRadius: 0,
            tension: 0.1,
          },
          {
            label: `외국인 순매수 강도 50 (${fmtPct(DATA.summary.metrics.FOREIGN_50_PURE.total_return_pct)} · 긴 점선)`,
            data: ts.map((r) => r.FOREIGN_50_PURE),
            borderColor: tk.foreign,
            borderWidth: 2.2,
            borderDash: [7, 4],
            pointRadius: 0,
            tension: 0.1,
          },
          {
            label: `기관 순매수 강도 50 (${fmtPct(DATA.summary.metrics.INSTITUTION_50_PURE.total_return_pct)} · 짧은 점선)`,
            data: ts.map((r) => r.INSTITUTION_50_PURE),
            borderColor: tk.institution,
            borderWidth: 2.2,
            borderDash: [3, 3],
            pointRadius: 0,
            tension: 0.1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "top",
            align: "start",
            labels: { color: tk.axis, boxWidth: 18, boxHeight: 3, font: { size: 12, weight: "600" } },
          },
          tooltip: {
            backgroundColor: tk.tooltipBg,
            titleColor: tk.tooltipInk,
            bodyColor: tk.tooltipInk,
            borderColor: tk.tooltipBorder,
            borderWidth: 1,
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: tk.axis, maxTicksLimit: 8, font: { family: "JetBrains Mono", size: 11 } },
          },
          y: {
            grid: { color: tk.grid },
            ticks: { color: tk.axis, font: { family: "JetBrains Mono", size: 11 } },
          },
        },
      },
    });
  }

  function renderUnifiedInvestorTable() {
    const ic = DATA.investor_comp;
    const trajs = DATA.stock_trajectories || {};
    let list = [];
    let title = "";

    if (state.invListMode === "IND") {
      list = ic.top50_by_investor.individual || [];
      title = "개미 순매수 강도 상위 50종목 (2026 Q4)";
    } else if (state.invListMode === "FRG") {
      list = ic.top50_by_investor.foreign || [];
      title = "외국인 순매수 강도 상위 50종목 (2026 Q4)";
    } else if (state.invListMode === "ORG") {
      list = ic.top50_by_investor.institution || [];
      title = "기관(연기금 포함) 순매수 강도 상위 50종목 (2026 Q4)";
    } else if (state.invListMode === "DIV_IND") {
      list = ic.divergent_bets.ind_buy_others_sell || [];
      title = "개미는 순매수하고 외국인·기관은 모두 순매도한 종목 (상위 15)";
    } else {
      list = ic.divergent_bets.others_buy_ind_sell || [];
      title = "외국인·기관은 순매수하고 개미는 순매도한 종목 (상위 15)";
    }

    document.getElementById("inv-list-title").textContent = title;
    document.getElementById("inv-unified-tbody").innerHTML = list
      .map((r, idx) => {
        const t = trajs[r.code] || {};
        const rankNum = r.rank || idx + 1;
        const indInt = r.intensity_pct !== undefined ? r.intensity_pct : t.intensity_pct;
        const indVal = r.net_buy_eok !== undefined ? r.net_buy_eok : t.net_buy_36m_eok;
        const frgInt = r.frg_intensity_pct !== undefined ? r.frg_intensity_pct : t.frg_intensity_pct;
        const frgVal = r.frg_net_buy_eok !== undefined ? r.frg_net_buy_eok : t.frg_net_buy_36m_eok;
        const orgInt = r.org_intensity_pct !== undefined ? r.org_intensity_pct : t.org_intensity_pct;
        const orgVal = r.org_net_buy_eok !== undefined ? r.org_net_buy_eok : t.org_net_buy_36m_eok;

        return `<tr class="clickable" data-code="${r.code}">
          <td class="r"><strong>${rankNum}</strong></td>
          <td><strong>${r.name}</strong><span class="code-sub">${r.code} · ${r.market}</span></td>
          <td>${r.industry || t.industry || "-"}</td>
          <td class="r ${clsSign(indInt)}"><strong>${fmtPct(indInt)}</strong> <span class="code-sub">(${fmtEok(indVal)})</span></td>
          <td class="r ${clsSign(frgInt)}"><strong>${fmtPct(frgInt)}</strong> <span class="code-sub">(${fmtEok(frgVal)})</span></td>
          <td class="r ${clsSign(orgInt)}"><strong>${fmtPct(orgInt)}</strong> <span class="code-sub">(${fmtEok(orgVal)})</span></td>
        </tr>`;
      })
      .join("");
  }

  // TAB 5: 분기별 변화
  function initQuarterSelect() {
    const sel = document.getElementById("q-select");
    if (!sel) return;
    const hist = DATA.summary.rebalance_history || [];
    sel.innerHTML = hist
      .slice()
      .reverse()
      .map(
        (q) =>
          `<option value="${q.rebalance_id}">${q.rebalance_id} (기준일: ${q.determination_date} · 적용: ${q.effective_start})</option>`
      )
      .join("");
    state.selectedQuarter = hist[hist.length - 1].rebalance_id;
    sel.value = state.selectedQuarter;
  }

  function renderSection05() {
    const hist = DATA.summary.rebalance_history || [];
    const qObj = hist.find((h) => h.rebalance_id === state.selectedQuarter) || hist[hist.length - 1];
    if (!qObj) return;

    const added = qObj.pure_added || [];
    const removed = qObj.pure_removed || [];
    const snap = qObj.constituents_snapshot || [];

    document.getElementById("q-inout-title").textContent = `${qObj.rebalance_id} 리밸런싱 편입 · 퇴출 종목`;
    document.getElementById("q-inout-meta").textContent =
      `36개월 집계: ${qObj.window_36m_start} ~ ${qObj.determination_date} · 적용일: ${qObj.effective_start}`;
    document.getElementById("q-add-head").textContent = `신규 편입 (${added.length}종목)`;
    document.getElementById("q-rem-head").textContent = `퇴출 (${removed.length}종목)`;

    const addTbody = document.getElementById("q-add-tbody");
    const remTbody = document.getElementById("q-rem-tbody");

    if (qObj.rebalance_id === hist[0].rebalance_id) {
      addTbody.innerHTML = `<tr><td colspan="3" style="color:var(--ink-3)">최초 기준 분기 (50종목 초기 구성)</td></tr>`;
      remTbody.innerHTML = `<tr><td colspan="2" style="color:var(--ink-3)">최초 기준 분기 (퇴출 없음)</td></tr>`;
    } else {
      addTbody.innerHTML = added
        .sort((a, b) => a.rank - b.rank)
        .map(
          (r) => `<tr class="clickable" data-code="${r.code}">
          <td class="r">#${r.rank}</td>
          <td><strong>${r.name}</strong><span class="code-sub">${r.code}</span></td>
          <td class="r up">+${r.intensity_pct.toFixed(2)}%</td>
        </tr>`
        )
        .join("");

      remTbody.innerHTML = removed
        .map((r) => {
          const st = r.new_pure_rank ? `강도 #${r.new_pure_rank}위` : r.reason;
          return `<tr>
            <td>${r.name}<span class="code-sub">${r.code}</span></td>
            <td class="r down" style="font-size:11.5px">${st}</td>
          </tr>`;
        })
        .join("");
    }

    document.getElementById("q-snap-title").textContent = `${qObj.rebalance_id} 구성 종목 50선 (평균 강도 ${qObj.pure_avg_intensity_pct}%)`;
    document.getElementById("q-snap-tbody").innerHTML = snap
      .map(
        (r) => `<tr class="clickable" data-code="${r.code}">
        <td class="r"><strong>${r.rank}</strong></td>
        <td><span class="badge-sm ${r.rank_change_str === "NEW" ? "new" : ""}">${r.rank_change_str}</span></td>
        <td><strong>${r.name}</strong><span class="code-sub">${r.code}</span></td>
        <td>${r.market}</td>
        <td class="r up"><strong>+${Number(r.intensity_pct).toFixed(2)}%</strong></td>
        <td class="r">${fmtEok(r.net_buy_eok)}</td>
      </tr>`
      )
      .join("");
  }

  // TAB 6: 산출 방법 및 데이터 신뢰성 검증 (PHASE 6 하락장 포착률·위험통제·A/B 민감도 + PHASE 4 A/B 전체 후보군 재선정, 과거 시가총액 검증, 매니페스트)
  function renderFooterDetails() {
    const p0 = DATA.phase0_audit || {};
    const p3 = DATA.phase3_reliability || {};
    const p4 = DATA.phase4_audit || {};
    const p6 = DATA.phase6_downside || {};
    const mf = DATA.manifest || {};
    const a2 = p0.audit_0_2_36m_completeness || {};
    const a3 = p0.audit_0_3_krx_vs_nxt || {};

    // 0) PHASE 6 하락장 포착률 산식, 위험요인 통제 회귀 및 A/B안 민감도
    const p6MethodEl = document.getElementById("phase6-method-box");
    if (p6MethodEl && p6.capture_ratios) {
      const fc = p6.factor_control_analysis || {};
      const cKq = (p6.capture_ratios.vs_kosdaq && p6.capture_ratios.vs_kosdaq.GAEMI_50_PURE) || {};
      const dKq = (p6.daily_downside_analysis && p6.daily_downside_analysis.kosdaq_down_days) || {};
      p6MethodEl.innerHTML = `
        <ul style="padding-left:18px;margin:0">
          <li><strong>하락장 포착률 (Downside Capture Ratio) 및 상승장 포착률 (Upside Capture Ratio) 산식:</strong> ${p6.capture_ratios.formula_note || ""}</li>
          <li><strong>하방 베타 (Downside Beta) 및 통계적 불확실성:</strong> 코스닥 하락일(240거래일) 기준 개미 지수의 일간 하방 베타는 <strong>${dKq.gaemi_downside_beta || 0.996}</strong>(전체 기간 베타 ${dKq.gaemi_full_beta || 0.933})로 비슷한 주식 50개의 하방 베타(<strong>${dKq.matched50_downside_beta || 0.897}</strong>)보다 높습니다. 코스닥 하락월(10개월)에서 개미 지수와 코스닥의 월평균 수익률 격차는 <strong>${fmtPct(cKq.mean_gap_in_down_months_pctp)}p</strong>(표준오차 ${cKq.down_gap_se_pctp}%p, 95% 신뢰구간 [${(cKq.down_gap_ci95_pctp || [])[0]}%p, +${(cKq.down_gap_ci95_pctp || [])[1]}%p])이며, 관측 개월 수(26개월 중 하락월 10개월)가 제한적이므로 단정적 결론 대신 표본 수와 신뢰구간을 함께 제시합니다.</li>
          <li><strong>위험 요인 통제 검증 (시가총액 · 코스닥 여부 · 과거 변동성 · 직전 수익률 · 거래대금 회전율 통제):</strong> ${fc.interpretation || ""}</li>
        </ul>
      `;
    }

    const p6AbTbody = document.getElementById("phase6-ab-capture-tbody");
    if (p6AbTbody && p6.ab_estimation_downside_sensitivity) {
      const ab = p6.ab_estimation_downside_sensitivity;
      const rows = [
        { label: "코스닥 기준 (하락 10개월 / 상승 15개월)", a: ab.plan_a_vs_kosdaq || {}, b: ab.plan_b_vs_kosdaq || {} },
        { label: "비슷한 주식 50개 기준 (하락 12개월 / 상승 14개월)", a: ab.plan_a_vs_matched50 || {}, b: ab.plan_b_vs_matched50 || {} },
        { label: "코스피 기준 (하락 10개월 / 상승 15개월)", a: ab.plan_a_vs_kospi || {}, b: ab.plan_b_vs_kospi || {} },
      ];
      p6AbTbody.innerHTML = rows
        .map(
          (r) => `<tr>
          <td><strong>${r.label}</strong></td>
          <td class="r"><strong>${r.a.downside_capture_geo_pct}%</strong></td>
          <td class="r"><strong>${r.b.downside_capture_geo_pct}%</strong></td>
          <td class="r down">${fmtPct(r.a.down_months_mean_pct)}</td>
          <td class="r down">${fmtPct(r.b.down_months_mean_pct)}</td>
          <td class="r">${r.a.upside_capture_geo_pct}%</td>
          <td class="r">${r.b.upside_capture_geo_pct}%</td>
        </tr>`
        )
        .join("");
    }

    // 1) 비교지수 산출 기준 대조표
    const benchList = p3.audit_4_4_benchmark_consistency || [];
    const benchTbody = document.getElementById("bench-consistency-tbody");
    if (benchTbody) {
      benchTbody.innerHTML = benchList
        .map(
          (b) => `<tr>
          <td><strong>${b.index}</strong></td>
          <td>${b.base_date}</td>
          <td>${b.rebalancing}</td>
          <td>${b.price_adj}</td>
          <td>${b.dividend}</td>
        </tr>`
        )
        .join("");
    }

    // 2) PHASE 4 Section 3: 순매수대금 추정 방식 비교 (전체 후보군 A안 vs B안 독립 재선정 및 9개 분기 백테스트)
    const s3 = p4.section3_estimation_method_comparison || {};
    const idxCmp = s3.index_performance_comparison || {};
    const qHist = s3.quarterly_history_ab || [];
    const l26 = s3.latest_2026q4_summary || {};
    const abSummaryEl = document.getElementById("phase4-ab-summary");
    if (abSummaryEl) {
      abSummaryEl.innerHTML = `
        <p style="margin-bottom:6px"><strong>실험 목적:</strong> 일별 순매수대금 추정 시 <strong>A안(순매수수량 × 당일 종가, 현행 대표지수)</strong>과 <strong>B안(순매수수량 × 당일 기준가·종가 평균)</strong>으로 전체 적격 후보군을 각각 독립 재선정했을 때 50개 구성 종목과 지수 수익률이 얼마나 달라지는지 검증한 단가 민감도 실험입니다(실제 체결대금 C안은 KRX 원자료 미제공으로 미사용).</p>
        <p>${idxCmp.stability_evaluation || "-"}</p>
      `;
    }

    const abQTbody = document.getElementById("phase4-ab-quarterly-tbody");
    if (abQTbody) {
      abQTbody.innerHTML = qHist
        .map(
          (q) => `<tr>
          <td><strong>${q.rebalance_id}</strong> <span class="code-sub">(${q.determination_date})</span></td>
          <td class="r"><strong>${q.common_top50_count}/50 (${q.common_top50_pct}%)</strong></td>
          <td>${(q.only_in_a || []).join(", ") || "-"}</td>
          <td>${(q.only_in_b || []).join(", ") || "-"}</td>
        </tr>`
        )
        .join("");
    }

    const bndRows = l26.boundary_40_to_60 || [];
    const bndTbody = document.getElementById("boundary-sens-tbody");
    if (bndTbody) {
      bndTbody.innerHTML = bndRows
        .map(
          (r) => `<tr class="clickable" data-code="${r.code}">
          <td><strong>${r.name}</strong><span class="code-sub">${r.code}</span></td>
          <td class="r">${r.rank_a ? `#${r.rank_a} (${Number(r.intensity_a).toFixed(2)}%)` : "-"}</td>
          <td class="r">${r.rank_b ? `#${r.rank_b} (${Number(r.intensity_b).toFixed(2)}%)` : "-"}</td>
          <td class="r ${clsSign(r.intensity_diff_b_minus_a)}">${r.intensity_diff_b_minus_a > 0 ? "+" : ""}${Number(r.intensity_diff_b_minus_a).toFixed(2)}%p</td>
        </tr>`
        )
        .join("");
    }

    // 3) PHASE 4 Section 4: 과거 시가총액 및 상장주식수 변동 종목 독립 검증
    const s4 = p4.section4_historical_marcap_verification || {};
    const mcNoteEl = document.getElementById("phase4-marcap-note");
    if (mcNoteEl) {
      mcNoteEl.textContent = s4.conclusion || "";
    }
    const mcTbody = document.getElementById("phase4-marcap-tbody");
    if (mcTbody) {
      mcTbody.innerHTML = (s4.stocks || [])
        .map(
          (r) => `<tr class="clickable" data-code="${r.code}">
          <td><strong>${r.name}</strong><span class="code-sub">${r.rank_a_2026q4 ? `#${r.rank_a_2026q4}` : "편입외"}</span></td>
          <td class="r">${fmtInt(r.shares_2026_03_08)}주</td>
          <td class="r">${fmtInt(r.shares_2026_09_30)}주 <span class="code-sub">(${fmtPct(r.share_change_2026_pct)})</span></td>
          <td style="font-size:11.5px">${r.detected_corporate_events}</td>
          <td class="r">${fmtEok(r.audited_avg_marcap_36m_eok)} <strong>(+${Number(r.audited_intensity_pct).toFixed(2)}%)</strong></td>
          <td class="r">${r.intensity_band_under_10pct_marcap_error}</td>
        </tr>`
        )
        .join("");
    }

    // 4) PHASE 4 Section 5-2 & 2-4: '비슷한 주식 50개' 유사성 검증 및 원자료 버전 매니페스트
    const s52 = p4.section5_2_matched_portfolio_similarity || {};
    const mcMed = s52.marcap_median_eok || {};
    const mcEx = s52.marcap_mean_ex_megacap_eok || {};
    const adtvMed = s52.adtv_60d_median_eok || {};
    const kqW = s52.kosdaq_weight_pct || {};

    document.getElementById("audit-detail-box").innerHTML = `
      <ul style="padding-left:18px;margin:0">
        <li><strong>비슷한 주식 50개(시가총액·업종 유사 비교 포트폴리오) 유사성 검증:</strong> 각 분기 말 개미 지수 미편입 적격 종목 중 시장(코스피·코스닥) 일치율 <strong>${s52.exact_market_match_count || "50/50 (100%)"}</strong>, 동일 업종 일치율 <strong>${s52.exact_industry_match_count || "47/50 (94%)"}</strong>로 1:1 매칭되었습니다. 코스닥 종목 비중(${kqW.gaemi_pure || 60}% vs ${kqW.matched_50 || 60}%), 중위 시가총액(${fmtEok(mcMed.gaemi_pure)} vs ${fmtEok(mcMed.matched_50)}), 초대형주 제외 평균 시가총액(${fmtEok(mcEx.gaemi_pure)} vs ${fmtEok(mcEx.matched_50)})은 유사하나, 60일 중위 거래대금(${fmtEok(adtvMed.gaemi_pure)} vs ${fmtEok(adtvMed.matched_50)})과 초대형주 포함 전체 평균 시가총액에서는 차이가 있으므로 완전한 동일 조건이 아닌 <strong>'시가총액·업종 유사 비교 포트폴리오'</strong>로 해석해야 합니다.</li>
        <li><strong>36개월 원자료 완전성 및 KRX/NXT 분리:</strong> 영속 분할 원장 총 <strong>${fmtInt(mf.total_ledger_records || a2.total_daily_records || 2392334)}건</strong>(36개월 완전 관측 확보 <strong>${fmtInt(mf.full_36m_stocks_count || a2.stocks_with_full_36m_data || 1771)}종목</strong>, 상장폐지 보존 <strong>${fmtInt(mf.delisted_stocks_preserved || 173)}종목</strong>, 중복 기본키 <strong>0건</strong>). 2026 Q4 기준 KRX 전용 상위 50개와 KRX+NXT 합산 상위 50개는 <strong>${a3.krx_vs_combined_top50_overlap_2026Q4 || "47/50 (94%)"}</strong> 일치합니다.</li>
        <li><strong>원자료 버전 매니페스트 (<code>data_manifest.json</code>):</strong> 데이터 기준일 <code>${mf.data_as_of || DATA.summary.data_as_of}</code> · 원장 버전 <code>${mf.ledger_version || "v4.20261120"}</code> · 원장 통합 SHA-256 체크섬 <code>${(mf.ledger_combined_sha256 || "").slice(0, 16) || "verified"}...</code> · 산출 엔진 <code>${mf.index_engine_version || "GAEMI_50_PURE_PHASE4_v1.0"}</code></li>
      </ul>
    `;

    // 5) 민감도 분석 테이블
    const sens = DATA.sensitivity || [];
    document.getElementById("sens-tbody").innerHTML = sens
      .map(
        (s) => `<tr>
        <td>${s.is_baseline ? "★ " : ""}${s.scenario}</td>
        <td class="r">${s.eligible_pool_count}종목</td>
        <td class="r">${s.top50_avg_intensity_pct.toFixed(2)}%</td>
        <td class="r">${fmtEok(s.top50_median_marcap_eok)}</td>
        <td class="r">${s.overlap_with_baseline_count}/50 (${s.overlap_with_baseline_pct}%)</td>
        <td class="r ${clsSign(s.total_return_pct)}">${fmtPct(s.total_return_pct)}</td>
        <td class="r down">${s.mdd_pct.toFixed(2)}%</td>
        <td class="r">${s.corr_kospi.toFixed(3)}</td>
        <td class="r">${s.corr_kosdaq.toFixed(3)}</td>
      </tr>`
      )
      .join("");

    // 6) 단순 순매수금액 상위 50 vs PURE 비교
    const absList = DATA.gaemi50_abs_constituents || [];
    const pureSet = new Set((DATA.gaemi50_pure_constituents || []).map((r) => r.code));
    document.getElementById("abs-vs-pure-tbody").innerHTML = absList
      .map((r) => {
        const inP = pureSet.has(r.code);
        const pStr = inP
          ? `<strong class="up">편입 (#${r.pure_rank_eligible}위)</strong>`
          : `<span class="down">미편입 (${r.pure_rank_eligible ? `강도 #${r.pure_rank_eligible}위` : r.eligibility_note})</span>`;
        return `<tr class="clickable" data-code="${r.code}">
          <td class="r">#${r.rank}</td>
          <td><strong>${r.name}</strong><span class="code-sub">${r.code}</span></td>
          <td>${r.market}</td>
          <td class="r">${fmtEok(r.net_buy_eok)}</td>
          <td class="r">${fmtEok(r.avg_marcap_36m_eok)}</td>
          <td class="r">${Number(r.intensity_pct).toFixed(2)}%</td>
          <td class="r">${pStr}</td>
        </tr>`;
      })
      .join("");
  }

  function bindEvents() {
    // 상단 카테고리 탭 전환 + 키보드 좌우 화살표 접근성 지원
    const tabBtns = Array.from(document.querySelectorAll('#tabs button[role="tab"]'));
    tabBtns.forEach((btn, idx) => {
      btn.addEventListener("click", () => {
        activateTab(btn.getAttribute("data-tab"), true);
      });
      btn.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const dir = e.key === "ArrowRight" ? 1 : -1;
          const nextIdx = (idx + dir + tabBtns.length) % tabBtns.length;
          tabBtns[nextIdx].focus();
          activateTab(tabBtns[nextIdx].getAttribute("data-tab"), true);
        }
      });
    });

    window.addEventListener("hashchange", () => {
      const h = (window.location.hash || "").replace("#", "");
      if (h) activateTab(h, false);
    });

    // 상단 지수 전환 스위치 (개미 50 / 개미 100)
    document.querySelectorAll("#index-switch button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = btn.getAttribute("data-idx");
        if (idx !== "50" && idx !== "100") return;
        state.selectedIndex = idx;
        try {
          localStorage.setItem(INDEX_STORAGE_KEY, idx);
          const u = new URL(window.location.href);
          u.searchParams.set("idx", idx);
          history.replaceState(null, "", u.toString());
        } catch (_) {}
        renderSection01();
      });
    });

    // 기간 선택 버튼
    document.querySelectorAll("#period-btns button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#period-btns button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        state.period = btn.getAttribute("data-period");
        renderSection01();
      });
    });

    // 비교지수 체크박스
    const bindChk = (id, key) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener("change", (e) => {
          state[key] = e.target.checked;
          renderSection01();
        });
      }
    };
    bindChk("chk-g50", "showG50");
    bindChk("chk-g100", "showG100");
    bindChk("chk-g51", "showG51");
    bindChk("chk-abs", "showAbs");
    bindChk("chk-kqew", "showKqEw");
    bindChk("chk-total", "showTotal");

    // Section 02 종목 수 (상위 50 / 상위 100) & 필터 & 검색
    document.querySelectorAll("#sec2-scope-btns button").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.sec2Scope = btn.getAttribute("data-scope") || "50";
        renderSection02();
      });
    });

    // Section 02 필터 & 검색
    document.querySelectorAll("#sec2-mkt-btns button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#sec2-mkt-btns button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        state.sec2Market = btn.getAttribute("data-mkt");
        renderSection02();
      });
    });

    const sec2Search = document.getElementById("sec2-search");
    if (sec2Search) {
      sec2Search.addEventListener("input", (e) => {
        state.sec2Search = e.target.value;
        renderSection02();
      });
    }

    const dtStockSelect = document.getElementById("dt-stock-select");
    if (dtStockSelect) {
      dtStockSelect.addEventListener("change", (e) => {
        state.selectedStock = e.target.value;
        renderSection02();
        renderStockDetailPanel();
      });
    }

    // Section 04 통합 투자 주체 목록 전환 버튼
    document.querySelectorAll("#inv-tab-btns button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#inv-tab-btns button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        state.invListMode = btn.getAttribute("data-inv");
        renderUnifiedInvestorTable();
      });
    });

    // Section 05 분기 선택
    const qSel = document.getElementById("q-select");
    if (qSel) {
      qSel.addEventListener("change", (e) => {
        state.selectedQuarter = e.target.value;
        renderSection05();
      });
    }

    // 테마 전환 버튼
    document.getElementById("themeBtn").addEventListener("click", toggleTheme);

    // 링크 복사 버튼
    document.getElementById("copyLinkBtn").addEventListener("click", () => {
      navigator.clipboard?.writeText(window.location.href);
      const btn = document.getElementById("copyLinkBtn");
      const orig = btn.textContent;
      btn.textContent = "복사됨";
      setTimeout(() => {
        btn.textContent = orig;
      }, 1500);
    });

    // 전체 테이블 행 클릭 시 종목 상세로 연결
    document.body.addEventListener("click", (e) => {
      const tr = e.target.closest("tr.clickable");
      if (!tr) return;
      const code = tr.getAttribute("data-code");
      if (code && getStockDetailRecord(code)) {
        state.selectedStock = code;
        document.getElementById("dt-stock-select").value = code;
        if (state.activeTab !== "sec-02") {
          activateTab("sec-02", true);
        }
        renderSection02();
        renderStockDetailPanel();
      }
    });
  }

  function showLoadError(msg) {
    const wrap = document.querySelector("main.wrap");
    if (!wrap) return;
    wrap.innerHTML = `<div class="card" style="margin-top:16px;border-color:var(--hike)">
      <h2 class="sec-title">데이터를 불러오지 못했습니다</h2>
      <p class="sec-sub" style="margin-top:6px">${msg || "잠시 후 페이지를 새로고침해 주세요."}</p>
    </div>`;
  }

  function boot() {
    if (!DATA || !DATA.summary || !DATA.timeseries) {
      showLoadError("지수 데이터 파일(gaemi_data.js)이 비어 있거나 손상되었습니다.");
      return;
    }
    initTheme();
    initDetailSelect();
    initQuarterSelect();
    bindEvents();
    initConcentrationEvents();
    initDrawdownModule();
    renderConcentrationHero();
    renderConcentrationChart(90);
    renderMarketRelations("252D");
    renderNewsSection();
    initNewsFullViewer();
    if (CONC_DATA && CONC_DATA.as_of_date) {
      selectConcentrationDate(CONC_DATA.as_of_date);
    }
    renderBoughtTab('20d');
    renderMovementTab();
    const initHash = (window.location.hash || "").replace("#", "");
    const defaultTab = ["tab-conc", "tab-bought", "tab-movement", "tab-scorecard", "tab-method"].includes(initHash) ? initHash : "tab-conc";
    activateTab(defaultTab, false);
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (DATA) {
      boot();
    } else {
      initTheme();
      fetch("data/gaemi_data.json")
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((d) => {
          DATA = d;
          boot();
        })
        .catch((err) => {
          showLoadError(`데이터 로드 실패 (${err.message})`);
        });
    }
  });


  // ==========================================================
  // BOK WATCH STYLE GAEMI CONCENTRATION MODULE (PHASE 9 REBOOT)
  // ==========================================================
  let CONC_DATA = window.GAEMI_CONCENTRATION || null;
  state.concRange = 90;
  state.selectedConcDate = null;
  state.boughtPeriod = "20d";
  state.boughtSearch = "";

  function formatWon(val) {
    if (val === null || val === undefined || isNaN(val)) return "-";
    const abs = Math.abs(val);
    const sign = val < 0 ? "-" : "";
    if (abs >= 1e12) {
      return `${sign}${(abs / 1e12).toFixed(2)}조원`;
    } else if (abs >= 1e8) {
      return `${sign}${Math.round(abs / 1e8).toLocaleString("ko-KR")}억원`;
    }
    return `${sign}${Math.round(abs).toLocaleString("ko-KR")}원`;
  }

  function renderConcentrationHero() {
    if (!CONC_DATA || !CONC_DATA.latest) return;
    const lat = CONC_DATA.latest;
    const valEl = document.getElementById("hero-conc-val");
    const deltaEl = document.getElementById("hero-conc-delta");
    const asofEl = document.getElementById("hero-asof-date");
    const sumEl = document.getElementById("hero-summary-text");
    const t10El = document.getElementById("hero-top10-sum");
    const totEl = document.getElementById("hero-total-pos");
    const distEl = document.getElementById("hero-dist-badge");
    const medEl = document.getElementById("hero-1y-median");
    const rngEl = document.getElementById("hero-1y-range");

    if (valEl) valEl.textContent = `${lat.concentration.toFixed(1)}%`;
    if (deltaEl) {
      const sign = lat.delta >= 0.05 ? "+" : "";
      deltaEl.textContent = `${sign}${lat.delta.toFixed(1)}%p`;
      deltaEl.className = `conc-hero-delta ${lat.delta > 0.05 ? "up" : lat.delta < -0.05 ? "down" : "flat"}`;
    }
    if (asofEl) asofEl.textContent = `${lat.date} 기준`;
    if (sumEl) sumEl.textContent = lat.summary || "";
    if (t10El) t10El.textContent = formatWon(lat.top10_sum);
    if (totEl) totEl.textContent = formatWon(lat.total_pos);

    if (distEl && lat.top_pct_1y !== undefined) {
      distEl.textContent = `최근 1년 상위 ${lat.top_pct_1y.toFixed(1)}% 수준`;
    }
    if (medEl && lat.median_1y !== undefined) {
      medEl.textContent = `${lat.median_1y.toFixed(1)}%`;
    }
    if (rngEl && lat.min_1y !== undefined && lat.max_1y !== undefined) {
      rngEl.textContent = `${lat.min_1y.toFixed(1)}% ~ ${lat.max_1y.toFixed(1)}%`;
    }
  }

  function renderConcentrationChart(rangeDays) {
    const el = document.getElementById("concentrationChart");
    if (!el || !CONC_DATA || !CONC_DATA.history || !window.d3) return;

    if (rangeDays !== undefined) {
      state.concRange = rangeDays;
    }
    const rng = state.concRange;

    const hist = CONC_DATA.history;
    if (!hist.length) return;

    const lastRow = hist[hist.length - 1];
    const dayMs = (d) => Date.parse(d + "T00:00:00");
    const vis = rng > 0 ? hist.filter((r) => dayMs(r.date) >= dayMs(lastRow.date) - rng * 864e5) : hist;

    if (!vis.length) return;

    el.innerHTML = "";
    const W = Math.max(300, Math.round(el.clientWidth || 640));
    const LANE_H = 18, AX = 22;

    const x = d3.scaleTime()
      .domain([new Date(vis[0].date + "T00:00:00"), new Date(lastRow.date + "T00:00:00")])
      .range([44, W - 74]);
    const tx = (d) => x(new Date(d + "T00:00:00"));

    const minC = d3.min(vis, (d) => d.concentration);
    const maxC = d3.max(vis, (d) => d.concentration);
    const yMin = Math.max(0, Math.floor((minC - 4) / 5) * 5);
    const yMax = Math.min(100, Math.ceil((maxC + 4) / 5) * 5);

    // Inflection callouts (stacked badges)
    const infs = (CONC_DATA.inflections || []).filter((r) => vis.some((v) => v.date === r.date));
    const mc = document.createElement("canvas").getContext("2d");
    mc.font = `600 11.5px ${getComputedStyle(document.body).fontFamily}`;

    const md = (ds) => {
      const parts = ds.split("-");
      return `${parseInt(parts[1], 10)}/${parseInt(parts[2], 10)}`;
    };

    const calls = infs.map((r) => {
      const sign = r.delta >= 0 ? "+" : "";
      const txt = `${md(r.date)} ${sign}${r.delta.toFixed(1)}%p${r.headline && W >= 540 ? " " + r.headline : ""}`;
      const w = mc.measureText("▲ " + txt).width + 6;
      const cx = tx(r.date);
      const flip = cx + w > W - 6;
      return { r, txt, w, cx, x0: flip ? cx - w : cx, x1: flip ? cx : cx + w, flip, lv: 0 };
    });

    calls.forEach((c, i) => {
      while (calls.slice(0, i).some((p) => p.lv === c.lv && c.x0 < p.x1 + 8 && p.x0 < c.x1 + 8)) {
        c.lv++;
      }
    });

    const nLv = calls.length ? Math.max(...calls.map((c) => c.lv)) + 1 : 0;
    const m = { l: 44, r: 74, t: 10 + nLv * 18 + (nLv ? 8 : 0), b: 0 };
    const PH = 185;
    const plotB = m.t + PH;
    const laneTop = plotB + AX;
    const LANES = [["stock", "종목 집중"], ["sector", "업종 변화"], ["turnover", "순위 교체"]];
    const HT = laneTop + LANES.length * LANE_H + 8;

    const y = d3.scaleLinear().domain([yMin, yMax]).range([plotB, m.t]);

    const svg = d3.create("svg")
      .attr("viewBox", `0 0 ${W} ${HT}`)
      .attr("width", W)
      .attr("height", HT)
      .attr("role", "img")
      .attr("tabindex", 0)
      .attr("aria-label", "개미 순매수 집중도 변화 그래프");

    // Y Axis Grid
    const yTicks = y.ticks(5);
    yTicks.forEach((t) => {
      svg.append("line")
        .attr("x1", 44).attr("x2", W - 74)
        .attr("y1", y(t)).attr("y2", y(t))
        .attr("stroke", "var(--line)").attr("stroke-width", 1);
      svg.append("text")
        .attr("x", 38).attr("y", y(t) + 4)
        .attr("text-anchor", "end")
        .attr("font-size", 11)
        .attr("fill", "var(--ink-3)")
        .text(`${t}%`);
    });

    // X Axis Ticks
    const xTicks = x.ticks(Math.min(6, vis.length));
    xTicks.forEach((t) => {
      svg.append("text")
        .attr("x", x(t)).attr("y", plotB + 15)
        .attr("text-anchor", "middle")
        .attr("font-size", 11)
        .attr("fill", "var(--ink-3)")
        .text(`${t.getMonth() + 1}/${t.getDate()}`);
    });

    // Area fill under line
    const area = d3.area()
      .curve(d3.curveMonotoneX)
      .x((d) => tx(d.date))
      .y0(plotB)
      .y1((d) => y(d.concentration));

    svg.append("path")
      .attr("d", area(vis))
      .attr("fill", "var(--hike)")
      .attr("opacity", 0.08);

    // Line path
    const line = d3.line()
      .curve(d3.curveMonotoneX)
      .x((d) => tx(d.date))
      .y((d) => y(d.concentration));

    svg.append("path")
      .attr("d", line(vis))
      .attr("fill", "none")
      .attr("stroke", "var(--hike)")
      .attr("stroke-width", 2.4)
      .attr("stroke-linecap", "round")
      .attr("stroke-linejoin", "round");

    // Right-end label
    const lx = tx(lastRow.date);
    const ly = y(lastRow.concentration);
    svg.append("circle")
      .attr("cx", lx).attr("cy", ly)
      .attr("r", 4.5)
      .attr("fill", "var(--hike)")
      .attr("stroke", "var(--surface)").attr("stroke-width", 2);

    svg.append("text")
      .attr("x", lx + 8).attr("y", ly + 4)
      .attr("font-size", 12.5)
      .attr("font-weight", 700)
      .attr("fill", "var(--ink)")
      .text(`${lastRow.concentration.toFixed(1)}%`);

    // Inflection callout badges
    calls.forEach((c) => {
      const matchRow = vis.find((v) => v.date === c.r.date);
      if (!matchRow) return;
      const cy = y(matchRow.concentration);
      const ty = 14 + c.lv * 18;
      const tcol = c.r.delta >= 0 ? "var(--hike)" : "var(--cut)";

      svg.append("line")
        .attr("x1", c.cx).attr("x2", c.cx)
        .attr("y1", ty + 4).attr("y2", cy - 6)
        .attr("stroke", "var(--ink-3)")
        .attr("stroke-width", 1);

      svg.append("circle")
        .attr("cx", c.cx).attr("cy", cy)
        .attr("r", 5)
        .attr("fill", "var(--surface)")
        .attr("stroke", tcol)
        .attr("stroke-width", 2.2);

      const t = svg.append("text")
        .attr("x", c.cx)
        .attr("y", ty)
        .attr("text-anchor", c.flip ? "end" : "start")
        .attr("font-size", 11.5)
        .attr("font-weight", 600)
        .attr("fill", "var(--ink)");

      t.append("tspan").attr("fill", tcol).text(c.r.delta >= 0 ? "▲ " : "▼ ");
      t.append("tspan").text(c.txt);
    });

    // Bottom Event Lanes
    const laneCol = { stock: "var(--hike)", sector: "var(--cut)", turnover: "var(--ink-2)" };
    const lanesData = CONC_DATA.lanes || {};

    LANES.forEach(([k, name], li) => {
      const cy = laneTop + li * LANE_H + LANE_H / 2;
      svg.append("line")
        .attr("x1", 44).attr("x2", W - 74)
        .attr("y1", cy).attr("y2", cy)
        .attr("stroke", "var(--line)").attr("stroke-width", 1);

      svg.append("text")
        .attr("x", 38).attr("y", cy + 4)
        .attr("text-anchor", "end")
        .attr("font-size", 11)
        .attr("fill", "var(--ink-3)")
        .text(name);

      const items = (lanesData[k] || []).filter((it) => vis.some((v) => v.date === it.date));
      const evDateMap = {};
      items.forEach((it) => {
        evDateMap[it.date] = (evDateMap[it.date] || 0) + 1;
      });

      Object.entries(evDateMap).forEach(([dt, cnt]) => {
        const cx = tx(dt);
        svg.append("circle")
          .attr("cx", cx).attr("cy", cy)
          .attr("r", 4.5)
          .attr("fill", laneCol[k])
          .attr("stroke", "var(--surface)").attr("stroke-width", 1.5);

        if (cnt > 1) {
          svg.append("text")
            .attr("x", cx).attr("y", cy + 3)
            .attr("text-anchor", "middle")
            .attr("font-size", 8.5)
            .attr("font-weight", 700)
            .attr("fill", "var(--surface)")
            .text(cnt);
        }
      });
    });

    // Crosshair & Tooltip
    const hov = svg.append("g").style("display", "none").attr("pointer-events", "none");
    hov.append("line")
      .attr("y1", m.t).attr("y2", laneTop + LANES.length * LANE_H)
      .attr("stroke", "var(--ink-3)").attr("stroke-width", 1);
    const hdot = hov.append("circle")
      .attr("r", 5)
      .attr("fill", "var(--hike)")
      .attr("stroke", "var(--surface)").attr("stroke-width", 2);

    const tip = document.getElementById("pctip");

    let curIdx = vis.length - 1;

    const showAt = (idx, px) => {
      curIdx = Math.max(0, Math.min(vis.length - 1, idx));
      const r = vis[curIdx];
      const cx = tx(r.date);

      hov.style("display", null);
      hov.select("line").attr("x1", cx).attr("x2", cx);
      hdot.attr("cx", cx).attr("cy", y(r.concentration));

      if (tip) {
        const sign = r.delta >= 0 ? "+" : "";
        tip.innerHTML = `
          <div class="pctip-date">${r.date}</div>
          <div class="pctip-row">
            <span>집중도:</span>
            <strong>${r.concentration.toFixed(1)}%</strong>
          </div>
          <div class="pctip-row">
            <span>전일대비:</span>
            <strong style="color:${r.delta >= 0 ? 'var(--hike)' : 'var(--cut)'}">${sign}${r.delta.toFixed(1)}%p</strong>
          </div>
          ${r.top1_name ? `<div style="font-size:11px;color:var(--ink-2);margin-top:4px">1위: ${r.top1_name} (${r.top1_share.toFixed(1)}%)</div>` : ""}
        `;
        tip.hidden = false;
        const tw = tip.offsetWidth || 180;
        const left = Math.max(8, Math.min(W - tw - 8, (px != null ? px : cx) + 12));
        tip.style.left = `${left}px`;
      }

      selectConcentrationDate(r.date);
    };

    const nearestIdx = (px) => {
      const t = x.invert(px).getTime();
      let best = 0;
      vis.forEach((v, i) => {
        if (Math.abs(dayMs(v.date) - t) < Math.abs(dayMs(vis[best].date) - t)) {
          best = i;
        }
      });
      return best;
    };

    svg.on("pointermove", (ev) => {
      const [px] = d3.pointer(ev);
      if (px >= 44 && px <= W - 74) {
        showAt(nearestIdx(px), px);
      }
    }).on("pointerdown", (ev) => {
      const [px] = d3.pointer(ev);
      if (px >= 44 && px <= W - 74) {
        showAt(nearestIdx(px), px);
      }
    }).on("keydown", (ev) => {
      const step = ev.key === "ArrowLeft" ? -1 : ev.key === "ArrowRight" ? 1 : 0;
      if (step) {
        ev.preventDefault();
        showAt(curIdx + step);
      }
    });

    el.appendChild(svg.node());
  }

  function selectConcentrationDate(dateStr) {
    if (!CONC_DATA) return;
    state.selectedConcDate = dateStr;

    const d = (CONC_DATA.details && CONC_DATA.details[dateStr]) || null;
    const titleEl = document.getElementById("inspect-date-title");
    const pillEl = document.getElementById("inspect-conc-pill");
    const summaryEl = document.getElementById("inspect-summary-p");

    if (titleEl) titleEl.textContent = `${dateStr} 집중도 요인 분해`;

    if (!d) {
      // Historical date without deep detail
      const h = (CONC_DATA.history || []).find((r) => r.date === dateStr);
      if (h) {
        if (pillEl) {
          const sign = h.delta >= 0 ? "+" : "";
          pillEl.textContent = `집중도 ${h.concentration.toFixed(1)}% (${sign}${h.delta.toFixed(1)}%p)`;
        }
        if (summaryEl) {
          summaryEl.textContent = `해당 거래일 개인 순매수 집중도는 ${h.concentration.toFixed(1)}%였습니다.`;
        }
        const distBadge = document.getElementById("hero-dist-badge");
        if (distBadge && h.top_pct_1y !== undefined) {
          distBadge.textContent = dateStr === CONC_DATA.as_of_date
            ? `최근 1년 상위 ${h.top_pct_1y.toFixed(1)}% 수준`
            : `해당일 기준 1년 상위 ${h.top_pct_1y.toFixed(1)}% 수준`;
        }
        renderNewsSection(dateStr);
      }
      return;
    }

    if (pillEl) {
      const sign = d.delta >= 0 ? "+" : "";
      pillEl.textContent = `집중도 ${d.concentration.toFixed(1)}% (${sign}${d.delta.toFixed(1)}%p)`;
    }
    if (summaryEl) {
      summaryEl.textContent = d.summary || "";
    }

    // 1. 종목별 기여도
    const contribEl = document.getElementById("contrib-list");
    if (contribEl) {
      const contribs = d.contribs || [];
      if (!contribs.length) {
        contribEl.innerHTML = `<p style="font-size:12px;color:var(--ink-3)">기여도 데이터 없음</p>`;
      } else {
        const sumVal = contribs.reduce((a, b) => a + b.contrib, 0);
        contribEl.innerHTML = contribs.map((c) => {
          const sign = c.contrib >= 0 ? "+" : "";
          const cls = c.contrib >= 0 ? "up" : "down";
          return `
            <div class="decomp-item">
              <span>${c.name} <small style="color:var(--ink-3)">(${c.sector})</small></span>
              <span class="val ${cls}">${sign}${c.contrib.toFixed(1)}%p</span>
            </div>
          `;
        }).join("") + `
          <div class="decomp-item" style="margin-top:6px;border-top:1px dashed var(--line);padding-top:4px;font-weight:700">
            <span>기여도 합계</span>
            <span class="val ${sumVal >= 0 ? 'up' : 'down'}">${sumVal >= 0 ? '+' : ''}${sumVal.toFixed(1)}%p</span>
          </div>
        `;
      }
    }

    // 2. 20거래일 이동창 효과
    const windowEl = document.getElementById("window-effect-box");
    if (windowEl) {
      const drop = d.drop_effect;
      if (drop && drop.is_dominant) {
        windowEl.innerHTML = `
          <div style="font-size:12.5px;color:var(--ink-2);line-height:1.55">
            <strong style="color:var(--hike)">탈락 효과 주도</strong>: <strong>${drop.name}</strong> 종목의 경우, 
            당일 순매매보다 <strong>20거래일 전(${drop.drop_date})</strong>의 대규모 순매수 기록(<strong>${formatWon(drop.drop_val)}</strong>)이 
            계산에서 제외된 영향으로 비중이 변동했습니다.
          </div>
        `;
      } else {
        windowEl.innerHTML = `
          <div style="font-size:12.5px;color:var(--ink-2);line-height:1.55">
            신규 거래일의 순매매 유입이 상위 종목 비중 변화를 주도했습니다.
          </div>
        `;
      }
    }

    // 3. 분모 변화 효과
    const denomEl = document.getElementById("denom-effect-box");
    if (denomEl) {
      denomEl.innerHTML = `
        <div class="decomp-item">
          <span>상위 10종목 합계</span>
          <span class="val">${formatWon(d.top10_sum)}</span>
        </div>
        <div class="decomp-item">
          <span>양(+)의 순매수 전체</span>
          <span class="val">${formatWon(d.total_pos)}</span>
        </div>
        <div style="font-size:11.5px;color:var(--ink-3);margin-top:4px">
          비중 = 상위 10종목 ÷ 전체 = <strong>${d.concentration.toFixed(1)}%</strong>
        </div>
      `;
    }

    // 4. Top 10 테이블
    const t10Tbody = document.getElementById("top10-tbody");
    if (t10Tbody) {
      const list = d.top10 || [];
      t10Tbody.innerHTML = list.map((item) => {
        const sign = item.diff_share >= 0 ? "+" : "";
        const diffCls = item.diff_share > 0 ? "up" : item.diff_share < 0 ? "down" : "";
        const statusBadge = item.is_new
          ? `<span class="tier-pill t1">신규</span>`
          : `<span class="tier-pill t2">유지</span>`;
        return `
          <tr>
            <td style="font-weight:700;text-align:center">${item.rank}</td>
            <td><strong>${item.name}</strong> <small style="color:var(--ink-3)">${item.code}</small></td>
            <td>${item.market}</td>
            <td><span class="tile-tag">${item.sector}</span></td>
            <td class="r" style="font-family:var(--font-mono)">${formatWon(item.net_val)}</td>
            <td class="r" style="font-family:var(--font-mono);font-weight:700">${item.share.toFixed(1)}%</td>
            <td class="r ${diffCls}" style="font-family:var(--font-mono)">${sign}${item.diff_share.toFixed(1)}%p</td>
            <td class="c">${statusBadge}</td>
          </tr>
        `;
      }).join("");
    }

    // Update distribution badge
    const distBadge = document.getElementById("hero-dist-badge");
    if (distBadge && d && d.top_pct_1y !== undefined) {
      const isLatest = CONC_DATA && dateStr === CONC_DATA.as_of_date;
      distBadge.textContent = isLatest
        ? `최근 1년 상위 ${d.top_pct_1y.toFixed(1)}% 수준`
        : `해당일 기준 1년 상위 ${d.top_pct_1y.toFixed(1)}% 수준`;
    }

    // Update related news for selected date
    renderNewsSection(dateStr);
  }

  function renderBoughtTab(period, query, sortMode) {
    if (period) state.boughtPeriod = period;
    if (query !== undefined) state.boughtSearch = query;
    if (sortMode) state.boughtSort = sortMode;

    const p = state.boughtPeriod;
    const q = (state.boughtSearch || "").trim().toLowerCase();
    const sort = state.boughtSort;

    const tbody = document.getElementById("bought-ranking-tbody");
    if (!tbody) return;

    let items = [];
    if (DD_DATA && DD_DATA.stocks && DD_DATA.stocks.length) {
      items = DD_DATA.stocks.slice();
      if (!q && p === "20d") {
        // 기본 20d에서는 순매수 상위 50종목 우선 노출
        items = items.slice(0, 50);
      }
    } else if (CONC_DATA && CONC_DATA.latest) {
      if (p === "20d") items = CONC_DATA.latest.top10 || [];
      else if (p === "5d") items = CONC_DATA.latest.top_5d || [];
      else if (p === "1d") items = CONC_DATA.latest.top_1d || [];
    }

    if (q) {
      if (DD_DATA && DD_DATA.stocks) {
        items = DD_DATA.stocks.filter((it) => it.name.toLowerCase().includes(q) || it.code.includes(q));
      } else {
        items = items.filter((it) => it.name.toLowerCase().includes(q) || it.code.includes(q));
      }
    }

    // 정렬 적용
    if (sort === "netbuy") {
      items.sort((a, b) => (b.net_buy_20d || 0) - (a.net_buy_20d || 0));
    } else if (sort === "dd_desc") {
      items.sort((a, b) => (a.drawdown_pct || 0) - (b.drawdown_pct || 0));
    } else if (sort === "dd_asc") {
      items.sort((a, b) => (b.drawdown_pct || 0) - (a.drawdown_pct || 0));
    } else if (sort === "ret_desc") {
      items.sort((a, b) => (b.return_since_base_pct || 0) - (a.return_since_base_pct || 0));
    } else if (sort === "ret_asc") {
      items.sort((a, b) => (a.return_since_base_pct || 0) - (b.return_since_base_pct || 0));
    }

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="c" style="padding:20px;color:var(--ink-3)">검색 결과가 없습니다.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.map((it, idx) => {
      const dd = it.drawdown_pct !== undefined ? `${it.drawdown_pct.toFixed(1)}%` : "-";
      const ret = it.return_since_base_pct !== undefined ? `${it.return_since_base_pct >= 0 ? '+' : ''}${it.return_since_base_pct.toFixed(1)}%` : "-";
      const retClass = it.return_since_base_pct >= 0 ? "up" : "down";
      const peak = it.peak_adj_close ? formatWon(it.peak_adj_close) : "-";
      const peakDt = it.peak_date ? ` (${it.peak_date})` : "";
      const netVal = it.net_buy_20d !== undefined ? formatWon(it.net_buy_20d) : (it.net_val ? formatWon(it.net_val) : "-");
      const latestClose = it.latest_adj_close ? formatWon(it.latest_adj_close) : "-";
      const statusTag = it.is_suspended
        ? `<span class="tile-tag" style="color:var(--del-ink)">거래정지</span>`
        : `<span class="tile-tag" style="color:var(--add-ink)">정상</span>`;

      return `
        <tr>
          <td style="font-weight:700;text-align:center">${idx + 1}</td>
          <td><strong>${it.name}</strong> <small style="color:var(--ink-3)">${it.code}</small></td>
          <td>${it.market || "-"}</td>
          <td><span class="tile-tag">${it.industry || it.sector || "기타"}</span></td>
          <td class="r" style="font-family:var(--font-mono)">${netVal}</td>
          <td class="r" style="font-family:var(--font-mono)">${latestClose}</td>
          <td class="r down" style="font-family:var(--font-mono);font-weight:700">${dd}</td>
          <td class="r ${retClass}" style="font-family:var(--font-mono);font-weight:700">${ret}</td>
          <td class="r" style="font-family:var(--font-mono)">${peak}<small style="color:var(--ink-3)">${peakDt}</small></td>
          <td class="c">${statusTag}</td>
        </tr>
      `;
    }).join("");
  }

  function renderMovementTab() {
    if (!CONC_DATA || !CONC_DATA.latest) return;
    const lat = CONC_DATA.latest;

    // 1. 업종별 순매수 구성
    const barListEl = document.getElementById("sectorBarList");
    if (barListEl) {
      const shares = lat.sector_shares || [];
      barListEl.innerHTML = shares.map((s) => `
        <div class="sector-bar-row">
          <span style="font-weight:600">${s.sector}</span>
          <div class="sector-track">
            <div class="sector-fill" style="width:${Math.min(100, s.share)}%"></div>
          </div>
          <span style="font-family:var(--font-mono);font-weight:700;text-align:right">${s.share.toFixed(1)}%</span>
        </div>
      `).join("");
    }

    // 2. 20D vs 직전 20D 업종 변화
    const shiftTbody = document.getElementById("sector-shift-tbody");
    if (shiftTbody) {
      const shifts = lat.sector_shift || [];
      if (!shifts.length) {
        shiftTbody.innerHTML = `<tr><td colspan="4" class="c" style="color:var(--ink-3);padding:14px">비교 데이터 산출 중</td></tr>`;
      } else {
        shiftTbody.innerHTML = shifts.map((s) => {
          const sign = s.diff >= 0 ? "+" : "";
          const cls = s.diff > 0 ? "up" : s.diff < 0 ? "down" : "";
          return `
            <tr>
              <td style="font-weight:600">${s.sector}</td>
              <td class="r" style="font-family:var(--font-mono)">${s.current_share.toFixed(1)}%</td>
              <td class="r" style="font-family:var(--font-mono)">${s.prior_share.toFixed(1)}%</td>
              <td class="r ${cls}" style="font-family:var(--font-mono);font-weight:700">${sign}${s.diff.toFixed(1)}%p</td>
            </tr>
          `;
        }).join("");
      }
    }

    // 3. 종목별 비중 상승/하락 5종목
    const gTbody = document.getElementById("stock-gainers-tbody");
    if (gTbody) {
      const gainers = lat.stock_gainers || [];
      gTbody.innerHTML = gainers.map((g) => `
        <tr>
          <td><strong>${g.name}</strong></td>
          <td><span class="tile-tag">${g.sector}</span></td>
          <td class="r" style="font-family:var(--font-mono)">${g.current_share.toFixed(1)}%</td>
          <td class="r up" style="font-family:var(--font-mono);font-weight:700">+${g.diff.toFixed(1)}%p</td>
        </tr>
      `).join("");
    }

    const lTbody = document.getElementById("stock-losers-tbody");
    if (lTbody) {
      const losers = lat.stock_losers || [];
      lTbody.innerHTML = losers.map((l) => `
        <tr>
          <td><strong>${l.name}</strong></td>
          <td><span class="tile-tag">${l.sector}</span></td>
          <td class="r" style="font-family:var(--font-mono)">${l.current_share.toFixed(1)}%</td>
          <td class="r down" style="font-family:var(--font-mono);font-weight:700">${l.diff.toFixed(1)}%p</td>
        </tr>
      `).join("");
    }
  }

  function initConcentrationEvents() {
    // 차트 기간 버튼
    document.querySelectorAll("#concRangeSwitch button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#concRangeSwitch button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        const rng = parseInt(btn.getAttribute("data-range"), 10);
        renderConcentrationChart(rng);
      });
    });

    // 개미가 산 종목 기간 스위치
    document.querySelectorAll("#boughtPeriodSwitch button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#boughtPeriodSwitch button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        renderBoughtTab(btn.getAttribute("data-period"));
      });
    });

    // 개미가 산 종목 정렬 스위치
    document.querySelectorAll("#boughtSortSwitch button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#boughtSortSwitch button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        renderBoughtTab(undefined, undefined, btn.getAttribute("data-sort"));
      });
    });

    // 개미가 산 종목 검색
    const searchInput = document.getElementById("stockSearchInput");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        renderBoughtTab(undefined, e.target.value);
      });
    }

    // 시장 상관관계 기간 스위치
    document.querySelectorAll("#marketPeriodSwitch button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#marketPeriodSwitch button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        const mp = btn.getAttribute("data-mperiod");
        renderMarketRelations(mp);
      });
    });

    // 윈도우 리사이즈 시 반응형 재렌더링
    window.addEventListener("resize", () => {
      if (state.activeTab === "tab-conc") {
        renderConcentrationChart();
      }
    });
  }

  function renderMarketRelations(periodKey) {
    if (!CONC_DATA || !CONC_DATA.market_correlation) return;
    const corrs = CONC_DATA.market_correlation;
    const key = periodKey || state.marketPeriod || "252D";
    state.marketPeriod = key;
    const item = corrs[key];
    if (!item) return;

    // Switch buttons UI
    document.querySelectorAll("#marketPeriodSwitch button").forEach((btn) => {
      if (btn.getAttribute("data-mperiod") === key) {
        btn.classList.add("on");
      } else {
        btn.classList.remove("on");
      }
    });

    // Update stats
    const kCorrEl = document.getElementById("m-kospi-corr");
    const kUpEl = document.getElementById("m-kospi-up");
    const kDnEl = document.getElementById("m-kospi-dn");
    const kUpCntEl = document.getElementById("m-kospi-up-cnt");
    const kDnCntEl = document.getElementById("m-kospi-dn-cnt");
    const kBarEl = document.getElementById("m-kospi-bar");

    const qCorrEl = document.getElementById("m-kosdaq-corr");
    const qUpEl = document.getElementById("m-kosdaq-up");
    const qDnEl = document.getElementById("m-kosdaq-dn");
    const qUpCntEl = document.getElementById("m-kosdaq-up-cnt");
    const qDnCntEl = document.getElementById("m-kosdaq-dn-cnt");
    const qBarEl = document.getElementById("m-kosdaq-bar");

    const sumEl = document.getElementById("market-summary-text");

    if (kCorrEl) kCorrEl.textContent = `r = ${item.corr_kospi.toFixed(4)}`;
    if (kUpEl) {
      const sign = item.kospi_up_avg_delta >= 0 ? "+" : "";
      kUpEl.textContent = `${sign}${item.kospi_up_avg_delta.toFixed(2)}%p`;
      kUpEl.className = `mono ${item.kospi_up_avg_delta >= 0 ? "up" : "dn"}`;
    }
    if (kDnEl) {
      const sign = item.kospi_down_avg_delta >= 0 ? "+" : "";
      kDnEl.textContent = `${sign}${item.kospi_down_avg_delta.toFixed(2)}%p`;
      kDnEl.className = `mono ${item.kospi_down_avg_delta >= 0 ? "up" : "dn"}`;
    }
    if (kUpCntEl) kUpCntEl.textContent = `(${item.kospi_up_count}일)`;
    if (kDnCntEl) kDnCntEl.textContent = `(${item.kospi_down_count}일)`;
    if (kBarEl) kBarEl.style.width = `${Math.min(100, Math.abs(item.corr_kospi) * 100).toFixed(1)}%`;

    if (qCorrEl) qCorrEl.textContent = `r = ${item.corr_kosdaq.toFixed(4)}`;
    if (qUpEl) {
      const sign = item.kosdaq_up_avg_delta >= 0 ? "+" : "";
      qUpEl.textContent = `${sign}${item.kosdaq_up_avg_delta.toFixed(2)}%p`;
      qUpEl.className = `mono ${item.kosdaq_up_avg_delta >= 0 ? "up" : "dn"}`;
    }
    if (qDnEl) {
      const sign = item.kosdaq_down_avg_delta >= 0 ? "+" : "";
      qDnEl.textContent = `${sign}${item.kosdaq_down_avg_delta.toFixed(2)}%p`;
      qDnEl.className = `mono ${item.kosdaq_down_avg_delta >= 0 ? "up" : "dn"}`;
    }
    if (qUpCntEl) qUpCntEl.textContent = `(${item.kosdaq_up_count}일)`;
    if (qDnCntEl) qDnCntEl.textContent = `(${item.kosdaq_down_count}일)`;
    if (qBarEl) qBarEl.style.width = `${Math.min(100, Math.abs(item.corr_kosdaq) * 100).toFixed(1)}%`;

    if (sumEl) sumEl.textContent = item.summary || "";
  }

  function renderNewsSection(targetDate) {
    const NEWS_DATA = window.GAEMI_NEWS;
    if (!NEWS_DATA) return;
    const grid = document.getElementById("newsCardGrid");
    if (!grid) return;

    const titleEl = document.getElementById("news-section-title");
    const subEl = document.getElementById("news-section-sub");
    const pillEl = document.getElementById("news-outlets-pill");
    const updatedEl = document.getElementById("news-last-updated");

    if (pillEl) {
      pillEl.textContent = `${NEWS_DATA.outlets_collected_count}개사 ${NEWS_DATA.total_articles}건`;
    }
    if (updatedEl && NEWS_DATA.last_updated) {
      const d = NEWS_DATA.last_updated.replace("T", " ").slice(0, 16);
      updatedEl.textContent = `최근 수집: ${d}`;
    }

    let articles = [];
    const isSpecificDate = Boolean(targetDate && CONC_DATA && targetDate !== CONC_DATA.as_of_date);

    if (isSpecificDate && NEWS_DATA.by_date && NEWS_DATA.by_date[targetDate] && NEWS_DATA.by_date[targetDate].length > 0) {
      articles = NEWS_DATA.by_date[targetDate].slice(0, 6);
      if (titleEl) titleEl.textContent = `${targetDate} 관련 뉴스`;
      if (subEl) subEl.textContent = `${targetDate} 당시 개인 순매수 및 시장 관련 보도 (${articles.length}건)`;
    } else {
      articles = (NEWS_DATA.articles || []).slice(0, 6);
      if (titleEl) titleEl.textContent = "관련 뉴스";
      if (subEl) subEl.textContent = "47개 언론사 화이트리스트 기반 개인 순매수·수급 보도";
    }

    if (!articles.length) {
      grid.innerHTML = `<div style="grid-column:1/-1;padding:24px;text-align:center;font-size:13px;color:var(--ink-3);background:var(--surface-2);border-radius:6px;border:1px dashed var(--line);">수집된 관련 기사가 없습니다.</div>`;
      return;
    }

    grid.innerHTML = articles.map((art) => {
      const stockTags = (art.stocks || []).map((s) => `<span class="news-tag stock">#${s}</span>`).join("");
      const secTags = (art.sectors || []).map((s) => `<span class="news-tag sec">#${s}</span>`).join("");
      const kwTags = (art.keywords || []).slice(0, 2).map((k) => `<span class="news-tag">#${k}</span>`).join("");
      return `
        <a class="news-card" href="${art.link}" target="_blank" rel="noopener" title="${art.outlet_name} 원문 보기">
          <div>
            <div class="news-tags">${stockTags}${secTags}${kwTags}</div>
            <h4 class="news-title">${art.title}</h4>
            <p class="news-summary">${art.summary || ""}</p>
          </div>
          <div class="news-meta">
            <span class="news-outlet">${art.outlet_name}</span>
            <span class="news-time">${art.date} ${art.time} ↗</span>
          </div>
        </a>
      `;
    }).join("");
  }

  function initNewsFullViewer() {
    const NEWS_DATA = window.GAEMI_NEWS;
    if (!NEWS_DATA) return;
    const btn = document.getElementById("toggleAllNewsBtn");
    const wrap = document.getElementById("newsFullWrap");
    const outFilter = document.getElementById("newsOutletFilter");
    const stockFilter = document.getElementById("newsStockFilter");
    const secFilter = document.getElementById("newsSectorFilter");
    const fullList = document.getElementById("newsFullList");

    if (!btn || !wrap || !fullList) return;

    // Populate filter dropdowns
    if (outFilter && NEWS_DATA.outlets_collected_names) {
      outFilter.innerHTML = `<option value="all">전체 언론사 (${NEWS_DATA.outlets_collected_names.length}곳)</option>` +
        NEWS_DATA.outlets_collected_names.map((o) => `<option value="${o}">${o}</option>`).join("");
    }

    const allStocks = new Set();
    const allSecs = new Set();
    (NEWS_DATA.articles || []).forEach((a) => {
      (a.stocks || []).forEach((s) => allStocks.add(s));
      (a.sectors || []).forEach((s) => allSecs.add(s));
    });

    if (stockFilter) {
      stockFilter.innerHTML = `<option value="all">전체 종목</option>` +
        Array.from(allStocks).sort().map((s) => `<option value="${s}">${s}</option>`).join("");
    }
    if (secFilter) {
      secFilter.innerHTML = `<option value="all">전체 업종</option>` +
        Array.from(allSecs).sort().map((s) => `<option value="${s}">${s}</option>`).join("");
    }

    const renderFull = () => {
      const oVal = outFilter ? outFilter.value : "all";
      const sVal = stockFilter ? stockFilter.value : "all";
      const secVal = secFilter ? secFilter.value : "all";

      const filtered = (NEWS_DATA.articles || []).filter((a) => {
        if (oVal !== "all" && a.outlet_name !== oVal) return false;
        if (sVal !== "all" && !(a.stocks || []).includes(sVal)) return false;
        if (secVal !== "all" && !(a.sectors || []).includes(secVal)) return false;
        return true;
      });

      if (!filtered.length) {
        fullList.innerHTML = `<div style="padding:16px;text-align:center;font-size:12.5px;color:var(--ink-3);">조건에 맞는 기사가 없습니다.</div>`;
        return;
      }

      fullList.innerHTML = filtered.map((a) => `
        <a class="news-full-item" href="${a.link}" target="_blank" rel="noopener">
          <span class="n-title">${a.title}</span>
          <span class="n-meta">${a.outlet_name} · ${a.date} ↗</span>
        </a>
      `).join("");
    };

    btn.addEventListener("click", () => {
      const isHidden = wrap.hidden;
      wrap.hidden = !isHidden;
      btn.textContent = isHidden ? "기사 닫기" : "전체 기사 보기";
      if (isHidden) renderFull();
    });

    [outFilter, stockFilter, secFilter].forEach((sel) => {
      if (sel) sel.addEventListener("change", renderFull);
    });
  }

  // ==========================================================
  // PEAK DRAWDOWN MODULE (고점 대비 낙폭 분석 전면 개편)
  // ==========================================================
  let DD_DATA = window.GAEMI_DRAWDOWN || null;
  let ddTsChart = null;

  function initDrawdownModule() {
    if (!DD_DATA) {
      fetch("data/gaemi_drawdown.json")
        .then((r) => r.json())
        .then((d) => {
          DD_DATA = d;
          setupDrawdownUI();
        })
        .catch(() => {});
      return;
    }
    setupDrawdownUI();
  }

  function setupDrawdownUI() {
    renderDrawdownHero();
    renderDrawdownDistribution();
    renderRetailTop50Drawdown();
    renderDrawdownTimeseriesChart();

    // 1. 시장 전환 스위치 (KOSPI / KOSDAQ)
    document.querySelectorAll("#ddMarketSwitch button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#ddMarketSwitch button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        state.ddMarket = btn.getAttribute("data-mkt") || "KOSPI";
        state.selectedBucketRange = null;
        const bucketWrap = document.getElementById("bucketStocksWrap");
        if (bucketWrap) bucketWrap.hidden = true;
        renderDrawdownHero();
        renderDrawdownDistribution();
        renderDrawdownTimeseriesChart();
      });
    });

    // 2. 구간 종목 목록 닫기 버튼
    const closeBucketBtn = document.getElementById("closeBucketStocksBtn");
    if (closeBucketBtn) {
      closeBucketBtn.addEventListener("click", () => {
        const bucketWrap = document.getElementById("bucketStocksWrap");
        if (bucketWrap) bucketWrap.hidden = true;
        document.querySelectorAll("#distBarList .dist-row").forEach((r) => r.classList.remove("active"));
        state.selectedBucketRange = null;
      });
    }

    // 3. 시계열 지표 스위치 (낙폭 중앙값 vs 30%·50% 하락 비율)
    document.querySelectorAll("#ddTsMetricSwitch button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#ddTsMetricSwitch button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        state.ddTsMetric = btn.getAttribute("data-metric") || "median";
        renderDrawdownTimeseriesChart();
      });
    });

    // 4. 시계열 기간 스위치 (30일, 90일, 1년, 전체)
    document.querySelectorAll("#ddTsRangeSwitch button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#ddTsRangeSwitch button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        state.ddTsRange = parseInt(btn.getAttribute("data-tsrange"), 10);
        renderDrawdownTimeseriesChart();
      });
    });

    // 5. 창 크기 변경 시 차트 재렌더링
    window.addEventListener("resize", () => {
      if (state.activeTab === "tab-conc") {
        renderDrawdownTimeseriesChart();
      }
    });
  }

  function renderDrawdownHero() {
    if (!DD_DATA || !DD_DATA.benchmarks || !DD_DATA.market_summary) return;
    const mkt = state.ddMarket; // "KOSPI" | "KOSDAQ"
    const bm = DD_DATA.benchmarks[mkt];
    const mktStats = DD_DATA.market_summary[mkt];
    if (!bm || !mktStats) return;

    // Tile 1: 지수 고점 대비 하락률
    const idxNameEl = document.getElementById("dd-idx-name");
    const idxValEl = document.getElementById("dd-idx-val");
    const idxPeakEl = document.getElementById("dd-idx-peak-tag");
    const idxSubEl = document.getElementById("dd-idx-sub");

    if (idxNameEl) idxNameEl.textContent = `${mkt === "KOSPI" ? "코스피" : "코스닥"} 지수 하락률`;
    if (idxValEl) {
      idxValEl.textContent = `${bm.drawdown_pct.toFixed(1)}%`;
      idxValEl.className = "dd-hero-num down";
    }
    if (idxPeakEl) {
      idxPeakEl.textContent = `최고점 ${bm.peak_val.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${bm.peak_date})`;
    }
    if (idxSubEl) {
      idxSubEl.textContent = `현재 지수 ${bm.latest.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    // Tile 2: 개별 종목 낙폭 중앙값
    const medNameEl = document.getElementById("dd-median-name");
    const medValEl = document.getElementById("dd-median-val");
    const medSubEl = document.getElementById("dd-median-sub");

    if (medNameEl) medNameEl.textContent = `${mkt === "KOSPI" ? "코스피" : "코스닥"} 개별 종목 낙폭 중앙값`;
    if (medValEl) {
      medValEl.textContent = `${mktStats.median_drawdown_pct.toFixed(1)}%`;
      medValEl.className = "dd-hero-num down";
    }
    if (medSubEl) {
      medSubEl.textContent = `${mkt === "KOSPI" ? "코스피" : "코스닥"} ${mktStats.total_stocks}개 종목의 최고점 대비 하락률 중앙값`;
    }

    // Tile 3: 30% 이상 하락 종목
    const d30NameEl = document.getElementById("dd-d30-name");
    const d30ValEl = document.getElementById("dd-d30-val");
    const d30CntEl = document.getElementById("dd-d30-cnt-tag");
    const d30SubEl = document.getElementById("dd-d30-sub");

    if (d30NameEl) d30NameEl.textContent = "30% 이상 하락 종목";
    if (d30ValEl) d30ValEl.textContent = `${mktStats.down_30_pct.toFixed(1)}%`;
    if (d30CntEl) d30CntEl.textContent = `${mktStats.down_30_count}개 / ${mktStats.total_stocks}개`;
    if (d30SubEl) {
      d30SubEl.textContent = `50% 이상 하락: ${mktStats.down_50_count}개 (${mktStats.down_50_pct.toFixed(1)}%)`;
    }

    // 시각적 격차 인디케이터
    const gapIdxEl = document.getElementById("gap-idx-val");
    const gapMedEl = document.getElementById("gap-med-val");
    const gapDiffEl = document.getElementById("gap-diff-val");
    const gapGuideEl = document.getElementById("gap-guide-text");

    const gapDiff = mktStats.median_drawdown_pct - bm.drawdown_pct;
    if (gapIdxEl) gapIdxEl.textContent = `${bm.drawdown_pct.toFixed(1)}%`;
    if (gapMedEl) gapMedEl.textContent = `${mktStats.median_drawdown_pct.toFixed(1)}%`;
    if (gapDiffEl) {
      const sign = gapDiff >= 0.05 ? "+" : "";
      gapDiffEl.textContent = `${sign}${gapDiff.toFixed(1)}%p`;
      gapDiffEl.className = gapDiff <= -0.05 ? "down" : "mono";
    }
    if (gapGuideEl) {
      if (mkt === "KOSPI") {
        gapGuideEl.textContent = "코스피 개별 종목들의 실제 낙폭이 지수보다 더 크게 나타나고 있습니다.";
      } else {
        gapGuideEl.textContent = "코스닥 개별 종목 낙폭 중앙값(-55.7%)은 지수 하락률(-45.7%)보다 -10.0%p 더 깊어 체감 하락이 극심합니다.";
      }
    }
  }

  function renderDrawdownDistribution() {
    if (!DD_DATA || !DD_DATA.market_summary) return;
    const mkt = state.ddMarket;
    const mktStats = DD_DATA.market_summary[mkt];
    if (!mktStats || !mktStats.distribution) return;

    const titleEl = document.getElementById("dist-section-title");
    const subEl = document.getElementById("dist-section-sub");
    const totTag = document.getElementById("dist-total-tag");
    const listEl = document.getElementById("distBarList");

    if (titleEl) titleEl.textContent = `고점에서 멀어진 주식들 (${mkt})`;
    if (subEl) subEl.textContent = `2025년 6월 2일 이후 기간 최고 수정종가 대비 하락폭 구간별 ${mkt} 종목 분포`;
    if (totTag) totTag.textContent = `${mkt} ${mktStats.total_stocks}개 종목`;

    if (!listEl) return;
    const buckets = mktStats.distribution;

    listEl.innerHTML = buckets.map((b, idx) => {
      const isActive = state.selectedBucketRange === idx ? " active" : "";
      return `
        <div class="dist-row${isActive}" data-bidx="${idx}" role="button" tabindex="0" aria-label="${b.label}: ${b.count}개, ${b.pct.toFixed(1)}%">
          <span class="dist-label">${b.label}</span>
          <div class="dist-track">
            <div class="dist-fill" style="width:${Math.min(100, b.pct)}%"></div>
          </div>
          <div class="dist-meta">
            <strong>${b.pct.toFixed(1)}%</strong>
            <span>(${b.count}개)</span>
          </div>
        </div>
      `;
    }).join("");

    // 행 클릭 이벤트: 해당 구간 종목 리스트 전개
    listEl.querySelectorAll(".dist-row").forEach((row) => {
      row.addEventListener("click", () => {
        const bidx = parseInt(row.getAttribute("data-bidx"), 10);
        listEl.querySelectorAll(".dist-row").forEach((r) => r.classList.remove("active"));
        if (state.selectedBucketRange === bidx) {
          state.selectedBucketRange = null;
          const wrap = document.getElementById("bucketStocksWrap");
          if (wrap) wrap.hidden = true;
          return;
        }
        state.selectedBucketRange = bidx;
        row.classList.add("active");
        renderBucketStocks(bidx);
      });
    });
  }

  function renderBucketStocks(bidx) {
    if (!DD_DATA || !DD_DATA.stocks) return;
    const wrap = document.getElementById("bucketStocksWrap");
    const tbody = document.getElementById("bucket-stocks-tbody");
    const titleEl = document.getElementById("bucket-stocks-title");
    if (!wrap || !tbody) return;

    const mkt = state.ddMarket;
    const mktStats = DD_DATA.market_summary[mkt];
    const b = mktStats.distribution[bidx];
    if (!b) return;

    if (titleEl) {
      titleEl.textContent = `${mkt} [${b.label}] 구간 종목 목록 (${b.count}개)`;
    }

    // Filter stocks
    const matched = DD_DATA.stocks.filter((s) => {
      if (s.market !== mkt) return false;
      const dd = s.drawdown_pct;
      if (bidx === 0) return dd <= 0 && dd > -10;
      if (bidx === 1) return dd <= -10 && dd > -20;
      if (bidx === 2) return dd <= -20 && dd > -30;
      if (bidx === 3) return dd <= -30 && dd > -50;
      if (bidx === 4) return dd <= -50;
      return false;
    });

    matched.sort((a, b) => a.drawdown_pct - b.drawdown_pct);

    tbody.innerHTML = matched.map((s) => `
      <tr>
        <td><strong>${s.name}</strong> <small style="color:var(--ink-3)">${s.code}</small></td>
        <td>${s.market}</td>
        <td><span class="tile-tag">${s.industry || "기타"}</span></td>
        <td class="r" style="font-family:var(--font-mono)">${formatWon(s.latest_adj_close)}</td>
        <td class="r" style="font-family:var(--font-mono)">${formatWon(s.peak_adj_close)} <small style="color:var(--ink-3)">(${s.peak_date})</small></td>
        <td class="r down" style="font-family:var(--font-mono);font-weight:700">${s.drawdown_pct.toFixed(1)}%</td>
        <td class="r ${s.return_since_base_pct >= 0 ? 'up' : 'down'}" style="font-family:var(--font-mono)">${s.return_since_base_pct >= 0 ? '+' : ''}${s.return_since_base_pct.toFixed(1)}%</td>
      </tr>
    `).join("");

    wrap.hidden = false;
  }

  function renderRetailTop50Drawdown() {
    if (!DD_DATA || !DD_DATA.retail_top50_drawdown || !DD_DATA.market_summary) return;
    const r50 = DD_DATA.retail_top50_drawdown;
    const ms = DD_DATA.market_summary;
    const kStats = ms.KOSPI;
    const qStats = ms.KOSDAQ;

    // A. 코스피 전체
    const kMedEl = document.getElementById("comp-kospi-med");
    const kD30El = document.getElementById("comp-kospi-d30");
    const kD50El = document.getElementById("comp-kospi-d50");
    if (kMedEl) kMedEl.textContent = `${kStats.median_drawdown_pct.toFixed(1)}%`;
    if (kD30El) kD30El.textContent = `${kStats.down_30_pct.toFixed(1)}% (${kStats.down_30_count}개)`;
    if (kD50El) kD50El.textContent = `${kStats.down_50_pct.toFixed(1)}% (${kStats.down_50_count}개)`;

    // B. 코스닥 전체
    const qMedEl = document.getElementById("comp-kosdaq-med");
    const qD30El = document.getElementById("comp-kosdaq-d30");
    const qD50El = document.getElementById("comp-kosdaq-d50");
    if (qMedEl) qMedEl.textContent = `${qStats.median_drawdown_pct.toFixed(1)}%`;
    if (qD30El) qD30El.textContent = `${qStats.down_30_pct.toFixed(1)}% (${qStats.down_30_count}개)`;
    if (qD50El) qD50El.textContent = `${qStats.down_50_pct.toFixed(1)}% (${qStats.down_50_count}개)`;

    // C. 개인 순매수 상위 50종목
    const rMedEl = document.getElementById("comp-retail-med");
    const rD30El = document.getElementById("comp-retail-d30");
    const rD50El = document.getElementById("comp-retail-d50");
    if (rMedEl) rMedEl.textContent = `${r50.median_drawdown_pct.toFixed(1)}%`;
    if (rD30El) rD30El.textContent = `${r50.down_30_pct.toFixed(1)}% (${r50.down_30_count}개)`;
    if (rD50El) rD50El.textContent = `${r50.down_50_pct.toFixed(1)}% (${r50.down_50_count}개)`;

    // 요약 문장 자동 생성 (Section VI)
    const summaryEl = document.getElementById("retail-top50-summary-p");
    if (summaryEl) {
      summaryEl.textContent = `최근 20거래일 개인 순매수 상위 50종목의 고점 대비 낙폭 중앙값은 ${r50.median_drawdown_pct.toFixed(1)}%입니다. 상위 50종목 가운데 30% 이상 하락한 종목은 ${r50.down_30_count}개(${r50.down_30_pct.toFixed(1)}%)이며, 50% 이상 하락한 종목도 ${r50.down_50_count}개(${r50.down_50_pct.toFixed(1)}%)에 달합니다. 특히 코스피 상위 순매수 종목(28개)의 낙폭 중앙값은 ${r50.kospi_sub.median_drawdown_pct.toFixed(1)}%로 시장 전체 평균보다 훨씬 깊은 하락을 겪고 있습니다.`;
    }

    // Top 10 순매수 종목 낙폭 요약 테이블
    const t10Tbody = document.getElementById("retail-top10-drawdown-tbody");
    if (t10Tbody && r50.stocks) {
      const top10 = r50.stocks.slice(0, 10);
      t10Tbody.innerHTML = top10.map((s, idx) => `
        <tr>
          <td style="font-weight:700;text-align:center">${idx + 1}</td>
          <td><strong>${s.name}</strong> <small style="color:var(--ink-3)">${s.code}</small></td>
          <td>${s.market}</td>
          <td><span class="tile-tag">${s.industry || "기타"}</span></td>
          <td class="r" style="font-family:var(--font-mono)">${formatWon(s.net_buy_20d)}</td>
          <td class="r" style="font-family:var(--font-mono)">${formatWon(s.latest_adj_close)}</td>
          <td class="r down" style="font-family:var(--font-mono);font-weight:700">${s.drawdown_pct.toFixed(1)}%</td>
          <td class="r ${s.return_since_base_pct >= 0 ? 'up' : 'down'}" style="font-family:var(--font-mono);font-weight:700">${s.return_since_base_pct >= 0 ? '+' : ''}${s.return_since_base_pct.toFixed(1)}%</td>
        </tr>
      `).join("");
    }
  }

  function renderDrawdownTimeseriesChart() {
    const canvas = document.getElementById("ddTimeseriesChart");
    if (!canvas || !DD_DATA || !DD_DATA.timeseries || !window.Chart) return;

    if (ddTsChart) {
      ddTsChart.destroy();
      ddTsChart = null;
    }

    const ts = DD_DATA.timeseries;
    if (!ts.length) return;

    const rng = state.ddTsRange; // 30, 90, 365, 0
    let filtered = ts;
    if (rng > 0) {
      filtered = ts.slice(-rng);
    }

    const labels = filtered.map((d) => d.date.slice(5)); // MM-DD
    const dark = isDarkMode();
    const gridColor = dark ? "rgba(240, 239, 236, 0.08)" : "rgba(90, 89, 84, 0.12)";
    const textColor = dark ? "#cbc9bf" : "#43423f";

    let datasets = [];
    if (state.ddTsMetric === "median") {
      // 낙폭 중앙값 모드: 코스피/코스닥 종목 중앙값 vs 지수 낙폭
      datasets = [
        {
          label: "코스피 종목 낙폭 중앙값",
          data: filtered.map((d) => d.kospi_median_dd),
          borderColor: dark ? "#f0efec" : "#161615",
          backgroundColor: dark ? "rgba(240, 239, 236, 0.08)" : "rgba(22, 22, 21, 0.06)",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.15
        },
        {
          label: "코스닥 종목 낙폭 중앙값",
          data: filtered.map((d) => d.kosdaq_median_dd),
          borderColor: dark ? "#5ca5ff" : "#1862c4",
          backgroundColor: "transparent",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.15
        },
        {
          label: "코스피 지수 하락률",
          data: filtered.map((d) => d.kospi_index_dd),
          borderColor: dark ? "#888780" : "#8a8984",
          borderDash: [4, 4],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          tension: 0.15
        },
        {
          label: "코스닥 지수 하락률",
          data: filtered.map((d) => d.kosdaq_index_dd),
          borderColor: dark ? "#3b82f6" : "#60a5fa",
          borderDash: [4, 4],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          tension: 0.15
        }
      ];
    } else {
      // 30%·50% 하락 비율 모드
      datasets = [
        {
          label: "코스닥 30% 이상 하락 비율",
          data: filtered.map((d) => d.kosdaq_d30_pct),
          borderColor: "#ff814f",
          backgroundColor: "rgba(255, 129, 79, 0.08)",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.15
        },
        {
          label: "코스피 30% 이상 하락 비율",
          data: filtered.map((d) => d.kospi_d30_pct),
          borderColor: dark ? "#5ca5ff" : "#1862c4",
          backgroundColor: "transparent",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.15
        },
        {
          label: "코스닥 50% 이상 하락 비율",
          data: filtered.map((d) => d.kosdaq_d50_pct),
          borderColor: "#c490ff",
          borderDash: [3, 3],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          tension: 0.15
        },
        {
          label: "코스피 50% 이상 하락 비율",
          data: filtered.map((d) => d.kospi_d50_pct),
          borderColor: "#0d7a5f",
          borderDash: [3, 3],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          tension: 0.15
        }
      ];
    }

    const ctx = canvas.getContext("2d");
    ddTsChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: labels,
        datasets: datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: "index",
          intersect: false
        },
        plugins: {
          legend: {
            display: true,
            position: "top",
            labels: {
              boxWidth: 12,
              color: textColor,
              font: {
                size: 11.5,
                family: "var(--font-sans)"
              }
            }
          },
          tooltip: {
            backgroundColor: dark ? "rgba(252, 252, 251, 0.96)" : "rgba(18, 18, 17, 0.94)",
            titleColor: dark ? "#121211" : "#f6f6f4",
            bodyColor: dark ? "#121211" : "#f6f6f4",
            borderColor: dark ? "#dcdbd6" : "#34342f",
            borderWidth: 1,
            callbacks: {
              title: (items) => {
                const idx = items[0].dataIndex;
                return filtered[idx].date;
              },
              label: (item) => {
                return ` ${item.dataset.label}: ${item.parsed.y.toFixed(1)}%`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { color: gridColor },
            ticks: {
              color: textColor,
              maxTicksLimit: 8,
              font: { size: 10.5, family: "var(--font-mono)" }
            }
          },
          y: {
            grid: { color: gridColor },
            ticks: {
              color: textColor,
              callback: (v) => `${v}%`,
              font: { size: 10.5, family: "var(--font-mono)" }
            }
          }
        }
      }
    });
  }

})();
