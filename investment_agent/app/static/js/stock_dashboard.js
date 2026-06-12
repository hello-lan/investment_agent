(function () {
  var searchInput = document.getElementById("stockSearch");
  var searchBtn = document.getElementById("searchBtn");
  var searchDropdown = document.getElementById("searchDropdown");
  var syncBadge = document.getElementById("syncBadge");
  var stockInfoBar = document.getElementById("stockInfoBar");
  var dashMain = document.getElementById("dashMain");
  var dashContent = document.getElementById("dashContent");
  var dashEmpty = document.getElementById("dashEmpty");
  var sideNav = document.getElementById("sideNav");

  var currentCode = null;
  var currentData = null;
  var charts = {};
  var searchTimer = null;
  var pollTimer = null;
  var dropdownIndex = -1;

  // ── 搜索 ──

  searchInput.addEventListener("input", function () {
    dropdownIndex = -1;
    var q = searchInput.value.trim();
    if (!q || q.length < 1) {
      searchDropdown.classList.remove("show");
      return;
    }
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
      if (dropdownIndex >= 0 && items.length > 0) {
        items[dropdownIndex].click();
      } else {
        doQuery();
      }
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
        if (results.length === 0) {
          searchDropdown.innerHTML = '<div class="dash-search-item" style="color:#999;">未找到匹配股票</div>';
        } else {
          results.forEach(function (s) {
            var div = document.createElement("div");
            div.className = "dash-search-item";
            div.innerHTML = '<span class="name">' + esc(s.name) + '</span>' +
              '<span><span class="code">' + esc(s.code) + '</span>' +
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

  // ── 加载看板 ──

  function loadDashboard(code) {
    dashEmpty.style.display = "none";
    stockInfoBar.style.display = "none";
    dashMain.style.display = "flex";
    dashContent.innerHTML = '<div class="dash-loading">加载中...</div>';
    setSyncBadge("");

    currentCode = code;
    fetchDashboard(code);
  }

  function fetchDashboard(code) {
    fetch("/api/stock-dashboard/" + code)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.status === "syncing" || data.status === "updating") {
          // 正在同步中
          setSyncBadge("syncing", "数据同步中...");
          dashContent.innerHTML = renderSkeleton();
          if (data.sections) {
            renderAll(data);
          }
          startPolling(code);
        } else if (data.status === "ready") {
          setSyncBadge("ready", "数据已就绪");
          renderAll(data);
          stopPolling();
        }
      })
      .catch(function (err) {
        dashContent.innerHTML = '<div class="dash-loading" style="color:#dc2626;">加载失败: ' + esc(String(err)) + '</div>';
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
            fetchDashboard(code); // 重新加载完整数据
          } else if (status.status === "error") {
            setSyncBadge("error", "同步失败: " + (status.error || ""));
            stopPolling();
          } else if (status.status === "syncing") {
            setSyncBadge("syncing", status.progress || "数据同步中...");
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

  // ── 渲染所有模块 ──

  function renderAll(data) {
    if (!data.sections) return;
    currentData = data;

    // 销毁旧图表
    Object.values(charts).forEach(function (c) { c.dispose(); });
    charts = {};

    // 股票信息条
    renderInfoBar(data.stock, data.sections.snapshot);

    // 渲染模块
    var html = "";
    html += renderProfitability(data.sections.profitability);
    html += renderROE(data.sections.roe_decomposition);
    html += renderFiveForces(data.sections.five_forces);
    html += renderFreeCashflow(data.sections.free_cashflow);
    html += renderGrowth(data.sections.growth);
    html += renderIncomePercentage(data.sections.income_percentage);
    html += renderOperation(data.sections.operation);
    html += renderFinancialHealth(data.sections.financial_health);
    html += renderWarnings(data.sections.warnings);

    dashContent.innerHTML = html;
    dashMain.style.display = "flex";

    // 初始化图表
    setTimeout(function () {
      initProfitabilityChart(data.sections.profitability);
      initGrowthCharts(data.sections.growth);
    }, 100);

    // 重置侧边导航
    resetSideNav();
  }

  function renderInfoBar(stock, snap) {
    stockInfoBar.style.display = "flex";
    document.getElementById("infoName").textContent = (stock && stock.name) || "-";
    document.getElementById("infoCode").textContent = (stock && stock.code) || "-";
    document.getElementById("infoIndustry").textContent = (stock && stock.industry) || "-";
    document.getElementById("infoMarketCap").textContent = fmtMarketCap(stock && stock.market_cap);
    document.getElementById("infoROE").textContent = snap ? fmtPct(snap.roe) : "-";
    document.getElementById("infoGrossMargin").textContent = snap ? fmtPct(snap.gross_margin) : "-";
    document.getElementById("infoUpdated").textContent = (stock && stock.updated_at)
      ? stock.updated_at.slice(0, 16).replace("T", " ") : "-";
  }

  // ── 1. 盈利能力 ──
  function renderProfitability(data) {
    if (!data) return "";
    return '<div class="dash-section" id="section-profitability">' +
      '<div class="dash-section-header"><h2>盈利能力</h2></div>' +
      '<div class="dash-section-body">' +
      '<div id="chart-profitability" class="dash-chart" style="height:320px;"></div>' +
      '<div class="dash-thresholds">参考阈值：净利润率 ≥ 15%，ROA ≥ 6%，ROE ≥ 10%</div>' +
      '</div></div>';
  }

  function initProfitabilityChart(data) {
    if (!data || !data.chart) return;
    var el = document.getElementById("chart-profitability");
    if (!el) return;
    var chart = echarts.init(el);
    var d = data.chart;
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["毛利率", "净利率", "ROE", "ROA"], top: 0 },
      grid: { left: 50, right: 20, top: 30, bottom: 50 },
      xAxis: { type: "category", data: d.dates, axisLabel: { rotate: 30, fontSize: 11 } },
      yAxis: { type: "value", name: "%", axisLabel: { fontSize: 11 } },
      series: [
        { name: "毛利率", type: "line", data: d.gross_margin, smooth: true, lineStyle: { color: "#4a6cf7" }, itemStyle: { color: "#4a6cf7" } },
        { name: "净利率", type: "line", data: d.net_margin, smooth: true, lineStyle: { color: "#16a34a" }, itemStyle: { color: "#16a34a" } },
        { name: "ROE", type: "line", data: d.roe, smooth: true, lineStyle: { color: "#ea580c" }, itemStyle: { color: "#ea580c" } },
        { name: "ROA", type: "line", data: d.roa, smooth: true, lineStyle: { color: "#8b5cf6" }, itemStyle: { color: "#8b5cf6" } },
      ],
    });
    charts.profitability = chart;
  }

  // ── 2. ROE 拆解 ──
  function renderROE(data) {
    if (!data || !data.table || !data.table.length) return "";
    var rows = data.table.map(function (r) {
      return "<tr>" +
        "<td>" + esc(r.date) + "</td>" +
        "<td class='num'>" + fmtPct(r.net_profit_rate) + "</td>" +
        "<td class='num'>" + fmtNum(r.turnover, 4) + "</td>" +
        "<td class='num'>" + fmtNum(r.leverage, 4) + "</td>" +
        "<td class='num'><strong>" + fmtPct(r.roe) + "</strong></td>" +
        "</tr>";
    }).join("");
    return sectionHTML("ROE 拆解", "section-roe", "ROE = 净利润率 × 总资产周转率 × 权益乘数",
      '<table class="dash-table"><thead><tr><th>报告期</th><th>净利润率(%)</th><th>总资产周转率</th><th>权益乘数</th><th>ROE(%)</th></tr></thead><tbody>' + rows + "</tbody></table>");
  }

  // ── 3. 五力分析 ──
  function renderFiveForces(data) {
    if (!data || !data.table || !data.table.length) return "";
    var rows = data.table.map(function (r) {
      return "<tr>" +
        "<td>" + esc(r.date) + "</td>" +
        "<td class='num'>" + fmtPct(r.ar_ratio) + "</td>" +
        "<td class='num'>" + fmtPct(r.prepay_ratio) + "</td>" +
        "<td class='num'>" + fmtPct(r.ap_ratio) + "</td>" +
        "<td class='num'>" + fmtPct(r.pr_ratio) + "</td>" +
        "<td class='num'><strong>" + fmtPct(r.gross_margin) + "</strong></td>" +
        "</tr>";
    }).join("");
    return sectionHTML("五力分析", "section-fiveforces", "上下游议价能力",
      '<table class="dash-table"><thead><tr><th>报告期</th><th>应收/营收(%)</th><th>预付/营收(%)</th><th>应付/营收(%)</th><th>预收/营收(%)</th><th>毛利率(%)</th></tr></thead><tbody>' + rows + "</tbody></table>");
  }

  // ── 4. 自由现金流 ──
  function renderFreeCashflow(data) {
    if (!data || !data.table || !data.table.length) return "";
    var rows = data.table.map(function (r) {
      return "<tr>" +
        "<td>" + esc(r.date) + "</td>" +
        "<td class='num'>" + fmtNum(r.operating_cf) + "亿</td>" +
        "<td class='num " + (r.cfr && r.cfr < 5 ? "warn" : "") + "'>" + fmtPct(r.cfr) + "</td>" +
        "<td class='num " + (r.cfnp && r.cfnp < 80 ? "warn" : "") + "'>" + fmtPct(r.cfnp) + "</td>" +
        "<td class='num'>" + fmtPct(r.yoy) + "</td>" +
        "</tr>";
    }).join("");
    return sectionHTML("历史自由现金流", "section-cashflow", "CFR = 经营现金流/营收，CFNP = 经营现金流/净利润",
      '<table class="dash-table"><thead><tr><th>报告期</th><th>经营现金流(亿)</th><th>CFR(%)</th><th>CFNP(%)</th><th>同比(%)</th></tr></thead><tbody>' + rows + "</tbody></table>");
  }

  // ── 5. 成长性 ──
  function renderGrowth(data) {
    if (!data) return "";
    var keys = ["revenue", "net_profit_growth", "net_profit_adjusted", "holders_equity", "total_assets"];
    var tabs = keys.map(function (k, i) {
      return '<button class="dash-tab' + (i === 0 ? " active" : "") + '" data-gkey="' + k + '">' +
        (data[k] ? data[k].label : k) + "</button>";
    }).join("");
    return '<div class="dash-section" id="section-growth">' +
      '<div class="dash-section-header"><h2>成长性</h2></div>' +
      '<div class="dash-section-body">' +
      '<div class="dash-tabs" id="growthTabs">' + tabs + "</div>" +
      '<div id="chart-growth" class="dash-chart" style="height:320px;"></div>' +
      "</div></div>";
  }

  function initGrowthCharts(data) {
    if (!data) return;
    var chartEl = document.getElementById("chart-growth");
    if (!chartEl) return;
    var chart = echarts.init(chartEl);
    charts.growth = chart;

    var currentKey = "revenue";

    function renderGrowthChart(key) {
      var d = data[key];
      if (!d) return;
      chart.setOption({
        tooltip: { trigger: "axis" },
        grid: { left: 60, right: 50, top: 20, bottom: 40 },
        xAxis: { type: "category", data: d.dates, axisLabel: { rotate: 30, fontSize: 11 } },
        yAxis: [
          { type: "value", name: "亿", axisLabel: { fontSize: 11 } },
          { type: "value", name: "%", axisLabel: { fontSize: 11 } },
        ],
        series: [
          { name: d.label, type: "bar", data: d.values, itemStyle: { color: "#4a6cf7" }, barMaxWidth: 32 },
          { name: "同比(%)", type: "line", yAxisIndex: 1, data: d.yoy || [], smooth: true,
            lineStyle: { color: "#ea580c", type: "dashed" }, itemStyle: { color: "#ea580c" },
            symbol: "circle", symbolSize: 6 },
        ],
      }, true);
    }

    renderGrowthChart(currentKey);

    // Tab 切换
    var tabs = document.querySelectorAll("#growthTabs .dash-tab");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        currentKey = tab.dataset.gkey;
        renderGrowthChart(currentKey);
      });
    });
  }

  // ── 6. 收益性（百分率利润表） ──
  function renderIncomePercentage(data) {
    if (!data || !data.table || !data.table.length) return "";
    var rows = data.table.map(function (r) {
      return "<tr>" +
        "<td>" + esc(r.date) + "</td>" +
        "<td class='num'><strong>" + fmtPct(r.gross_margin) + "</strong></td>" +
        "<td class='num'>" + fmtPct(r.sales_fee_pct) + "</td>" +
        "<td class='num'>" + fmtPct(r.manage_fee_pct) + "</td>" +
        "<td class='num'>" + fmtPct(r.rd_pct) + "</td>" +
        "<td class='num'>" + fmtPct(r.finance_pct) + "</td>" +
        "</tr>";
    }).join("");
    return sectionHTML("收益性", "section-incomepct", "各项费用占营业收入百分比",
      '<table class="dash-table"><thead><tr><th>报告期</th><th>毛利率(%)</th><th>销售费用(%)</th><th>管理费用(%)</th><th>研发费用(%)</th><th>财务费用(%)</th></tr></thead><tbody>' + rows + "</tbody></table>");
  }

  // ── 7. 营运能力 ──
  function renderOperation(data) {
    if (!data || !data.table || !data.table.length) return "";
    var rows = data.table.map(function (r) {
      return "<tr>" +
        "<td>" + esc(r.report_date) + "</td>" +
        "<td class='num'>" + fmtNum(r.ar_turnover_days) + "</td>" +
        "<td class='num'>" + fmtNum(r.inventory_turnover_days) + "</td>" +
        "<td class='num'>" + fmtNum(r.fixed_asset_turnover) + "</td>" +
        "<td class='num'>" + fmtNum(r.total_asset_turnover) + "</td>" +
        "</tr>";
    }).join("");
    return sectionHTML("营运能力", "section-operation", "周转效率",
      '<table class="dash-table"><thead><tr><th>报告期</th><th>应收周转天数</th><th>存货周转天数</th><th>固定资产周转率</th><th>总资产周转率</th></tr></thead><tbody>' + rows + "</tbody></table>");
  }

  // ── 8. 财务风险 ──
  function renderFinancialHealth(data) {
    if (!data || !data.table || !data.table.length) return "";
    var rows = data.table.map(function (r) {
      return "<tr>" +
        "<td>" + esc(r.date) + "</td>" +
        "<td class='num " + (r.debt_ratio && r.debt_ratio > 60 ? "warn" : "") + "'>" + fmtPct(r.debt_ratio) + "</td>" +
        "<td class='num'>" + fmtNum(r.equity_multiplier, 4) + "</td>" +
        "<td class='num " + (r.current_ratio && r.current_ratio < 1.5 ? "warn" : "") + "'>" + fmtNum(r.current_ratio) + "</td>" +
        "<td class='num " + (r.quick_ratio && r.quick_ratio < 1 ? "warn" : "") + "'>" + fmtNum(r.quick_ratio) + "</td>" +
        "<td class='num'>" + fmtPct(r.ar_revenue_ratio) + "</td>" +
        "<td class='num " + (r.goodwill_equity_ratio && r.goodwill_equity_ratio > 30 ? "warn" : "") + "'>" + fmtPct(r.goodwill_equity_ratio) + "</td>" +
        "<td class='num " + (r.cash_debt_ratio && r.cash_debt_ratio < 100 ? "warn" : "") + "'>" + fmtPct(r.cash_debt_ratio) + "</td>" +
        "</tr>";
    }).join("");
    return sectionHTML("财务风险", "section-finhealth", "",
      '<table class="dash-table"><thead><tr><th>报告期</th><th>资产负债率(%)</th><th>权益乘数</th><th>流动比率</th><th>速动比率</th><th>应收/营收(%)</th><th>商誉/权益(%)</th><th>现金/有息负债(%)</th></tr></thead><tbody>' + rows + "</tbody></table>" +
      '<div class="dash-thresholds"><ul><li>流动比率 &lt; 1.5 可能面临短期偿债压力</li><li>速动比率 &lt; 1 需关注（制造业/零售业）</li><li>商誉/权益 &gt; 30% 需警惕商誉减值风险</li><li>现金/有息负债 &lt; 100% 表示现金不足以覆盖有息负债</li></ul></div>');
  }

  // ── 9. 排雷 ──
  function renderWarnings(data) {
    if (!data) return "";

    var html = '<div class="dash-section" id="section-warnings">' +
      '<div class="dash-section-header"><h2>排雷</h2></div>' +
      '<div class="dash-section-body">';

    // 货币资金
    if (data.currency_funds && data.currency_funds.table) {
      html += '<div class="warning-section"><h4>货币资金</h4><table class="dash-table"><thead><tr>' +
        '<th>报告期</th><th>货币资金(亿)</th><th>现金/总资产(%)</th><th>资产负债率(%)</th><th>现金/营收(%)</th>' +
        '</tr></thead><tbody>';
      data.currency_funds.table.forEach(function (r) {
        html += "<tr><td>" + esc(r.date) + "</td>" +
          "<td class='num'>" + fmtNum(r.currency_funds) + "</td>" +
          "<td class='num " + (r.cf_assets_ratio && r.cf_assets_ratio < 10 ? "warn" : "") + "'>" + fmtPct(r.cf_assets_ratio) + "</td>" +
          "<td class='num'>" + fmtPct(r.debt_ratio) + "</td>" +
          "<td class='num'>" + fmtPct(r.cf_revenue_ratio) + "</td></tr>";
      });
      html += "</tbody></table></div>";
    }

    // 应收
    if (data.receivables && data.receivables.table) {
      html += '<div class="warning-section"><h4>应收票据</h4><table class="dash-table"><thead><tr>' +
        '<th>报告期</th><th>应收/营收(%)</th><th>应收票据/营收(%)</th><th>应收票据(亿)</th><th>应付票据(亿)</th><th>应收周转天数</th><th>其他应收/总资产(%)</th>' +
        '</tr></thead><tbody>';
      data.receivables.table.forEach(function (r) {
        html += "<tr><td>" + esc(r.date) + "</td>" +
          "<td class='num " + (r.ar_revenue_ratio && r.ar_revenue_ratio > 30 ? "warn" : "") + "'>" + fmtPct(r.ar_revenue_ratio) + "</td>" +
          "<td class='num'>" + fmtPct(r.bills_receivable_revenue_ratio) + "</td>" +
          "<td class='num'>" + fmtNum(r.bills_receivable) + "</td>" +
          "<td class='num'>" + fmtNum(r.bills_payable) + "</td>" +
          "<td class='num'>" + fmtNum(r.ar_turnover_days) + "</td>" +
          "<td class='num'>" + fmtPct(r.other_receivables_assets_ratio) + "</td></tr>";
      });
      html += "</tbody></table></div>";
    }

    // 存货及其他
    if (data.other_assets && data.other_assets.table) {
      html += '<div class="warning-section"><h4>存货及其他资产</h4><table class="dash-table"><thead><tr>' +
        '<th>报告期</th><th>存货/总资产(%)</th><th>在建工程/总资产(%)</th><th>交易性金融资产/总资产(%)</th><th>固定资产周转率</th><th>存货周转天数</th>' +
        '</tr></thead><tbody>';
      data.other_assets.table.forEach(function (r) {
        html += "<tr><td>" + esc(r.date) + "</td>" +
          "<td class='num " + (r.inventory_assets_ratio && r.inventory_assets_ratio > 30 ? "warn" : "") + "'>" + fmtPct(r.inventory_assets_ratio) + "</td>" +
          "<td class='num " + (r.construction_assets_ratio && r.construction_assets_ratio > 20 ? "warn" : "") + "'>" + fmtPct(r.construction_assets_ratio) + "</td>" +
          "<td class='num'>" + fmtPct(r.tradable_fin_assets_ratio) + "</td>" +
          "<td class='num'>" + fmtNum(r.fixed_asset_turnover) + "</td>" +
          "<td class='num'>" + fmtNum(r.inventory_turnover_days) + "</td></tr>";
      });
      html += "</tbody></table></div>";
    }

    html += "</div></div>";
    return html;
  }

  // ── 骨架屏 ──
  function renderSkeleton() {
    var html = "";
    for (var i = 0; i < 9; i++) {
      html += '<div class="dash-section"><div class="dash-section-header"><h2>加载中...</h2></div>' +
        '<div class="dash-section-body"><div class="skeleton" style="height:200px;"></div></div></div>';
    }
    return html;
  }

  // ── 侧边导航滚动高亮 ──
  function resetSideNav() {
    var items = sideNav.querySelectorAll(".dash-nav-item");
    items.forEach(function (item) { item.classList.remove("active"); });
    if (items.length > 0) items[0].classList.add("active");
  }

  var scrollTimeout;
  dashContent.addEventListener("scroll", function () {
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(updateActiveNav, 100);
  });

  function updateActiveNav() {
    var sections = dashContent.querySelectorAll(".dash-section");
    var navItems = sideNav.querySelectorAll(".dash-nav-item");
    var scrollTop = dashContent.scrollTop + 80;

    sections.forEach(function (sec, i) {
      var top = sec.offsetTop;
      var bottom = top + sec.offsetHeight;
      if (scrollTop >= top && scrollTop < bottom) {
        navItems.forEach(function (n) { n.classList.remove("active"); });
        if (navItems[i]) navItems[i].classList.add("active");
      }
    });
  }

  // 导航点击
  sideNav.addEventListener("click", function (e) {
    var a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    var target = document.querySelector(a.getAttribute("href"));
    if (target) {
      dashContent.scrollTo({ top: target.offsetTop - 20, behavior: "smooth" });
    }
  });

  // ── 工具函数 ──
  function sectionHTML(title, id, subtitle, body) {
    return '<div class="dash-section" id="' + id + '">' +
      '<div class="dash-section-header"><h2>' + title + '</h2>' +
      (subtitle ? '<span class="badge">' + subtitle + '</span>' : '') +
      '</div><div class="dash-section-body">' + body + "</div></div>";
  }

  function esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function fmtPct(v) { if (v === null || v === undefined) return "-"; return Number(v).toFixed(2) + "%"; }
  function fmtNum(v, d) { d = d || 2; if (v === null || v === undefined) return "-"; return Number(v).toFixed(d); }
  function fmtMarketCap(v) { if (v === null || v === undefined) return "-"; v = Number(v); if (v >= 1e12) return (v / 1e12).toFixed(2) + "万亿"; if (v >= 1e8) return (v / 1e8).toFixed(0) + "亿"; return v + ""; }

  // ── 窗口resize ──
  window.addEventListener("resize", function () {
    Object.values(charts).forEach(function (c) { c.resize(); });
  });

  // ── 支持 URL 参数跳转 ──
  var urlParams = new URLSearchParams(window.location.search);
  var codeFromUrl = urlParams.get("code");
  if (codeFromUrl) {
    searchInput.value = codeFromUrl;
    doQuery();
  }
})();