// ── Utils ──

function esc(s) {
  return String(s != null ? s : '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatNum(n) {
  if (n == null) return '-';
  return Number(n).toLocaleString();
}

function formatCost(c, currency) {
  if (c == null) return '-';
  var symbol = currency === 'CNY' ? '¥' : '$';
  return symbol + Number(c).toFixed(4);
}

function formatTime(t) {
  if (!t) return '-';
  var s = String(t).replace('T', ' ').slice(0, 19);
  if (s.length >= 16) s = s.slice(5, 16); // MM-DD HH:mm
  return s;
}

function formatFullTime(t) {
  if (!t) return '-';
  return String(t).replace('T', ' ').slice(0, 19);
}

function shortId(id) {
  if (!id) return '-';
  return id.length > 8 ? id.slice(0, 8) + '…' : id;
}

function parseDetail(d) {
  if (!d) return {};
  try { return JSON.parse(d); } catch (e) { return {}; }
}

// ── Event type → badge class ──

var EVT_CATEGORY = {
  tool_call: 'tool', tool_result: 'tool',
  text_delta: 'engine', slow_think: 'engine', done: 'engine',
  error: 'engine', interrupted: 'engine',
  context_budget: 'system', cache_metrics: 'system'
};

function evtCategory(type) {
  return EVT_CATEGORY[type] || 'system';
}

// ── State ──

var _timer = null;
var _isLoading = false;
var _activeTab = 'traces';
var _cachedSessions = [];
var _lastTraceTime = null;
var _lastCostTime = null;
var _prevSessionId = '';
var _prevTaskId = '';

function updateLastTraceTime(rows) {
  var maxT = null;
  for (var i = 0; i < rows.length; i++) {
    var t = rows[i].created_at;
    if (t && (!maxT || t > maxT)) maxT = t;
  }
  if (maxT) _lastTraceTime = maxT;
}

function updateLastCostTime(rows) {
  var maxT = null;
  for (var i = 0; i < rows.length; i++) {
    var t = rows[i].created_at;
    if (t && (!maxT || t > maxT)) maxT = t;
  }
  if (maxT) _lastCostTime = maxT;
}

// ── Filters ──

function getFilters() {
  return {
    session_id: document.getElementById('sessionId').value.trim(),
    task_id: document.getElementById('taskId').value.trim(),
    limit: parseInt(document.getElementById('limit').value || '200'),
  };
}

function buildQuery(filters) {
  var p = new URLSearchParams();
  if (filters.session_id) p.set('session_id', filters.session_id);
  if (filters.task_id) p.set('task_id', filters.task_id);
  if (filters.limit) p.set('limit', String(filters.limit));
  if (filters.since) p.set('since', filters.since);
  return p.toString();
}

// ── Tab switching ──

function switchTab(name) {
  _activeTab = name;
  document.querySelectorAll('.obs-tab').forEach(function(el) {
    if (el.dataset.tab === name) el.classList.add('active');
    else el.classList.remove('active');
  });
  document.querySelectorAll('.obs-tab-panel').forEach(function(el) {
    if (el.id === 'tab-' + name) el.classList.add('active');
    else el.classList.remove('active');
  });
  resetTimer();
  loadData();
}

// ── Data loading router ──

async function loadData() {
  if (_isLoading || document.visibilityState !== 'visible') return;
  _isLoading = true;
  try {
    if (_activeTab === 'traces') await loadTraces();
    else if (_activeTab === 'tokens') await loadTokens();
    else if (_activeTab === 'cost') await loadCost();
    document.getElementById('lastUpdated').textContent = '最后更新：' + new Date().toLocaleTimeString();
  } finally {
    _isLoading = false;
  }
}

async function loadTraces() {
  var elError = document.getElementById('traceError');
  var elEmpty = document.getElementById('traceEmpty');
  var elContent = document.getElementById('traceContent');
  elError.style.display = 'none';

  var filters = getFilters();
  // 用户过滤条件变更 → 全量刷新
  if (filters.session_id !== _prevSessionId || filters.task_id !== _prevTaskId) {
    _lastTraceTime = null;
    _prevSessionId = filters.session_id;
    _prevTaskId = filters.task_id;
  }
  // 增量刷新：带上 since（无过滤条件时才增量）
  if (_lastTraceTime && !filters.session_id && !filters.task_id) {
    filters.since = _lastTraceTime;
  }

  try {
    var q = buildQuery(filters);
    var rows = await fetch('/api/observability/traces?' + q).then(function(r) { return r.json(); });

    if (_lastTraceTime) {
      // 增量模式
      if (!rows.length) return; // 无新数据，不动 DOM
      mergeNewTraces(rows);
      updateLastTraceTime(rows);
    } else {
      // 全量模式
      elEmpty.style.display = 'none';
      if (!rows.length) { elEmpty.style.display = ''; return; }
      var html = buildAllTracesHtml(rows);
      elContent.innerHTML = html;
      updateLastTraceTime(rows);
    }
  } catch (e) {
    elError.textContent = '加载失败：' + e.message;
    elError.style.display = '';
  }
}

async function loadTokens() {
  var elError = document.getElementById('tokenError');
  var elEmpty = document.getElementById('tokenEmpty');
  elError.style.display = 'none';
  elEmpty.style.display = 'none';

  try {
    var sessions = await fetch('/api/observability/sessions?limit=200').then(function(r) { return r.json(); });
    if (!sessions.length) { elEmpty.style.display = ''; return; }
    _cachedSessions = sessions;
    updateSummaryStats(sessions);
    renderSessionTable(sessions);
    populateComparisonDropdowns(sessions);
  } catch (e) {
    elError.textContent = '加载失败：' + e.message;
    elError.style.display = '';
  }
}

async function loadCost() {
  var elError = document.getElementById('costError');
  var elEmpty = document.getElementById('costEmpty');
  var tbody = document.querySelector('#costTable tbody');
  elError.style.display = 'none';

  var filters = getFilters();
  if (filters.session_id !== _prevSessionId || filters.task_id !== _prevTaskId) {
    _lastCostTime = null;
    _prevSessionId = filters.session_id;
    _prevTaskId = filters.task_id;
  }
  if (_lastCostTime && !filters.session_id && !filters.task_id) {
    filters.since = _lastCostTime;
  }

  try {
    var q = buildQuery(filters);
    var rows = await fetch('/api/observability/cost?' + q).then(function(r) { return r.json(); });

    if (_lastCostTime) {
      if (!rows.length) return;
      // 新增行前插到 tbody 顶部
      tbody.insertAdjacentHTML('afterbegin', buildCostRows(rows));
      updateLastCostTime(rows);
    } else {
      elEmpty.style.display = 'none';
      if (!rows.length) { elEmpty.style.display = ''; return; }
      tbody.innerHTML = buildCostRows(rows);
      updateLastCostTime(rows);
    }
  } catch (e) {
    elError.textContent = '加载失败：' + e.message;
    elError.style.display = '';
  }
}

// ── Hierarchical Trace Rendering ──

function buildAllTracesHtml(rows) {
  var grouped = groupTraces(rows);
  var html = '';
  grouped.forEach(function(session) {
    html += buildSessionAccordion(session.id, session.tasks);
  });
  return html;
}

function buildSessionAccordion(sessionId, taskMap) {
  var tasks = Array.from(taskMap.values());

  // sort tasks by first step time descending
  tasks.sort(function(a, b) {
    var ta = a[0] ? a[0].created_at : '';
    var tb = b[0] ? b[0].created_at : '';
    return String(tb).localeCompare(String(ta));
  });

  var firstWithTokens = tasks.reduce(function(found, steps) {
    if (found) return found;
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].input_tokens != null || steps[i].output_tokens != null) return steps[i];
    }
    return null;
  }, null);
  var totalIn = firstWithTokens ? firstWithTokens.input_tokens : null;
  var totalOut = firstWithTokens ? firstWithTokens.output_tokens : null;
  var model = firstWithTokens ? firstWithTokens.model : null;
  var agentName = tasks.reduce(function(found, steps) {
    if (found) return found;
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].agent_name) return steps[i].agent_name;
    }
    return null;
  }, null);

  var times = tasks.map(function(steps) { return steps[0] && steps[0].created_at; }).filter(Boolean).sort();
  var tFirst = times[0], tLast = times[times.length - 1];

  var html = '<div class="obs-accordion" data-sid="' + esc(sessionId) + '">';
  html += '<div class="obs-acc-header session-level" onclick="toggleAcc(this)">';
  html += '<span class="obs-arrow">▶</span>';
  html += '<span class="obs-session-id" title="' + esc(sessionId) + '">' + esc(shortId(sessionId)) + '</span>';
  html += '<span class="obs-session-meta">';
  html += '<span class="obs-meta-tasks">📋 ' + tasks.length + ' 个任务</span>';
  if (totalIn != null) html += '<span class="obs-meta-in">🔤 输入 ' + formatNum(totalIn) + '</span>';
  if (totalOut != null) html += '<span class="obs-meta-out">🔤 输出 ' + formatNum(totalOut) + '</span>';
  html += '<span class="obs-meta-time">📅 ' + formatTime(tFirst) + ' ~ ' + formatTime(tLast) + '</span>';
  if (model) html += '<span class="obs-badge obs-badge-model">' + esc(model) + '</span>';
  if (agentName) html += '<span class="obs-badge" style="background:#e8eaf6;color:#3949ab;">' + esc(agentName) + '</span>';
  html += '</span></div>';

  html += '<div class="obs-acc-body"><div style="padding:4px 0;">';
  tasks.forEach(function(steps) { html += renderTaskAccordion(steps); });
  html += '</div></div></div>';
  return html;
}

