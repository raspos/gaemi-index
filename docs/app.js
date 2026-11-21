(function () {
  "use strict";

  let DATA = window.GAEMI_DATA || null;
  let mainChart = null;
  let sizeChart = null;
  let trajChart = null;

  const state = {
    chartPeriod: "ALL",
    chartMode: "INDEX", // INDEX | RETURN
    activeTab: "PURE",  // PURE | ABS
    marketFilter: "ALL",
    searchQuery: "",
    selectedQuarter: null,
    diffGroup: "NEW",   // NEW | EXC | COM
    selectedStockCode: "417200", // LS머트리얼즈 (#1 in PURE)
    trajRightAxis: "PRICE", // PRICE | MARCAP
  };

  function fmtNum(n, digits = 2) {
    if (n === null || n === undefined || isNaN(n)) return "-";
    return Number(n).toLocaleString("ko-KR", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function fmtInt(n) {
    if (n === null || n === undefined || isNaN(n)) return "-";
    return Math.round(Number(n)).toLocaleString("ko-KR");
  }

  function fmtEokFromEok(eokVal) {
    if (eokVal === null || eokVal === undefined || isNaN(eokVal)) return "-";
    const eok = Number(eokVal);
    if (Math.abs(eok) >= 10000) {
      const jo = Math.trunc(eok / 10000);
      const rem = Math.round(Math.abs(eok % 10000));
      return `${jo.toLocaleString("ko-KR")}조 ${rem.toLocaleString("ko-KR")}억`;
    }
    return `${Math.round(eok).toLocaleString("ko-KR")}억`;
  }

  function fmtSignedPct(v, digits = 2) {
    if (v === null || v === undefined || isNaN(v)) return "-";
    const num = Number(v);
    const sign = num > 0 ? "+" : "";
    return `${sign}${num.toFixed(digits)}%`;
  }

  function signClass(v) {
    const num = Number(v);
    if (num > 0) return "up";
    if (num < 0) return "down";
    return "";
  }

  // 상단 스코어보드 렌더링
  function renderScoreboard() {
    const s = DATA.summary;
    const m = s.metrics;
    const curReb = s.current_rebalance;

    document.getElementById("header-asof").textContent =
      `데이터 기준일: ${s.data_as_of} (적용 분기: ${curReb.rebalance_id} · 정기 기준일: ${curReb.determination_date})`;
    document.getElementById("spec-asof").textContent =
      `${s.data_as_of} (최신 정기 리밸런싱 기준일: ${curReb.determination_date} / 적용 시작일: ${curReb.effective_start})`;

    function fillCard(prefix, obj) {
      document.getElementById(`val-${prefix}`).textContent = fmtNum(obj.current, 2);
      const chgEl = document.getElementById(`chg-${prefix}`);
      const sign = obj.daily_change_pt > 0 ? "▲ +" : obj.daily_change_pt < 0 ? "▼ " : "";
      chgEl.textContent = `${sign}${fmtNum(obj.daily_change_pt, 2)} (${fmtSignedPct(obj.daily_change_pct)})`;
      chgEl.className = `score-change ${signClass(obj.daily_change_pct)}`;

      const cumEl = document.getElementById(`cum-${prefix}`);
      cumEl.textContent = fmtSignedPct(obj.total_return_pct);
      cumEl.className = `meta-v ${signClass(obj.total_return_pct)}`;

      const mddEl = document.getElementById(`mdd-${prefix}`);
      mddEl.textContent = `${fmtNum(obj.mdd_pct, 2)}%`;
      mddEl.className = "meta-v down";

      const volEl = document.getElementById(`vol-${prefix}`);
      if (volEl) volEl.textContent = `${fmtNum(obj.ann_volatility_pct, 2)}%`;
    }

    fillCard("pure", m.GAEMI_50_PURE);
    fillCard("kospi", m.KOSPI);
    fillCard("kosdaq", m.KOSDAQ);
    fillCard("abs", m.GAEMI_50_ABS);

    document.getElementById("corr-pure").textContent =
      `${m.GAEMI_50_PURE.corr_kospi.toFixed(2)} / ${m.GAEMI_50_PURE.corr_kosdaq.toFixed(2)}`;
    document.getElementById("corr-abs").textContent =
      `${m.GAEMI_50_ABS.corr_kospi.toFixed(2)} / ${m.GAEMI_50_ABS.corr_kosdaq.toFixed(2)}`;
    document.getElementById("common-abs").textContent =
      `${DATA.comparison.common_count}/50 (${DATA.comparison.common_pct}%)`;

    document.getElementById("raw-kospi").textContent = `실제 ${fmtNum(m.KOSPI_raw, 2)}`;
    document.getElementById("raw-kosdaq").textContent = `실제 ${fmtNum(m.KOSDAQ_raw, 2)}`;

    const gapKospi = m.GAEMI_50_PURE.total_return_pct - m.KOSPI.total_return_pct;
    const gapKospiEl = document.getElementById("gap-kospi");
    gapKospiEl.textContent = `${gapKospi > 0 ? "+" : ""}${gapKospi.toFixed(2)}%p`;
    gapKospiEl.className = `meta-v ${signClass(gapKospi)}`;

    const gapKosdaq = m.GAEMI_50_PURE.total_return_pct - m.KOSDAQ.total_return_pct;
    const gapKosdaqEl = document.getElementById("gap-kosdaq");
    gapKosdaqEl.textContent = `${gapKosdaq > 0 ? "+" : ""}${gapKosdaq.toFixed(2)}%p`;
    gapKosdaqEl.className = `meta-v ${signClass(gapKosdaq)}`;
  }

  // ① 메인 비교 차트
  function getFilteredTimeseries() {
    const ts = DATA.timeseries;
    if (!ts || !ts.length) return [];
    const maxDate = ts[ts.length - 1].date;
    const maxObj = new Date(maxDate);
    let cutDate = "2000-01-01";

    if (state.chartPeriod === "1Y") {
      const d = new Date(maxObj);
      d.setFullYear(d.getFullYear() - 1);
      cutDate = d.toISOString().slice(0, 10);
    } else if (state.chartPeriod === "6M") {
      const d = new Date(maxObj);
      d.setMonth(d.getMonth() - 6);
      cutDate = d.toISOString().slice(0, 10);
    } else if (state.chartPeriod === "3M") {
      const d = new Date(maxObj);
      d.setMonth(d.getMonth() - 3);
      cutDate = d.toISOString().slice(0, 10);
    } else if (state.chartPeriod === "YTD") {
      cutDate = `${maxDate.slice(0, 4)}-01-01`;
    }
    return ts.filter((r) => r.date >= cutDate);
  }

  function renderMainChart() {
    const rows = getFilteredTimeseries();
    if (!rows.length) return;

    const bPure = rows[0].GAEMI_50_PURE;
    const bKospi = rows[0].KOSPI_norm;
    const bKosdaq = rows[0].KOSDAQ_norm;
    const bAbs = rows[0].GAEMI_50_ABS;

    const labels = rows.map((r) => r.date);
    const isReturn = state.chartMode === "RETURN";

    const dPure = rows.map((r) =>
      isReturn ? Number(((r.GAEMI_50_PURE / bPure - 1) * 100).toFixed(2)) : r.GAEMI_50_PURE
    );
    const dKospi = rows.map((r) =>
      isReturn ? Number(((r.KOSPI_norm / bKospi - 1) * 100).toFixed(2)) : r.KOSPI_norm
    );
    const dKosdaq = rows.map((r) =>
      isReturn ? Number(((r.KOSDAQ_norm / bKosdaq - 1) * 100).toFixed(2)) : r.KOSDAQ_norm
    );
    const dAbs = rows.map((r) =>
      isReturn ? Number(((r.GAEMI_50_ABS / bAbs - 1) * 100).toFixed(2)) : r.GAEMI_50_ABS
    );

    const rebalanceIndices = [];
    rows.forEach((r, idx) => {
      if (r.is_rebalance_date && idx > 0) {
        rebalanceIndices.push({ index: idx, label: r.rebalance_id });
      }
    });

    const rebalanceLinePlugin = {
      id: "rebalanceLines",
      afterDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea) return;
        ctx.save();
        rebalanceIndices.forEach((item) => {
          const x = scales.x.getPixelForValue(item.index);
          if (x >= chartArea.left && x <= chartArea.right) {
            ctx.beginPath();
            ctx.setLineDash([3, 3]);
            ctx.strokeStyle = "rgba(20, 20, 19, 0.25)";
            ctx.lineWidth = 1;
            ctx.moveTo(x, chartArea.top);
            ctx.lineTo(x, chartArea.bottom);
            ctx.stroke();

            ctx.fillStyle = "#4a4945";
            ctx.font = "600 10px 'JetBrains Mono', monospace";
            ctx.fillText(item.label, x + 4, chartArea.top + 12);
          }
        });
        ctx.restore();
      },
    };

    const ctx = document.getElementById("mainIndexChart").getContext("2d");
    if (mainChart) mainChart.destroy();

    mainChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "GAEMI 50 PURE (순매수 강도 Top 50)",
            data: dPure,
            borderColor: "#c83e2b",
            backgroundColor: "rgba(200, 62, 43, 0.08)",
            borderWidth: 2.8,
            pointRadius: 0,
            pointHoverRadius: 4,
            tension: 0.1,
          },
          {
            label: "KOSPI (1,000 환산)",
            data: dKospi,
            borderColor: "#141413",
            backgroundColor: "transparent",
            borderWidth: 1.8,
            pointRadius: 0,
            pointHoverRadius: 3,
            tension: 0.1,
          },
          {
            label: "KOSDAQ (1,000 환산)",
            data: dKosdaq,
            borderColor: "#1d5b8c",
            backgroundColor: "transparent",
            borderWidth: 1.8,
            pointRadius: 0,
            pointHoverRadius: 3,
            tension: 0.1,
          },
          {
            label: "기존 GAEMI 50 (절대금액 Top 50)",
            data: dAbs,
            borderColor: "#8c877e",
            backgroundColor: "transparent",
            borderWidth: 1.5,
            borderDash: [4, 3],
            pointRadius: 0,
            pointHoverRadius: 3,
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
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(20, 20, 19, 0.94)",
            titleFont: { family: "JetBrains Mono", size: 12 },
            bodyFont: { family: "Pretendard", size: 12 },
            padding: 10,
            callbacks: {
              label(context) {
                const v = context.parsed.y;
                if (isReturn) return ` ${context.dataset.label}: ${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
                return ` ${context.dataset.label}: ${fmtNum(v, 2)} pt`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { maxTicksLimit: 8, font: { family: "JetBrains Mono", size: 11 }, color: "#76746e" },
          },
          y: {
            grid: { color: "#e6e3dc" },
            ticks: {
              font: { family: "JetBrains Mono", size: 11 },
              color: "#4a4945",
              callback(value) {
                return isReturn ? `${value > 0 ? "+" : ""}${value}%` : fmtInt(value);
              },
            },
          },
        },
      },
      plugins: [rebalanceLinePlugin],
    });
  }

  // ② 구성종목 테이블 렌더링 (순매수 강도 순위 vs 절대 순매수액 순위 병기)
  function renderConstituentTable() {
    const isPure = state.activeTab === "PURE";
    const rawList = isPure ? DATA.gaemi50_pure_constituents : DATA.gaemi50_abs_constituents;
    const curReb = DATA.summary.current_rebalance;
    const noteEl = document.getElementById("constituent-window-note");

    if (isPure) {
      noteEl.textContent = `공식 대표지수 GAEMI 50 PURE 현재 포트폴리오 (${curReb.rebalance_id} · 집계기간: ${curReb.window_36m_start} ~ ${curReb.determination_date} · 시총 3,000억+ · 60일 평균거래대금 10억+ · 36개월 원자료 확보)`;
    } else {
      noteEl.textContent = `내부 비교지수: 기존 순매수 절대금액 상위 50개 종목 (${curReb.rebalance_id} · 시가총액 보정 전 단순 순매수액 순위)`;
    }

    const kospiCnt = rawList.filter((r) => r.market === "KOSPI").length;
    const kosdaqCnt = rawList.filter((r) => r.market === "KOSDAQ").length;
    document.querySelectorAll("#market-filter-btns .btn-toggle").forEach((btn) => {
      const m = btn.getAttribute("data-mkt");
      if (m === "ALL") btn.textContent = `전체 (${rawList.length})`;
      if (m === "KOSPI") btn.textContent = `KOSPI (${kospiCnt})`;
      if (m === "KOSDAQ") btn.textContent = `KOSDAQ (${kosdaqCnt})`;
    });

    const q = state.searchQuery.trim().toLowerCase();
    const filtered = rawList.filter((item) => {
      if (state.marketFilter !== "ALL" && item.market !== state.marketFilter) return false;
      if (q && !item.name.toLowerCase().includes(q) && !item.code.toLowerCase().includes(q)) return false;
      return true;
    });

    const maxInt = Math.max(...rawList.map((r) => Number(r.intensity_pct) || 1), 1);
    const tbody = document.getElementById("constituent-tbody");

    tbody.innerHTML = filtered
      .map((item) => {
        const pctWidth = Math.max(2, Math.min(100, (Number(item.intensity_pct) / maxInt) * 100));
        const pureRankDisp = item.pure_rank || item.pure_rank_eligible || "-";
        const absRankDisp = `#${item.abs_rank_all}`;
        const rChg = item.rank_change_str || "-";
        const rChgCls = rChg === "NEW" ? "new" : rChg.includes("▲") ? "up" : rChg.includes("▼") ? "down" : "";
        const sinceRet = item.since_entry_return_pct !== undefined ? fmtSignedPct(item.since_entry_return_pct) : "-";
        const sinceCls = signClass(item.since_entry_return_pct);
        const curW = item.current_weight_pct !== undefined ? `${Number(item.current_weight_pct).toFixed(2)}%` : "2.00%";
        const shortSize = (item.size_bucket || "").split(" ")[0];

        return `<tr data-code="${item.code}" title="클릭하여 ${item.name} 상세 지표 및 추이 보기">
          <td class="num"><strong>#${isPure ? item.rank : pureRankDisp}</strong></td>
          <td><span class="rank-delta ${rChgCls}">${rChg}</span></td>
          <td class="num" style="color:var(--ink-secondary)">${absRankDisp}</td>
          <td><strong>${item.name}</strong><span class="stock-code">${item.code}</span></td>
          <td><span class="mkt-tag">${item.market}</span> <span style="font-size:11px;color:var(--ink-muted)">${shortSize}</span></td>
          <td class="num"><strong class="up">${Number(item.intensity_pct).toFixed(2)}%</strong></td>
          <td class="bar-cell">
            <div class="val-bar-bg">
              <div class="val-bar-fill" style="width:${pctWidth.toFixed(1)}%"></div>
            </div>
          </td>
          <td class="num"><strong>${fmtEokFromEok(item.net_buy_eok)}</strong></td>
          <td class="num" style="color:var(--ink-secondary)">${fmtEokFromEok(item.avg_marcap_36m_eok)}</td>
          <td class="num" style="color:var(--ink-muted)">${fmtEokFromEok(item.end_marcap_eok)}</td>
          <td style="font-family:var(--font-mono);font-size:11.5px">${item.entry_quarter || "-"} <span style="color:var(--ink-muted)">(${item.quarters_included_count || 1}회)</span></td>
          <td class="num ${sinceCls}"><strong>${sinceRet}</strong></td>
          <td class="num">${curW}</td>
        </tr>`;
      })
      .join("");

    tbody.querySelectorAll("tr").forEach((tr) => {
      tr.addEventListener("click", () => {
        const code = tr.getAttribute("data-code");
        if (code && DATA.stock_trajectories[code]) {
          selectStockForDetail(code, true);
        }
      });
    });
  }

  function selectStockForDetail(code, scroll = false) {
    state.selectedStockCode = code;
    const sel = document.getElementById("trajectory-stock-select");
    if (sel) sel.value = code;
    renderStockDetailSection();
    if (scroll) {
      document.getElementById("sec-stock-detail").scrollIntoView({ behavior: "smooth" });
    }
  }

  // ③ 종목별 상세 화면 (6대 필수 지표 + 이중축 추이 차트)
  function initTrajectorySelect() {
    const trajs = DATA.stock_trajectories || {};
    const sel = document.getElementById("trajectory-stock-select");

    const pureMap = new Map(DATA.gaemi50_pure_constituents.map((r) => [r.code, r.rank]));
    const absMap = new Map(DATA.gaemi50_abs_constituents.map((r) => [r.code, r.rank]));

    const codes = Object.keys(trajs).sort((a, b) => {
      const ra = pureMap.has(a) ? pureMap.get(a) : 100 + (absMap.get(a) || 99);
      const rb = pureMap.has(b) ? pureMap.get(b) : 100 + (absMap.get(b) || 99);
      return ra - rb;
    });

    sel.innerHTML = codes
      .map((c) => {
        const t = trajs[c];
        const rPure = t.pure_rank ? `강도 #${t.pure_rank}` : "강도 적격외";
        const rAbs = `절대 #${t.abs_rank}`;
        return `<option value="${c}">${t.name} (${c}) — [${rPure} · ${rAbs} · 강도 ${Number(t.intensity_pct).toFixed(2)}%]</option>`;
      })
      .join("");

    if (!trajs[state.selectedStockCode] && codes.length) {
      state.selectedStockCode = codes[0];
    }
    sel.value = state.selectedStockCode;
  }

  function renderStockDetailSection() {
    const t = DATA.stock_trajectories[state.selectedStockCode];
    if (!t) return;

    // 6대 필수 지표 카드 채우기
    document.getElementById("dt-netbuy").textContent = fmtEokFromEok(t.net_buy_36m_eok);
    document.getElementById("dt-name-sub").textContent = `${t.name} (${t.code}) · ${t.market} · ${t.industry}`;

    document.getElementById("dt-avgmc").textContent = fmtEokFromEok(t.avg_marcap_36m_eok);
    document.getElementById("dt-endmc-sub").textContent = `기준일 시총: ${fmtEokFromEok(t.end_marcap_eok)}`;

    document.getElementById("dt-intensity").textContent = `${Number(t.intensity_pct).toFixed(2)}%`;

    const pRankStr = t.pure_rank ? `강도 #${t.pure_rank}위` : "자격 미달";
    document.getElementById("dt-ranks").textContent = `${pRankStr} / 절대 #${t.abs_rank}위`;
    document.getElementById("dt-elig-sub").textContent = t.in_pure50
      ? "GAEMI 50 PURE 편입 종목"
      : `PURE 미편입 (${t.eligibility_note || "순위 50위 밖"})`;

    const rChgEl = document.getElementById("dt-rankchg");
    rChgEl.textContent = t.rank_change_str || "-";
    rChgEl.className = `v ${t.rank_change_str && t.rank_change_str.includes("▲") ? "up" : t.rank_change_str && t.rank_change_str.includes("▼") ? "down" : ""}`;
    document.getElementById("dt-prevrank-sub").textContent = t.prev_quarter_rank
      ? `전 분기(2026 Q3) 강도 순위: #${t.prev_quarter_rank}위`
      : "전 분기 PURE 50 편입 이력 없음";

    const eRetEl = document.getElementById("dt-entryret");
    if (t.since_entry_return_pct !== null && t.since_entry_return_pct !== undefined) {
      eRetEl.textContent = fmtSignedPct(t.since_entry_return_pct);
      eRetEl.className = `v ${signClass(t.since_entry_return_pct)}`;
      document.getElementById("dt-entryq-sub").textContent =
        `최초 편입: ${t.entry_quarter} (${t.entry_date}) · 누적 ${t.included_quarters.length}회 편입`;
    } else {
      eRetEl.textContent = "미편입";
      eRetEl.className = "v";
      document.getElementById("dt-entryq-sub").textContent = "2024 Q4 ~ 2026 Q4 기간 중 PURE 편입 이력 없음";
    }

    // 차트 렌더링
    const isMarcap = state.trajRightAxis === "MARCAP";
    const rightSeries = isMarcap ? t.marcap_eok : t.prices;
    const rightLabel = isMarcap ? "시가총액 (우축, 억 원)" : "수정 기준 종가 (우축, 원)";
    document.getElementById("traj-right-legend").textContent = rightLabel;
    document.getElementById("traj-stock-summary").textContent =
      `${t.name}(${t.code}) · 순매수 강도: ${Number(t.intensity_pct).toFixed(2)}% (36개월 순매수 ${fmtEokFromEok(t.net_buy_36m_eok)} / 평균시총 ${fmtEokFromEok(t.avg_marcap_36m_eok)})`;

    const ctx = document.getElementById("stockTrajectoryChart").getContext("2d");
    if (trajChart) trajChart.destroy();

    trajChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: t.dates,
        datasets: [
          {
            label: "36개월 개인 누적 순매수대금 (억 원)",
            data: t.cum_net_buy_eok,
            borderColor: "#c83e2b",
            backgroundColor: "rgba(200, 62, 43, 0.12)",
            fill: true,
            borderWidth: 2.4,
            pointRadius: 0,
            pointHoverRadius: 4,
            yAxisID: "yNet",
            tension: 0.15,
          },
          {
            label: rightLabel,
            data: rightSeries,
            borderColor: "#141413",
            backgroundColor: "transparent",
            borderWidth: 2.0,
            pointRadius: 0,
            pointHoverRadius: 4,
            yAxisID: "yRight",
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
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(20, 20, 19, 0.94)",
            callbacks: {
              label(context) {
                if (context.dataset.yAxisID === "yNet") {
                  return ` 누적 순매수: ${fmtInt(context.parsed.y)}억 원 (${fmtEokFromEok(context.parsed.y)})`;
                }
                if (isMarcap) {
                  return ` 시가총액: ${fmtEokFromEok(context.parsed.y)}`;
                }
                return ` 주가: ${fmtInt(context.parsed.y)}원`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { maxTicksLimit: 9, font: { family: "JetBrains Mono", size: 11 }, color: "#76746e" },
          },
          yNet: {
            type: "linear",
            position: "left",
            grid: { color: "#e6e3dc" },
            title: {
              display: true,
              text: "개인 누적 순매수 (억 원)",
              color: "#c83e2b",
              font: { family: "Pretendard", size: 11, weight: "700" },
            },
            ticks: {
              font: { family: "JetBrains Mono", size: 11 },
              color: "#c83e2b",
              callback: (v) => `${fmtInt(v)}억`,
            },
          },
          yRight: {
            type: "linear",
            position: "right",
            grid: { drawOnChartArea: false },
            title: {
              display: true,
              text: isMarcap ? "시가총액 (억 원)" : "주가 (원)",
              color: "#141413",
              font: { family: "Pretendard", size: 11, weight: "700" },
            },
            ticks: {
              font: { family: "JetBrains Mono", size: 11 },
              color: "#141413",
              callback: (v) => (isMarcap ? fmtEokFromEok(v) : `${fmtInt(v)}원`),
            },
          },
        },
      },
    });
  }

  // ④ 기존 지수와 8대 차이 검증 섹션 렌더링
  function renderComparisonSection() {
    const comp = DATA.comparison;

    // 1) 시가총액 규모별 비교 테이블 및 차트
    const sizeTbody = document.getElementById("size-comp-tbody");
    sizeTbody.innerHTML = comp.size_comparison
      .map((r) => {
        const sign = r.diff_count > 0 ? "+" : "";
        const cls = signClass(r.diff_count);
        return `<tr>
          <td><strong>${r.size_bucket}</strong></td>
          <td class="num"><strong>${r.pure_count}종목 (${r.pure_weight_pct}%)</strong></td>
          <td class="num" style="color:var(--ink-secondary)">${r.abs_count}종목 (${r.abs_weight_pct}%)</td>
          <td class="num ${cls}"><strong>${sign}${r.diff_count}종목 (${sign}${r.diff_weight_pct}%p)</strong></td>
        </tr>`;
      })
      .join("");

    const ctxSize = document.getElementById("sizeComparisonChart").getContext("2d");
    if (sizeChart) sizeChart.destroy();
    sizeChart = new Chart(ctxSize, {
      type: "bar",
      data: {
        labels: comp.size_comparison.map((r) => r.size_bucket.replace(" (", "\n(")),
        datasets: [
          {
            label: "GAEMI 50 PURE 비중 (%)",
            data: comp.size_comparison.map((r) => r.pure_weight_pct),
            backgroundColor: "#c83e2b",
          },
          {
            label: "기존 절대금액 Top 50 비중 (%)",
            data: comp.size_comparison.map((r) => r.abs_weight_pct),
            backgroundColor: "#8c877e",
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
            labels: { font: { family: "Pretendard", size: 11 }, boxWidth: 12 },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { family: "Pretendard", size: 11 } } },
          y: {
            max: 70,
            grid: { color: "#e6e3dc" },
            ticks: { font: { family: "JetBrains Mono", size: 11 }, callback: (v) => `${v}%` },
          },
        },
      },
    });

    // 2) 업종별 구성 변화 테이블
    const indTbody = document.getElementById("industry-comp-tbody");
    indTbody.innerHTML = comp.industry_comparison
      .filter((r) => r.pure_count > 0 || r.abs_count > 0)
      .map((r) => {
        const sign = r.diff_count > 0 ? "+" : "";
        const cls = signClass(r.diff_count);
        return `<tr>
          <td>${r.industry}</td>
          <td class="num"><strong>${r.pure_count} (${r.pure_weight_pct}%)</strong></td>
          <td class="num" style="color:var(--ink-secondary)">${r.abs_count} (${r.abs_weight_pct}%)</td>
          <td class="num ${cls}">${sign}${r.diff_count} (${sign}${r.diff_weight_pct}%p)</td>
        </tr>`;
      })
      .join("");

    // 3) 삼성전자·SK하이닉스 분기별 강도 순위 추이 테이블
    const gHistTbody = document.getElementById("giants-history-tbody");
    gHistTbody.innerHTML = comp.giants_focus.quarterly_history
      .slice()
      .reverse()
      .map((q) => {
        const s = q.samsung;
        const h = q.hynix;
        const sTag = s.selected_in_pure50
          ? `<strong class="up">편입 (#${s.pure_rank})</strong>`
          : `<span class="down">미선정 (#${s.pure_rank})</span>`;
        const hTag = h.selected_in_pure50
          ? `<strong class="up">편입 (#${h.pure_rank})</strong>`
          : `<span class="down">미선정 (#${h.pure_rank})</span>`;
        return `<tr>
          <td style="font-family:var(--font-mono)"><strong>${q.rebalance_id}</strong></td>
          <td class="num">${s.intensity_pct.toFixed(2)}% · ${sTag} <span style="color:var(--ink-muted)">(절대 #${s.abs_rank})</span></td>
          <td class="num">${h.intensity_pct.toFixed(2)}% · ${hTag} <span style="color:var(--ink-muted)">(절대 #${h.abs_rank})</span></td>
        </tr>`;
      })
      .join("");

    // 삼성전자·SK하이닉스 카드 클릭 시 상세 화면 연동
    document.getElementById("card-samsung").style.cursor = "pointer";
    document.getElementById("card-samsung").onclick = () => selectStockForDetail("005930", true);
    document.getElementById("card-hynix").style.cursor = "pointer";
    document.getElementById("card-hynix").onclick = () => selectStockForDetail("000660", true);

    renderDiffGroupTable();
  }

  function renderDiffGroupTable() {
    const comp = DATA.comparison;
    const descEl = document.getElementById("diff-group-desc");
    const tbody = document.getElementById("diff-group-tbody");
    let rows = [];

    if (state.diffGroup === "NEW") {
      descEl.textContent = `순매수 절대금액 기준으로는 51위~287위였으나, 평균 시가총액 대비 순매수 강도(9.5%~34.8%)가 높아 GAEMI 50 PURE에 새롭게 편입된 ${comp.newly_included_count}개 종목입니다.`;
      rows = comp.newly_included_stocks.map((r) => ({
        rankStr: `PURE #${r.rank}`,
        code: r.code,
        name: r.name,
        market: r.market,
        intensity: `${r.intensity_pct.toFixed(2)}%`,
        netBuy: fmtEokFromEok(r.net_buy_eok),
        avgMc: fmtEokFromEok(r.avg_marcap_36m_eok),
        note: `절대순위 #${r.abs_rank_all}위 → 강도 #${r.rank}위 진입`,
      }));
    } else if (state.diffGroup === "EXC") {
      descEl.textContent = `기존 절대금액 Top 50에 포함되었으나, 시가총액 대비 순매수 강도가 낮거나(삼성전자·LG화학·현대모비스 등) 36개월 관측기간·시총 요건 미달로 제외된 ${comp.excluded_count}개 종목입니다.`;
      rows = comp.excluded_from_abs_stocks.map((r) => ({
        rankStr: `절대 #${r.rank}`,
        code: r.code,
        name: r.name,
        market: r.market,
        intensity: `${r.intensity_pct.toFixed(2)}%`,
        netBuy: fmtEokFromEok(r.net_buy_eok),
        avgMc: fmtEokFromEok(r.avg_marcap_36m_eok),
        note:
          r.eligibility_note === "적격"
            ? `강도 순위 #${r.pure_rank_eligible}위 (50위권 밖 탈락)`
            : r.eligibility_note,
      }));
    } else {
      descEl.textContent = `절대 순매수금액 상위 50위와 순매수 강도 상위 50위에 모두 포함된 공통 핵심 종목 ${comp.common_count}개(${comp.common_pct}%)입니다.`;
      rows = comp.common_stocks.map((r) => ({
        rankStr: `PURE #${r.rank}`,
        code: r.code,
        name: r.name,
        market: r.market,
        intensity: `${r.intensity_pct.toFixed(2)}%`,
        netBuy: fmtEokFromEok(r.net_buy_eok),
        avgMc: fmtEokFromEok(r.avg_marcap_36m_eok),
        note: `절대금액 #${r.abs_rank_all}위 · 양쪽 모두 편입`,
      }));
    }

    tbody.innerHTML = rows
      .map(
        (r) => `<tr data-code="${r.code}">
        <td class="num"><strong>${r.rankStr}</strong></td>
        <td><strong>${r.name}</strong><span class="stock-code">${r.code}</span> <span class="mkt-tag">${r.market}</span></td>
        <td class="num"><strong class="up">${r.intensity}</strong></td>
        <td class="num">${r.netBuy}</td>
        <td class="num" style="color:var(--ink-secondary)">${r.avgMc}</td>
        <td style="font-size:11.5px;color:var(--ink-secondary)">${r.note}</td>
      </tr>`
      )
      .join("");

    tbody.querySelectorAll("tr").forEach((tr) => {
      tr.addEventListener("click", () => {
        const c = tr.getAttribute("data-code");
        if (c && DATA.stock_trajectories[c]) {
          selectStockForDetail(c, true);
        }
      });
    });
  }

  // 분기별 PURE 신규 편입·퇴출 렌더링
  function initQuarterSelect() {
    const hist = DATA.summary.rebalance_history;
    const sel = document.getElementById("quarter-select");
    sel.innerHTML = hist
      .slice()
      .reverse()
      .map(
        (q) =>
          `<option value="${q.rebalance_id}">${q.rebalance_id} (기준일: ${q.determination_date})</option>`
      )
      .join("");
    state.selectedQuarter = hist[hist.length - 1].rebalance_id;
    sel.value = state.selectedQuarter;
  }

  function renderQuarterlyInOut() {
    const hist = DATA.summary.rebalance_history;
    const qObj = hist.find((h) => h.rebalance_id === state.selectedQuarter) || hist[hist.length - 1];
    const added = qObj.pure_added || [];
    const removed = qObj.pure_removed || [];

    document.getElementById("inout-meta").textContent =
      `집계기간: ${qObj.window_36m_start} ~ ${qObj.determination_date} | 적용일: ${qObj.effective_start} | Top 50 평균 순매수 강도: ${qObj.pure_avg_intensity_pct}%`;
    document.getElementById("added-count-title").textContent = `PURE 신규 편입 (${added.length}종목)`;
    document.getElementById("removed-count-title").textContent = `PURE 퇴출 (${removed.length}종목)`;

    const addedListEl = document.getElementById("added-list");
    const removedListEl = document.getElementById("removed-list");

    if (qObj.rebalance_id === hist[0].rebalance_id) {
      addedListEl.innerHTML = `<li><span style="color:var(--ink-muted)">최초 기준 분기 (50종목 초기 구성)</span></li>`;
      removedListEl.innerHTML = `<li><span style="color:var(--ink-muted)">최초 기준 분기 (퇴출 없음)</span></li>`;
    } else {
      addedListEl.innerHTML = added.length
        ? added
            .sort((a, b) => a.rank - b.rank)
            .map(
              (item) =>
                `<li><span><strong>${item.name}</strong> <span class="stock-code">${item.code}</span></span><span style="font-family:var(--font-mono);font-size:11.5px;color:var(--up)">#${item.rank} (강도 ${Number(item.intensity_pct).toFixed(1)}%)</span></li>`
            )
            .join("")
        : `<li><span style="color:var(--ink-muted)">변동 없음</span></li>`;

      removedListEl.innerHTML = removed.length
        ? removed
            .map((item) => {
              const rNote = item.new_pure_rank ? `강도 #${item.new_pure_rank}위` : item.reason;
              return `<li><span>${item.name} <span class="stock-code">${item.code}</span></span><span style="font-family:var(--font-mono);font-size:11px;color:var(--down)">${rNote}</span></li>`;
            })
            .join("")
        : `<li><span style="color:var(--ink-muted)">변동 없음</span></li>`;
    }
  }

  // ⑤ 민감도 분석 테이블 렌더링
  function renderSensitivityTable() {
    const sens = DATA.sensitivity || [];
    const tbody = document.getElementById("sensitivity-tbody");
    tbody.innerHTML = sens
      .map((s) => {
        const bg = s.is_baseline ? "style='background:#efeae1;font-weight:700'" : "";
        const retCls = signClass(s.total_return_pct);
        return `<tr ${bg}>
          <td>${s.is_baseline ? "★ " : ""}${s.scenario}</td>
          <td class="num">${s.eligible_pool_count}종목</td>
          <td class="num">${s.top50_avg_intensity_pct.toFixed(2)}%</td>
          <td class="num">${fmtEokFromEok(s.top50_median_marcap_eok)}</td>
          <td class="num">${s.overlap_with_baseline_count}/50 (${s.overlap_with_baseline_pct}%)</td>
          <td class="num">${fmtNum(s.final_index, 2)}</td>
          <td class="num ${retCls}">${fmtSignedPct(s.total_return_pct)}</td>
          <td class="num down">${s.mdd_pct.toFixed(2)}%</td>
          <td class="num">${s.ann_volatility_pct.toFixed(2)}%</td>
          <td class="num">${s.corr_kospi.toFixed(3)}</td>
          <td class="num">${s.corr_kosdaq.toFixed(3)}</td>
        </tr>`;
      })
      .join("");
  }

  function bindEvents() {
    document.querySelectorAll("#chart-period-btns .btn-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#chart-period-btns .btn-toggle").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.chartPeriod = btn.getAttribute("data-period");
        renderMainChart();
      });
    });

    document.querySelectorAll("#chart-mode-btns .btn-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#chart-mode-btns .btn-toggle").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.chartMode = btn.getAttribute("data-mode");
        renderMainChart();
      });
    });

    document.querySelectorAll("#constituent-tab-btns .btn-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#constituent-tab-btns .btn-toggle").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.activeTab = btn.getAttribute("data-tab");
        renderConstituentTable();
      });
    });

    document.querySelectorAll("#market-filter-btns .btn-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#market-filter-btns .btn-toggle").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.marketFilter = btn.getAttribute("data-mkt");
        renderConstituentTable();
      });
    });

    document.getElementById("stock-search").addEventListener("input", (e) => {
      state.searchQuery = e.target.value;
      renderConstituentTable();
    });

    document.getElementById("trajectory-stock-select").addEventListener("change", (e) => {
      state.selectedStockCode = e.target.value;
      renderStockDetailSection();
    });

    document.querySelectorAll("#traj-right-axis-btns .btn-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#traj-right-axis-btns .btn-toggle").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.trajRightAxis = btn.getAttribute("data-axis");
        renderStockDetailSection();
      });
    });

    document.querySelectorAll("#diff-group-btns .btn-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#diff-group-btns .btn-toggle").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.diffGroup = btn.getAttribute("data-diff");
        renderDiffGroupTable();
      });
    });

    document.getElementById("quarter-select").addEventListener("change", (e) => {
      state.selectedQuarter = e.target.value;
      renderQuarterlyInOut();
    });
  }

  function init() {
    if (!DATA) {
      fetch("data/gaemi_data.json")
        .then((r) => r.json())
        .then((d) => {
          DATA = d;
          boot();
        });
    } else {
      boot();
    }
  }

  function boot() {
    initQuarterSelect();
    initTrajectorySelect();
    bindEvents();
    renderScoreboard();
    renderMainChart();
    renderConstituentTable();
    renderStockDetailSection();
    renderComparisonSection();
    renderQuarterlyInOut();
    renderSensitivityTable();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
