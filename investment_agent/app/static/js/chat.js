let currentSessionId=null,currentTaskId=null,currentEventSource=null,totalInputTokens=0,totalOutputTokens=0,totalCacheReadTokens=0,totalCacheCreationTokens=0,totalCostUsd=0,totalCurrency='USD',currentAgentId=null,currentFile=null;
let allSessions=[],agentMap={};
let userScrolledUp=false, hasNewContentSinceScroll=false;

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ALLOWED_EXTS = new Set(['.txt','.md','.pdf','.xlsx','.xls','.docx','.doc']);
const AGENT_ICONS = ['📊','🔍','💡','📈','🧠','⚡','🎯','🔬','💼','📋'];

function escapeHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function _safeUrl(url){
  const u = String(url || '').trim();
  if (!u) return '#';
  if (u.startsWith('/')) return u;
  try {
    const p = new URL(u, window.location.origin);
    if (['http:', 'https:', 'mailto:'].includes(p.protocol)) return p.href;
  } catch (_) {}
  return '#';
}

function _normalizeLinkArgs(args){
  if (args.length === 1 && args[0] && typeof args[0] === 'object') {
    return { href: args[0].href || '', title: args[0].title || '', text: args[0].text || '' };
  }
  return { href: args[0] || '', title: args[1] || '', text: args[2] || '' };
}

function _normalizeImageArgs(args){
  if (args.length === 1 && args[0] && typeof args[0] === 'object') {
    return { href: args[0].href || '', title: args[0].title || '', text: args[0].text || '' };
  }
  return { href: args[0] || '', title: args[1] || '', text: args[2] || '' };
}

function renderMarkdown(t){
  const src = String(t || '');
  if (!window.marked || !window.DOMPurify) {
    return escapeHtml(src).replace(/\n/g, '<br>');
  }
  try {
    marked.setOptions({ gfm: true, breaks: false, headerIds: false, mangle: false });
    const renderer = new marked.Renderer();
    renderer.link = function(...args){
      const { href, title, text } = _normalizeLinkArgs(args);
      const safe = _safeUrl(href);
      const tAttr = title ? ` title="${escapeHtml(title)}"` : '';
      return `<a href="${safe}" target="_blank" rel="noopener noreferrer"${tAttr}>${text}</a>`;
    };
    renderer.image = function(...args){
      const { href, title, text } = _normalizeImageArgs(args);
      const safe = _safeUrl(href);
      const tAttr = title ? ` title="${escapeHtml(title)}"` : '';
      return `<img src="${safe}" alt="${escapeHtml(text || '')}" loading="lazy"${tAttr}>`;
    };
    const raw = marked.parse(src, { renderer });
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  } catch (_) {
    return escapeHtml(src).replace(/\n/g, '<br>');
  }
}

/* ====== 加载状态 ====== */

function _showSkeleton(containerId, count){
  const el = document.getElementById(containerId);
  if (!el) return;
  let html = '';
  for (let i = 0; i < count; i++){
    html += '<div class="skeleton-item' + (i % 2 ? ' short' : '') + '"></div>';
  }
  el.innerHTML = html;
}

function _showSpinner(containerId, text){
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = '<div class="loading-spinner">' + escapeHtml(text || '加载中...') + '</div>';
}

/* ====== Agent list ====== */