function groupTraces(rows) {
  var sessions = new Map();
  rows.forEach(function(r) {
    var sid = r.session_id || '__unknown__';
    var tid = r.task_id || '__unknown__';
    if (!sessions.has(sid)) sessions.set(sid, { id: sid, tasks: new Map() });
    var session = sessions.get(sid);
    if (!session.tasks.has(tid)) session.tasks.set(tid, []);
    session.tasks.get(tid).push(r);
  });
  // Sort steps within each task
  sessions.forEach(function(session) {
    session.tasks.forEach(function(steps) {
      steps.sort(function(a, b) {
        var sa = a.step, sb = b.step;
        if (sa == null && sb == null) return String(a.created_at || '').localeCompare(String(b.created_at || ''));
        if (sa == null) return -1;
        if (sb == null) return 1;
        return sa - sb;
      });
    });
  });
  return sessions;
}

function renderTaskAccordion(steps) {
  if (!steps.length) return '';
  var first = steps[0];
  var taskId = first.task_id || '';
  var model = first.model;
  var inTok = first.input_tokens;
  var outTok = first.output_tokens;

  // Extract context_budget and cache_metrics
  var ctxBudgetIdx = -1;
  var ctxSteps = [];
  for (var i = 0; i < steps.length; i++) {
    if (steps[i].event_type === 'context_budget') ctxBudgetIdx = i;
    if (steps[i].event_type === 'cache_metrics') ctxSteps.push(steps[i]);
  }
  var ctxCard = '';
  if (ctxBudgetIdx !== -1) {
    ctxCard = renderContextBudget(steps[ctxBudgetIdx].detail);
  }

  // Time range
  var times = steps.map(function(s) { return s.created_at; }).filter(Boolean).sort();
  var tFirst = times[0], tLast = times[times.length - 1];

  var html = '<div class="obs-accordion" data-tid="' + esc(taskId) + '">';
  html += '<div class="obs-acc-header task-level" onclick="toggleAcc(this)">';
  html += '<span class="obs-arrow">▶</span>';
  html += '<span class="obs-task-id" title="' + esc(taskId) + '">' + esc(shortId(taskId)) + '</span>';
  html += '<span class="obs-task-meta">';
  if (model) html += '<span>模型 ' + esc(model) + '</span>';
  if (inTok != null) html += '<span>输入 ' + formatNum(inTok) + '</span>';
  if (outTok != null) html += '<span>输出 ' + formatNum(outTok) + '</span>';
  html += '<span>' + steps.length + ' 个事件</span>';
  html += '<span>📅 ' + formatTime(tFirst) + '</span>';
  html += '</span></div>';

  html += '<div class="obs-acc-body">';
  html += ctxCard;

  // Also show cache_metrics as system cards
  ctxSteps.forEach(function(cs) {
    var detail = parseDetail(cs.detail);
    html += '<div class="obs-ctx-card">';
    html += '<div class="obs-ctx-title">🗂️ Cache Metrics</div>';
    html += '<div style="font-size:11px;color:#555;">';
    if (detail.cache_read_tokens) html += 'cache_read: ' + formatNum(detail.cache_read_tokens) + ' &nbsp; ';
    if (detail.cache_creation_tokens) html += 'cache_creation: ' + formatNum(detail.cache_creation_tokens);
    html += '</div></div>';
  });

  // Step rows (exclude context_budget, it's already shown as a card)
  steps.forEach(function(s) {
    if (s.event_type === 'context_budget') return;
    html += buildStepRow(s);
  });

  html += '</div></div>';
  return html;
}

