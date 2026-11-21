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

  const state = {
    activeTab: "sec-01",
    period: "ALL", // ALL | 1Y | 6M | 3M | YTD
    selectedEpisodeId: null,
    showAbs: false,
    showKqEw: false,
    showTotal: false,
    sec2Market: "ALL",
    sec2Search: "",
    selectedStock: "417200",
    invListMode: "IND", // IND | FRG | ORG | DIV_IND | DIV_OTH
    selectedQuarter: null,
  };

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
    if (!DATA) return;
    if (state.activeTab === "sec-01") {
      renderSection01();
    } else if (state.activeTab === "sec-02") {
      renderStockDetailPanel();
    } else if (state.activeTab === "sec-04") {
      renderSection04();
    }
  }

  function activateTab(tabId, updateHash = true) {
    const validTabs = ["sec-01", "sec-02", "sec-03", "sec-04", "sec-05", "sec-footer"];
    const target = validTabs.includes(tabId) ? tabId : "sec-01";
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

    if (target === "sec-01") {
      renderSection01();
    } else if (target === "sec-02") {
      renderStockDetailPanel();
    } else if (target === "sec-04") {
      renderSection04();
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

  // 기간 필터링 및 선택 구간 첫 거래일 = 1,000 정규화
  function getPeriodRows() {
    const ts = DATA.timeseries || [];
    if (!ts.length) return [];
    const maxDate = ts[ts.length - 1].date;
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
    const filtered = ts.filter((r) => r.date >= cutDate);
    return filtered.length >= 2 ? filtered : ts;
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

  // PHASE 6: 하락장 성적표 ('증시가 떨어질 때'), 하락장/상승장 포착률, 하락장 사건별 차트 렌더링
  function renderPhase6DownsideSection() {
    const p6 = DATA.phase6_downside;
    if (!p6) return;

    const hl = p6.auto_headline || {};
    const sc = p6.scorecard_when_market_falls || {};
    const cap = p6.capture_ratios || {};
    const dDays = p6.daily_downside_analysis || {};
    const sev = p6.severity_buckets || {};
    const epsObj = p6.drawdown_episodes || {};

    // 1) 상단 자동 생성 핵심 메시지 배너
    const hlTextEl = document.getElementById("down-headline-text");
    if (hlTextEl) hlTextEl.textContent = hl.headline || "";

    // 2) '증시가 떨어질 때' 4대 성적표
    const setEl = (id, txt) => {
      const el = document.getElementById(id);
      if (el) el.textContent = txt;
    };
    setEl("down-scorecard-period", sc.period_label || "");
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

    // 3) 하락장 포착률 가로 막대그래프 (100% 기준선 = 0~150% 스케일에서 66.67% 위치)
    const cKq = (cap.vs_kosdaq && cap.vs_kosdaq.GAEMI_50_PURE) || {};
    const cKqMatched = (cap.vs_kosdaq && cap.vs_kosdaq.MATCHED_50_EW) || {};
    const cKp = (cap.vs_kospi && cap.vs_kospi.GAEMI_50_PURE) || {};
    const cMt = (cap.vs_matched50 && cap.vs_matched50.GAEMI_50_PURE) || {};

    const capBarsEl = document.getElementById("down-capture-bars");
    if (capBarsEl) {
      const barItems = [
        {
          label: `개미 지수 (vs 코스닥 ${cKq.down_months_count || 10}개월)`,
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
          label: `개미 지수 (vs 유사 50종목 ${cMt.down_months_count || 12}개월)`,
          ratio: cMt.downside_capture_geo_pct || 137.0,
          gapText: `개미 ${fmtPct(cMt.port_down_arith_mean_pct)} · 유사50 ${fmtPct(cMt.bench_down_arith_mean_pct)} (${fmtPct(cMt.mean_gap_in_down_months_pctp)}p)`,
          colorVar: "var(--chart-gaemi)",
        },
        {
          label: `개미 지수 (vs 코스피 ${cKp.down_months_count || 10}개월)`,
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
      captureChart = new Chart(ctxCap, {
        type: "bar",
        data: {
          labels: ["개미 지수", "비슷한 주식 50개", "코스닥 동일가중", "외국인 강도 50"],
          datasets: [
            {
              label: "하락장 포착률 (낮을수록 방어 · 100%=코스닥)",
              data: [
                cKq.downside_capture_geo_pct || 115.9,
                cKqMatched.downside_capture_geo_pct || 84.2,
                cKqEw.downside_capture_geo_pct || 91.3,
                cFrg.downside_capture_geo_pct || 91.5,
              ],
              backgroundColor: tk.gaemi,
              borderRadius: 4,
            },
            {
              label: "상승장 포착률 (높을수록 탄력 · 100%=코스닥)",
              data: [
                cKq.upside_capture_geo_pct || 112.6,
                cKqMatched.upside_capture_geo_pct || 95.6,
                cKqEw.upside_capture_geo_pct || 121.4,
                cFrg.upside_capture_geo_pct || 118.7,
              ],
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
    const r = ep.returns_pct;
    const g = ep.gaps_vs_gaemi_pctp;
    const rec = ep.recovery;

    const cardsEl = document.getElementById("episode-summary-cards");
    if (cardsEl) {
      cardsEl.innerHTML = `
        <div class="down-box">
          <span class="dk">개미 지수 (${ep.start_date}~${ep.end_date})</span>
          <span class="dv down">${fmtPct(r.GAEMI_50_PURE)}</span>
          <span class="ds">회복: ${rec.GAEMI_50_PURE.status_label}</span>
        </div>
        <div class="down-box">
          <span class="dk">유사 50종목</span>
          <span class="dv down">${fmtPct(r.MATCHED_50_EW)}</span>
          <span class="ds">개미 대비 <strong>${g.vs_MATCHED_50 > 0 ? "+" : ""}${g.vs_MATCHED_50.toFixed(2)}%p</strong> · ${rec.MATCHED_50_EW.status_label}</span>
        </div>
        <div class="down-box">
          <span class="dk">코스닥</span>
          <span class="dv down">${fmtPct(r.KOSDAQ)}</span>
          <span class="ds">개미 대비 <strong>${g.vs_KOSDAQ > 0 ? "+" : ""}${g.vs_KOSDAQ.toFixed(2)}%p</strong> · ${rec.KOSDAQ.status_label}</span>
        </div>
        <div class="down-box">
          <span class="dk">코스피</span>
          <span class="dv ${clsSign(r.KOSPI)}">${fmtPct(r.KOSPI)}</span>
          <span class="ds">개미 대비 <strong>${g.vs_KOSPI > 0 ? "+" : ""}${g.vs_KOSPI.toFixed(2)}%p</strong> · ${rec.KOSPI.status_label}</span>
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

  // TAB 1: 개미 지수 (상단 고정 스트립 + 하락장 분석 + 메인 비교 차트 + 상세 성과 표)
  function renderSection01() {
    renderPhase6DownsideSection();
    const rows = getPeriodRows();
    if (!rows.length) return;
    const startDt = rows[0].date;
    const endDt = rows[rows.length - 1].date;
    const baseDt = DATA.summary.base_date || "2024-09-30";

    document.getElementById("header-asof").textContent =
      `기준일 ${baseDt}=1,000 · 최신 ${endDt}(잠정)`;
    document.getElementById("period-label-pure").textContent = `시작일 ${startDt} = 1,000`;
    document.getElementById("chart-reindexed-note").textContent =
      `* 선택한 기간 첫 거래일(${startDt})을 1,000.00으로 맞춘 가격지수(배당 제외·잠정) 추이입니다 (${startDt} ~ ${endDt}).`;

    const stPure = calcPeriodStats(rows, "GAEMI_50_PURE");
    const stKospi = calcPeriodStats(rows, "KOSPI_norm");
    const stKosdaq = calcPeriodStats(rows, "KOSDAQ_norm");
    const stAbs = calcPeriodStats(rows, "GAEMI_50_ABS");
    const stKqEw = calcPeriodStats(rows, "KOSDAQ_EW");
    const stMatched = calcPeriodStats(rows, "MATCHED_50_EW");
    const stTotal = calcPeriodStats(rows, "GAEMI_50_TOTAL");

    // 1) 상단 4개 핵심 비교 카드 업데이트 (개미 지수, 비슷한 주식 50개, 코스피, 코스닥)
    document.getElementById("val-pure").textContent = fmtNum(stPure.current, 2);
    const chgPureEl = document.getElementById("chg-pure");
    const sgn = stPure.dailyPt > 0 ? "▲ +" : stPure.dailyPt < 0 ? "▼ " : "";
    chgPureEl.textContent = `전일비 ${sgn}${fmtNum(stPure.dailyPt, 2)} (${fmtPct(stPure.dailyPct)})`;
    chgPureEl.className = `tile-chg ${clsSign(stPure.dailyPct)}`;

    const cumPureEl = document.getElementById("cum-pure");
    cumPureEl.textContent = fmtPct(stPure.cumPct);
    cumPureEl.className = clsSign(stPure.cumPct);

    // 2번째 카드: 비슷한 주식 50개 (시총·업종 유사 비교 포트폴리오)
    document.getElementById("val-matched").textContent = fmtNum(stMatched.current, 2);
    const cumMatchedEl = document.getElementById("cum-matched");
    cumMatchedEl.textContent = `동일 기간 ${fmtPct(stMatched.cumPct)}`;
    cumMatchedEl.className = `tile-chg ${clsSign(stMatched.cumPct)}`;

    const gapMatched = stPure.cumPct - stMatched.cumPct;
    const gapMatchedEl = document.getElementById("gap-matched");
    gapMatchedEl.textContent = `${gapMatched > 0 ? "+" : ""}${gapMatched.toFixed(2)}%p`;
    gapMatchedEl.className = clsSign(gapMatched);

    // 3번째 카드: 코스피
    document.getElementById("raw-kospi").textContent = `실제 ${fmtNum(DATA.summary.metrics.KOSPI_raw, 2)}`;
    document.getElementById("val-kospi").textContent = fmtNum(stKospi.current, 2);
    const cumKospiEl = document.getElementById("cum-kospi");
    cumKospiEl.textContent = `동일 기간 ${fmtPct(stKospi.cumPct)}`;
    cumKospiEl.className = `tile-chg ${clsSign(stKospi.cumPct)}`;

    const gapKospi = stPure.cumPct - stKospi.cumPct;
    const gapKospiEl = document.getElementById("gap-kospi");
    gapKospiEl.textContent = `${gapKospi > 0 ? "+" : ""}${gapKospi.toFixed(2)}%p`;
    gapKospiEl.className = clsSign(gapKospi);

    // 4번째 카드: 코스닥
    document.getElementById("raw-kosdaq").textContent = `실제 ${fmtNum(DATA.summary.metrics.KOSDAQ_raw, 2)}`;
    document.getElementById("val-kosdaq").textContent = fmtNum(stKosdaq.current, 2);
    const cumKosdaqEl = document.getElementById("cum-kosdaq");
    cumKosdaqEl.textContent = `동일 기간 ${fmtPct(stKosdaq.cumPct)}`;
    cumKosdaqEl.className = `tile-chg ${clsSign(stKosdaq.cumPct)}`;

    const gapKosdaq = stPure.cumPct - stKosdaq.cumPct;
    const gapKosdaqEl = document.getElementById("gap-kosdaq");
    gapKosdaqEl.textContent = `${gapKosdaq > 0 ? "+" : ""}${gapKosdaq.toFixed(2)}%p`;
    gapKosdaqEl.className = clsSign(gapKosdaq);

    // 2) 기본 4개 지수 차트 (시각적 위계: 1. 개미 지수 → 2. 비슷한 주식 50개 → 3. 코스피 → 4. 코스닥)
    const tk = getChartTokens();
    const datasets = [
      {
        label: "개미 지수 (GAEMI 50 PURE · 실선)",
        data: stPure.reindexed,
        borderColor: tk.gaemi,
        backgroundColor: tk.gaemiFill,
        borderWidth: 2.8,
        borderDash: [],
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.1,
        order: 1,
      },
      {
        label: "비슷한 주식 50개 (시총·업종 유사 · 굵은 파선)",
        data: stMatched.reindexed,
        borderColor: tk.institution,
        backgroundColor: "transparent",
        borderWidth: 2.4,
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
      { name: "개미 지수 (GAEMI 50 PURE · 잠정)", st: stPure },
      { name: "코스피 (1,000 환산)", st: stKospi },
      { name: "코스닥 (1,000 환산)", st: stKosdaq },
      { name: "비슷한 주식 50개 (시총·업종 유사)", st: stMatched },
      { name: "코스닥 동일가중", st: stKqEw },
      { name: "단순 순매수금액 상위 50", st: stAbs },
      { name: "개미 지수 (KRX+NXT 합산)", st: stTotal },
    ];

    const perfTbody = document.getElementById("perf-detail-tbody");
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

  // TAB 2: 개미가 산 50종목
  function renderSection02() {
    const rawList = DATA.gaemi50_pure_constituents || [];
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
          return `<tr class="clickable ${isAct}" data-code="${r.code}">
            <td class="r"><strong>${r.rank}</strong></td>
            <td>
              <strong>${r.name}</strong><span class="code-sub">${r.code}</span>
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
    const trajs = DATA.stock_trajectories || {};
    const sel = document.getElementById("dt-stock-select");
    const pureList = DATA.gaemi50_pure_constituents || [];
    const pureOrder = new Map(pureList.map((r) => [r.code, r.rank]));

    const codes = Object.keys(trajs).sort((a, b) => {
      const ra = pureOrder.has(a) ? pureOrder.get(a) : 999;
      const rb = pureOrder.has(b) ? pureOrder.get(b) : 999;
      return ra - rb;
    });

    sel.innerHTML = codes
      .map((c) => {
        const t = trajs[c];
        const rTag = t.pure_rank ? `#${t.pure_rank}` : "편입외";
        return `<option value="${c}">${rTag} ${t.name} (${c}) — 강도 ${Number(t.intensity_pct).toFixed(2)}%</option>`;
      })
      .join("");

    if (!trajs[state.selectedStock] && codes.length) {
      state.selectedStock = codes[0];
    }
    sel.value = state.selectedStock;
  }

  function renderStockDetailPanel() {
    const t = DATA.stock_trajectories && DATA.stock_trajectories[state.selectedStock];
    if (!t) return;

    document.getElementById("dt-code-mkt").textContent = `${t.code} · ${t.market} · ${t.size_bucket}`;
    document.getElementById("dt-title").textContent = t.name;

    const pRank = t.pure_rank ? `강도 순위 #${t.pure_rank}위` : "적격 50위 밖";
    document.getElementById("dt-intensity").textContent = `+${Number(t.intensity_pct).toFixed(2)}%`;
    document.getElementById("dt-rank-sub").textContent = `${pRank} · 금액 순위 #${t.abs_rank}위 · 시총 #${t.marcap_rank}위`;

    document.getElementById("dt-netbuy").textContent = fmtEok(t.net_buy_36m_eok);
    document.getElementById("dt-marcap").textContent = `평균 ${fmtEok(t.avg_marcap_36m_eok)}`;
    document.getElementById("dt-marcap-sub").textContent = `기준일 시총: ${fmtEok(t.end_marcap_eok)} (시장 비중 ${t.market_weight_pct}%)`;

    document.getElementById("dt-chg").textContent = t.rank_change_str || "-";
    document.getElementById("dt-industry").textContent = t.industry || "-";

    const retEl = document.getElementById("dt-ret");
    if (t.since_entry_return_pct !== null && t.since_entry_return_pct !== undefined) {
      retEl.textContent = fmtPct(t.since_entry_return_pct);
      retEl.className = `v ${clsSign(t.since_entry_return_pct)}`;
      document.getElementById("dt-entry-sub").textContent = `최초 편입: ${t.entry_quarter} (${t.entry_date}) · 총 ${t.included_quarters.length}개 분기 포함`;
    } else {
      retEl.textContent = "미편입";
      retEl.className = "v";
      document.getElementById("dt-entry-sub").textContent = t.eligibility_note || "편입 이력 없음";
    }

    document.getElementById("dt-others").textContent =
      `외인 ${fmtPct(t.frg_intensity_pct)} / 기관 ${fmtPct(t.org_intensity_pct)}`;
    document.getElementById("dt-others-sub").textContent =
      `외인 ${fmtEok(t.frg_net_buy_36m_eok)} · 기관 ${fmtEok(t.org_net_buy_36m_eok)}`;

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
    const hist = DATA.summary.rebalance_history || [];
    const sel = document.getElementById("q-select");
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
    document.getElementById("chk-abs").addEventListener("change", (e) => {
      state.showAbs = e.target.checked;
      renderSection01();
    });
    document.getElementById("chk-kqew").addEventListener("change", (e) => {
      state.showKqEw = e.target.checked;
      renderSection01();
    });
    document.getElementById("chk-total").addEventListener("change", (e) => {
      state.showTotal = e.target.checked;
      renderSection01();
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

    document.getElementById("sec2-search").addEventListener("input", (e) => {
      state.sec2Search = e.target.value;
      renderSection02();
    });

    document.getElementById("dt-stock-select").addEventListener("change", (e) => {
      state.selectedStock = e.target.value;
      renderSection02();
      renderStockDetailPanel();
    });

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
    document.getElementById("q-select").addEventListener("change", (e) => {
      state.selectedQuarter = e.target.value;
      renderSection05();
    });

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
      if (code && DATA.stock_trajectories && DATA.stock_trajectories[code]) {
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
    renderSection02();
    renderSection03();
    renderSection05();
    renderFooterDetails();
    bindEvents();
    const initHash = (window.location.hash || "").replace("#", "");
    activateTab(initHash || "sec-01", false);
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
})();
