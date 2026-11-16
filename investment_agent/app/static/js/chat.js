let currentSessionId=null,currentTaskId=null,currentEventSource=null,totalInputTokens=0,totalOutputTokens=0,totalCacheReadTokens=0,totalCacheCreationTokens=0,totalCostUsd=0,totalCurrency='USD',currentAgentId=null,currentModelId=null,currentFile=null,currentStreamState=null;
let allSessions=[],agentMap={},modelMap={},modelList=[];
let userScrolledUp=false, hasNewContentSinceScroll=false;

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ALLOWED_EXTS = new Set(['.txt','.md','.pdf','.xlsx','.xls','.docx','.doc']);
const STREAM_RENDER_INTERVAL_MS = 60;
const DATA_PATH_RE = /data[/\\](?:[^/\\\s`'"<>|]+[/\\])+[^/\\\s`'"<>|]+[/\\]?/gi;

let _drawerNavStack = [];
let _drawerEscBound = false;
const DRAWER_WIDTH_KEY = 'fileDrawerWidth';
const DRAWER_MIN_WIDTH = 320;
const DRAWER_MAX_WIDTH_RATIO = 0.92;
let _drawerResizing = false;
let _drawerCurrentFile = null;

function escapeHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function _pathExt(name){
  const m = String(name || '').toLowerCase().match(/(\.[a-z0-9]+)$/);
  return m ? m[1] : '';
}

function _inferPathFtype(displayPath){
  const p = String(displayPath || '').replace(/\\/g, '/');
  if (/\/$/.test(p)) return 'folder';
  const base = p.split('/').pop() || '';
  const ext = _pathExt(base);
  if (!ext) return 'folder';
  if (ext === '.json') return 'json';
  if (ext === '.pdf') return 'pdf';
  if (ext === '.md' || ext === '.markdown') return 'markdown';
  return 'text';
}

function _toApiPath(displayPath){
  let p = String(displayPath || '').trim().replace(/\\/g, '/');
  p = p.replace(/\/+$/, '');
  if (/^data\//i.test(p)) p = p.slice(5);
  return p;
}

function _displayDataPath(apiPath){
  const p = String(apiPath || '').replace(/\\/g, '/').replace(/^\/+/, '');
  return p ? ('data/' + p) : 'data';
}

function _buildPathChip(displayPath){
  const ftype = _inferPathFtype(displayPath);
  const apiPath = _toApiPath(displayPath);
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'path-chip';
  btn.dataset.path = apiPath;
  btn.dataset.ftype = ftype;
  btn.title = '打开 ' + displayPath;
  const icon = document.createElement('span');
  icon.className = 'path-icon path-icon-' + ftype;
  icon.setAttribute('aria-hidden', 'true');
  const text = document.createElement('span');
  text.className = 'path-text';
  text.textContent = displayPath.replace(/\\/g, '/');
  btn.appendChild(icon);
  btn.appendChild(text);
  return btn;
}

function _shouldSkipPathNode(node){
  let el = node.parentElement;
  while (el) {
    if (el.tagName === 'A' || el.tagName === 'BUTTON') return true;
    if (el.classList && el.classList.contains('path-chip')) return true;
    el = el.parentElement;
  }
  return false;
}

function linkifyDataPaths(html){
  const src = String(html || '');
  if (!src || !/data[/\\]/i.test(src)) return src;
  const wrap = document.createElement('div');
  wrap.innerHTML = src;
  const walker = document.createTreeWalker(wrap, NodeFilter.SHOW_TEXT, null);
  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);
  for (const textNode of nodes) {
    if (_shouldSkipPathNode(textNode)) continue;
    const value = textNode.nodeValue;
    if (!value || !/data[/\\]/i.test(value)) continue;
    DATA_PATH_RE.lastIndex = 0;
    let match;
    let last = 0;
    const frag = document.createDocumentFragment();
    let changed = false;
    while ((match = DATA_PATH_RE.exec(value)) !== null) {
      let raw = match[0];
      // Strip trailing punctuation that the char-class may have absorbed
      raw = raw.replace(/[.,;:!?，。；：！？、）)】》」』]+$/u, '');
      if (!raw || !/[/\\]/.test(raw.slice(4))) continue;
      const absEnd = match.index + match[0].length;
      const usedEnd = match.index + raw.length;
      if (match.index > last) {
        frag.appendChild(document.createTextNode(value.slice(last, match.index)));
      }
      frag.appendChild(_buildPathChip(raw));
      if (usedEnd < absEnd) {
        frag.appendChild(document.createTextNode(value.slice(usedEnd, absEnd)));
      }
      last = absEnd;
      changed = true;
    }
    if (!changed) continue;
    if (last < value.length) frag.appendChild(document.createTextNode(value.slice(last)));
    textNode.parentNode.replaceChild(frag, textNode);
  }
  return wrap.innerHTML;
}

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

function _normalizeRendererArgs(args){
  if (args.length === 1 && args[0] && typeof args[0] === 'object') {
    return { href: args[0].href || '', title: args[0].title || '', text: args[0].text || '' };
  }
  return { href: args[0] || '', title: args[1] || '', text: args[2] || '' };
}

function _renderAssistantText(bodyEl, text){
  bodyEl.innerHTML = renderMarkdown(text);
}

function _scheduleAssistantRender(s, bodyEl){
  if (s.renderTimer) return;
  s.renderTimer = window.setTimeout(function(){
    s.renderTimer = null;
    _renderAssistantText(bodyEl, s.aText);
  }, STREAM_RENDER_INTERVAL_MS);
}

function _flushAssistantRender(s, bodyEl){
  if (s.renderTimer) {
    clearTimeout(s.renderTimer);
    s.renderTimer = null;
  }
  _renderAssistantText(bodyEl, s.aText);
}

function _finalizeAssistantRender(s){
  const b = s.replyBlock;
  if (!b) return;
  _flushAssistantRender(s, b.bodyEl);
}

function _resetStreamRenderState(s){
  if (s.renderTimer) {
    clearTimeout(s.renderTimer);
    s.renderTimer = null;
  }
}

function _createStreamState(replyBlock){
  return {
    replyBlock: replyBlock || null,
    aText: '',
    pendingTool: null,
    thinkSteps: [],
    renderTimer: null,
  };
}

function renderMarkdown(t){
  const src = String(t || '');
  if (!window.marked || !window.DOMPurify) {
    return linkifyDataPaths(escapeHtml(src).replace(/\n/g, '<br>'));
  }
  try {
    marked.setOptions({ gfm: true, breaks: false, headerIds: false, mangle: false });
    const renderer = new marked.Renderer();
    renderer.link = function(...args){
      const { href, title, text } = _normalizeRendererArgs(args);
      const safe = _safeUrl(href);
      const tAttr = title ? ` title="${escapeHtml(title)}"` : '';
      return `<a href="${safe}" target="_blank" rel="noopener noreferrer"${tAttr}>${text}</a>`;
    };
    renderer.image = function(...args){
      const { href, title, text } = _normalizeRendererArgs(args);
      const safe = _safeUrl(href);
      const tAttr = title ? ` title="${escapeHtml(title)}"` : '';
      return `<img src="${safe}" alt="${escapeHtml(text || '')}" loading="lazy"${tAttr}>`;
    };
    const raw = marked.parse(src, { renderer });
    const clean = DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
    return linkifyDataPaths(clean);
  } catch (_) {
    return linkifyDataPaths(escapeHtml(src).replace(/\n/g, '<br>'));
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

function _agentSkillsCount(agent){
  try {
    return Array.isArray(agent.skills) ? agent.skills.length : JSON.parse(agent.skills || '[]').length;
  } catch(e){
    return 0;
  }
}

async function loadAgents(){
  try {
    const agents = await fetch('/api/agents').then(r => r.json());
    Object.keys(agentMap).forEach(k => { delete agentMap[k]; });
    agents.forEach((a) => { agentMap[a.id] = a; });
    if (!agents.length) {
      document.getElementById('agentContext').style.display = 'none';
      return agents;
    }
    if (!currentAgentId && agents[0]) {
      selectAgent(agents[0].id, true);
    } else if (currentAgentId && agentMap[currentAgentId]) {
      selectAgent(currentAgentId, true);
    }
    return agents;
  } catch(e) {
    console.error('loadAgents', e);
    return [];
  }
}

function resetUsageStats(){
  totalInputTokens = 0;
  totalOutputTokens = 0;
  totalCacheReadTokens = 0;
  totalCacheCreationTokens = 0;
  totalCostUsd = 0;
  totalCurrency = 'USD';
  updateStats();
}

function _modelDisplayName(modelId){
  if (!modelId) return '';
  const m = modelMap[modelId];
  return m ? (m.name || m.model || modelId) : modelId;
}

function _agentBoundModelLabel(agent){
  if (!agent) return '系统默认';
  const boundId = (agent.model_id || '').trim();
  if (!boundId) return '系统默认';
  return _modelDisplayName(boundId) || boundId;
}

function _effectiveModelLabel(){
  if (currentModelId) return _modelDisplayName(currentModelId) || currentModelId;
  const agent = currentAgentId ? agentMap[currentAgentId] : null;
  return _agentBoundModelLabel(agent);
}

function _refreshAgentModelUI(){
  const agent = currentAgentId ? agentMap[currentAgentId] : null;
  if (!agent) return;

  const header = document.getElementById('centerHeader');
  const nameEl = document.getElementById('centerAgentName');
  const modelEl = document.getElementById('centerModelName');
  if (header && nameEl) {
    header.style.display = '';
    nameEl.textContent = agent.name;
  }
  if (modelEl) modelEl.textContent = _effectiveModelLabel();

  const ctx = document.getElementById('agentContext');
  if (ctx) {
    ctx.style.display = '';
    document.getElementById('ctxAgentName').textContent = agent.name;
    const skillsCount = _agentSkillsCount(agent);
    const modelLabel = currentModelId
      ? (_effectiveModelLabel() + '（覆盖）')
      : _agentBoundModelLabel(agent);
    document.getElementById('ctxAgentDetail').textContent =
      '模型 ' + modelLabel + ' · 挂载 ' + skillsCount + ' 个 Skill';
  }
}

function selectAgent(id, silent){
  currentAgentId = id;
  const agent = agentMap[id];
  if (!agent) return;

  // 切换 Agent 时重置为该 Agent 绑定模型（默认）
  currentModelId = null;
  _refreshAgentModelUI();

  if (!silent) {
    currentSessionId = null;
    document.getElementById('messages').innerHTML = _welcomeHtml();
    resetUsageStats();
  }
  loadSessions();
}

async function loadModels(){
  try {
    const data = await fetch('/api/settings/models').then(r => r.json());
    modelList = data.list || [];
    Object.keys(modelMap).forEach(k => { delete modelMap[k]; });
    modelList.forEach(m => { modelMap[m.id] = m; });
    _refreshAgentModelUI();
    return modelList;
  } catch(e) {
    console.error('loadModels', e);
    modelList = [];
    return [];
  }
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
  _closeStreamConnection();

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
    resetUsageStats();
  }
  loadSessions();
}

function newSession(){
  _closeStreamConnection();
  currentSessionId = null;
  document.getElementById('messages').innerHTML = _welcomeHtml();
  resetUsageStats();
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
  _append('<div class="msg user"><div class="msg-bubble">' + linkifyDataPaths(escapeHtml(text)) + '</div></div>');
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

function _closeStreamConnection(){
  if (currentStreamState) {
    _resetStreamRenderState(currentStreamState);
    currentStreamState = null;
  }
  if (currentEventSource){ currentEventSource.close(); currentEventSource = null; }
}

function finishStream(){
  _closeStreamConnection();
  setRunning(false); loadSessions();
}

function stopTask(){
  if (currentTaskId) fetch('/api/chat/' + currentTaskId + '/interrupt', {method:'POST'});
  _closeStreamConnection();
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
    _scheduleAssistantRender(s, b.bodyEl);
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
  } else if (ev.type === 'workflow_start'){
    const detail = (ev.workflow_name || 'Workflow') + ' · ' + (ev.node_count || 0) + ' 个节点';
    _addThinkStep(_ensureBlock(s, setState), s.thinkSteps, '🧭', 'Workflow 启动', detail);
  } else if (ev.type === 'workflow_node_ready'){
    const deps = (ev.depends_on || []).length;
    const inputs = (ev.input_from || []).length;
    _addThinkStep(_ensureBlock(s, setState), s.thinkSteps, '📦', `节点就绪：${ev.node_id}`, `${ev.node_type} · 依赖 ${deps} · 输入 ${inputs}`);
  } else if (ev.type === 'workflow_node_start'){
    _addThinkStep(_ensureBlock(s, setState), s.thinkSteps, '▶️', `执行节点：${ev.node_id}`, ev.task || ev.node_type || '');
  } else if (ev.type === 'workflow_node_done'){
    _addThinkStep(_ensureBlock(s, setState), s.thinkSteps, '✅', `节点完成：${ev.node_id}`, ev.output_preview || ev.node_type || '');
  } else if (ev.type === 'workflow_node_error'){
    _addThinkStep(_ensureBlock(s, setState), s.thinkSteps, '❌', `节点失败：${ev.node_id}`, ev.message || '执行失败');
  } else if (ev.type === 'workflow_done'){
    const detail = `完成 ${ev.completed_nodes || 0}/${ev.node_count || 0} 个节点`;
    _addThinkStep(_ensureBlock(s, setState), s.thinkSteps, '🏁', 'Workflow 完成', detail);
  } else if (ev.type === 'slow_think'){
    _addThinkStep(_ensureBlock(s, setState), s.thinkSteps, '💭', '策略复盘', ev.content);
  } else if (ev.type === 'done'){
    _finalizeAssistantRender(s);
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
    _finalizeAssistantRender(s);
    removeThinking();
    if (ev.message) _append('<div class="msg-info">' + escapeHtml(ev.message) + '</div>');
    const b = s.replyBlock;
    if (b) _collapseThink(b, s.thinkSteps);
    finishStream();
  } else if (ev.type === 'error'){
    _finalizeAssistantRender(s);
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
  resetUsageStats();

  try {
    const retryBody = {session_id: currentSessionId};
    if (currentModelId) retryBody.model_id = currentModelId;
    const res = await fetch('/api/chat/retry', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(retryBody),
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
    currentStreamState = _createStreamState(replyBlock);

    _connectToStream(currentTaskId, {
      getState: () => currentStreamState,
      setState: (updates) => Object.assign(currentStreamState, updates),
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
  currentStreamState = _createStreamState(replyBlock);

  _connectToStream(taskId, {
    getState: () => currentStreamState,
    setState: (updates) => Object.assign(currentStreamState, updates),
  });

  loadSessions();
}

/* ====== 快捷命令 ====== */

const SLASH_COMMANDS = [
  { name: '/clear', desc: '新建对话', run: () => newSession() },
  { name: '/agent', desc: '切换 Agent', run: () => openAgentPicker() },
  { name: '/model', desc: '切换模型', run: () => openModelPicker() },
];

let _slashMatches = [];
let _slashIndex = 0;
let _slashOpen = false;
let _slashMode = 'commands'; // 'commands' | 'agents' | 'models'
let _agentPickerItems = [];
let _modelPickerItems = [];

function hideSlashMenu(){
  _slashOpen = false;
  _slashMatches = [];
  _slashIndex = 0;
  _slashMode = 'commands';
  _agentPickerItems = [];
  _modelPickerItems = [];
  const menu = document.getElementById('slashMenu');
  if (menu){ menu.style.display = 'none'; menu.innerHTML = ''; }
}

function _slashQueryFromInput(value, cursorPos){
  if (!value || value[0] !== '/') return null;
  const spaceIdx = value.search(/\s/);
  if (spaceIdx >= 0) return null;
  if (typeof cursorPos === 'number' && cursorPos > value.length) return null;
  if (typeof cursorPos === 'number' && cursorPos < 1) return null;
  return value;
}

function _getSlashMatches(query){
  if (query == null) return [];
  return SLASH_COMMANDS.filter(c => c.name.startsWith(query));
}

function updateSlashMenu(){
  const input = document.getElementById('inputBox');
  const menu = document.getElementById('slashMenu');
  if (!input || !menu) return;

  if (_slashMode === 'agents' || _slashMode === 'models') return;

  const query = _slashQueryFromInput(input.value, input.selectionStart);
  const matches = _getSlashMatches(query);
  if (!matches.length){
    hideSlashMenu();
    return;
  }

  if (_slashMatches.length !== matches.length ||
      _slashMatches.some((m, i) => m.name !== matches[i].name)) {
    _slashIndex = 0;
  } else {
    _slashIndex = Math.max(0, Math.min(_slashIndex, matches.length - 1));
  }
  _slashMatches = matches;
  _slashMode = 'commands';
  _slashOpen = true;

  menu.innerHTML = matches.map((c, i) =>
    `<div class="slash-item${i === _slashIndex ? ' active' : ''}" role="option" data-idx="${i}"` +
    ` onclick="selectSlashItem(${i})">` +
    `<span class="slash-item-name">${escapeHtml(c.name)}</span>` +
    `<span class="slash-item-desc">${escapeHtml(c.desc)}</span></div>`
  ).join('');
  menu.style.display = '';
}

function _renderAgentPicker(){
  const menu = document.getElementById('slashMenu');
  if (!menu) return;

  const hint = '<div class="slash-menu-hint">选择Agent, ↑↓选择，Enter确认</div>';

  if (!_agentPickerItems.length) {
    menu.innerHTML = hint +
      '<div class="slash-item slash-item-empty">暂无 Agent，请先在 <a href="/agents">Agent 配置</a> 页创建</div>';
    menu.style.display = '';
    _slashOpen = true;
    return;
  }

  _slashIndex = Math.max(0, Math.min(_slashIndex, _agentPickerItems.length - 1));
  menu.innerHTML = hint + _agentPickerItems.map((a, i) => {
    const active = i === _slashIndex ? ' active' : '';
    const currentMark = a.id === currentAgentId
      ? '<span class="slash-item-current">(当前)</span>'
      : '';
    return `<div class="slash-item${active}" role="option" data-idx="${i}"` +
      ` onclick="selectSlashItem(${i})">` +
      `<span class="slash-item-name">${escapeHtml(a.name)}</span>${currentMark}</div>`;
  }).join('');
  menu.style.display = '';
  _slashOpen = true;
}

async function openAgentPicker(){
  const input = document.getElementById('inputBox');
  if (input){ input.value = ''; autoResize(input); }

  const agents = Object.values(agentMap);
  if (!agents.length) {
    await loadAgents();
  }
  const list = Object.values(agentMap);
  _slashMode = 'agents';
  _agentPickerItems = list;
  _slashMatches = [];
  _slashIndex = Math.max(0, list.findIndex(a => a.id === currentAgentId));
  if (_slashIndex < 0) _slashIndex = 0;
  _renderAgentPicker();
  if (input) input.focus();
}

function _renderModelPicker(){
  const menu = document.getElementById('slashMenu');
  if (!menu) return;

  const hint = '<div class="slash-menu-hint">选择模型, ↑↓选择，Enter确认</div>';
  _slashIndex = Math.max(0, Math.min(_slashIndex, _modelPickerItems.length - 1));
  menu.innerHTML = hint + _modelPickerItems.map((item, i) => {
    const active = i === _slashIndex ? ' active' : '';
    const isCurrent = item.id === null
      ? currentModelId === null
      : item.id === currentModelId;
    const currentMark = isCurrent
      ? '<span class="slash-item-current">(当前)</span>'
      : '';
    const desc = item.desc
      ? `<span class="slash-item-desc">${escapeHtml(item.desc)}</span>`
      : '';
    return `<div class="slash-item${active}" role="option" data-idx="${i}"` +
      ` onclick="selectSlashItem(${i})">` +
      `<span class="slash-item-name">${escapeHtml(item.name)}</span>${currentMark}${desc}</div>`;
  }).join('');
  menu.style.display = '';
  _slashOpen = true;
}

async function openModelPicker(){
  const input = document.getElementById('inputBox');
  if (input){ input.value = ''; autoResize(input); }

  if (!modelList.length) {
    await loadModels();
  }
  const agent = currentAgentId ? agentMap[currentAgentId] : null;
  const boundLabel = _agentBoundModelLabel(agent);
  const items = [
    { id: null, name: '默认', desc: boundLabel },
    ...modelList.map(m => ({
      id: m.id,
      name: m.name || m.model || m.id,
      desc: '',
    })),
  ];
  _slashMode = 'models';
  _modelPickerItems = items;
  _slashMatches = [];
  if (currentModelId === null) {
    _slashIndex = 0;
  } else {
    const idx = items.findIndex(it => it.id === currentModelId);
    _slashIndex = idx >= 0 ? idx : 0;
  }
  _renderModelPicker();
  if (input) input.focus();
}

function selectSlashItem(idx){
  if (_slashMode === 'agents') {
    if (idx < 0 || idx >= _agentPickerItems.length) return;
    _slashIndex = idx;
    confirmAgentPicker();
    return;
  }
  if (_slashMode === 'models') {
    if (idx < 0 || idx >= _modelPickerItems.length) return;
    _slashIndex = idx;
    confirmModelPicker();
    return;
  }
  if (idx < 0 || idx >= _slashMatches.length) return;
  _slashIndex = idx;
  completeSlashCommand();
}

function completeSlashCommand(){
  const input = document.getElementById('inputBox');
  if (!input || !_slashMatches.length) return;
  const cmd = _slashMatches[_slashIndex] || _slashMatches[0];
  if (cmd.name === '/agent' || cmd.name === '/model') {
    executeSlashCommand(cmd);
    return;
  }
  input.value = cmd.name;
  autoResize(input);
  hideSlashMenu();
  input.focus();
  const len = input.value.length;
  input.setSelectionRange(len, len);
}

function confirmAgentPicker(){
  const agent = _agentPickerItems[_slashIndex] || _agentPickerItems[0];
  const input = document.getElementById('inputBox');
  if (input){ input.value = ''; autoResize(input); }
  hideSlashMenu();
  if (agent) selectAgent(agent.id);
}

function confirmModelPicker(){
  const item = _modelPickerItems[_slashIndex] || _modelPickerItems[0];
  const input = document.getElementById('inputBox');
  if (input){ input.value = ''; autoResize(input); }
  hideSlashMenu();
  if (!item) return;
  currentModelId = item.id; // null = 默认
  _refreshAgentModelUI();
}

function executeSlashCommand(cmd){
  const input = document.getElementById('inputBox');
  if (input){ input.value = ''; autoResize(input); }
  if (cmd.name === '/agent') {
    openAgentPicker();
    return;
  }
  if (cmd.name === '/model') {
    openModelPicker();
    return;
  }
  hideSlashMenu();
  cmd.run();
}

function onInputBoxInput(el){
  autoResize(el);
  if (_slashMode === 'agents' || _slashMode === 'models') {
    const v = el.value;
    if (!v || v[0] !== '/') {
      hideSlashMenu();
      updateSlashMenu();
      return;
    }
  }
  updateSlashMenu();
}

function _moveSlashSelection(delta){
  if (!_slashOpen) return;
  let count = _slashMatches.length;
  if (_slashMode === 'agents') count = _agentPickerItems.length;
  else if (_slashMode === 'models') count = _modelPickerItems.length;
  if (!count) return;
  _slashIndex = (_slashIndex + delta + count) % count;
  const menu = document.getElementById('slashMenu');
  if (!menu) return;
  menu.querySelectorAll('.slash-item').forEach((el, i) => {
    el.classList.toggle('active', i === _slashIndex);
  });
}

/* ====== 发送消息 ====== */

async function sendMessage(){
  const input = document.getElementById('inputBox');
  const text = input.value.trim();
  if (!text && !currentFile) return;

  const slashCmd = SLASH_COMMANDS.find(c => c.name === text);
  if (slashCmd){
    executeSlashCommand(slashCmd);
    return;
  }

  userScrolledUp = false;
  hasNewContentSinceScroll = false;
  _updateScrollButton();

  const displayText = currentFile ? (text || '(无文本问题)') + '\n\n[已上传文件] ' + currentFile.name : text;
  input.value = ''; autoResize(input);
  hideSlashMenu();
  appendUserMsg(displayText);
  showThinking(); setRunning(true);

  let data;
  if (currentFile){
    const fd = new FormData();
    if (currentSessionId) fd.append('session_id', currentSessionId);
    if (currentAgentId) fd.append('agent_id', currentAgentId);
    if (currentModelId) fd.append('model_id', currentModelId);
    fd.append('message', text);
    fd.append('file', currentFile);
    const res = await fetch('/api/chat',{ method:'POST', body:fd });
    data = await res.json();
  } else {
    const payload = {session_id: currentSessionId, message: text, agent_id: currentAgentId};
    if (currentModelId) payload.model_id = currentModelId;
    const res = await fetch('/api/chat',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload),
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

  currentStreamState = _createStreamState(null);

  _connectToStream(currentTaskId, {
    getState: () => currentStreamState,
    setState: (updates) => Object.assign(currentStreamState, updates),
  });

  // 刷新会话列表以显示运行中状态
  loadSessions();
}

function handleKey(e){
  if (_slashOpen){
    if (e.key === 'ArrowDown'){ e.preventDefault(); _moveSlashSelection(1); return; }
    if (e.key === 'ArrowUp'){ e.preventDefault(); _moveSlashSelection(-1); return; }
    if (e.key === 'Escape'){ e.preventDefault(); hideSlashMenu(); return; }
    if (_slashMode === 'agents'){
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)){
        e.preventDefault();
        confirmAgentPicker();
        return;
      }
    } else if (_slashMode === 'models'){
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)){
        e.preventDefault();
        confirmModelPicker();
        return;
      }
    } else {
      if (e.key === 'Tab'){ e.preventDefault(); completeSlashCommand(); return; }
      if (e.key === 'Enter' && !e.shiftKey){
        e.preventDefault();
        const cmd = _slashMatches[_slashIndex] || _slashMatches[0];
        if (cmd){ executeSlashCommand(cmd); }
        return;
      }
    }
  }
  if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); sendMessage(); }
}
function autoResize(el){ el.style.height='auto'; el.style.height=Math.min(el.scrollHeight, 120) + 'px'; }

function fillExample(text){
  const input = document.getElementById('inputBox');
  if (input){ input.value = text; autoResize(input); hideSlashMenu(); input.focus(); }
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

/* ====== 文件路径抽屉预览 ====== */

function _formatSize(bytes){
  if (bytes == null || isNaN(bytes)) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function _drawerEls(){
  return {
    overlay: document.getElementById('fileDrawerOverlay'),
    drawer: document.getElementById('fileDrawer'),
    title: document.getElementById('fileDrawerTitle'),
    path: document.getElementById('fileDrawerPath'),
    body: document.getElementById('fileDrawerBody'),
    back: document.getElementById('fileDrawerBack'),
    close: document.getElementById('fileDrawerClose'),
    resizer: document.getElementById('fileDrawerResizer'),
    toolbar: document.getElementById('fileDrawerToolbar'),
  };
}

function _dataFileUrl(apiPath){
  return '/data-files/' + String(apiPath || '').split('/').filter(Boolean).map(encodeURIComponent).join('/');
}

function _clearDrawerToolbar(){
  const els = _drawerEls();
  _drawerCurrentFile = null;
  if (!els.toolbar) return;
  els.toolbar.innerHTML = '';
  els.toolbar.style.display = 'none';
}

function _triggerBlobDownload(blob, filename){
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || 'download';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
}

function _downloadDrawerSource(){
  const file = _drawerCurrentFile;
  if (!file) return;
  if (file.type === 'text' && file.content != null) {
    const mime = file.ext === '.json' ? 'application/json'
      : (file.ext === '.html' || file.ext === '.htm') ? 'text/html'
      : (file.ext === '.md' || file.ext === '.markdown') ? 'text/markdown;charset=utf-8'
      : 'text/plain;charset=utf-8';
    _triggerBlobDownload(new Blob([file.content], { type: mime }), file.name || 'download.txt');
    return;
  }
  const a = document.createElement('a');
  a.href = file.url || _dataFileUrl(file.path);
  a.download = file.name || 'download';
  a.target = '_blank';
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function _downloadDrawerMarkdownPdf(){
  const file = _drawerCurrentFile;
  if (!file || !window.html2pdf) {
    alert('PDF 导出组件未加载，请刷新后重试');
    return;
  }
  const container = document.createElement('div');
  container.style.padding = '24px';
  container.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';
  container.style.fontSize = '13px';
  container.style.lineHeight = '1.7';
  container.style.color = '#333';
  container.style.maxWidth = '800px';
  container.style.margin = '0 auto';
  try {
    container.innerHTML = window.marked
      ? marked.parse(file.content || '')
      : '<pre>' + escapeHtml(file.content || '') + '</pre>';
  } catch (_) {
    container.textContent = file.content || '';
  }
  const pdfName = String(file.name || 'document').replace(/\.md$/i, '').replace(/\.markdown$/i, '') + '.pdf';
  html2pdf().set({
    margin: [15, 15, 15, 15],
    filename: pdfName,
    image: { type: 'jpeg', quality: 0.95 },
    html2canvas: { scale: 2, logging: false, useCORS: true },
    jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
  }).from(container).save();
}

function _buildDrawerDownloadToolbar(file){
  const els = _drawerEls();
  if (!els.toolbar || !file) {
    _clearDrawerToolbar();
    return;
  }
  _drawerCurrentFile = file;
  els.toolbar.innerHTML = '';
  els.toolbar.style.display = 'flex';

  const isMd = file.ext === '.md' || file.ext === '.markdown';
  const wrap = document.createElement('div');
  wrap.className = 'drawer-download-wrap';

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'drawer-download-btn';
  btn.title = '下载';
  btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';

  if (!isMd) {
    btn.addEventListener('click', function(e){
      e.preventDefault();
      e.stopPropagation();
      _downloadDrawerSource();
    });
    wrap.appendChild(btn);
    els.toolbar.appendChild(wrap);
    return;
  }

  const dropdown = document.createElement('div');
  dropdown.className = 'drawer-download-dropdown';

  const mdItem = document.createElement('button');
  mdItem.type = 'button';
  mdItem.className = 'drawer-download-item';
  mdItem.innerHTML = 'Markdown<span class="desc">下载源文件 (.md)</span>';
  mdItem.addEventListener('click', function(e){
    e.preventDefault();
    e.stopPropagation();
    dropdown.classList.remove('show');
    _downloadDrawerSource();
  });

  const pdfItem = document.createElement('button');
  pdfItem.type = 'button';
  pdfItem.className = 'drawer-download-item';
  pdfItem.innerHTML = 'PDF<span class="desc">渲染后转换 (.pdf)</span>';
  pdfItem.addEventListener('click', function(e){
    e.preventDefault();
    e.stopPropagation();
    dropdown.classList.remove('show');
    _downloadDrawerMarkdownPdf();
  });

  dropdown.appendChild(mdItem);
  dropdown.appendChild(pdfItem);
  btn.addEventListener('click', function(e){
    e.preventDefault();
    e.stopPropagation();
    dropdown.classList.toggle('show');
  });
  wrap.appendChild(btn);
  wrap.appendChild(dropdown);
  els.toolbar.appendChild(wrap);
}

function _drawerMaxWidth(){
  return Math.max(DRAWER_MIN_WIDTH, Math.floor(window.innerWidth * DRAWER_MAX_WIDTH_RATIO));
}

function _clampDrawerWidth(px){
  const n = Math.round(Number(px) || 0);
  return Math.min(_drawerMaxWidth(), Math.max(DRAWER_MIN_WIDTH, n));
}

function _readStoredDrawerWidth(){
  try {
    const v = localStorage.getItem(DRAWER_WIDTH_KEY);
    if (!v) return null;
    const n = parseInt(v, 10);
    return isNaN(n) ? null : n;
  } catch (_) {
    return null;
  }
}

function _saveDrawerWidth(px){
  try { localStorage.setItem(DRAWER_WIDTH_KEY, String(px)); } catch (_) {}
}

function _applyDrawerWidth(px){
  const els = _drawerEls();
  if (!els.drawer) return;
  const w = _clampDrawerWidth(px != null ? px : (_readStoredDrawerWidth() || 560));
  els.drawer.style.width = w + 'px';
  return w;
}

function _setDrawerHeader(name, apiPath){
  const els = _drawerEls();
  if (els.title) els.title.textContent = name || '文件预览';
  if (els.path) els.path.textContent = _displayDataPath(apiPath);
  if (els.back) els.back.style.display = _drawerNavStack.length > 1 ? '' : 'none';
}

function openFileDrawer(){
  const els = _drawerEls();
  if (!els.drawer || !els.overlay) return;
  _applyDrawerWidth();
  els.overlay.hidden = false;
  requestAnimationFrame(function(){
    els.overlay.classList.add('open');
    els.drawer.classList.add('open');
    els.drawer.setAttribute('aria-hidden', 'false');
  });
  if (!_drawerEscBound) {
    _drawerEscBound = true;
    document.addEventListener('keydown', _onDrawerKeydown);
  }
}

function closeFileDrawer(){
  const els = _drawerEls();
  if (!els.drawer || !els.overlay) return;
  els.overlay.classList.remove('open');
  els.drawer.classList.remove('open');
  els.drawer.setAttribute('aria-hidden', 'true');
  window.setTimeout(function(){
    if (!els.drawer.classList.contains('open')) els.overlay.hidden = true;
  }, 220);
  _drawerNavStack = [];
  _clearDrawerToolbar();
  if (_drawerEscBound) {
    document.removeEventListener('keydown', _onDrawerKeydown);
    _drawerEscBound = false;
  }
}

function _onDrawerKeydown(e){
  if (e.key === 'Escape') closeFileDrawer();
}

function _drawerShowLoading(){
  const els = _drawerEls();
  _clearDrawerToolbar();
  if (els.body) els.body.innerHTML = '<div class="loading">加载中...</div>';
}

function _drawerShowError(msg){
  const els = _drawerEls();
  _clearDrawerToolbar();
  if (els.body) els.body.innerHTML = '<div class="drawer-error">' + escapeHtml(msg || '加载失败') + '</div>';
}

function _ftypeFromEntry(entry){
  if (!entry) return 'text';
  if (entry.type === 'dir') return 'folder';
  return _inferPathFtype(entry.name || entry.path || '');
}

function _renderDirListing(entries, apiPath){
  const els = _drawerEls();
  _clearDrawerToolbar();
  const name = (apiPath || '').split('/').filter(Boolean).pop() || 'data';
  _setDrawerHeader(name, apiPath || '');
  if (!entries || !entries.length) {
    els.body.innerHTML = '<div class="drawer-empty">该目录为空</div>';
    return;
  }
  let html = '<ul class="drawer-dir-list">';
  for (const entry of entries) {
    const ftype = _ftypeFromEntry(entry);
    const meta = entry.type === 'dir'
      ? (entry.hasChildren ? '文件夹' : '空文件夹')
      : _formatSize(entry.size);
    html +=
      '<li><button type="button" class="drawer-dir-item" data-path="' + escapeHtml(entry.path) +
      '" data-ftype="' + ftype + '">' +
      '<span class="path-icon path-icon-' + ftype + '" aria-hidden="true"></span>' +
      '<span class="dir-name">' + escapeHtml(entry.name) + '</span>' +
      '<span class="dir-meta">' + escapeHtml(meta) + '</span>' +
      '</button></li>';
  }
  html += '</ul>';
  els.body.innerHTML = html;
}

function _renderFilePreview(data, apiPath){
  const els = _drawerEls();
  const title = (data.name || apiPath) + (data.size != null ? ' (' + _formatSize(data.size) + ')' : '');
  _setDrawerHeader(title, apiPath);
  const fileMeta = {
    path: apiPath,
    name: data.name || (apiPath || '').split('/').pop() || 'download',
    type: data.type,
    ext: data.ext || _pathExt(data.name || apiPath),
    content: data.content,
    url: data.url || _dataFileUrl(apiPath),
  };
  _buildDrawerDownloadToolbar(fileMeta);
  if (data.type === 'pdf' || data.type === 'binary') {
    els.body.innerHTML = '<iframe src="' + escapeHtml(data.url) + '" title="' + escapeHtml(data.name || '') + '"></iframe>';
    return;
  }
  if (data.type === 'text') {
    let inner;
    if (data.ext === '.md' || data.ext === '.markdown') {
      try {
        if (window.marked) {
          const rawMd = marked.parse(data.content || '');
          const cleanMd = window.DOMPurify
            ? DOMPurify.sanitize(rawMd, { USE_PROFILES: { html: true } })
            : rawMd;
          inner = linkifyDataPaths(cleanMd);
        } else {
          inner = '<pre>' + escapeHtml(data.content || '') + '</pre>';
        }
      } catch (_) {
        inner = '<pre>' + escapeHtml(data.content || '') + '</pre>';
      }
    } else if (data.ext === '.json') {
      let pretty = data.content || '';
      try { pretty = JSON.stringify(JSON.parse(pretty), null, 2); } catch (_) {}
      inner = '<pre>' + escapeHtml(pretty) + '</pre>';
    } else if (data.ext === '.html' || data.ext === '.htm') {
      inner =
        '<div style="margin-bottom:12px;padding:8px 12px;background:var(--c-warning-bg);border-radius:4px;font-size:12px;color:var(--c-warning);">HTML 源文件预览</div>' +
        '<pre>' + escapeHtml(data.content || '') + '</pre>';
    } else {
      inner = '<pre>' + escapeHtml(data.content || '') + '</pre>';
    }
    els.body.innerHTML = '<div class="drawer-content">' + inner + '</div>';
    return;
  }
  _clearDrawerToolbar();
  _drawerShowError('不支持的文件类型');
}

async function _fetchChildren(apiPath){
  const q = apiPath ? ('?path=' + encodeURIComponent(apiPath)) : '';
  const res = await fetch('/api/files/children' + q);
  if (!res.ok) throw new Error('目录不存在或无法访问');
  return res.json();
}

async function _fetchView(apiPath){
  const res = await fetch('/api/files/view?path=' + encodeURIComponent(apiPath));
  if (!res.ok) throw new Error('文件不存在或无法访问');
  return res.json();
}

async function _loadDrawerTarget(apiPath, ftype, pushStack){
  const path = String(apiPath || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  const kind = ftype || _inferPathFtype(path);
  if (pushStack !== false) {
    _drawerNavStack.push({ path: path, ftype: kind });
  }
  _drawerShowLoading();
  openFileDrawer();
  try {
    if (kind === 'folder') {
      const entries = await _fetchChildren(path);
      _renderDirListing(entries, path);
      return;
    }
    try {
      const data = await _fetchView(path);
      _renderFilePreview(data, path);
    } catch (fileErr) {
      // 可能是无扩展名目录被误判为文件
      const entries = await _fetchChildren(path);
      if (_drawerNavStack.length) _drawerNavStack[_drawerNavStack.length - 1].ftype = 'folder';
      _renderDirListing(entries, path);
    }
  } catch (err) {
    _setDrawerHeader(path.split('/').pop() || '预览', path);
    _drawerShowError(err.message || '加载失败');
  }
}

function openPathInDrawer(apiPath, ftype){
  _drawerNavStack = [];
  _loadDrawerTarget(apiPath, ftype, true);
}

function _drawerGoBack(){
  if (_drawerNavStack.length <= 1) {
    closeFileDrawer();
    return;
  }
  _drawerNavStack.pop();
  const prev = _drawerNavStack[_drawerNavStack.length - 1];
  _loadDrawerTarget(prev.path, prev.ftype, false);
}

function _initDrawerResize(){
  const els = _drawerEls();
  if (!els.drawer || !els.resizer) return;
  _applyDrawerWidth();

  function onMove(e){
    if (!_drawerResizing) return;
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const width = _clampDrawerWidth(window.innerWidth - clientX);
    els.drawer.style.width = width + 'px';
    if (e.cancelable) e.preventDefault();
  }

  function onUp(){
    if (!_drawerResizing) return;
    _drawerResizing = false;
    els.drawer.classList.remove('is-resizing');
    document.body.classList.remove('file-drawer-resizing');
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    document.removeEventListener('touchmove', onMove);
    document.removeEventListener('touchend', onUp);
    const w = _clampDrawerWidth(els.drawer.getBoundingClientRect().width);
    els.drawer.style.width = w + 'px';
    _saveDrawerWidth(w);
  }

  function onDown(e){
    if (e.button != null && e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    _drawerResizing = true;
    els.drawer.classList.add('is-resizing');
    document.body.classList.add('file-drawer-resizing');
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.addEventListener('touchmove', onMove, { passive: false });
    document.addEventListener('touchend', onUp);
  }

  els.resizer.addEventListener('mousedown', onDown);
  els.resizer.addEventListener('touchstart', onDown, { passive: false });

  window.addEventListener('resize', function(){
    if (!els.drawer.classList.contains('open')) return;
    _applyDrawerWidth(els.drawer.getBoundingClientRect().width);
  });
}

function _initFileDrawer(){
  const els = _drawerEls();
  if (!els.drawer) return;
  _initDrawerResize();
  document.addEventListener('click', function(e){
    if (!els.toolbar) return;
    const open = els.toolbar.querySelector('.drawer-download-dropdown.show');
    if (!open) return;
    if (e.target.closest('.drawer-download-wrap')) return;
    open.classList.remove('show');
  });
  if (els.overlay) {
    els.overlay.addEventListener('click', function(){ closeFileDrawer(); });
  }
  if (els.close) {
    els.close.addEventListener('click', function(){ closeFileDrawer(); });
  }
  if (els.back) {
    els.back.addEventListener('click', function(){ _drawerGoBack(); });
  }
  if (els.body) {
    els.body.addEventListener('click', function(e){
      const chip = e.target.closest('.path-chip');
      if (chip && els.body.contains(chip)) {
        e.preventDefault();
        _loadDrawerTarget(chip.dataset.path || '', chip.dataset.ftype || '', true);
        return;
      }
      const row = e.target.closest('.drawer-dir-item');
      if (!row) return;
      e.preventDefault();
      _loadDrawerTarget(row.dataset.path || '', row.dataset.ftype || '', true);
    });
  }
  const messages = document.getElementById('messages');
  if (messages) {
    messages.addEventListener('click', function(e){
      const chip = e.target.closest('.path-chip');
      if (!chip || !messages.contains(chip)) return;
      e.preventDefault();
      e.stopPropagation();
      openPathInDrawer(chip.dataset.path || '', chip.dataset.ftype || '');
    });
  }
}

/* ====== 页面初始化 ====== */

window.addEventListener('DOMContentLoaded', () => {
  _initScrollListener();
  _initDragDrop();
  _initFileDrawer();
  const params = new URLSearchParams(location.search);
  const sid = params.get('session');
  const aid = params.get('agent');
  if (aid) currentAgentId = aid;
  Promise.all([loadAgents(), loadModels()]).then(async () => {
    _refreshAgentModelUI();
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