function renderContextBudget(detailJson) {
  var d = parseDetail(detailJson);
  var sys = d.system_tokens != null ? formatNum(d.system_tokens) : '-';
  var tools = d.tools_tokens != null ? formatNum(d.tools_tokens) : '-';
  var msgs = d.messages_tokens != null ? formatNum(d.messages_tokens) : '-';
  var total = d.total_tokens != null ? formatNum(d.total_tokens) : '-';
  var maxT = d.model_max_tokens != null ? formatNum(d.model_max_tokens) : '-';
  var warnings = Array.isArray(d.warnings) ? d.warnings : [];

  var html = '<div class="obs-ctx-card">';
  html += '<div class="obs-ctx-title">📐 上下文预算</div>';
  html += '<div class="obs-ctx-grid">';
  html += '<div class="obs-ctx-item"><div class="obs-ctx-value">' + sys + '</div><div class="obs-ctx-label">System</div></div>';
  html += '<div class="obs-ctx-item"><div class="obs-ctx-value">' + tools + '</div><div class="obs-ctx-label">Tools</div></div>';
  html += '<div class="obs-ctx-item"><div class="obs-ctx-value">' + msgs + '</div><div class="obs-ctx-label">Messages</div></div>';
  html += '<div class="obs-ctx-item"><div class="obs-ctx-value">' + total + ' / ' + maxT + '</div><div class="obs-ctx-label">总计 / 上限</div></div>';
  html += '</div>';
  if (warnings.length) {
    html += '<div class="obs-ctx-warn">⚠ ' + warnings.map(esc).join(', ') + '</div>';
  }
  html += '</div>';
  return html;
}

