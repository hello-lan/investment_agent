(function () {
  var searchInput = document.getElementById("stockSearch");
  var searchBtn = document.getElementById("searchBtn");
  var searchDropdown = document.getElementById("searchDropdown");
  var syncBadge = document.getElementById("syncBadge");
  var dashMain = document.getElementById("dashMain");
  var dashContent = document.getElementById("dashContent");
  var dashEmpty = document.getElementById("dashEmpty");
  var sideNav = document.getElementById("sideNav");

  var currentCode = null;
  var charts = [];
  var searchTimer = null;
  var pollTimer = null;
  var dropdownIndex = -1;

  var C = {
    text: "#8b9cb3", axis: "#2d3a4f", blue: "#3b82f6", green: "#10b981",
    warn: "#f59e0b", purple: "#a78bfa", red: "#ef4444", cyan: "#22d3ee",
  };

  var EIGHT_QUESTIONS = [
    { q: "靠什么赚钱？", note: "商业模式、核心驱动力（产品/市场/资本）" },
    { q: "顺风还是逆风？", note: "政策、宏观、行业周期" },
    { q: "空间有多大？", note: "渗透率、TAM、国内/海外" },
    { q: "竞争格局好不好？", note: "集中度、价格战风险、新进入者" },
    { q: "有什么优势？", note: "成本/技术/品牌/渠道护城河" },
    { q: "管理层行不行？", note: "治理、战略执行、传承" },
    { q: "风险在哪里？", note: "技术颠覆、增速放缓、会计风险" },
    { q: "未来会怎样？", note: "综合预判 + 两分钟独白" },
  ];

  // ── 搜索 ──

  searchInput.addEventListener("input", function () {
    dropdownIndex = -1;
    var q = searchInput.value.trim();
    if (!q) { searchDropdown.classList.remove("show"); return; }
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { doSearch(q); }, 300);
  });

  searchInput.addEventListener("keydown", function (e) {
    var items = searchDropdown.querySelectorAll(".dash-search-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      dropdownIndex = Math.min(dropdownIndex + 1, items.length - 1);
      updateDropdownActive(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      dropdownIndex = Math.max(dropdownIndex - 1, -1);
      updateDropdownActive(items);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (dropdownIndex >= 0 && items.length) items[dropdownIndex].click();
      else doQuery();
    } else if (e.key === "Escape") {
      searchDropdown.classList.remove("show");
    }
  });

  searchBtn.addEventListener("click", doQuery);
  document.addEventListener("click", function (e) {
    if (!searchDropdown.contains(e.target) && e.target !== searchInput) {
      searchDropdown.classList.remove("show");
    }
  });

  function updateDropdownActive(items) {
    items.forEach(function (item, i) {
      item.classList.toggle("active", i === dropdownIndex);
    });
  }

  function doSearch(q) {
    fetch("/api/stocks/search?q=" + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var results = data.results || [];
        searchDropdown.innerHTML = "";
        if (!results.length) {
          searchDropdown.innerHTML = '<div class="dash-search-item" style="color:var(--muted)">未找到匹配股票</div>';
        } else {
          results.forEach(function (s) {
            var div = document.createElement("div");
            div.className = "dash-search-item";
            div.innerHTML = '<span>' + esc(s.name) + '</span><span><span class="code">' + esc(s.code) + '</span>' +
              (s.industry ? '<span class="industry">' + esc(s.industry) + '</span>' : '') + '</span>';
            div.addEventListener("click", function () {
              searchInput.value = s.code;
              searchDropdown.classList.remove("show");
              doQuery();
            });
            searchDropdown.appendChild(div);
          });
        }
        searchDropdown.classList.add("show");
      });
  }

  function doQuery() {
    var q = searchInput.value.trim();
    if (!q) return;
    searchDropdown.classList.remove("show");
    currentCode = q;
    loadDashboard(q);
  }

  function loadDashboard(code) {
    dashEmpty.style.display = "none";
    dashMain.style.display = "flex";
    dashContent.innerHTML = '<div class="dash-loading">加载中...</div>';
    setSyncBadge("");
    fetchDashboard(code);
  }

  function fetchDashboard(code) {
    fetch("/api/stock-dashboard/" + code)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.status === "syncing") {
          setSyncBadge("syncing", "数据同步中...");
          dashContent.innerHTML = '<div class="dash-loading">首次加载，正在获取数据...</div>';
          startPolling(code);
        } else if (data.status === "updating" || data.status === "ready") {
          setSyncBadge(data.status === "updating" ? "syncing" : "ready",
            data.status === "updating" ? "数据更新中..." : "数据已就绪");
          renderAll(data);
          if (data.status === "updating") startPolling(code);
          else stopPolling();
        }
      })
      .catch(function (err) {
        dashContent.innerHTML = '<div class="dash-loading" style="color:var(--danger)">加载失败: ' + esc(String(err)) + '</div>';
        setSyncBadge("error", "加载失败");
      });
  }

  function startPolling(code) {
    stopPolling();
    pollTimer = setInterval(function () {
      fetch("/api/stock-dashboard/" + code + "/status")
        .then(function (r) { return r.json(); })
        .then(function (status) {
          if (status.status === "ready") {
            setSyncBadge("ready", "数据已就绪");
            stopPolling();
            fetchDashboard(code);
          } else if (status.status === "error") {
            setSyncBadge("error", "同步失败");
            stopPolling();
          }
        });
    }, 2000);
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function setSyncBadge(cls, text) {
    syncBadge.style.display = text ? "inline-block" : "none";
    syncBadge.textContent = text || "";
    syncBadge.className = "dash-sync-badge " + (cls || "");
  }

  // ── 渲染 ──

  function renderAll(data) {
    disposeCharts();
    var s = data.sections || {};
    var stock = data.stock || {};
    var snap = s.snapshot || {};

    var html = '';
    html += '<div class="dash-page-title"><h1>企业分析看板</h1>' +
      '<p class="subtitle">七步法看报表 + 商业八问</p></div>';
    html += renderSnapshot(stock, snap);
    html += renderStep1(s.step1);
    html += renderStep2(s.step2);
    html += renderStep3(s.step3);
    html += renderStep4(s.step4);
    html += renderStep5(s.step5);
    html += renderStep6(s.step6);
    html += renderStep7(s.step7);
    html += renderEight();

    dashContent.innerHTML = html;
    setTimeout(function () { initCharts(s); }, 80);
    bindNav();
  }

  function renderSnapshot(stock, snap) {
    var name = stock.name || currentCode || "-";
    var meta = [stock.industry, snap.report_date ? "数据截至 " + snap.report_date : ""].filter(Boolean).join(" · ");
    return '<section id="snapshot" class="snapshot-bar">' +
      '<div class="stock-name">' + esc(name) + ' ' + esc(stock.code || "") + '</div>' +
      '<div class="stock-meta">' + esc(meta || "—") + '</div>' +
      '<div class="kpi-row">' +
      kpi("营业收入", fmtYi(snap.revenue)) +
      kpi("归母净利润", fmtYi(snap.net_profit)) +
      kpi("净利率", fmtPct(snap.net_margin)) +
      kpi("毛利率", fmtPct(snap.gross_margin)) +
      kpi("ROE", fmtPct(snap.roe), snap.roe > 20 ? "good" : "") +
      kpi("经营现金流/净利润", snap.cfnp != null ? fmtNum(snap.cfnp, 2) : "—") +
      kpi("自由现金流", snap.fcf != null ? (snap.fcf_positive ? "正向" : fmtYi(snap.fcf)) : "—",
        snap.fcf_positive ? "good" : "") +
      '</div></section>';
  }

  function kpi(label, value, cls) {
    return '<div class="kpi"><div class="label">' + esc(label) + '</div>' +
      '<div class="value' + (cls ? " " + cls : "") + '">' + esc(value) + '</div></div>';
  }

  function renderStep1(d) {
    if (!d) return section("step1", "① 营收与盈利质量", "七步法 · 第一步 · 多年度趋势", '<div class="dash-loading">暂无数据</div>');
    var years = d.years || [];
    var b = d.basic || {};
    var q = d.quality || {};

    var basicRows = [
      ["营业收入", b.revenue, "yi"],
      ["收入同比增速", b.revenue_yoy, "pct"],
      ["归母净利润", b.net_profit, "yi"],
      ["经营利润", b.operating_profit, "yi"],
      ["金融利润", b.financial_profit, "yi"],
      ["净利润同比增速", b.net_profit_yoy, "pct"],
      ["净利率", b.net_margin, "pct"],
      ["扣非净利润", b.net_profit_adjusted, "yi"],
      ["经营净现金流", b.operating_cf, "yi"],
      ["自由现金流 FCF", b.fcf, "yi"],
      ["毛利（收入−成本）", b.gross_profit, "yi"],
      ["毛利率", b.gross_margin, "pct"],
    ];

    var qualityRows = [
      ["① 扣非净利润 / 归母净利润", q.deduct_ratio, "ratio"],
      ["② 经营利润 / 归母净利润", q.operating_ratio, "ratio"],
      ["③ 经营现金流 / 归母净利润", q.cfnp, "num"],
      ["④ 自由现金流 FCF", q.fcf_sign, "text"],
      ["净利润 vs 归母净利润", q.minority_gap, "text"],
    ];
    var qualityHints = ["", "", "同向、无量级差", "持续负需警觉", "归母≫净利需警惕"];

    var body = '<div class="framework-box"><strong>观察要点：</strong>规模 → 多年发展过程 → 盈利质量四关系（逐年对比）<br>' +
      '<strong>数据口径：</strong>年报 · 合并报表 · 单位亿元</div>' +
      '<div class="sub-title">营收基本数据（单位：亿元）</div>' +
      renderYearTable(years, basicRows) +
      '<div class="sub-title">盈利质量四关系</div>' +
      renderYearTable(years, qualityRows, qualityHints);

    return section("step1", "① 营收与盈利质量", "七步法 · 第一步 · 多年度趋势", body);
  }

  function renderStep2(d) {
    if (!d) return section("step2", "② 成本费用构成", "七步法 · 第二步", "");
    var l = d.latest || {};
    var body = '<div class="framework-box"><strong>逻辑：</strong>毛利率反映竞争壁垒；毛利率 − 净利率 → 期间费用与其他损益</div>' +
      '<div class="metric-grid">' +
      metricCard("毛利率 − 净利率", fmtPct(l.margin_gap), "≈ 期间费用率") +
      metricCard("研发费用率", fmtPct(l.rd_rate), "", "技术型企业关键") +
      metricCard("销售费用率", fmtPct(l.sales_rate), "To C 品牌关键") +
      metricCard("管理费用率", fmtPct(l.admin_rate), "收入扩张时应呈下降趋势") +
      metricCard("财务费用率", fmtPct(l.finance_rate), "有息负债企业重点关注") +
      '</div>' +
      '<div class="sub-title">毛利率与净利率</div><div id="chart-step2-margin" class="chart-box"></div>' +
      '<div id="chart-step2-expense" class="chart-box"></div>';
    return section("step2", "② 成本费用构成", "七步法 · 第二步", body);
  }

  function renderStep3(d) {
    if (!d) return section("step3", "③ 成长性", "七步法 · 第三步", "");
    var l = d.latest || {};
    var body = '<div class="framework-box"><strong>适用：</strong>成长型企业重点看增速；关注 3/5 年复合增长率</div>' +
      '<div class="metric-grid">' +
      metricCard("收入同比增速", fmtPct(l.revenue_yoy), "关注增速拐点") +
      metricCard("归母净利润同比增速", fmtPct(l.profit_yoy), "利润增速应与收入匹配") +
      metricCard("3 年复合增速（收入）", l.revenue_cagr3 != null ? "≈" + fmtPct(l.revenue_cagr3) : "—", "平滑单年波动") +
      metricCard("3 年复合增速（利润）", l.profit_cagr3 != null ? "≈" + fmtPct(l.profit_cagr3) : "—", "") +
      metricCard("5 年复合增速（收入）", l.revenue_cagr5 != null ? fmtPct(l.revenue_cagr5) : "—", "") +
      metricCard("5 年复合增速（利润）", l.profit_cagr5 != null ? fmtPct(l.profit_cagr5) : "—", "") +
      '</div><div id="chart-step3-growth" class="chart-box"></div>';
    return section("step3", "③ 成长性", "七步法 · 第三步", body);
  }

  function renderStep4(d) {
    var body = '<div class="framework-box"><strong>目标：</strong>拆分收入/毛利来源；识别增长曲线与业务接力</div>';
    if (!d || !d.available) {
      body += '<div class="unavailable-box">' + esc((d && d.message) || "分业务数据暂不可用") + '</div>';
    }
    return section("step4", "④ 业务构成", "七步法 · 第四步 · 增长驱动力", body);
  }

  function renderStep5(d) {
    if (!d) return section("step5", "⑤ 资产负债", "七步法 · 第五步", "");
    var l = d.latest || {};
    var body = '<div class="framework-box"><strong>观察要点：</strong>总资产结构 → 有息/无息债务 → 净经营资产 vs 净金融资产</div>' +
      '<div class="metric-grid">' +
      compCard("总资产", fmtYi(l.total_assets) + " 亿",
        [["流动资产 " + fmtYi(l.current_assets) + " 亿", l.current_pct],
         ["非流动资产 " + fmtYi(l.noncurrent_assets) + " 亿", l.noncurrent_pct]]) +
      metricCard("资产负债率", fmtPct(l.debt_ratio), "", l.debt_ratio > 70 ? ">70% 需重点关注" : "") +
      compCard("有息负债 / 无息负债", "",
        [["有息负债 " + fmtYi(l.interest_debt) + " 亿", l.interest_pct],
         ["无息负债 " + fmtYi(l.non_interest_debt) + " 亿", l.non_interest_pct]]) +
      metricCard("净经营资产 NOA", (l.noa >= 0 ? "" : "") + fmtYi(l.noa) + " 亿", "为正 → 日常经营净投入") +
      metricCard("净金融资产", (l.nfa >= 0 ? "+" : "") + fmtYi(l.nfa) + " 亿", "为正 → 净持有金融资产") +
      metricCard("净经营资产收益率", fmtPct(l.noa_return), "", "越高越好") +
      '</div>';

    if (d.table && d.table.length) {
      body += '<div class="sub-title">资产负债表（单位：亿元 · 年末数）</div><div class="table-wrap"><table class="data-table bs-balance">' +
        '<thead><tr><th>项目</th>' + d.table.map(function (r) { return '<th>' + esc(r.year) + '</th>'; }).join("") + '</tr></thead><tbody>';
      var bsRows = [
        { section: true, label: "资产" },
        { label: "货币资金", key: "currency_funds", level: "detail" },
        { label: "存货", key: "inventory", level: "detail" },
        { label: "其他流动资产", key: "other_current", level: "detail" },
        { label: "流动资产", key: "current_assets", level: "category" },
        { label: "非流动资产", key: "noncurrent_assets", level: "category" },
        { label: "资产合计", key: "total_assets", level: "grand" },
        { section: true, label: "负债" },
        { label: "有息负债", key: "interest_debt", level: "category" },
        { label: "应付账款", key: "accounts_payable", level: "detail" },
        { label: "预收账款", key: "advance_receivables", level: "detail" },
        { label: "合同负债", key: "contract_liab", level: "detail" },
        { label: "无息负债（狭义）", key: "non_interest_debt", level: "category" },
        { label: "负债合计", key: "total_liab", level: "grand" },
        { section: true, label: "比率与权益" },
        { label: "资产负债率", key: "debt_ratio", level: "metric", fmt: "pct" },
        { label: "归母净资产", key: "parent_equity", level: "grand" },
      ];
      bsRows.forEach(function (row) {
        if (row.section) {
          body += '<tr class="bs-section"><td colspan="' + (d.table.length + 1) + '">' + esc(row.label) + '</td></tr>';
          return;
        }
        var rowCls = "bs-" + row.level;
        body += '<tr class="' + rowCls + '"><td class="row-label">' + esc(row.label) + '</td>';
        d.table.forEach(function (col) {
          var v = col[row.key];
          body += '<td class="num">' + (row.fmt === "pct" ? fmtPct(v) : fmtCell(v)) + '</td>';
        });
        body += '</tr>';
      });
      body += '</tbody></table></div>';
    }
    return section("step5", "⑤ 资产负债", "七步法 · 第五步 · 财务风险", body);
  }

  function renderStep6(d) {
    if (!d) return section("step6", "⑥ 投入产出", "七步法 · 第六步", "");
    var body = '<div class="framework-box"><strong>三维投入：</strong>营运资本 WC、固定资产/长期资产、人力</div>' +
      '<div class="sub-title">一元收入需要 WC</div><div id="chart-step6-wc" class="chart-box" style="margin-top:0"></div>' +
      '<p class="anno-note">WC（狭义）= 应收 + 预付 + 存货 + 合同资产 − 应付 − 预收 − 合同负债</p>';

    if (d.wc_table && d.wc_table.length) {
      body += '<div class="sub-title">WC 分析</div>' + renderSimpleTable(d.wc_table, [
        { label: "一元收入需要 WC（元）", key: "wc_per_revenue" },
        { label: "WC / 亿元", key: "wc" },
        { label: "应收 / 亿元", key: "ar", indent: true },
        { label: "预付 / 亿元", key: "prepayment", indent: true },
        { label: "存货 / 亿元", key: "inventory", indent: true },
        { label: "应付 / 亿元", key: "accounts_payable", indent: true },
        { label: "预收 / 亿元", key: "advance_receivables", indent: true },
        { label: "合同负债 / 亿元", key: "contract_liab", indent: true },
        { label: "应收占收入 / %", key: "ar_ratio", pct: true },
        { label: "存货占收入 / %", key: "inventory_ratio", pct: true },
        { label: "新增 WC / 亿元", key: "wc_delta" },
      ]);
    }

    body += '<div class="sub-title" style="margin-top:16px">一元收入需要的固定资产 & 长期资产</div>' +
      '<div id="chart-step6-fa" class="chart-box" style="margin-top:0"></div>';

    if (d.fa_table && d.fa_table.length) {
      body += '<div class="sub-title">固定资产分析</div>' + renderSimpleTable(d.fa_table, [
        { label: "一元收入需要的固定资产 / 元", key: "fa_per_revenue" },
        { label: "一元收入需要的长期资产 / 元", key: "lt_per_revenue" },
        { label: "固定资产 / 亿元", key: "fixed_assets" },
        { label: "长期经营资产 / 亿元", key: "long_operating_assets" },
        { label: "折旧 / 亿元", key: "depreciation" },
        { label: "折旧占收入 / %", key: "depr_ratio", pct: true },
      ]);
    }

    if (d.human && !d.human.available) {
      body += '<div class="sub-title" style="margin-top:16px">人力投入</div>' +
        '<div class="unavailable-box">' + esc(d.human.message) + '</div>';
    }
    return section("step6", "⑥ 投入产出（WC · 固定资产 · 人力）", "七步法 · 第六步", body);
  }

  function renderStep7(d) {
    if (!d) return section("step7", "⑦ 收益率（ROE 拆解）", "七步法 · 第七步", "");
    var l = d.latest || {};
    var body = '<div class="framework-box"><strong>杜邦：</strong>ROE = 销售净利率 × 总资产周转率 × 权益乘数</div>' +
      '<div class="metric-grid">' +
      metricCard("ROE（摊薄/加权）", fmtPct(l.roe), "", ">20% 较优秀") +
      metricCard("ROA", fmtPct(l.roa), "去杠杆后总资产获利能力") +
      metricCard("ROIC", fmtPct(l.roic), "无杠杆盈利") +
      metricCard("销售净利率（杜邦）", fmtPct(l.net_profit_rate), "") +
      metricCard("总资产周转率", l.turnover != null ? fmtNum(l.turnover, 2) + " 次" : "—", "") +
      metricCard("权益乘数", l.leverage != null ? fmtNum(l.leverage, 2) : "—", "杠杆水平") +
      '</div><div id="chart-step7-roe" class="chart-box"></div>';

    if (d.dupont_table && d.dupont_table.length) {
      body += '<div class="sub-title">ROE 与杜邦分析</div>' +
        '<p class="roe-dupont-caption">杜邦三因子逐年对比 <span class="badge-inline">ROE = 净利润率 × 总资产周转率 × 权益乘数</span></p>' +
        '<div class="table-wrap"><table class="dash-table"><thead><tr><th>指标</th>' +
        d.dupont_table.map(function (r) { return '<th>' + esc(r.year) + '</th>'; }).join("") +
        '</tr></thead><tbody>' +
        dupontRow("净利润率(%)", d.dupont_table, "net_profit_rate", "pct") +
        dupontRow("总资产周转率", d.dupont_table, "turnover") +
        dupontRow("权益乘数", d.dupont_table, "leverage") +
        dupontRow("ROE(%)", d.dupont_table, "roe", "pct", true) +
        '</tbody></table></div>';
    }
    return section("step7", "⑦ 收益率（ROE 拆解）", "七步法 · 第七步", body);
  }

  function renderEight() {
    var cards = EIGHT_QUESTIONS.map(function (item, i) {
      return '<div class="q-card"><div class="q-num">Q' + (i + 1) + '</div>' +
        '<div class="q-text">' + esc(item.q) + '</div>' +
        '<div class="q-note">' + esc(item.note) + '</div></div>';
    }).join("");
    return section("eight", "商业八问（非财务定性）", "材料研读清单", '<div class="eight-q">' + cards + '</div>');
  }

  // ── 图表 ──

  function initCharts(s) {
    if (s.step2 && s.step2.chart) initStep2Charts(s.step2.chart);
    if (s.step3 && s.step3.chart) initStep3Chart(s.step3.chart);
    if (s.step6) {
      if (s.step6.wc_chart) initWcChart(s.step6.wc_chart);
      if (s.step6.fa_chart) initFaChart(s.step6.fa_chart);
    }
    if (s.step7 && s.step7.chart) initRoeChart(s.step7.chart);
  }

  function axisStyle() {
    return {
      axisLine: { lineStyle: { color: C.axis } },
      axisLabel: { color: C.text, fontSize: 11 },
      splitLine: { lineStyle: { color: C.axis, type: "dashed" } },
    };
  }

  function baseGrid() {
    return { left: 48, right: 48, top: 44, bottom: 32, containLabel: true };
  }

  function initChart(id, option) {
    var el = document.getElementById(id);
    if (!el) return;
    var chart = echarts.init(el, null, { renderer: "canvas" });
    chart.setOption(option);
    charts.push(chart);
  }

  function initStep2Charts(c) {
    initChart("chart-step2-margin", {
      title: { text: "毛利率 · 净利率", left: "center", top: 8, textStyle: { color: C.text, fontSize: 13 } },
      tooltip: { trigger: "axis", backgroundColor: "#1a2332", borderColor: C.axis, textStyle: { color: "#e8edf4" } },
      legend: { top: 8, right: 12, textStyle: { color: C.text, fontSize: 11 } },
      grid: baseGrid(),
      xAxis: { type: "category", data: c.dates, ...axisStyle() },
      yAxis: { type: "value", name: "%", nameTextStyle: { color: C.text }, ...axisStyle() },
      series: [
        { name: "毛利率", type: "line", smooth: true, data: c.gross_margin, lineStyle: { color: C.purple, width: 2 }, itemStyle: { color: C.purple } },
        { name: "净利率", type: "line", smooth: true, data: c.net_margin, lineStyle: { color: C.green, width: 2 }, itemStyle: { color: C.green } },
      ],
    });
    initChart("chart-step2-expense", {
      title: { text: "期间费用率构成", left: "center", top: 8, textStyle: { color: C.text, fontSize: 13 } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { top: 8, right: 12, textStyle: { color: C.text, fontSize: 11 } },
      grid: baseGrid(),
      xAxis: { type: "category", data: c.dates, ...axisStyle() },
      yAxis: { type: "value", name: "%", nameTextStyle: { color: C.text }, ...axisStyle() },
      series: [
        { name: "研发费用率", type: "bar", stack: "fee", data: c.rd_rate, itemStyle: { color: C.purple } },
        { name: "销售费用率", type: "bar", stack: "fee", data: c.sales_rate, itemStyle: { color: C.blue } },
        { name: "管理费用率", type: "bar", stack: "fee", data: c.admin_rate, itemStyle: { color: C.cyan } },
        { name: "财务费用率", type: "bar", stack: "fee", data: c.finance_rate, itemStyle: { color: C.text } },
      ],
    });
  }

  function initStep3Chart(c) {
    initChart("chart-step3-growth", {
      title: { text: "收入 / 利润同比增速", left: "center", top: 8, textStyle: { color: C.text, fontSize: 13 } },
      tooltip: { trigger: "axis" },
      legend: { top: 8, right: 12, textStyle: { color: C.text, fontSize: 11 } },
      grid: baseGrid(),
      xAxis: { type: "category", data: c.dates, ...axisStyle() },
      yAxis: { type: "value", name: "%", nameTextStyle: { color: C.text }, ...axisStyle() },
      series: [
        { name: "收入增速", type: "bar", data: (c.revenue_yoy || []).map(function (v) {
          return { value: v, itemStyle: { color: v < 0 ? C.warn : C.blue } };
        }), barMaxWidth: 32 },
        { name: "利润增速", type: "bar", data: (c.profit_yoy || []).map(function (v) {
          var capped = v > 200 ? 200 : v;
          return { value: capped, itemStyle: { color: v < 0 ? C.red : C.green } };
        }), barMaxWidth: 32 },
      ],
    });
  }

  function initWcChart(c) {
    initChart("chart-step6-wc", {
      title: { text: "1 元收入需要的 WC", left: "center", top: 8, textStyle: { color: C.text, fontSize: 13 } },
      grid: baseGrid(),
      xAxis: { type: "category", data: c.dates, ...axisStyle() },
      yAxis: { type: "value", name: "元", nameTextStyle: { color: C.text }, ...axisStyle() },
      series: [{
        type: "line", smooth: true, data: c.wc_per_revenue,
        lineStyle: { color: C.warn, width: 2 }, itemStyle: { color: C.warn },
        areaStyle: { color: "rgba(245,158,11,0.10)" },
      }],
    });
  }

  function initFaChart(c) {
    initChart("chart-step6-fa", {
      title: { text: "1 元收入需要的固定资产 & 长期资产", left: "center", top: 8, textStyle: { color: C.text, fontSize: 13 } },
      tooltip: { trigger: "axis" },
      legend: { top: 8, right: 12, textStyle: { color: C.text, fontSize: 11 } },
      grid: baseGrid(),
      xAxis: { type: "category", data: c.dates, ...axisStyle() },
      yAxis: { type: "value", name: "元", nameTextStyle: { color: C.text }, ...axisStyle() },
      series: [
        { name: "固定资产", type: "line", smooth: true, data: c.fa_per_revenue, lineStyle: { color: C.blue, width: 2 }, itemStyle: { color: C.blue } },
        { name: "长期资产", type: "line", smooth: true, data: c.lt_per_revenue, lineStyle: { color: C.purple, width: 2 }, itemStyle: { color: C.purple } },
      ],
    });
  }

  function initRoeChart(c) {
    initChart("chart-step7-roe", {
      title: { text: "ROE · ROA · ROIC 趋势", left: "center", top: 8, textStyle: { color: C.text, fontSize: 13 } },
      tooltip: { trigger: "axis" },
      legend: { top: 8, right: 12, textStyle: { color: C.text, fontSize: 11 } },
      grid: baseGrid(),
      xAxis: { type: "category", data: c.dates, ...axisStyle() },
      yAxis: { type: "value", name: "%", nameTextStyle: { color: C.text }, ...axisStyle() },
      series: [
        { name: "ROE", type: "line", smooth: true, data: c.roe, lineStyle: { color: C.blue, width: 2 }, itemStyle: { color: C.blue } },
        { name: "ROA", type: "line", smooth: true, data: c.roa, lineStyle: { color: C.green, width: 2 }, itemStyle: { color: C.green } },
        { name: "ROIC", type: "line", smooth: true, data: c.roic, lineStyle: { color: C.purple, width: 2 }, itemStyle: { color: C.purple } },
      ],
    });
  }

  function disposeCharts() {
    charts.forEach(function (c) { c.dispose(); });
    charts = [];
  }

  // ── 导航 ──

  function bindNav() {
    sideNav.addEventListener("click", function (e) {
      var a = e.target.closest("a");
      if (!a) return;
      e.preventDefault();
      var target = document.querySelector(a.getAttribute("href"));
      if (target && dashContent) {
        var top = target.getBoundingClientRect().top
          - dashContent.getBoundingClientRect().top
          + dashContent.scrollTop - 12;
        dashContent.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      }
    });

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var id = entry.target.id;
          sideNav.querySelectorAll(".dash-nav-item").forEach(function (n) {
            n.classList.toggle("active", n.getAttribute("href") === "#" + id);
          });
        }
      });
    }, { root: dashContent, rootMargin: "-20% 0px -60% 0px", threshold: 0 });

    ["snapshot", "step1", "step2", "step3", "step4", "step5", "step6", "step7", "eight"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) observer.observe(el);
    });
  }

  // ── 工具 ──

  function section(id, title, tag, body) {
    return '<section id="' + id + '" class="dash-section">' +
      '<div class="section-header"><h2>' + esc(title) + '</h2><span class="tag">' + esc(tag) + '</span></div>' +
      '<div class="section-body">' + body + '</div></section>';
  }

  function metricCard(name, val, hint, threshold) {
    return '<div class="metric-card"><div class="m-name">' + esc(name) + '</div>' +
      '<div class="m-val">' + esc(val) + '</div>' +
      (hint ? '<div class="m-hint">' + esc(hint) + '</div>' : '') +
      (threshold ? '<div class="m-threshold">' + esc(threshold) + '</div>' : '') +
      '</div>';
  }

  function compCard(name, val, rows) {
    var comp = rows.map(function (r) {
      return '<div class="comp-row"><span>' + esc(r[0]) + '</span><span class="comp-pct">' + fmtPct(r[1]) + '</span></div>';
    }).join("");
    var bar = rows.length === 2 ?
      '<div class="comp-bar"><span style="width:' + (rows[0][1] || 0) + '%"></span><span style="width:' + (rows[1][1] || 0) + '%"></span></div>' : "";
    return '<div class="metric-card"><div class="m-name">' + esc(name) + '</div>' +
      (val ? '<div class="m-val">' + esc(val) + '</div>' : '') +
      '<div class="m-composition">' + comp + bar + '</div></div>';
  }

  function renderYearTable(years, rows, hints) {
    var h = '<div class="table-wrap"><table class="data-table"><thead><tr><th>指标</th>';
    years.forEach(function (y) { h += '<th>' + esc(y) + '</th>'; });
    if (hints) h += '<th>判断要点</th>';
    h += '</tr></thead><tbody>';
    rows.forEach(function (row, i) {
      h += '<tr><td class="row-label">' + esc(row[0]) + '</td>';
      (row[1] || []).forEach(function (v) {
        h += '<td class="num">' + fmtByType(v, row[2]) + '</td>';
      });
      if (hints) h += '<td style="text-align:left;font-size:11px;color:var(--muted)">' + esc(hints[i] || "") + '</td>';
      h += '</tr>';
    });
    return h + '</tbody></table></div>';
  }

  function renderSimpleTable(data, cols) {
    var h = '<div class="table-wrap"><table class="data-table"><thead><tr><th>类目</th>';
    data.forEach(function (r) { h += '<th>' + esc(r.year) + '</th>'; });
    h += '</tr></thead><tbody>';
    cols.forEach(function (col) {
      h += '<tr><td class="row-label' + (col.indent ? " indent-1" : "") + '">' + esc(col.label) + '</td>';
      data.forEach(function (r) {
        var v = r[col.key];
        h += '<td class="num">' + (col.pct ? fmtPct(v) : fmtCell(v)) + '</td>';
      });
      h += '</tr>';
    });
    return h + '</tbody></table></div>';
  }

  function dupontRow(label, data, key, fmt, bold) {
    var h = '<tr><td>' + esc(label) + '</td>';
    data.forEach(function (r) {
      var v = r[key];
      h += '<td class="num' + (bold && v > 20 ? " good" : "") + '">' +
        (bold ? "<strong>" : "") + (fmt === "pct" ? fmtPct(v) : fmtNum(v, 4)) + (bold ? "</strong>" : "") + '</td>';
    });
    return h + '</tr>';
  }

  function fmtByType(v, type) {
    if (v == null) return "—";
    if (type === "pct") return fmtPct(v);
    if (type === "yi") return fmtYi(v);
    if (type === "ratio") return fmtNum(v, 2);
    return String(v);
  }

  function fmtCell(v) {
    if (v == null) return "—";
    return fmtNum(v, 2);
  }

  function fmtYi(v) {
    if (v == null) return "—";
    return fmtNum(v, 2);
  }

  function fmtPct(v) {
    if (v == null) return "—";
    return Number(v).toFixed(2) + "%";
  }

  function fmtNum(v, d) {
    d = d == null ? 2 : d;
    if (v == null) return "—";
    return Number(v).toFixed(d);
  }

  function esc(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  window.addEventListener("resize", function () {
    charts.forEach(function (c) { c.resize(); });
  });

  var urlParams = new URLSearchParams(window.location.search);
  var codeFromUrl = urlParams.get("code");
  if (codeFromUrl) {
    searchInput.value = codeFromUrl;
    doQuery();
  }
})();
