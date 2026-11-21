(function () {
  "use strict";

  let DATA = window.GAEMI_DATA || null;
  let mainChart = null;
  let detailChart = null;
  let invChart = null;

  const state = {
    activeTab: "sec-01",
    period: "ALL", // ALL | 1Y | 6M | 3M | YTD
    showAbs: false,
    showKqEw: false,
    showMatched: false,
    showTotal: false,
    sec2Market: "ALL",
    sec2Search: "",
    selectedStock: "417200",
    divergentMode: "IND_BUY", // IND_BUY | OTH_BUY
    selectedQuarter: null,
  };

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

    // 숨겨져 있던 캔버스가 표시될 때 Chart.js 리사이즈 및 재렌더링
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

  function isDarkMode() {
    const curr = document.documentElement.getAttribute("data-theme");
    return (
      curr === "dark" ||
      (!curr && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
    );
  }

  function getChartColors() {
    const dark = isDarkMode();
    return {
      dark,
      kospi: dark ? "#f5c542" : "#1f7a4c", // 다크모드: 선명한 골드(#f5c542), 라이트모드: 선명한 에메랄드 그린(#1f7a4c)
      priceLine: dark ? "#e8e6df" : "#222220",
      text: dark ? "#c3c2b7" : "#52514e",
      grid: dark ? "rgba(255, 255, 255, 0.10)" : "rgba(140, 140, 135, 0.18)",
      rebLine: dark ? "rgba(210, 208, 200, 0.35)" : "rgba(122, 121, 116, 0.35)",
      rebText: dark ? "#b5b4ac" : "#7a7974",
    };
  }

  function clsSign(v) {
    const num = Number(v);
    if (num > 0) return "up";
    if (num < 0) return "down";
    return "";
  }

  // PHASE 6: 3가지 짧은 데이터 팩트 배너
  function renderFactsBar() {
    const facts = DATA.summary.key_facts || [];
    const el = document.getElementById("facts-bar");
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

  // 기간 필터링 및 기간 시작일=1,000 재정규화 계산
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
    const dailyPct = ((cur / prev - 1) * 100);
    const dailyPt = cur - prev;
    const cumPct = ((cur / 1000.0 - 1) * 100);

    // 일별 수익률 시계열
    const rets = [];
    for (let i = 1; i < reindexed.length; i++) {
      rets.push(reindexed[i] / reindexed[i - 1] - 1);
    }

    // MDD
    let peak = reindexed[0];
    let mdd = 0;
    for (let i = 0; i < reindexed.length; i++) {
      if (reindexed[i] > peak) peak = reindexed[i];
      const dd = (reindexed[i] / peak - 1) * 100;
      if (dd < mdd) mdd = dd;
    }

    // 연율 변동성
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

  // SECTION 01 렌더링 (상단 타일 + 비교 차트 + 접기 상세표)
  function renderSection01() {
    const rows = getPeriodRows();
    if (!rows.length) return;
    const startDt = rows[0].date;
    const endDt = rows[rows.length - 1].date;

    document.getElementById("header-asof").textContent = `기준일: ${endDt}`;
    document.getElementById("period-label-pure").textContent = `${startDt} = 1,000`;
    document.getElementById("chart-reindexed-note").textContent =
      `* 선택한 기간 시작일(${startDt})을 1,000.00으로 정규화한 가격지수(배당 미포함) 추이입니다 (${startDt} ~ ${endDt}).`;

    const stPure = calcPeriodStats(rows, "GAEMI_50_PURE");
    const stKospi = calcPeriodStats(rows, "KOSPI_norm");
    const stKosdaq = calcPeriodStats(rows, "KOSDAQ_norm");
    const stAbs = calcPeriodStats(rows, "GAEMI_50_ABS");
    const stKqEw = calcPeriodStats(rows, "KOSDAQ_EW");
    const stMatched = calcPeriodStats(rows, "MATCHED_50_EW");
    const stTotal = calcPeriodStats(rows, "GAEMI_50_TOTAL");

    // 1) 상단 3개 타일 업데이트
    document.getElementById("val-pure").textContent = fmtNum(stPure.current, 2);
    const chgPureEl = document.getElementById("chg-pure");
    const sgn = stPure.dailyPt > 0 ? "▲ +" : stPure.dailyPt < 0 ? "▼ " : "";
    chgPureEl.textContent = `전일비 ${sgn}${fmtNum(stPure.dailyPt, 2)} (${fmtPct(stPure.dailyPct)})`;
    chgPureEl.className = `tile-chg ${clsSign(stPure.dailyPct)}`;

    const cumPureEl = document.getElementById("cum-pure");
    cumPureEl.textContent = fmtPct(stPure.cumPct);
    cumPureEl.className = clsSign(stPure.cumPct);

    document.getElementById("raw-kospi").textContent = `실제 ${fmtNum(DATA.summary.metrics.KOSPI_raw, 2)}`;
    document.getElementById("val-kospi").textContent = fmtNum(stKospi.current, 2);
    const cumKospiEl = document.getElementById("cum-kospi");
    cumKospiEl.textContent = `기간 ${fmtPct(stKospi.cumPct)}`;
    cumKospiEl.className = `tile-chg ${clsSign(stKospi.cumPct)}`;

    const gapKospi = stPure.cumPct - stKospi.cumPct;
    const gapKospiEl = document.getElementById("gap-kospi");
    gapKospiEl.textContent = `${gapKospi > 0 ? "+" : ""}${gapKospi.toFixed(2)}%p`;
    gapKospiEl.className = clsSign(gapKospi);

    document.getElementById("raw-kosdaq").textContent = `실제 ${fmtNum(DATA.summary.metrics.KOSDAQ_raw, 2)}`;
    document.getElementById("val-kosdaq").textContent = fmtNum(stKosdaq.current, 2);
    const cumKosdaqEl = document.getElementById("cum-kosdaq");
    cumKosdaqEl.textContent = `기간 ${fmtPct(stKosdaq.cumPct)}`;
    cumKosdaqEl.className = `tile-chg ${clsSign(stKosdaq.cumPct)}`;

    const gapKosdaq = stPure.cumPct - stKosdaq.cumPct;
    const gapKosdaqEl = document.getElementById("gap-kosdaq");
    gapKosdaqEl.textContent = `${gapKosdaq > 0 ? "+" : ""}${gapKosdaq.toFixed(2)}%p`;
    gapKosdaqEl.className = clsSign(gapKosdaq);

    // 2) 차트 데이터셋 구성 (기본 3개 + 선택 활성화)
    const palette = getChartColors();
    const datasets = [
      {
        label: "GAEMI 50 PURE (개미 지수)",
        data: stPure.reindexed,
        borderColor: "#eb6834",
        backgroundColor: "rgba(235, 104, 52, 0.08)",
        borderWidth: 2.6,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.1,
      },
      {
        label: "코스피 (1,000 환산)",
        data: stKospi.reindexed,
        borderColor: palette.kospi,
        backgroundColor: "transparent",
        borderWidth: 2.2,
        pointRadius: 0,
        pointHoverRadius: 3,
        tension: 0.1,
      },
      {
        label: "코스닥 (1,000 환산)",
        data: stKosdaq.reindexed,
        borderColor: "#3b82f6",
        backgroundColor: "transparent",
        borderWidth: 2.0,
        pointRadius: 0,
        pointHoverRadius: 3,
        tension: 0.1,
      },
    ];

    if (state.showAbs) {
      datasets.push({
        label: "기존 절대금액 GAEMI 50",
        data: stAbs.reindexed,
        borderColor: "#9ca3af",
        backgroundColor: "transparent",
        borderWidth: 1.7,
        borderDash: [4, 3],
        pointRadius: 0,
        tension: 0.1,
      });
    }
    if (state.showKqEw) {
      datasets.push({
        label: "코스닥 동일가중 비교지수",
        data: stKqEw.reindexed,
        borderColor: "#10b981",
        backgroundColor: "transparent",
        borderWidth: 1.7,
        borderDash: [3, 2],
        pointRadius: 0,
        tension: 0.1,
      });
    }
    if (state.showMatched) {
      datasets.push({
        label: "시총·업종 유사 50종목 비교 포트폴리오",
        data: stMatched.reindexed,
        borderColor: "#a855f7",
        backgroundColor: "transparent",
        borderWidth: 1.7,
        borderDash: [5, 2],
        pointRadius: 0,
        tension: 0.1,
      });
    }
    if (state.showTotal) {
      datasets.push({
        label: "GAEMI 50 PURE (KRX+NXT 통합)",
        data: stTotal.reindexed,
        borderColor: "#f97316",
        backgroundColor: "transparent",
        borderWidth: 1.6,
        borderDash: [2, 2],
        pointRadius: 0,
        tension: 0.1,
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
        ctx.save();
        rebMarkers.forEach((m) => {
          const x = scales.x.getPixelForValue(m.index);
          if (x >= chartArea.left && x <= chartArea.right) {
            ctx.beginPath();
            ctx.setLineDash([3, 3]);
            ctx.strokeStyle = palette.rebLine;
            ctx.moveTo(x, chartArea.top);
            ctx.lineTo(x, chartArea.bottom);
            ctx.stroke();
            ctx.fillStyle = palette.rebText;
            ctx.font = "600 10px 'JetBrains Mono', monospace";
            ctx.fillText(m.label, x + 3, chartArea.top + 11);
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
              color: palette.text,
              boxWidth: 14,
              boxHeight: 3,
              font: { size: 12, weight: "600" },
            },
          },
          tooltip: {
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
            ticks: { color: palette.text, maxTicksLimit: 8, font: { family: "JetBrains Mono", size: 11 } },
          },
          y: {
            grid: { color: palette.grid },
            ticks: { color: palette.text, font: { family: "JetBrains Mono", size: 11 } },
          },
        },
      },
      plugins: [rebPlugin],
    });

    // 3) 접기 상세 성과 테이블 렌더링
    const tableConfigs = [
      { name: "개미 지수 (GAEMI 50 PURE)", st: stPure },
      { name: "코스피 (1,000 환산)", st: stKospi },
      { name: "코스닥 (1,000 환산)", st: stKosdaq },
      { name: "코스닥 동일가중 비교지수", st: stKqEw },
      { name: "시총·업종 유사 50종목 비교 포트폴리오", st: stMatched },
      { name: "기존 절대금액 GAEMI 50", st: stAbs },
      { name: "GAEMI 50 PURE (KRX+NXT 통합)", st: stTotal },
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

  // SECTION 02: 개미는 무엇을 샀나
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
          <td class="r"><strong class="up">${Number(r.intensity_pct).toFixed(2)}%</strong></td>
          <td class="r ${retCls}">${fmtPct(r.since_entry_return_pct)}</td>
        </tr>`;
      })
      .join("");

    tbody.querySelectorAll("tr").forEach((tr) => {
      tr.addEventListener("click", () => {
        const c = tr.getAttribute("data-code");
        if (c) {
          state.selectedStock = c;
          document.getElementById("dt-stock-select").value = c;
          renderSection02();
          renderStockDetailPanel();
        }
      });
    });

    // 업종별 구성 및 시가총액 구간별 구성
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
    const t = DATA.stock_trajectories[state.selectedStock];
    if (!t) return;

    document.getElementById("dt-code-mkt").textContent = `${t.code} · ${t.market} · ${t.size_bucket}`;
    document.getElementById("dt-title").textContent = t.name;

    const pRank = t.pure_rank ? `강도 순위 #${t.pure_rank}위` : "적격 50위 밖";
    document.getElementById("dt-intensity").textContent = `${Number(t.intensity_pct).toFixed(2)}%`;
    document.getElementById("dt-rank-sub").textContent = `${pRank} · 절대금액 #${t.abs_rank}위 · 시총 #${t.marcap_rank}위`;

    document.getElementById("dt-netbuy").textContent = fmtEok(t.net_buy_36m_eok);
    document.getElementById("dt-marcap").textContent = `평균 ${fmtEok(t.avg_marcap_36m_eok)}`;
    document.getElementById("dt-marcap-sub").textContent = `기준일 시총: ${fmtEok(t.end_marcap_eok)} (시장 비중 ${t.market_weight_pct}%)`;

    document.getElementById("dt-chg").textContent = t.rank_change_str || "-";
    document.getElementById("dt-industry").textContent = t.industry || "-";

    const retEl = document.getElementById("dt-ret");
    if (t.since_entry_return_pct !== null && t.since_entry_return_pct !== undefined) {
      retEl.textContent = fmtPct(t.since_entry_return_pct);
      retEl.className = `v ${clsSign(t.since_entry_return_pct)}`;
      document.getElementById("dt-entry-sub").textContent = `최초 편입: ${t.entry_quarter} (${t.entry_date}) · 총 ${t.included_quarters.length}개 분기 편입`;
    } else {
      retEl.textContent = "미편입";
      retEl.className = "v";
      document.getElementById("dt-entry-sub").textContent = t.eligibility_note || "편입 이력 없음";
    }

    document.getElementById("dt-others").textContent =
      `외인 ${fmtPct(t.frg_intensity_pct)} / 기관 ${fmtPct(t.org_intensity_pct)}`;
    document.getElementById("dt-others-sub").textContent =
      `외인 ${fmtEok(t.frg_net_buy_36m_eok)} · 기관 ${fmtEok(t.org_net_buy_36m_eok)}`;

    const palette = getChartColors();
    const ctx = document.getElementById("detailChart").getContext("2d");
    if (detailChart) detailChart.destroy();
    detailChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: t.dates,
        datasets: [
          {
            label: "개인 누적 추정 순매수대금 (억 원)",
            data: t.cum_net_buy_eok,
            borderColor: "#eb6834",
            backgroundColor: "rgba(235, 104, 52, 0.14)",
            fill: true,
            borderWidth: 2,
            pointRadius: 0,
            yAxisID: "yNet",
            tension: 0.15,
          },
          {
            label: "주가 (원)",
            data: t.prices,
            borderColor: palette.priceLine,
            backgroundColor: "transparent",
            borderWidth: 2.0,
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
        plugins: { legend: { display: false } },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: palette.text, maxTicksLimit: 6, font: { family: "JetBrains Mono", size: 10 } },
          },
          yNet: {
            position: "left",
            grid: { color: palette.grid },
            ticks: {
              font: { family: "JetBrains Mono", size: 10 },
              color: "#eb6834",
              callback: (v) => `${fmtInt(v)}억`,
            },
          },
          yPrc: {
            position: "right",
            grid: { drawOnChartArea: false },
            ticks: {
              color: palette.priceLine,
              font: { family: "JetBrains Mono", size: 10 },
              callback: (v) => `${fmtInt(v)}원`,
            },
          },
        },
      },
    });
  }

  // SECTION 03: 개미는 시장과 얼마나 다른가
  function renderSection03() {
    const md = DATA.market_diff;
    const as = md.active_share;

    document.getElementById("as-mc50-txt").textContent = `${as.marcap_top50_ew_vs_market_pct.toFixed(1)}%`;
    document.getElementById("as-pure-txt").textContent = `${as.gaemi_pure_vs_market_pct.toFixed(1)}%`;
    document.getElementById("as-excess-txt").textContent = `+${as.pure_excess_active_share_over_marcap50_ew_pct.toFixed(1)}%p`;

    const asItems = [
      {
        label: "개미 지수 (GAEMI 50 PURE · 50종목 동일가중)",
        val: as.gaemi_pure_vs_market_pct,
        cls: "",
      },
      {
        label: "시가총액·업종 유사 50종목 비교 포트폴리오 (동일가중)",
        val: as.matched_size_sector_50_ew_vs_market_pct,
        cls: "blue",
      },
      {
        label: "기존 절대금액 GAEMI 50 (50종목 동일가중)",
        val: as.gaemi_abs_vs_market_pct,
        cls: "muted",
      },
      {
        label: "시장 시가총액 상위 50 동일가중 (순수 동일가중 구조 효과)",
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

    // C. 코스닥 유사성 비교
    const kqSim = md.kosdaq_similarity;
    document.getElementById("kq-sim-summary").textContent =
      `판별 결과: ${kqSim.diagnosis_category}`;
    document.getElementById("kq-sim-detail").textContent = kqSim.diagnosis_detail;

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

    // B-1. 시가총액 규모별 비중 차이
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

    // B-2. 업종별 비중 차이
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

    // 개미 지수에만 높은 비중으로 포함된 종목
    document.getElementById("sec3-overweight-tbody").innerHTML = md.overweight_in_gaemi_top15
      .map(
        (r) => `<tr class="clickable" data-code="${r.code}">
        <td class="r">#${r.rank}</td>
        <td><strong>${r.name}</strong><span class="code-sub">${r.code}</span></td>
        <td class="r up">${r.intensity_pct.toFixed(2)}%</td>
        <td class="r"><strong>2.00%</strong></td>
        <td class="r">${r.market_weight_pct.toFixed(3)}%</td>
      </tr>`
      )
      .join("");

    // 시장 대형주 중 개미 지수에 없는 종목
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

  // SECTION 04: 누가 무엇을 샀나
  function renderSection04() {
    const ic = DATA.investor_comp;
    const ov = ic.overlaps;

    document.getElementById("ov-ind-frg").textContent = `${ov.ind_vs_frg_count}종목 (${ov.ind_vs_frg_pct}%)`;
    document.getElementById("ov-ind-frg-names").textContent = ov.ind_vs_frg_stocks.length
      ? `공통 종목: ${ov.ind_vs_frg_stocks.join(", ")}`
      : "공통 종목 없음";

    document.getElementById("ov-ind-org").textContent = `${ov.ind_vs_org_count}종목 (${ov.ind_vs_org_pct}%)`;
    document.getElementById("ov-ind-org-names").textContent = ov.ind_vs_org_stocks.length
      ? `공통 종목: ${ov.ind_vs_org_stocks.join(", ")}`
      : "50개 중 겹치는 종목이 1개도 없습니다.";

    document.getElementById("ov-frg-org").textContent = `${ov.frg_vs_org_count}종목 (${ov.frg_vs_org_pct}%)`;
    document.getElementById("ov-frg-org-names").textContent = ov.frg_vs_org_stocks.length
      ? `공통 종목: ${ov.frg_vs_org_stocks.join(", ")}`
      : "공통 종목 없음";

    // 주체별 상위 50 테이블
    function fillInvTable(tbodyId, list, intCol, valCol) {
      document.getElementById(tbodyId).innerHTML = list
        .map(
          (r) => `<tr class="clickable" data-code="${r.code}">
          <td class="r"><strong>${r.rank}</strong></td>
          <td><strong>${r.name}</strong><span class="code-sub">${r.market}</span></td>
          <td class="r up"><strong>${Number(r[intCol]).toFixed(2)}%</strong></td>
          <td class="r">${fmtEok(r[valCol])}</td>
        </tr>`
        )
        .join("");
    }

    fillInvTable("inv-ind-tbody", ic.top50_by_investor.individual, "intensity_pct", "net_buy_eok");
    fillInvTable("inv-frg-tbody", ic.top50_by_investor.foreign, "frg_intensity_pct", "frg_net_buy_eok");
    fillInvTable("inv-org-tbody", ic.top50_by_investor.institution, "org_intensity_pct", "org_net_buy_eok");

    renderDivergentTable();

    // 업종별 차이
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

    // ⑤ 투자 주체별 가상 지수 차트
    const palette = getChartColors();
    const ts = DATA.timeseries || [];
    const ctx = document.getElementById("investorIndexChart").getContext("2d");
    if (invChart) invChart.destroy();
    invChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: ts.map((r) => r.date),
        datasets: [
          {
            label: `개인 순매수 강도 상위 50 (${fmtPct(DATA.summary.metrics.GAEMI_50_PURE.total_return_pct)})`,
            data: ts.map((r) => r.GAEMI_50_PURE),
            borderColor: "#eb6834",
            borderWidth: 2.4,
            pointRadius: 0,
            tension: 0.1,
          },
          {
            label: `외국인 순매수 강도 상위 50 (${fmtPct(DATA.summary.metrics.FOREIGN_50_PURE.total_return_pct)})`,
            data: ts.map((r) => r.FOREIGN_50_PURE),
            borderColor: "#3b82f6",
            borderWidth: 2.1,
            pointRadius: 0,
            tension: 0.1,
          },
          {
            label: `기관(연기금 포함) 순매수 강도 상위 50 (${fmtPct(DATA.summary.metrics.INSTITUTION_50_PURE.total_return_pct)})`,
            data: ts.map((r) => r.INSTITUTION_50_PURE),
            borderColor: "#10b981",
            borderWidth: 2.1,
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
            labels: { color: palette.text, boxWidth: 14, boxHeight: 3 },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: palette.text, maxTicksLimit: 8, font: { family: "JetBrains Mono", size: 11 } },
          },
          y: {
            grid: { color: palette.grid },
            ticks: { color: palette.text, font: { family: "JetBrains Mono", size: 11 } },
          },
        },
      },
    });
  }

  function renderDivergentTable() {
    const db = DATA.investor_comp.divergent_bets;
    const list = state.divergentMode === "IND_BUY" ? db.ind_buy_others_sell : db.others_buy_ind_sell;
    document.getElementById("divergent-tbody").innerHTML = list
      .map(
        (r) => `<tr class="clickable" data-code="${r.code}">
        <td><strong>${r.name}</strong><span class="code-sub">${r.code}</span></td>
        <td class="r ${clsSign(r.intensity_pct)}"><strong>${fmtPct(r.intensity_pct)}</strong> <span class="code-sub">(${fmtEok(r.net_buy_eok)})</span></td>
        <td class="r ${clsSign(r.frg_intensity_pct)}">${fmtPct(r.frg_intensity_pct)} <span class="code-sub">(${fmtEok(r.frg_net_buy_eok)})</span></td>
        <td class="r ${clsSign(r.org_intensity_pct)}">${fmtPct(r.org_intensity_pct)} <span class="code-sub">(${fmtEok(r.org_net_buy_eok)})</span></td>
      </tr>`
      )
      .join("");
  }

  // SECTION 05: 개미의 선택은 바뀌었나
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

    document.getElementById("q-inout-title").textContent = `${qObj.rebalance_id} 정기 리밸런싱 편입 · 퇴출 종목`;
    document.getElementById("q-inout-meta").textContent =
      `36개월 집계 구간: ${qObj.window_36m_start} ~ ${qObj.determination_date} · 리밸런싱 적용일: ${qObj.effective_start}`;
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
          <td class="r up">${r.intensity_pct.toFixed(2)}%</td>
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
        <td class="r up"><strong>${Number(r.intensity_pct).toFixed(2)}%</strong></td>
        <td class="r">${fmtEok(r.net_buy_eok)}</td>
      </tr>`
      )
      .join("");
  }

  // FOOTER 접기 영역 렌더링
  function renderFooterDetails() {
    const p0 = DATA.phase0_audit || {};
    const a1 = p0.audit_0_1_net_buy_estimation || {};
    const a2 = p0.audit_0_2_36m_completeness || {};
    const a3 = p0.audit_0_3_krx_vs_nxt || {};
    const a4 = p0.audit_0_4_historical_marcap_and_recalculation || {};
    const rec = a4.recalculation_constituent_change_2026Q4 || {};

    document.getElementById("audit-detail-box").innerHTML = `
      <ul style="padding-left:18px;margin:0">
        <li><strong>0-1. 순매수대금 산출 및 오차 검증:</strong> ${a1.method || "-"} (${a1.validation_against_execution_amount || "-"})</li>
        <li><strong>0-2. 36개월 원자료 완전성 보강:</strong> 기존 200일만 수집되었던 시가총액 후보군 ${a2.expanded_stock_count || 669}개 종목의 2021.09~2026.11 전체 기간 원자료를 추가 수집하여 총 <strong>${fmtInt(a2.total_daily_records || 2392334)}건</strong>(36개월 완전 관측 확보 <strong>${fmtInt(a2.stocks_with_full_36m_data || 1771)}개 종목</strong>) 원장으로 재산출했습니다.</li>
        <li><strong>0-3. KRX 전용 vs KRX+NXT 통합 비교:</strong> KRX 통계에 NXT(2025.03.04 출범) 거래는 포함되지 않으며 중복은 0건입니다. 2026 Q4 기준 KRX 전용 상위 50개와 KRX+NXT 통합 상위 50개는 <strong>${a3.krx_vs_combined_top50_overlap_2026Q4 || "47/50 (94%)"}</strong> 일치하며, 누적 수익률은 KRX 전용 <strong>${fmtPct(a3.krx_pure_total_return_pct)}</strong>(${a3.krx_pure_final_index}pt) vs KRX+NXT 통합 <strong>${fmtPct(a3.combined_pure_total_return_pct)}</strong>(${a3.combined_pure_final_index}pt)입니다.</li>
        <li><strong>0-4. 과거 시가총액 공식 스냅샷 보정 및 재산출 전후 변화:</strong> ${a4.anchor_method || "-"} 보정 결과, 2026 Q4 구성 종목은 보정 전과 <strong>${rec.overlap_with_pre_audit_count || 49}/50개 일치</strong>(신규 진입: ${(rec.newly_entered_after_audit || []).join(", ") || "없음"} / 제외: ${(rec.removed_after_audit || []).join(", ") || "없음"})하며, 과거 분기 중형주 완전 반영으로 2024.09.30 이후 지수는 <strong>757.28pt(-24.27%)</strong>로 산출되었습니다.</li>
      </ul>
    `;

    // 민감도 분석 테이블
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

    // 기존 절대금액 상위 50 vs PURE 비교
    const absList = DATA.gaemi50_abs_constituents || [];
    const pureSet = new Set((DATA.gaemi50_pure_constituents || []).map((r) => r.code));
    document.getElementById("abs-vs-pure-tbody").innerHTML = absList
      .map((r) => {
        const inP = pureSet.has(r.code);
        const pStr = inP
          ? `<strong class="up">PURE 편입 (#${r.pure_rank_eligible}위)</strong>`
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
    // 상단 카테고리 탭 전환 (해당 카테고리만 화면에 표시)
    document.querySelectorAll('#tabs button[role="tab"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetTab = btn.getAttribute("data-tab");
        activateTab(targetTab, true);
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
    document.getElementById("chk-matched").addEventListener("change", (e) => {
      state.showMatched = e.target.checked;
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

    // Section 04 반대편에 선 종목 버튼
    document.querySelectorAll("#divergent-btns button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#divergent-btns button").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        state.divergentMode = btn.getAttribute("data-div");
        renderDivergentTable();
      });
    });

    // Section 05 분기 선택
    document.getElementById("q-select").addEventListener("change", (e) => {
      state.selectedQuarter = e.target.value;
      renderSection05();
    });

    // 테마 전환 버튼
    document.getElementById("themeBtn").addEventListener("click", () => {
      const root = document.documentElement;
      root.setAttribute("data-theme", isDarkMode() ? "light" : "dark");
      renderSection01();
      renderStockDetailPanel();
      renderSection04();
    });

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

    // 전체 테이블 행 클릭 시 종목 상세로 연결 (다른 탭에서 클릭 시 02 탭으로 자동 전환)
    document.body.addEventListener("click", (e) => {
      const tr = e.target.closest("tr.clickable");
      if (!tr) return;
      const code = tr.getAttribute("data-code");
      if (code && DATA.stock_trajectories[code]) {
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

  function boot() {
    initDetailSelect();
    initQuarterSelect();
    renderFactsBar();
    renderSection01();
    renderSection02();
    renderStockDetailPanel();
    renderSection03();
    renderSection04();
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
      fetch("data/gaemi_data.json")
        .then((r) => r.json())
        .then((d) => {
          DATA = d;
          boot();
        });
    }
  });
})();