function toggleAcc(header) {
  var body = header.nextElementSibling;
  if (!body || !body.classList.contains('obs-acc-body')) return;
  var isOpen = body.classList.contains('open');
  if (isOpen) {
    body.classList.remove('open');
    header.classList.remove('open');
  } else {
    body.classList.add('open');
    header.classList.add('open');
  }
}

function buildStepRow(step) {
  var cat = evtCategory(step.event_type);
  var timeStr = formatFullTime(step.created_at);
  var stepNum = step.step != null ? step.step : '—';
  var detailText = '';
  var detailObj = parseDetail(step.detail);
  if (step.event_type === 'tool_call' && detailObj.tool_name) {
    detailText = detailObj.tool_name;
    if (detailObj.tool_input) {
      var inputStr = typeof detailObj.tool_input === 'string' ? detailObj.tool_input : JSON.stringify(detailObj.tool_input);
      detailText += '(' + inputStr.slice(0, 80) + ')';
    }
  } else if (step.event_type === 'tool_result' && detailObj.tool_name) {
    detailText = detailObj.tool_name + ' → ' + esc(String(detailObj.result_preview || '').slice(0, 100));
  } else if (step.event_type === 'cache_metrics') {
    detailText = 'cache_read: ' + (detailObj.cache_read_tokens || 0) + ' / cache_creation: ' + (detailObj.cache_creation_tokens || 0);
  } else if (step.event_type === 'done' && detailObj.usage) {
    detailText = '完成 — 输入 ' + formatNum(detailObj.usage.input_tokens) + ' / 输出 ' + formatNum(detailObj.usage.output_tokens);
  } else {
    detailText = esc(String(step.detail || '').slice(0, 120));
  }
  return '<div class="obs-step-row" data-trace-id="' + esc(step.id) + '">' +
    '<span class="obs-step-num">' + stepNum + '</span>' +
    '<span class="obs-step-time">' + esc(timeStr) + '</span>' +
    '<span><span class="obs-evt-badge obs-evt-' + cat + '">' + esc(step.event_type) + '</span>' +
    ' <span class="obs-step-detail">' + detailText + '</span></span>' +
    '</div>';
}