async function loadAgents(){
  const list = document.getElementById('agentList');
  _showSkeleton('agentList', 3);
  try {
    const agents = await fetch('/api/agents').then(r => r.json());
    agents.forEach((a, i) => { agentMap[a.id] = a; });
    if (!agents.length) {
      list.innerHTML = '<div class="agent-empty">暂无 Agent，请先在 <a href="/agents">Agent 配置</a> 页创建</div>';
      document.getElementById('agentContext').style.display = 'none';
      return;
    }
    const currentId = currentAgentId || (agents[0] && agents[0].id);
    list.innerHTML = agents.map((a, i) => {
      const active = a.id === currentId ? ' active' : '';
      const icon = AGENT_ICONS[i % AGENT_ICONS.length];
      const modelName = (a.model_id || '未设置');
      let skillsCount = 0;
      try { skillsCount = JSON.parse(a.skills || '[]').length; } catch(e){}
      return `<div class="agent-item${active}" data-id="${a.id}" onclick="selectAgent('${a.id}')">
        <div class="agent-icon">${icon}</div>
        <div class="agent-info">
          <div class="agent-name">${escapeHtml(a.name)}</div>
          <div class="agent-meta">${escapeHtml(modelName)}${skillsCount ? ' · '+skillsCount+' Skills' : ''}</div>
        </div>
        <span class="agent-badge" id="badge-${a.id}">-</span>
        <button class="btn-new-agent" onclick="event.stopPropagation();newSession()" title="新对话">+</button>
      </div>`;
    }).join('');
    if (!currentAgentId && agents[0]) {
      selectAgent(agents[0].id, true);
    }
  } catch(e) {
    list.innerHTML = '<div class="agent-empty">加载失败</div>';
  }
}

function selectAgent(id, silent){
  currentAgentId = id;
  const agent = agentMap[id];
  if (!agent) return;

  document.querySelectorAll('.agent-item').forEach(el => el.classList.remove('active'));
  const item = document.querySelector(`.agent-item[data-id="${id}"]`);
  if (item) item.classList.add('active');

  const header = document.getElementById('centerHeader');
  const nameEl = document.getElementById('centerAgentName');
  if (header && nameEl) {
    header.style.display = '';
    nameEl.textContent = agent.name;
  }

  const ctx = document.getElementById('agentContext');
  if (ctx) {
    ctx.style.display = '';
    document.getElementById('ctxAgentName').textContent = agent.name;
    let modelName = agent.model_id || '未设置模型';
    let skillsCount = 0;
    try { skillsCount = JSON.parse(agent.skills || '[]').length; } catch(e){}
    document.getElementById('ctxAgentDetail').textContent = '模型 ' + escapeHtml(modelName) + ' · 挂载 ' + skillsCount + ' 个 Skill';
  }

  if (!silent) {
    currentSessionId = null;
    document.getElementById('messages').innerHTML = _welcomeHtml();
    totalInputTokens = 0; totalOutputTokens = 0; totalCacheReadTokens = 0; totalCacheCreationTokens = 0; totalCostUsd = 0; totalCurrency = 'USD'; updateStats();
  }
  loadSessions();
}

/* ====== Sessions (right panel) ====== */

