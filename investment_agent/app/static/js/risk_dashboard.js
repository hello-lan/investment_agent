(function () {
  var searchInput = document.getElementById("riskSearch");
  var gradeFilter = document.getElementById("gradeFilter");
  var refreshBtn = document.getElementById("refreshBtn");
  var summaryEl = document.getElementById("riskSummary");
  var emptyEl = document.getElementById("riskEmpty");
  var listEl = document.getElementById("riskList");
  var detailEl = document.getElementById("riskDetail");
  var detailContent = document.getElementById("riskDetailContent");
  var backBtn = document.getElementById("backBtn");

  var allReports = [];
  var searchTimer = null;

  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function badgeClass(grade) {
    return "risk-badge risk-badge-" + (grade || "neutral");
  }

  function loadReports() {
    var q = searchInput.value.trim();
    var grade = gradeFilter.value;
    var url = "/api/risk-dashboard/reports?q=" + encodeURIComponent(q);
    if (grade) url += "&grade=" + encodeURIComponent(grade);

    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        allReports = data.reports || [];
        renderSummary(data.summary || {});
        if (!allReports.length) {
          emptyEl.style.display = "block";
          listEl.style.display = "none";
        } else {
          emptyEl.style.display = "none";
          listEl.style.display = "grid";
          renderList(allReports);
        }
      })
      .catch(function (err) {
        emptyEl.innerHTML = '<p style="color:var(--danger)">加载失败: ' + esc(String(err)) + '</p>';
      });
  }

  function renderSummary(s) {
    summaryEl.innerHTML =
      kpi("总计", s.total || 0) +
      kpi("极高风险", s.critical || 0, "critical") +
      kpi("高风险", s.high || 0, "high") +
      kpi("存疑", s.warn || 0, "warn") +
      kpi("通过", s.pass || 0, "pass");
  }

  function kpi(label, val, grade) {
    var color = grade === "critical" || grade === "high" ? "var(--danger)"
      : grade === "warn" ? "var(--warn)" : grade === "pass" ? "var(--accent2)" : "var(--text)";
    return '<div class="risk-kpi"><div class="label">' + esc(label) + '</div>' +
      '<div class="value" style="color:' + color + '">' + val + '</div></div>';
  }

  function renderList(reports) {
    listEl.innerHTML = reports.map(function (r) {
      var drivers = (r.drivers || []).slice(0, 2).map(function (d) {
        return "<li>" + esc(d) + "</li>";
      }).join("");
      return '<div class="risk-card" data-path="' + esc(r.file_path || "") + '">' +
        '<div class="risk-card-header">' +
          '<span class="risk-card-title">' + esc(r.company || r.code) + ' <span style="color:var(--muted);font-weight:400">' + esc(r.code) + '</span></span>' +
          '<span class="' + badgeClass(r.risk_grade) + '">' + esc(r.risk_level || "未知") + '</span>' +
        '</div>' +
        '<div class="risk-card-meta">' +
          esc(r.report_period || "") + ' · 结论: ' + esc(r.conclusion || "-") +
          ' · 疑点 ' + (r.red_flag_count || 0) + ' 项' +
        '</div>' +
        (drivers ? '<ul class="risk-drivers">' + drivers + '</ul>' : '') +
      '</div>';
    }).join("");

    listEl.querySelectorAll(".risk-card").forEach(function (card) {
      card.addEventListener("click", function () {
        showDetail(card.getAttribute("data-path"));
      });
    });
  }

  function showDetail(path) {
    if (!path) return;
    fetch("/api/risk-dashboard/detail?path=" + encodeURIComponent(path))
      .then(function (r) { return r.json(); })
      .then(function (r) {
        listEl.style.display = "none";
        summaryEl.style.display = "none";
        emptyEl.style.display = "none";
        detailEl.style.display = "block";

        var flags = (r.red_flags || []).map(function (f) {
          return '<li class="risk-flag-item"><strong>' + esc(f.section) + '</strong> · ' + esc(f.name) +
            (f.rule ? '<div class="risk-flag-rule">' + esc(f.rule) + '</div>' : '') + '</li>';
        }).join("");

        detailContent.innerHTML =
          '<div class="risk-detail-section">' +
            '<div style="display:flex;justify-content:space-between;align-items:center">' +
              '<h2 style="font-size:18px">' + esc(r.company) + ' (' + esc(r.code) + ')</h2>' +
              '<span class="' + badgeClass(r.risk_grade) + '">' + esc(r.risk_level) + '</span>' +
            '</div>' +
            '<p class="risk-card-meta" style="margin-top:8px">' +
              esc(r.report_period) + ' · ' + esc(r.analysis_date) + ' · 置信度 ' + esc(r.confidence || "-") +
            '</p>' +
            '<p style="margin-top:12px;font-size:14px"><strong>结论：</strong>' + esc(r.conclusion) + '</p>' +
            (r.audit_opinion ? '<p style="margin-top:8px;font-size:13px;color:var(--muted)">审计意见：' + esc(r.audit_opinion) + '</p>' : '') +
            (r.cf_portrait ? '<p style="margin-top:8px;font-size:13px;color:var(--muted)">现金流肖像：' + esc(r.cf_portrait) + '</p>' : '') +
          '</div>' +
          (flags ? '<div class="risk-detail-section"><h3>疑点清单 (' + (r.red_flag_count || 0) + ')</h3><ul class="risk-flag-list">' + flags + '</ul></div>' : '') +
          (r.drivers && r.drivers.length ? '<div class="risk-detail-section"><h3>主要驱动因素</h3><ul class="risk-drivers">' +
            r.drivers.map(function (d) { return '<li>' + esc(d) + '</li>'; }).join("") + '</ul></div>' : '');
      });
  }

  backBtn.addEventListener("click", function () {
    detailEl.style.display = "none";
    summaryEl.style.display = "grid";
    loadReports();
  });

  searchInput.addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadReports, 300);
  });
  gradeFilter.addEventListener("change", loadReports);
  refreshBtn.addEventListener("click", loadReports);

  loadReports();
})();