function updateSessionHeader(sessionEl, taskMap) {
  var header = sessionEl.querySelector(':scope > .obs-acc-header');
  if (!header) return;
  var tasks = Array.from(taskMap.values());
  var metaEl = header.querySelector('.obs-session-meta');
  if (!metaEl) return;

  // Update task count
  var tasksSpan = metaEl.querySelector('.obs-meta-tasks');
  if (tasksSpan) tasksSpan.textContent = '📋 ' + tasks.length + ' 个任务';

  // Update token count from first task with tokens
  var firstWithTokens = null;
  tasks.forEach(function(steps) {
    if (firstWithTokens) return;
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].input_tokens != null || steps[i].output_tokens != null) {
        firstWithTokens = steps[i];
        return;
      }
    }
  });
  var inSpan = metaEl.querySelector('.obs-meta-in');
  var outSpan = metaEl.querySelector('.obs-meta-out');
  if (firstWithTokens) {
    if (inSpan) inSpan.textContent = '🔤 输入 ' + formatNum(firstWithTokens.input_tokens);
    else if (firstWithTokens.input_tokens != null) {
      inSpan = document.createElement('span');
      inSpan.className = 'obs-meta-in';
      inSpan.textContent = '🔤 输入 ' + formatNum(firstWithTokens.input_tokens);
      metaEl.insertBefore(inSpan, metaEl.querySelector('.obs-meta-time'));
    }
    if (outSpan) outSpan.textContent = '🔤 输出 ' + formatNum(firstWithTokens.output_tokens);
    else if (firstWithTokens.output_tokens != null) {
      outSpan = document.createElement('span');
      outSpan.className = 'obs-meta-out';
      outSpan.textContent = '🔤 输出 ' + formatNum(firstWithTokens.output_tokens);
      metaEl.insertBefore(outSpan, metaEl.querySelector('.obs-meta-time'));
    }
  }

  // Update time range
  var times = [];
  tasks.forEach(function(steps) {
    steps.forEach(function(s) { if (s.created_at) times.push(s.created_at); });
  });
  times.sort();
  var timeSpan = metaEl.querySelector('.obs-meta-time');
  if (timeSpan && times.length) {
    timeSpan.textContent = '📅 ' + formatTime(times[0]) + ' ~ ' + formatTime(times[times.length - 1]);
  }
}

function mergeNewTraces(newRows) {
  var elContent = document.getElementById('traceContent');
  var grouped = groupTraces(newRows);

  grouped.forEach(function(session) {
    var sessionEl = elContent.querySelector('[data-sid="' + CSS.escape(session.id) + '"]');
    if (!sessionEl) {
      // New session — prepend to top
      elContent.insertAdjacentHTML('afterbegin', buildSessionAccordion(session.id, session.tasks));
      return;
    }
    // Existing session — merge tasks
    var sessionBody = sessionEl.querySelector(':scope > .obs-acc-body > div');
    if (!sessionBody) return;

    session.tasks.forEach(function(steps, taskId) {
      var taskEl = sessionBody.querySelector('[data-tid="' + CSS.escape(taskId) + '"]');
      if (!taskEl) {
        // New task — prepend to session body
        sessionBody.insertAdjacentHTML('afterbegin', renderTaskAccordion(steps));
        return;
      }
      // Existing task — append new step rows
      var taskBody = taskEl.querySelector(':scope > .obs-acc-body');
      if (!taskBody) return;
      var existingIds = {};
      taskBody.querySelectorAll('.obs-step-row').forEach(function(el) {
        var tid = el.dataset.traceId;
        if (tid) existingIds[tid] = true;
      });
      steps.forEach(function(s) {
        if (s.event_type === 'context_budget') return;
        if (existingIds[s.id]) return;
        taskBody.insertAdjacentHTML('beforeend', buildStepRow(s));
      });
    });

    // Rebuild taskMap from merged data to update header
    var mergedTaskMap = new Map();
    // Collect existing tasks (by data-tid)
    sessionBody.querySelectorAll(':scope > .obs-accordion[data-tid]').forEach(function(el) {
      var tid = el.dataset.tid;
      mergedTaskMap.set(tid, [{ created_at: el.querySelector('.obs-step-row') ? el.querySelector('.obs-step-time').textContent : '' }]);
    });
    // Add/overwrite with new tasks
    session.tasks.forEach(function(steps, taskId) {
      mergedTaskMap.set(taskId, steps);
    });
    updateSessionHeader(sessionEl, mergedTaskMap);
  });

  // Remove empty/loading placeholders
  var emptyEl = document.getElementById('traceEmpty');
  if (emptyEl) emptyEl.style.display = 'none';
}