async function loadSessions(){
  const list = document.getElementById('historyList');
  const countEl = document.getElementById('historyCount');
  _showSkeleton('historyList', 4);
  try {
    allSessions = await fetch('/api/sessions').then(r => r.json());
  } catch(e) {
    allSessions = [];
  }

  // update badges
  const counts = {};
  allSessions.forEach(s => {
    if (s.agent_id) counts[s.agent_id] = (counts[s.agent_id] || 0) + 1;
  });
  Object.keys(agentMap).forEach(aid => {
    const badge = document.getElementById('badge-' + aid);
    if (badge) badge.textContent = counts[aid] || '0';
  });

  const filtered = currentAgentId
    ? allSessions.filter(s => s.agent_id === currentAgentId)
    : [];

  countEl.textContent = filtered.length ? '共 ' + filtered.length + ' 条' : '';

  if (!filtered.length) {
    list.innerHTML = '<div class="history-empty">暂无历史会话</div>';
    return;
  }

  list.innerHTML = filtered.map(s => {
    const active = s.id === currentSessionId ? ' active' : '';
    const running = s.status === 'running';
    const runningCls = running ? ' is-running' : '';
    const spinner = running ? '<span class="running-spinner"></span>' : '';
    const title = s.title || '未命名';
    const date = (s.created_at || '').slice(0, 16);
    const preview = s.preview ? '<div class="sess-preview">' + escapeHtml(s.preview) + '</div>' : '';
    return `<div class="session-row${active}${runningCls}" data-sid="${s.id}" onclick="loadSession('${s.id}')">
      <div class="sess-title">${spinner}${escapeHtml(title)}</div>
      ${preview}
      <div class="sess-bottom">
        <span class="sess-meta">${date}</span>
        <div class="sess-actions">
          <button class="btn-continue" onclick="event.stopPropagation();loadSession('${s.id}')">${running ? '查看进度' : '继续对话'}</button>
          <button class="btn-del" onclick="event.stopPropagation();deleteSession('${s.id}')">删除</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function loadSession(sid){
  // 如果有正在运行的 SSE 连接，先关闭
  if (currentEventSource){ currentEventSource.close(); currentEventSource = null; }

  currentSessionId = sid;
  _showSpinner('messages', '加载会话中...');

  // 检查是否是运行中的会话
  const sessionData = allSessions.find(s => s.id === sid);
  if (sessionData && sessionData.status === 'running' && sessionData.current_task_id) {
    await reconnectToTask(sid, sessionData.current_task_id);
    return;
  }

  try {
    const data = await fetch('/api/sessions/' + sid).then(r => r.json());
    if (data.session && data.session.agent_id && data.session.agent_id !== currentAgentId) {
      currentAgentId = data.session.agent_id;
      selectAgent(data.session.agent_id, true);
    }
    const c = document.getElementById('messages');
    c.innerHTML = '';
    (data.messages || []).forEach(m => {
      if (m.role === 'user') appendUserMsg(m.content);
      else if (m.role === 'assistant') appendAssistantMsg(m.content);
    });
    // 设置会话累计 token 统计
    const sess = data.session || {};
    totalInputTokens = sess.input_tokens || 0;
    totalOutputTokens = sess.output_tokens || 0;
    totalCacheReadTokens = sess.cache_read_tokens || 0;
    totalCacheCreationTokens = sess.cache_creation_tokens || 0;
    totalCostUsd = sess.cost_usd || 0;
    totalCurrency = sess.currency || 'USD';
    updateStats();
    setRunning(false);
    loadSessions();
  } catch(e) {
    console.error('loadSession', e);
  }
}

async function deleteSession(sid){
  if (!confirm('确认删除该会话？')) return;
  await fetch('/api/sessions/' + sid, {method:'DELETE'});
  if (currentSessionId === sid) {
    currentSessionId = null;
    document.getElementById('messages').innerHTML = _welcomeHtml();
    totalInputTokens = 0; totalOutputTokens = 0; totalCacheReadTokens = 0; totalCacheCreationTokens = 0; totalCostUsd = 0; totalCurrency = 'USD'; updateStats();
  }
  loadSessions();
}

function newSession(){
  if (currentEventSource){ currentEventSource.close(); currentEventSource = null; }
  currentSessionId = null;
  document.getElementById('messages').innerHTML = _welcomeHtml();
  totalInputTokens = 0; totalOutputTokens = 0; totalCacheReadTokens = 0; totalCacheCreationTokens = 0; totalCostUsd = 0; totalCurrency = 'USD'; updateStats();
  setRunning(false);
  loadSessions();
}

/* ====== Chat ====== */

function _append(html){
  const c = document.getElementById('messages');
  const d = document.createElement('div');
  d.innerHTML = html; c.appendChild(d); c.scrollTop = c.scrollHeight;
  return d;
}

function _fileExt(name){
  const i = String(name || '').lastIndexOf('.');
  return i >= 0 ? String(name).slice(i).toLowerCase() : '';
}

function triggerFileSelect(){
  const el = document.getElementById('fileInput');
  if (el) el.click();
}

function _validateAndSetFile(file){
  if (!file) return false;
  const ext = _fileExt(file.name);
  if (!ALLOWED_EXTS.has(ext)){
    alert('不支持的文件类型，仅支持 txt/md/pdf/xlsx/xls/docx/doc');
    return false;
  }
  if (file.size > MAX_UPLOAD_BYTES){
    alert('文件过大，最大支持 10MB');
    return false;
  }
  currentFile = file;
  const chip = document.getElementById('fileNameChip');
  const btnClear = document.getElementById('btnClearFile');
  if (chip){ chip.textContent = file.name + ' (' + Math.ceil(file.size/1024) + 'KB)'; chip.style.display = 'inline-block'; }
  if (btnClear){ btnClear.style.display = 'inline-block'; }
  return true;
}

function onFileSelected(e){
  const file = e?.target?.files?.[0] || null;
  if (!file){ clearFile(); return; }
  if (!_validateAndSetFile(file)) clearFile();
}

function clearFile(){
  currentFile = null;
  const el = document.getElementById('fileInput');
  if (el) el.value = '';
  const chip = document.getElementById('fileNameChip');
  const btnClear = document.getElementById('btnClearFile');
  if (chip){ chip.textContent = ''; chip.style.display = 'none'; }
  if (btnClear){ btnClear.style.display = 'none'; }
}

function appendUserMsg(text){
  const w = document.getElementById('welcome'); if (w) w.remove();
  _append('<div class="msg user"><div class="msg-bubble">' + escapeHtml(text) + '</div></div>');
}

function appendAssistantMsg(md){
  return _append('<div class="msg assistant"><div class="msg-bubble">' + renderMarkdown(md) + '</div></div>');
}

function _createReplyBlock(){
  const container = document.createElement('div');
  container.className = 'msg assistant';
  container.innerHTML =
    '<div class="msg-bubble">' +
      '<div class="bubble-content">' +
        '<div class="thinking-inline"><span></span><span></span><span></span></div>' +
      '</div>' +
      '<div class="think-process" style="display:none">' +
        '<div class="think-current"></div>' +
        '<div class="think-summary" style="display:none"></div>' +
        '<div class="think-steps" style="display:none"></div>' +
      '</div>' +
    '</div>' +
    '<div class="retry-area" style="display:none">' +
      '<button class="btn-retry" onclick="retryTask()">🔄 重试</button>' +
    '</div>';
  document.getElementById('messages').appendChild(container);
  return {
    container,
    bodyEl: container.querySelector('.bubble-content'),
    thinkEl: container.querySelector('.think-process'),
    currentEl: container.querySelector('.think-current'),
    stepsEl: container.querySelector('.think-steps'),
    summaryEl: container.querySelector('.think-summary'),
    retryEl: container.querySelector('.retry-area'),
  };
}

function _addThinkStep(block, thinkSteps, icon, label, detail){
  block.thinkEl.style.display = '';
  thinkSteps.push({ icon, label, detail });
  let html = '<span class="think-spinner"></span> <span class="step-icon">' + icon + '</span> <span class="step-label">' + escapeHtml(label) + '</span>';
  if (detail) {
    html += ' <span class="step-detail-inline">' + escapeHtml((detail || '').slice(0, 80)) + '</span>';
  }
  block.currentEl.innerHTML = html;
}

function _collapseThink(block, thinkSteps){
  const n = thinkSteps.length;
  if (!n) { block.thinkEl.style.display = 'none'; return; }

  block.currentEl.style.display = 'none';
  block.stepsEl.style.display = '';
  block.summaryEl.style.display = '';

  const TRUNCATE_AT = 120;
  block.stepsEl.innerHTML = thinkSteps.map((s, idx) => {
    let detailHtml = '';
    if (s.detail) {
      const isLong = s.detail.length > TRUNCATE_AT;
      const shortText = escapeHtml(s.detail.slice(0, TRUNCATE_AT));
      const fullText = escapeHtml(s.detail);
      if (isLong) {
        detailHtml = ' <span class="step-detail step-detail-expandable" data-step="' + idx + '">' +
          '<span class="step-detail-short">' + shortText + '...</span>' +
          '<span class="step-detail-full" style="display:none">' + fullText + '</span>' +
          '</span>' +
          '<button class="step-toggle-btn" onclick="_toggleStepDetail(this)">展开</button>';
      } else {
        detailHtml = ' <span class="step-detail">' + shortText + '</span>';
      }
    }
    return '<div class="think-step"><span class="step-icon">' + s.icon + '</span><span class="step-label">' + escapeHtml(s.label) + '</span>' +
      detailHtml + '</div>';
  }).join('');

  block.summaryEl.innerHTML = '思考过程 (' + n + '步) <span class="think-arrow">▼</span>';
  block.thinkEl.classList.add('collapsed');

  block.summaryEl.onclick = function(){
    block.thinkEl.classList.toggle('collapsed');
    var arr = block.summaryEl.querySelector('.think-arrow');
    if (arr) arr.textContent = block.thinkEl.classList.contains('collapsed') ? '▼' : '▲';
    scrollToBottom(true);
  };
}

function showThinking(){
  removeThinking();
  _append('<div id="thinking" class="thinking"><span></span><span></span><span></span></div>');
}

function removeThinking(){ const el = document.getElementById('thinking'); if (el) el.remove(); }

function updateStats(override){
  const inp = override?.input ?? totalInputTokens;
  const out = override?.output ?? totalOutputTokens;
  const cost = override?.cost ?? totalCostUsd;
  const cacheRead = override?.cacheRead ?? totalCacheReadTokens;
  const cacheCreation = override?.cacheCreation ?? totalCacheCreationTokens;
  const currency = override?.currency ?? totalCurrency;
  document.getElementById('statInput').textContent = inp.toLocaleString();
  document.getElementById('statOutput').textContent = out.toLocaleString();

  // 缓存命中
  const cacheReadRow = document.getElementById('statCacheReadRow');
  const cacheReadVal = document.getElementById('statCacheRead');
  if (cacheRead > 0) {
    if (cacheReadRow) cacheReadRow.style.display = '';
    if (cacheReadVal) cacheReadVal.textContent = cacheRead.toLocaleString();
  } else {
    if (cacheReadRow) cacheReadRow.style.display = 'none';
  }

  // 缓存未命中（写入）
  const cacheMissRow = document.getElementById('statCacheMissRow');
  const cacheMissVal = document.getElementById('statCacheMiss');
  if (cacheCreation > 0) {
    if (cacheMissRow) cacheMissRow.style.display = '';
    if (cacheMissVal) cacheMissVal.textContent = cacheCreation.toLocaleString();
  } else {
    if (cacheMissRow) cacheMissRow.style.display = 'none';
  }

  const symbol = currency === 'CNY' ? '¥' : '$';
  document.getElementById('statCost').textContent = cost > 0 ? symbol + cost.toFixed(4) : '-';
}

function setRunning(r){
  document.getElementById('btnSend').style.display = r ? 'none' : 'inline-block';
  document.getElementById('btnStop').style.display = r ? 'inline-block' : 'none';
}

function finishStream(){
  if (currentEventSource){ currentEventSource.close(); currentEventSource = null; }
  setRunning(false); loadSessions();
}

function stopTask(){
  if (currentTaskId) fetch('/api/chat/' + currentTaskId + '/interrupt', {method:'POST'});
  if (currentEventSource){ currentEventSource.close(); currentEventSource = null; }
  removeThinking(); setRunning(false);
}

/* ====== 共享 SSE 事件处理 ====== */

function _connectToStream(taskId, state){
  const es = new EventSource('/api/chat/' + taskId + '/stream');
  currentEventSource = es;

  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === '_ping') return;  // 心跳，忽略

    _handleStreamEvent(ev, state);
  };

  es.onerror = () => {
    removeThinking();
    finishStream();
  };

  return es;
}

function _handleStreamEvent(ev, state){
  const { getState, setState } = state;
  const s = getState();

  if (ev.type === 'text_delta'){
    const b = _ensureBlock(s, setState);
    const spin = b.bodyEl.querySelector('.thinking-inline');
    if (spin) spin.remove();
    // 隐藏重试按钮（如果有）
    if (b.retryEl) b.retryEl.style.display = 'none';
    s.aText += ev.content;
    b.bodyEl.innerHTML = renderMarkdown(s.aText);
    if (userScrolledUp) {
      hasNewContentSinceScroll = true;
      _updateScrollButton();
    } else {
      scrollToBottom();
    }
  } else if (ev.type === 'tool_call'){
    const b = _ensureBlock(s, setState);
    const spin = b.bodyEl.querySelector('.thinking-inline');
    if (spin) spin.remove();
    s.pendingTool = ev;
  } else if (ev.type === 'tool_result'){
    _addThinkStep(_ensureBlock(s, setState), s.thinkSteps, '🔧', s.pendingTool?.tool || ev.tool, ev.output);
    s.pendingTool = null;
  } else if (ev.type === 'slow_think'){
    _addThinkStep(_ensureBlock(s, setState), s.thinkSteps, '💭', '策略复盘', ev.content);
  } else if (ev.type === 'done'){
    const b = s.replyBlock;
    if (b) {
      const spin = b.bodyEl.querySelector('.thinking-inline');
      if (spin) spin.remove();
      _collapseThink(b, s.thinkSteps);
    } else { removeThinking(); }
    totalInputTokens += (ev.usage?.input_tokens || 0);
    totalOutputTokens += (ev.usage?.output_tokens || 0);
    // 缓存统计：优先使用事件中嵌入的信息（由 task_manager 注入），fallback 到 usage
    totalCacheReadTokens += (ev.cache_read_tokens || ev.usage?.cache_read_tokens || 0);
    totalCacheCreationTokens += (ev.cache_creation_tokens || ev.usage?.cache_creation_tokens || 0);
    // 费用：由 task_manager 注入，累加到当前会话总计
    if (ev.cost != null) {
      totalCostUsd += Number(ev.cost);
      totalCurrency = ev.currency || 'USD';
    }
    updateStats(); finishStream();
  } else if (ev.type === 'interrupted'){
    removeThinking();
    if (ev.message) _append('<div class="msg-info">' + escapeHtml(ev.message) + '</div>');
    const b = s.replyBlock;
    if (b) _collapseThink(b, s.thinkSteps);
    finishStream();
  } else if (ev.type === 'error'){
    removeThinking();
    const b = s.replyBlock;
    if (b) _collapseThink(b, s.thinkSteps);
    // 显示错误信息
    const errorEl = _append('<div class="stream-error msg-error">' + escapeHtml(ev.message || '执行出错') + '</div>');
    // 显示重试按钮
    _showRetryButton(b, errorEl);
    finishStream();
  }
}

function _ensureBlock(s, setState){
  if (!s.replyBlock) {
    removeThinking();
    const block = _createReplyBlock();
    setState({ replyBlock: block });
    // 同时更新外层引用
    s.replyBlock = block;
  }
  return s.replyBlock;
}

function _showRetryButton(replyBlock, errorEl){
  if (replyBlock && replyBlock.retryEl) {
    replyBlock.retryEl.style.display = '';
    replyBlock._errorEl = errorEl;
  } else {
    // 没有 reply block（错误发生在第一个 text_delta 之前），追加一个重试区域
    const container = document.createElement('div');
    container.className = 'msg assistant';
    container.innerHTML =
      '<div class="retry-area">' +
        '<button class="btn-retry" onclick="retryTask()">🔄 重试</button>' +
      '</div>';
    document.getElementById('messages').appendChild(container);
    container._errorEl = errorEl;
    // 记录为当前 replyBlock 以便 retryTask 找到
    window._orphanRetryContainer = container;
  }
}

/* ====== 重试 ====== */

async function retryTask(){
  if (!currentSessionId) return;

  // 找到并隐藏所有重试按钮和错误信息
  document.querySelectorAll('.retry-area').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.stream-error').forEach(el => el.remove());
  if (window._orphanRetryContainer) {
    window._orphanRetryContainer.remove();
    window._orphanRetryContainer = null;
  }

  // 重置状态
  showThinking(); setRunning(true);
  totalInputTokens = 0; totalOutputTokens = 0; totalCacheReadTokens = 0; totalCacheCreationTokens = 0; totalCostUsd = 0; totalCurrency = 'USD'; updateStats();

  try {
    const res = await fetch('/api/chat/retry', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: currentSessionId}),
    });
    const data = await res.json();

    if (!data?.task_id){
      removeThinking();
      const msg = data?.detail || data?.error || '重试请求失败';
      _append('<div class="msg-error">' + escapeHtml(msg) + '</div>');
      setRunning(false);
      return;
    }

    currentTaskId = data.task_id;

    // 创建新的回复块用于重试输出
    const replyBlock = _createReplyBlock();
    const s = {
      replyBlock: replyBlock,
      aText: '',
      pendingTool: null,
      thinkSteps: [],
    };

    _connectToStream(currentTaskId, {
      getState: () => s,
      setState: (updates) => Object.assign(s, updates),
    });

  } catch(e) {
    removeThinking();
    _append('<div class="msg-error">重试请求失败: ' + escapeHtml(e.message) + '</div>');
    setRunning(false);
  }
}

/* ====== 重连运行中的任务 ====== */

async function reconnectToTask(sessionId, taskId){
  currentSessionId = sessionId;
  currentTaskId = taskId;

  // 更新会话高亮
  document.querySelectorAll('.session-row').forEach(el => el.classList.remove('active'));
  const row = document.querySelector(`.session-row[data-sid="${sessionId}"]`);
  if (row) row.classList.add('active');

  // 加载历史消息
  const c = document.getElementById('messages');
  c.innerHTML = '';

  try {
    const data = await fetch('/api/sessions/' + sessionId).then(r => r.json());
    if (data.session && data.session.agent_id && data.session.agent_id !== currentAgentId) {
      currentAgentId = data.session.agent_id;
      selectAgent(data.session.agent_id, true);
    }
    (data.messages || []).forEach(m => {
      if (m.role === 'user') appendUserMsg(m.content);
      else if (m.role === 'assistant') appendAssistantMsg(m.content);
    });
  } catch(e) {
    console.error('reconnectToTask: load messages failed', e);
  }

  // 设置运行状态
  showThinking(); setRunning(true);

  // 创建回复块用于接收回放+实时事件
  const replyBlock = _createReplyBlock();
  const s = {
    replyBlock: replyBlock,
    aText: '',
    pendingTool: null,
    thinkSteps: [],
  };

  _connectToStream(taskId, {
    getState: () => s,
    setState: (updates) => Object.assign(s, updates),
  });

  loadSessions();
}

/* ====== 发送消息 ====== */

async function sendMessage(){
  const input = document.getElementById('inputBox');
  const text = input.value.trim();
  if (!text && !currentFile) return;

  userScrolledUp = false;
  hasNewContentSinceScroll = false;
  _updateScrollButton();

  const displayText = currentFile ? (text || '(无文本问题)') + '\n\n[已上传文件] ' + currentFile.name : text;
  input.value = ''; autoResize(input);
  appendUserMsg(displayText);
  showThinking(); setRunning(true);

  let data;
  if (currentFile){
    const fd = new FormData();
    if (currentSessionId) fd.append('session_id', currentSessionId);
    if (currentAgentId) fd.append('agent_id', currentAgentId);
    fd.append('message', text);
    fd.append('file', currentFile);
    const res = await fetch('/api/chat',{ method:'POST', body:fd });
    data = await res.json();
  } else {
    const res = await fetch('/api/chat',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({session_id: currentSessionId, message: text, agent_id: currentAgentId}),
    });
    data = await res.json();
  }

  if (!data?.task_id){
    removeThinking();
    const msg = data?.detail || data?.error || '请求失败';
    _append('<div class="msg-error">' + escapeHtml(msg) + '</div>');
    setRunning(false);
    return;
  }

  clearFile();
  currentTaskId = data.task_id;
  currentSessionId = data.session_id;

  const replyBlock = null;
  const s = {
    replyBlock: replyBlock,
    aText: '',
    pendingTool: null,
    thinkSteps: [],
  };

  _connectToStream(currentTaskId, {
    getState: () => s,
    setState: (updates) => Object.assign(s, updates),
  });

  // 刷新会话列表以显示运行中状态
  loadSessions();
}

function handleKey(e){ if (e.key==='Enter' && !e.shiftKey){ e.preventDefault(); sendMessage(); } }
function autoResize(el){ el.style.height='auto'; el.style.height=Math.min(el.scrollHeight, 120) + 'px'; }

function fillExample(text){
  const input = document.getElementById('inputBox');
  if (input){ input.value = text; autoResize(input); input.focus(); }
}

/* ====== 自动滚动控制 ====== */

function _isNearBottom(el, threshold){
  return el.scrollHeight - el.scrollTop - el.clientHeight < (threshold || 50);
}

function scrollToBottom(force){
  const el = document.getElementById('messages');
  if (!el) return;
  if (force || !userScrolledUp){
    el.scrollTop = el.scrollHeight;
    userScrolledUp = false;
    hasNewContentSinceScroll = false;
    _updateScrollButton();
  }
}

function _updateScrollButton(){
  let btn = document.getElementById('btnScrollDown');
  if (!btn) return;
  btn.style.display = (userScrolledUp && hasNewContentSinceScroll) ? 'flex' : 'none';
}

/* ====== 文件拖拽上传 ====== */

let _dragCounter = 0;

function _initDragDrop(){
  const main = document.querySelector('.main');
  if (!main || main._dragBound) return;
  main._dragBound = true;

  main.addEventListener('dragenter', function(e){
    e.preventDefault();
    _dragCounter++;
    main.classList.add('drag-over');
  });

  main.addEventListener('dragleave', function(e){
    e.preventDefault();
    _dragCounter--;
    if (_dragCounter <= 0){
      _dragCounter = 0;
      main.classList.remove('drag-over');
    }
  });

  main.addEventListener('dragover', function(e){
    e.preventDefault();
  });

  main.addEventListener('drop', function(e){
    e.preventDefault();
    _dragCounter = 0;
    main.classList.remove('drag-over');
    const file = e.dataTransfer?.files?.[0];
    if (file) _validateAndSetFile(file);
  });
}

function _initScrollListener(){
  const el = document.getElementById('messages');
  if (!el || el._scrollBound) return;
  el._scrollBound = true;
  el.addEventListener('scroll', function(){
    const nearBottom = _isNearBottom(el, 50);
    if (nearBottom){
      userScrolledUp = false;
      hasNewContentSinceScroll = false;
    } else {
      userScrolledUp = true;
    }
    _updateScrollButton();
  });
}

function _toggleStepDetail(btn){
  const step = btn.parentElement;
  const shortEl = step.querySelector('.step-detail-short');
  const fullEl = step.querySelector('.step-detail-full');
  const expanded = btn.textContent === '收起';
  if (expanded) {
    shortEl.style.display = '';
    fullEl.style.display = 'none';
    btn.textContent = '展开';
  } else {
    shortEl.style.display = 'none';
    fullEl.style.display = '';
    btn.textContent = '收起';
  }
}

function _welcomeHtml(){
  return '<div id="welcome" class="welcome">' +
    '<div class="welcome-title">输入股票代码或公司名称，开始分析</div>' +
    '<div class="welcome-examples">' +
      '<div class="example-card" onclick="fillExample(\'分析贵州茅台（600519）的基本面\')">分析贵州茅台（600519）的基本面</div>' +
      '<div class="example-card" onclick="fillExample(\'对比宁德时代和比亚迪的财务数据\')">对比宁德时代和比亚迪的财务数据</div>' +
      '<div class="example-card" onclick="fillExample(\'查看招商银行最新估值水平\')">查看招商银行最新估值水平</div>' +
    '</div></div>';
}

/* ====== 页面初始化 ====== */

window.addEventListener('DOMContentLoaded', () => {
  _initScrollListener();
  _initDragDrop();
  const params = new URLSearchParams(location.search);
  const sid = params.get('session');
  const aid = params.get('agent');
  if (aid) currentAgentId = aid;
  loadAgents().then(async () => {
    if (sid) {
      await loadSession(sid);
    } else {
      await loadSessions();
      // 检查是否有运行中的会话，自动重连
      _autoReconnectRunning();
    }
  });
});

function _autoReconnectRunning(){
  if (!currentAgentId) return;
  const running = allSessions.find(s =>
    s.agent_id === currentAgentId && s.status === 'running' && s.current_task_id
  );
  if (running) {
    reconnectToTask(running.id, running.current_task_id);
  }
}
