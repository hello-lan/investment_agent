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
    html += renderUsageGuide();
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

  function renderUsageGuide() {
    return '<div class="guide-intro">' +
      '<div class="guide-title">如何阅读本看板</div>' +
      '<ul>' +
      '<li><strong>导航：</strong>左侧切换七步法模块；上方快照条看最新体量与关键比率，下方表格看多年趋势，图表看结构与变化方向。</li>' +
      '<li><strong>方法：</strong>先抽取数据、再分析；发现疑问回到年报/公告找原因，数字与材料双循环印证，直至有答案或确认「看不懂」。</li>' +
      '<li><strong>图表：</strong>折线看趋势与拐点，柱状看单年波动；单点异常务必对照历史与同业，变动剧烈时查具体事项（并购、转型、一次性损益等）。</li>' +
      '</ul></div>';
  }

  function guideHint(html) {
    return '<div class="guide-hint">' + html + '</div>';
  }

  function chartGuide(html) {
    return '<p class="chart-guide">' + html + '</p>';
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
      '</div>' +
      '<p class="snapshot-guide">' +
      '<strong>快读：</strong>收入看规模，归母净利润看盈利水平，净利率/毛利率看赚钱效率。' +
      '经营现金流÷净利润宜同向、接近 1；持续偏离或自由现金流长期为负，需在第一步与第六步查 WC、信用与再投资。' +
      'ROE 大于 20% 通常较优秀，但单年数据需对照历史。</p>' +
      '</section>';
  }

  function kpi(label, value, cls) {
    return '<div class="kpi"><div class="label">' + esc(label) + '</div>' +
      '<div class="value' + (cls ? " " + cls : "") + '">' + esc(value) + '</div></div>';
  }

  function renderStep1(d) {
    if (!d) return section("step1", "① 营收与盈利质量", '<div class="dash-loading">暂无数据</div>');
    var years = d.years || [];
    var b = d.basic || {};
    var q = d.quality || {};

    var fcfHelp = helpIcon("自由现金流 FCF 计算口径",
      '<div class="tt-title">计算口径</div>' +
      '<div class="tt-formula">FCF = 经营净现金流 − CAPEX</div>' +
      '<div class="tt-detail">CAPEX 取现金流量表中购建固定资产、无形资产和其他长期资产支付的现金；反映企业经营可自由支配的现金</div>');

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
      {
        labelHtml: "自由现金流 FCF" + fcfHelp,
        data: b.fcf,
        type: "yi",
      },
      ["毛利（收入−成本）", b.gross_profit, "yi"],
      ["毛利率", b.gross_margin, "pct"],
    ];

    var qualityRows = [
      ["① 扣非净利润 / 归母净利润", q.deduct_ratio, "ratio"],
      {
        labelHtml: "② 经营利润" + helpIcon("经营利润计算口径",
          '<div class="tt-title">计算口径</div>' +
          '<div class="tt-formula">经营利润 = 归母净利润 − 金融利润</div>' +
          '<div class="tt-detail">反映日常主营业务创造的利润</div>') +
          " / 归母净利润",
        data: q.operating_ratio,
        type: "ratio",
      },
      ["③ 经营现金流 / 归母净利润", q.cfnp, "num"],
      {
        labelHtml: "④ 自由现金流 FCF" + fcfHelp,
        data: b.fcf,
        type: "yi",
      },
      ["净利润 ÷ 归母净利润", q.net_profit_ratio, "ratio"],
    ];
    var qualityHints = [
      "差距小→主业盈利；归母小于扣非多为股权激励等，反之需查原因；多数年份差距大→改用扣非口径",
      {
        html: "金融利润" + helpIcon("金融利润计算口径",
          '<div class="tt-title">计算口径</div>' +
          '<div class="tt-formula">金融利润 ≈ 公允价值变动 + 投资收益</div>' +
          '<div class="tt-detail">可含净利息收入；联营/合营投资收益较大时可酌情扣除</div>') +
          "占比低→业务驱动获利；占比高→查投资收益、公允价值变动",
      },
      "同向、无量级差；利润增、现金流增更慢→警觉竞争恶化或会计风险",
      "偶发负→查 WC 增量与 Capex；持续负→生意难以现金自洽",
      "约等于 1 可忽略；远大于 1→警惕少数股东扛亏，不符合商业规律，往往是造假和操纵造成",
    ];

    var body = '<div class="framework-box"><strong>观察顺序：</strong>规模（收入/利润/利润率）→ 多年发展过程（起落原因）→ 盈利质量四关系（逐年对比）<br>' +
      '<strong>数据口径：</strong>年报 · 合并报表 · 单位亿元</div>' +
      guideHint('<strong>怎么看表：</strong>从左到右读时间轴，先看收入与利润体量，再看增速行的起落。' +
        '收入与利润「一落一起」或单年剧变时，<strong>需进一步确认</strong>：查当年年报「经营情况讨论与分析」、重大事项公告，弄清是战略调整、行业周期还是一次性因素。') +
      '<div class="sub-title">营收基本数据（单位：亿元）</div>' +
      renderYearTable(years, basicRows) +
      '<div class="sub-title">盈利质量四关系</div>' +
      guideHint('<strong>四关系：</strong>①扣非/归母 ②经营利润/归母（≈剔除金融收益）③经营现金流/归母净利润 ④自由现金流符号与持续性。' +
        '右侧「判断要点」列提示正常区间；③④异常时回到第六步 WC 表，核对应收、存货是否与收入同步增长。') +
      renderYearTable(years, qualityRows, qualityHints);

    return section("step1", "① 营收与盈利质量", body);
  }

  function renderStep2(d) {
    if (!d) return section("step2", "② 成本费用构成", "");
    var l = d.latest || {};
    var body = '<div class="framework-box"><strong>逻辑：</strong>毛利率反映竞争壁垒与客户转换成本；毛利率 − 净利率 → 期间费用与其他损益；费用结构揭示商业模式（研发驱动 vs 市场驱动）</div>' +
      guideHint('<strong>怎么看：</strong>毛利率与净利率折线图看多年趋势——代工转品牌、产品高端化常伴随毛利率抬升，但需<strong>同业对比</strong>区分企业能力与行业格局。' +
        '期间费用堆叠图看费用「花在哪」：技术型看研发率，To C 品牌看销售率；收入高增但销售费率仍升→问是否依赖投放；管理费率收入扩张时应下降（规模效应）。' +
        '毛利率减净利率差额很大时，<strong>需查</strong>投资收益、资产减值、营业外收支等非经常性项目。') +
      '<div class="metric-grid">' +
      metricCard("毛利率 − 净利率", fmtPct(l.margin_gap), "≈ 期间费用率") +
      metricCard("研发费用率", fmtPct(l.rd_rate), "", "技术型企业关键") +
      metricCard("销售费用率", fmtPct(l.sales_rate), "To C 品牌关键") +
      metricCard("管理费用率", fmtPct(l.admin_rate), "收入扩张时应呈下降趋势") +
      metricCard("财务费用率", fmtPct(l.finance_rate), "有息负债企业重点关注") +
      '</div>' +
      '<div class="sub-title">毛利率与净利率</div>' +
      chartGuide('<strong>读图：</strong>紫线毛利率、绿线净利率；两条线同步上行较健康。间距扩大→期间费用或其他损益吞噬利润；间距收窄→盈利效率改善或费用控制见效。') +
      '<div id="chart-step2-margin" class="chart-box"></div>' +
      chartGuide('<strong>读图：</strong>堆叠柱为各费用率占收入比重；柱体总高度≈期间费用率。研发（紫）与销售（蓝）谁主导，反映企业是技术驱动还是市场驱动；对比同业判断是否合理。') +
      '<div id="chart-step2-expense" class="chart-box"></div>';
    return section("step2", "② 成本费用构成", body);
  }

  function renderStep3(d) {
    if (!d) return section("step3", "③ 成长性", "");
    var l = d.latest || {};
    var body = '<div class="framework-box"><strong>适用：</strong>成长型企业重点看增速；关注 3/5 年复合增长率平滑单年波动；周期型、困境反转、隐蔽资产型需换分析重心</div>' +
      guideHint('<strong>怎么看：</strong>柱状图蓝柱为收入增速、绿柱为利润增速。单年利润暴增常因基数低（如扭亏次年），宜对照 3/5 年 CAGR 卡片看整体印象。' +
        '利润增速长期远超收入→利润率扩张是否可持续；利润负增长而收入正增长→<strong>需查</strong>费用、减值或毛利率变化。' +
        '高成长股增速放缓时，业绩与估值可能双重承压（戴维斯双杀），勿简单外推峰值年份。') +
      '<div class="metric-grid">' +
      metricCard("收入同比增速", fmtPct(l.revenue_yoy), "关注增速拐点") +
      metricCard("归母净利润同比增速", fmtPct(l.profit_yoy), "利润增速应与收入匹配") +
      metricCard("3 年复合增速（收入）", l.revenue_cagr3 != null ? "≈" + fmtPct(l.revenue_cagr3) : "—", "平滑单年波动") +
      metricCard("3 年复合增速（利润）", l.profit_cagr3 != null ? "≈" + fmtPct(l.profit_cagr3) : "—", "") +
      metricCard("5 年复合增速（收入）", l.revenue_cagr5 != null ? fmtPct(l.revenue_cagr5) : "—", "") +
      metricCard("5 年复合增速（利润）", l.profit_cagr5 != null ? fmtPct(l.profit_cagr5) : "—", "") +
      '</div>' +
      chartGuide('<strong>读图：</strong>关注增速拐点（由正转负或大幅放缓）及利润柱是否被截断（>200% 显示为 200%）。' +
        '逐年波动剧烈时，以 CAGR 为主、单年为辅；异常年份标记后去年报核对当年事件。') +
      '<div id="chart-step3-growth" class="chart-box"></div>';
    return section("step3", "③ 成长性", body);
  }

  function renderStep4(d) {
    var body = '<div class="framework-box"><strong>目标：</strong>拆分收入/毛利来源（产品/区域/渠道）；识别增长曲线与业务接力；理想态可量价拆解（量增还是价升）</div>' +
      guideHint('<strong>怎么看：</strong>结果数字背后是驱动力——哪条业务在增长、毛利贡献是否一致、OEM 是否在收缩、新品牌是否接力。' +
        '公开披露往往达不到产品级量价，<strong>数据不足时</strong>请查年报「主营业务分行业/分产品情况」，用故事验证数据、用数据验证故事。' +
        '分业务毛利率差异大时，未来整体毛利率可按各业务占比与毛利率加权估算。');
    if (!d || !d.available) {
      body += '<div class="unavailable-box">' + esc((d && d.message) || "分业务数据暂不可用") + '</div>';
    }
    return section("step4", "④ 业务构成", body);
  }

  function renderStep5(d) {
    if (!d) return section("step5", "⑤ 资产负债", "");
    var l = d.latest || {};
    var interestDebtHelp = helpIcon("有息负债计算口径",
      '<div class="tt-title">计算口径</div>' +
      '<div class="tt-formula">有息负债 = 短期借款 + 长期借款 + 应付债券 + 租赁负债 + 一年内到期非流动负债</div>');
    var nonInterestDebtHelp = helpIcon("无息负债计算口径",
      '<div class="tt-title">计算口径</div>' +
      '<div class="tt-formula">无息负债（狭义）= 应付账款 + 预收账款 + 合同负债</div>' +
      '<div class="tt-detail">不含应付工资、应付税费等与经营关联度较小的项目</div>');
    var finAssetHelp = helpIcon("金融资产计算口径",
      '<div class="tt-title">计算口径</div>' +
      '<div class="tt-formula">金融资产 = 货币资金 + 交易性金融资产 + 以公允价值计量且变动计入当期损益的金融资产 + 可供出售金融资产 + 持有至到期投资 + 债权投资</div>' +
      '<div class="tt-detail">理财、投资等非主营持有的金融资产；与经营资产拆分后用于计算净金融资产</div>');
    var opAssetHelp = helpIcon("经营资产计算口径",
      '<div class="tt-title">计算口径</div>' +
      '<div class="tt-formula">经营资产 = 总资产 − 金融资产</div>' +
      '<div class="tt-detail">服务日常经营活动的资产，如存货、应收、固定资产、无形资产、商誉等其余资产项目</div>');
    var opLiabHelp = helpIcon("经营负债计算口径",
      '<div class="tt-title">计算口径</div>' +
      '<div class="tt-formula">经营负债 = 总负债 − 有息负债</div>' +
      '<div class="tt-detail">无息负债及应付工资、税费等日常经营相关负债；有息负债视为金融负债</div>');
    var noaHelp = helpIcon("净经营资产计算口径",
      '<div class="tt-title">计算口径</div>' +
      '<div class="tt-formula">净经营资产 = 经营资产 − 经营负债</div>' +
      '<div class="tt-detail">经营资产 = 总资产 − 金融资产；经营负债 = 总负债 − 有息负债</div>');
    var nfaHelp = helpIcon("净金融资产计算口径",
      '<div class="tt-title">计算口径</div>' +
      '<div class="tt-formula">净金融资产 = 金融资产 − 金融负债</div>' +
      '<div class="tt-detail">金融负债取有息负债；为正表示净持有金融资产，为负表示净金融负债</div>');
    var body = '<div class="framework-box"><strong>观察要点：</strong>总资产结构 → 有息/无息债务 → 资产负债率 → 净经营资产 vs 净金融资产</div>' +
      guideHint('<strong>怎么看：</strong>业绩优秀、资产不重的公司，资产负债表信息量有限，<strong>一眼无异常即可</strong>。' +
        '重点盯：存货（面向消费者、制造类常藏雷）、有息负债占比、资产负债率超过 70%。' +
        '无息负债多通常意味对供应商/客户议价强；净金融资产为正→资金充裕。' +
        '归母净利润与净利润差距悬殊时，<strong>需查</strong>控股结构（利润在子公司还是母公司）。') +
      '<div class="metric-grid">' +
      compCard("总资产", fmtYi(l.total_assets) + " 亿",
        [["流动资产 " + fmtYi(l.current_assets) + " 亿", l.current_pct],
         ["非流动资产 " + fmtYi(l.noncurrent_assets) + " 亿", l.noncurrent_pct]]) +
      metricCard("资产负债率", fmtPct(l.debt_ratio), "", l.debt_ratio > 70 ? ">70% 需重点关注" : "") +
      compCard("有息负债 / 无息负债", "", [
        { html: "有息负债" + interestDebtHelp + " " + fmtYi(l.interest_debt) + " 亿", pct: l.interest_pct },
        { html: "无息负债" + nonInterestDebtHelp + " " + fmtYi(l.non_interest_debt) + " 亿", pct: l.non_interest_pct },
      ]) +
      metricCard("", (l.noa >= 0 ? "" : "") + fmtYi(l.noa) + " 亿", "为正 → 日常经营净投入", "",
        "净经营资产 NOA" + noaHelp) +
      metricCard("", (l.nfa >= 0 ? "+" : "") + fmtYi(l.nfa) + " 亿", "为正 → 净持有金融资产", "",
        "净金融资产" + nfaHelp) +
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
        { labelHtml: "有息负债" + interestDebtHelp, key: "interest_debt", level: "category" },
        { label: "应付账款", key: "accounts_payable", level: "detail" },
        { label: "预收账款", key: "advance_receivables", level: "detail" },
        { label: "合同负债", key: "contract_liab", level: "detail" },
        { labelHtml: "无息负债（狭义）" + nonInterestDebtHelp, key: "non_interest_debt", level: "category" },
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
        var rowLabel = row.labelHtml ? row.labelHtml : esc(row.label);
        body += '<tr class="' + rowCls + '"><td class="row-label">' + rowLabel + '</td>';
        d.table.forEach(function (col) {
          var v = col[row.key];
          body += '<td class="num">' + (row.fmt === "pct" ? fmtPct(v) : fmtCell(v)) + '</td>';
        });
        body += '</tr>';
      });
      body += '</tbody></table></div>';
      if (d.reconstruct_table && d.reconstruct_table.length) {
        body += '<div class="sub-title" style="margin-top:16px">资产负债重构表</div>' +
          reconstructGuideHtml(opAssetHelp, opLiabHelp, finAssetHelp, interestDebtHelp) +
          guideHint('<strong>怎么看表：</strong>从左到右看多年趋势；先核对<strong>净资产 ≈ 净经营资产 + 净金融资产</strong>是否大致成立（拆分口径一致时应对得上）。' +
            '<strong>净经营资产</strong>为正→为日常经营净投入净资产；为负→更多靠供应商、预收款等他人资金经营（可对照第六步 WC 理解上下游地位）。' +
            '<strong>净金融资产</strong>为正→净持有金融资产、资金较充裕；为负→净金融负债、经营部分靠借贷支撑。' +
            '<strong>净经营资产收益率</strong>反映经营资产创利效率，越高越好；单年异常或剧烈波动→查经营利润质量、并购或资产重分类。' +
            '业绩优秀、资产不重的公司通常一眼无大碍；有疑点再回上方资产负债表逐项核对。') +
          renderSimpleTable(d.reconstruct_table, [
            { label: "净资产 / 亿元", key: "net_equity" },
            { label: "净经营资产 / 亿元", key: "noa" },
            { label: "净金融资产 / 亿元", key: "nfa" },
            { label: "净经营资产收益率 / %", key: "noa_return", pct: true },
          ]);
      }
    }
    return section("step5", "⑤ 资产负债", body);
  }

  function renderStep6(d) {
    if (!d) return section("step6", "⑥ 投入产出", "");
    var body = '<div class="framework-box"><strong>三维投入：</strong>营运资本 WC、固定资产/长期资产、人力。核心效率：<strong>1 元收入需要的 WC / 固定资产</strong>，需看历史趋势并与同业对比</div>' +
      guideHint('<strong>怎么看：</strong>WC 反映商业模式与上下游地位——强势企业可少赊销、多占供应商资金（指标低甚至为负）。' +
        '应收或存货增速大幅超过收入→<strong>需警觉</strong>竞争恶化、放宽信用或跌价准备不足；新增 WC 大增时查转型、备货策略。' +
        '固定资产图看资产「重不重」；长期资产远高于固定资产→查商誉、无形资产；单年人均固定资产剧变→查并购、自建办公楼等是否有效投资。') +
      '<div class="sub-title">一元收入需要 WC</div>' +
      chartGuide('<strong>读图：</strong>纵轴为每 1 元销售收入需垫付的营运资金（元）。趋势上行→占用流动资金增多；下行或转负→对上下游议价增强。单点数据不可靠时对照 3–5 年均值。') +
      '<div id="chart-step6-wc" class="chart-box" style="margin-top:0"></div>' +
      '<p class="anno-note">WC（狭义）= 应收 + 预付 + 存货 + 合同资产 − 应付 − 预收 − 合同负债；1 元收入需要的 WC = WC ÷ 销售收入。用于 DCF 再投资估算与竞争地位侧面判断。</p>';

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
      chartGuide('<strong>读图：</strong>蓝线固定资产、紫线长期经营资产。两者差距大→关注商誉、开发支出等；制造业固定资产仍很低→可能是代工/轻资产模式。' +
        '折旧占收入低且固定资产占比低→并非典型重资产制造。') +
      '<div id="chart-step6-fa" class="chart-box" style="margin-top:0"></div>' +
      '<p class="anno-note">固定资产 = 固定资产 + 在建工程 + 工程物资 + 固定资产清理；长期经营资产另含无形资产、开发支出、使用权资产、商誉等。1 元收入需要的固定资产 = 固定资产 ÷ 销售收入。</p>';

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
    return section("step6", "⑥ 投入产出（WC · 固定资产 · 人力）", body);
  }

  function renderStep7(d) {
    if (!d) return section("step7", "⑦ 收益率（ROE 拆解）", "");
    var l = d.latest || {};
    var body = '<div class="framework-box"><strong>杜邦：</strong>ROE = 销售净利率 × 总资产周转率 × 权益乘数；ROE 持续高于 20% 较优秀，但要看持续性与驱动因子</div>' +
      guideHint('<strong>怎么看：</strong>三线图看 ROE/ROA/ROIC 历史——单年 ROE 极高可能是峰值（收入暴增或低基数），<strong>需对照杜邦表</strong>看是利润率、周转还是杠杆驱动。' +
        '净利率上升驱动 ROE 较良性；靠杠杆抬 ROE 需警惕。ROIC 与 ROE 偏离大→查资本结构与金融资产。' +
        '资产周转天数可进一步拆解应收、存货周转，收入快增时周转加快通常是好事。') +
      '<div class="metric-grid">' +
      metricCard("ROE（摊薄/加权）", fmtPct(l.roe), "", ">20% 较优秀") +
      metricCard("ROA", fmtPct(l.roa), "去杠杆后总资产获利能力") +
      metricCard("ROIC", fmtPct(l.roic), "无杠杆盈利") +
      metricCard("销售净利率（杜邦）", fmtPct(l.net_profit_rate), "") +
      metricCard("总资产周转率", l.turnover != null ? fmtNum(l.turnover, 2) + " 次" : "—", "") +
      metricCard("权益乘数", l.leverage != null ? fmtNum(l.leverage, 2) : "—", "杠杆水平") +
      '</div>' +
      chartGuide('<strong>读图：</strong>蓝 ROE、绿 ROA、紫 ROIC。ROA 反映去杠杆后总资产获利能力；ROE 与 ROA 差距来自财务杠杆。' +
        '某年 ROE/ROA/ROIC 同时大幅波动→回到第一步查当年利润质量与资产负债表异常。') +
      '<div id="chart-step7-roe" class="chart-box"></div>';

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
    return section("step7", "⑦ 收益率（ROE 拆解）", body);
  }

  function renderEight() {
    var intro = guideHint('<strong>怎么用：</strong>财务数字是业务在货币维度的呈现；八问是研读公告、深度研报、行业文章时的<strong>问题清单</strong>。' +
      '看报表时发现疑问→带着问题读材料；读材料时→回到看板核对数字。最后做「两分钟独白」：为什么感兴趣、成功条件、主要风险。' +
      '看不懂也是结论，代表超出能力圈。');
    var cards = EIGHT_QUESTIONS.map(function (item, i) {
      return '<div class="q-card"><div class="q-num">Q' + (i + 1) + '</div>' +
        '<div class="q-text">' + esc(item.q) + '</div>' +
        '<div class="q-note">' + esc(item.note) + '</div></div>';
    }).join("");
    return section("eight", "商业八问（非财务定性）", intro + '<div class="eight-q">' + cards + '</div>');
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

  function section(id, title, body) {
    return '<section id="' + id + '" class="dash-section">' +
      '<div class="section-header"><h2>' + esc(title) + '</h2></div>' +
      '<div class="section-body">' + body + '</div></section>';
  }

  function metricCard(name, val, hint, threshold, nameHtml) {
    var nameBlock = nameHtml
      ? '<div class="m-name-row"><span class="m-name" style="margin:0">' + nameHtml + '</span></div>'
      : '<div class="m-name">' + esc(name) + '</div>';
    return '<div class="metric-card">' + nameBlock +
      '<div class="m-val">' + esc(val) + '</div>' +
      (hint ? '<div class="m-hint">' + esc(hint) + '</div>' : '') +
      (threshold ? '<div class="m-threshold">' + esc(threshold) + '</div>' : '') +
      '</div>';
  }

  function compCard(name, val, rows) {
    function rowPct(r) {
      return r.pct != null ? r.pct : r[1];
    }
    var comp = rows.map(function (r) {
      var label = r.html ? r.html : esc(r[0]);
      return '<div class="comp-row"><span>' + label + '</span><span class="comp-pct">' + fmtPct(rowPct(r)) + '</span></div>';
    }).join("");
    var bar = rows.length === 2 ?
      '<div class="comp-bar"><span style="width:' + (rowPct(rows[0]) || 0) + '%"></span><span style="width:' + (rowPct(rows[1]) || 0) + '%"></span></div>' : "";
    return '<div class="metric-card"><div class="m-name">' + esc(name) + '</div>' +
      (val ? '<div class="m-val">' + esc(val) + '</div>' : '') +
      '<div class="m-composition">' + comp + bar + '</div></div>';
  }

  function reconstructGuideHtml(opAssetHelp, opLiabHelp, finAssetHelp, interestDebtHelp) {
    function formulaRow(label, exprHtml) {
      return '<div class="reconstruct-formula-item">' +
        '<span class="eq-label">' + esc(label) + '</span>' +
        '<span class="eq-expr">' + exprHtml + '</span></div>';
    }
    return '<div class="reconstruct-guide">' +
      '<div class="reconstruct-guide-title">计算口径</div>' +
      '<div class="reconstruct-formula-list">' +
      formulaRow("净资产", '<span class="eq-formula">资产合计 − 负债合计</span>' +
        '<span class="eq-connector">=</span>' +
        '<span class="eq-formula">净经营资产 + 净金融资产</span>') +
      formulaRow("净经营资产", '<span class="eq-formula">经营资产' + opAssetHelp + ' − 经营负债' + opLiabHelp + '</span>') +
      formulaRow("净金融资产", '<span class="eq-formula">金融资产' + finAssetHelp + ' − 有息负债' + interestDebtHelp + '</span>') +
      '</div>' +
      '<div class="reconstruct-guide-foot">' +
      '<span class="eq-foot-label">净经营资产收益率</span>' +
      '<span class="eq-formula">经营利润 ÷ 净经营资产</span>' +
      '<span class="eq-foot-note">（经营利润见第一步口径）</span></div>' +
      '</div>';
  }

  function helpIcon(ariaLabel, tooltipHtml) {
    return '<span class="help-icon" tabindex="0" aria-label="' + esc(ariaLabel) + '">?' +
      '<span class="help-tooltip help-tooltip-lg">' + tooltipHtml + '</span></span>';
  }

  function renderYearTable(years, rows, hints) {
    var h = '<div class="table-wrap"><table class="data-table"><thead><tr><th>指标</th>';
    years.forEach(function (y) { h += '<th>' + esc(y) + '</th>'; });
    if (hints) h += '<th>判断要点</th>';
    h += '</tr></thead><tbody>';
    rows.forEach(function (row, i) {
      var label, data, type;
      if (row.labelHtml) {
        label = row.labelHtml;
        data = row.data;
        type = row.type;
      } else {
        label = esc(row[0]);
        data = row[1];
        type = row[2];
      }
      h += '<tr><td class="row-label">' + label + '</td>';
      (data || []).forEach(function (v) {
        h += '<td class="num">' + fmtByType(v, type) + '</td>';
      });
      if (hints) {
        var hint = hints[i];
        if (hint && hint.html) {
          h += '<td class="hint-cell">' + hint.html + '</td>';
        } else {
          h += '<td class="hint-cell">' + esc(hint || "") + '</td>';
        }
      }
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