// ── Token Analysis Rendering ──

function updateSummaryStats(sessions) {
  var totalInput = 0, totalOutput = 0, totalCost = 0, totalTasks = 0;
  sessions.forEach(function(s) {
    totalInput += s.total_input_tokens || 0;
    totalOutput += s.total_output_tokens || 0;
    totalCost += s.total_cost_usd || 0;
    totalTasks += s.task_count || 0;
  });
  document.getElementById('sumSessions').textContent = formatNum(sessions.length);
  document.getElementById('sumInputTokens').textContent = formatNum(totalInput);
  document.getElementById('sumOutputTokens').textContent = formatNum(totalOutput);
  document.getElementById('sumCost').textContent = formatCost(totalCost);
  document.getElementById('sumAvgTokens').textContent = totalTasks > 0 ? formatNum(Math.round((totalInput + totalOutput) / totalTasks)) : '-';
}

function renderSessionTable(sessions) {
  var tbody = document.querySelector('#sessionTable tbody');
  tbody.innerHTML = sessions.map(function(s) {
    return '<tr>' +
      '<td style="font-family:monospace;font-weight:500;" title="' + esc(s.session_id) + '">' + esc(shortId(s.session_id)) + '</td>' +
      '<td>' + esc(s.agent_name || '-') + '</td>' +
      '<td>' + s.task_count + '</td>' +
      '<td style="text-align:right">' + formatNum(s.total_input_tokens) + '</td>' +
      '<td style="text-align:right">' + formatNum(s.total_output_tokens) + '</td>' +
      '<td style="text-align:right">' + formatCost(s.total_cost_usd, s.currency) + '</td>' +
      '<td style="font-size:11px;">' + formatTime(s.first_seen) + ' ~ ' + formatTime(s.last_seen) + '</td>' +
      '<td>' + esc(s.models || '') + '</td>' +
      '</tr>';
  }).join('');
}

function populateComparisonDropdowns(sessions) {
  var html = '<option value="">-- 选择会话 A --</option>';
  sessions.forEach(function(s) {
    var parts = [shortId(s.session_id)];
    if (s.agent_name) parts.push(s.agent_name);
    parts.push(s.task_count + ' tasks');
    parts.push(s.models || '');
    var label = parts.join(' — ');
    html += '<option value="' + esc(s.session_id) + '">' + esc(label) + '</option>';
  });
  var selA = document.getElementById('compareSessionA');
  var selB = document.getElementById('compareSessionB');
  var curA = selA.value;
  var curB = selB.value;
  selA.innerHTML = html;
  selB.innerHTML = html.replace(/会话 A/g, '会话 B');
  if (curA) selA.value = curA;
  if (curB) selB.value = curB;
}

// ── Comparison ──

async function loadComparison() {
  var idA = document.getElementById('compareSessionA').value;
  var idB = document.getElementById('compareSessionB').value;
  var container = document.getElementById('comparisonResult');
  if (!idA || !idB) { container.innerHTML = ''; return; }
  if (idA === idB) {
    container.innerHTML = '<div style="color:#e65100;font-size:13px;padding:12px 0;">需要两个不同的会话才能对比</div>';
    return;
  }

  try {
    var qA = 'session_id=' + encodeURIComponent(idA) + '&limit=200';
    var qB = 'session_id=' + encodeURIComponent(idB) + '&limit=200';
    var _a = await fetch('/api/observability/sessions?' + qA).then(function(r) { return r.json(); });
    var _b = await fetch('/api/observability/sessions?' + qB).then(function(r) { return r.json(); });
    var tasksA = Array.isArray(_a) ? _a : [];
    var tasksB = Array.isArray(_b) ? _b : [];
    renderComparison(tasksA, tasksB);

    // Find matching session metadata from cache
    var metaA = _cachedSessions.find(function(s) { return s.session_id === idA; });
    var metaB = _cachedSessions.find(function(s) { return s.session_id === idB; });
    if (metaA && metaB) {
      renderTokenBars(metaA, metaB, tasksA, tasksB);
    }
  } catch (e) {
    container.innerHTML = '<div class="obs-error" style="display:block;">对比加载失败：' + esc(e.message) + '</div>';
  }
}

function renderComparison(tasksA, tasksB) {
  var totalInA = 0, totalOutA = 0, totalCostA = 0;
  var totalInB = 0, totalOutB = 0, totalCostB = 0;
  tasksA.forEach(function(t) { totalInA += t.input_tokens || 0; totalOutA += t.output_tokens || 0; totalCostA += t.cost_usd || 0; });
  tasksB.forEach(function(t) { totalInB += t.input_tokens || 0; totalOutB += t.output_tokens || 0; totalCostB += t.cost_usd || 0; });

  var rows = [
    { label: '任务数', valA: tasksA.length, valB: tasksB.length, fmt: 'num' },
    { label: '总输入 Token', valA: totalInA, valB: totalInB, fmt: 'num' },
    { label: '总输出 Token', valA: totalOutA, valB: totalOutB, fmt: 'num' },
    { label: '总 Token', valA: totalInA + totalOutA, valB: totalInB + totalOutB, fmt: 'num' },
    { label: '平均输入/任务', valA: tasksA.length ? totalInA / tasksA.length : 0, valB: tasksB.length ? totalInB / tasksB.length : 0, fmt: 'num' },
    { label: '平均输出/任务', valA: tasksA.length ? totalOutA / tasksA.length : 0, valB: tasksB.length ? totalOutB / tasksB.length : 0, fmt: 'num' },
    { label: '总费用 USD', valA: totalCostA, valB: totalCostB, fmt: 'cost' },
    { label: '平均费用/任务', valA: tasksA.length ? totalCostA / tasksA.length : 0, valB: tasksB.length ? totalCostB / tasksB.length : 0, fmt: 'cost' },
  ];

  var html = '<table class="obs-cmp-table"><thead><tr>' +
    '<th>指标</th><th>会话 A</th><th>会话 B</th><th>差异</th></tr></thead><tbody>';
  rows.forEach(function(r) {
    var aStr = r.fmt === 'cost' ? formatCost(r.valA) : formatNum(Math.round(r.valA));
    var bStr = r.fmt === 'cost' ? formatCost(r.valB) : formatNum(Math.round(r.valB));
    var delta = calcDelta(r.valA, r.valB, r.fmt);
    html += '<tr><td class="obs-cmp-label">' + esc(r.label) + '</td>' +
      '<td class="obs-cmp-col-a">' + aStr + '</td>' +
      '<td class="obs-cmp-col-b">' + bStr + '</td>' +
      '<td class="obs-cmp-col-delta">' + delta + '</td></tr>';
  });
  html += '</tbody></table>';

  document.getElementById('comparisonResult').innerHTML = html;
}

function calcDelta(valA, valB, fmt) {
  if (valA == null || valB == null) return '<span class="obs-delta" style="color:#888;">--</span>';
  var diff = valB - valA;
  if (Math.abs(diff) < 0.0001 && valA === 0) return '<span class="obs-delta" style="color:#888;">--</span>';
  var pct = valA !== 0 ? (diff / valA) * 100 : (diff > 0 ? 100 : -100);
  var absPct = Math.abs(pct);
  var diffStr = fmt === 'cost' ? formatCost(diff) : formatNum(Math.round(diff));
  var sign = diff > 0 ? '+' : '';
  // For tokens/cost: decrease (diff < 0) is good (green), increase is bad (red)
  var cls = diff < 0 ? 'pos' : (diff > 0 ? 'neg' : '');
  if (!cls) return '<span class="obs-delta" style="color:#888;">--</span>';
  return '<span class="obs-delta ' + cls + '">' + sign + diffStr + '</span>' +
    '<span class="obs-delta-pct ' + cls + '">(' + sign + absPct.toFixed(1) + '%)</span>';
}

function renderTokenBars(metaA, metaB, tasksA, tasksB) {
  var container = document.getElementById('comparisonResult');
  var html = container.innerHTML;

  html += '<div style="margin-top:18px;"><h4 style="font-size:13px;margin-bottom:10px;">Token 分布对比</h4>';
  html += '<div class="obs-legend">';
  html += '<span><span class="obs-swatch" style="background:#1a1a2e;"></span> 输入</span>';
  html += '<span><span class="obs-swatch" style="background:#90caf9;"></span> 输出</span>';
  html += '</div>';

  // Session A bars
  html += '<div style="font-size:12px;font-weight:500;margin-bottom:6px;color:#666;">会话 A: ' + esc(shortId(metaA.session_id)) + '</div>';
  var maxVal = 0;
  var allTasks = tasksA.concat(tasksB);
  allTasks.forEach(function(t) {
    var v = (t.input_tokens || 0) + (t.output_tokens || 0);
    if (v > maxVal) maxVal = v;
  });
  if (maxVal === 0) maxVal = 1;

  tasksA.forEach(function(t, i) {
    html += renderBarRow('任务 ' + (i + 1), t.input_tokens || 0, t.output_tokens || 0, maxVal);
  });

  html += '<div style="font-size:12px;font-weight:500;margin:14px 0 6px;color:#666;">会话 B: ' + esc(shortId(metaB.session_id)) + '</div>';
  tasksB.forEach(function(t, i) {
    html += renderBarRow('任务 ' + (i + 1), t.input_tokens || 0, t.output_tokens || 0, maxVal);
  });

  html += '</div>';
  container.innerHTML = html;
}

function renderBarRow(label, inTok, outTok, maxVal) {
  var inPct = Math.round((inTok / maxVal) * 80);
  var outPct = Math.round((outTok / maxVal) * 80);
  return '<div class="obs-bar-row">' +
    '<span class="obs-bar-label">' + esc(label) + '</span>' +
    '<div class="obs-bar-track">' +
    '<div class="obs-bar-in" style="width:' + Math.max(1, inPct) + 'px;"></div>' +
    '<div class="obs-bar-out" style="width:' + Math.max(1, outPct) + 'px;"></div>' +
    '</div>' +
    '<span class="obs-bar-val">' + formatNum(inTok) + ' / ' + formatNum(outTok) + '</span>' +
    '</div>';
}

// ── Cost Table Rendering ──

function buildCostRows(rows) {
  return rows.map(function(r) {
    return '<tr>' +
      '<td style="font-size:11px;">' + esc(formatFullTime(r.created_at)) + '</td>' +
      '<td style="font-family:monospace;" title="' + esc(r.session_id) + '">' + esc(shortId(r.session_id)) + '</td>' +
      '<td>' + esc(r.agent_name || '-') + '</td>' +
      '<td style="font-family:monospace;" title="' + esc(r.task_id) + '">' + esc(shortId(r.task_id)) + '</td>' +
      '<td>' + esc(r.model) + '</td>' +
      '<td style="text-align:right">' + formatNum(r.input_tokens) + '</td>' +
      '<td style="text-align:right">' + formatNum(r.output_tokens) + '</td>' +
      '<td style="text-align:right">' + formatCost(r.cost_usd, r.currency) + '</td>' +
      '</tr>';
  }).join('');
}

function renderCostTable(rows) {
  var tbody = document.querySelector('#costTable tbody');
  tbody.innerHTML = buildCostRows(rows);
}

// ── Autorefresh ──

function resetTimer() {
  if (_timer) { clearInterval(_timer); _timer = null; }
  var auto = document.getElementById('autoRefresh').value;
  if (auto === 'on') {
    _timer = setInterval(loadData, 5000);
  }
}

// ── Init ──

function init() {
  try {
    document.querySelectorAll('.obs-tab').forEach(function(el) {
      el.addEventListener('click', function() { switchTab(this.dataset.tab); });
    });
    document.getElementById('btnRefresh').addEventListener('click', loadData);
    document.getElementById('autoRefresh').addEventListener('change', resetTimer);
    document.getElementById('sessionId').addEventListener('change', loadData);
    document.getElementById('taskId').addEventListener('change', loadData);
    document.getElementById('limit').addEventListener('change', loadData);
    var selA = document.getElementById('compareSessionA');
    var selB = document.getElementById('compareSessionB');
    if (selA) selA.addEventListener('change', loadComparison);
    if (selB) selB.addEventListener('change', loadComparison);
    resetTimer();
    loadData();
  } catch (e) {
    document.getElementById('traceContent').innerHTML = '<div class="obs-error" style="display:block;">初始化失败：' + esc(e.message) + '</div>';
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

document.addEventListener('visibilitychange', function() {
  if (document.visibilityState === 'visible') loadData();
});
