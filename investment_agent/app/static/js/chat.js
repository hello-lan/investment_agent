let currentSessionId=null,currentTaskId=null,currentEventSource=null,totalInputTokens=0,totalOutputTokens=0,currentAgentId=null,currentFile=null;
let allSessions=[],agentMap={};

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

/* ====== Agent list ====== */

async function loadAgents(){
  const list = document.getElementById('agentList');
  try {
    const agents = await fetch('/api/agents').then(r => r.json());
    agents.forEach((a, i) => { agentMap[a.id] = a; });
    if (!agents.length) {
      list.innerHTML = '<div class="agent-empty">暂无 Agent，请先在 <a href="/agents" style="color:#1a1a2e">Agent 配置</a> 页创建</div>';
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
    document.getElementById('messages').innerHTML = '<div id="welcome" style="text-align:center;color:#999;margin-top:60px;font-size:14px;">输入股票代码或公司名称，开始分析</div>';
    totalInputTokens = 0; totalOutputTokens = 0; updateStats();
  }
  loadSessions();
}

/* ====== Sessions (right panel) ====== */

async function loadSessions(){
  const list = document.getElementById('historyList');
  const countEl = document.getElementById('historyCount');
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
    const title = s.title || '未命名';
    const date = (s.created_at || '').slice(0, 16);
    return `<div class="session-row${active}" data-sid="${s.id}" onclick="loadSession('${s.id}')">
      <div class="sess-title">${escapeHtml(title)}</div>
      <div class="sess-meta"><span>${date}</span></div>
    </div>`;
  }).join('');
}

async function loadSession(sid){
  currentSessionId = sid;
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
    loadSessions();
  } catch(e) {
    console.error('loadSession', e);
  }
}

function newSession(){
  currentSessionId = null;
  document.getElementById('messages').innerHTML = '<div id="welcome" style="text-align:center;color:#999;margin-top:60px;font-size:14px;">输入股票代码或公司名称，开始分析</div>';
  totalInputTokens = 0; totalOutputTokens = 0; updateStats();
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

function onFileSelected(e){
  const file = e?.target?.files?.[0] || null;
  if (!file){ clearFile(); return; }
  const ext = _fileExt(file.name);
  if (!ALLOWED_EXTS.has(ext)){
    alert('不支持的文件类型，仅支持 txt/md/pdf/xlsx/xls/docx/doc');
    clearFile();
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES){
    alert('文件过大，最大支持 10MB');
    clearFile();
    return;
  }
  currentFile = file;
  const chip = document.getElementById('fileNameChip');
  const btnClear = document.getElementById('btnClearFile');
  if (chip){ chip.textContent = file.name + ' (' + Math.ceil(file.size/1024) + 'KB)'; chip.style.display = 'inline-block'; }
  if (btnClear){ btnClear.style.display = 'inline-block'; }
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

function appendToolStep(name, output){
  _append('<div class="tool-step"><span class="tool-name">🔧 ' + escapeHtml(name) + '</span><div class="tool-result">' + escapeHtml((output||'').slice(0,300)) + '</div></div>');
}

function appendSlowThink(content){
  _append('<div class="slow-think">💭 <strong>策略复盘：</strong>' + escapeHtml(content) + '</div>');
}

function showThinking(){
  removeThinking();
  _append('<div id="thinking" class="thinking"><span></span><span></span><span></span></div>');
}

function removeThinking(){ const el = document.getElementById('thinking'); if (el) el.remove(); }

function updateStats(){
  document.getElementById('statInput').textContent = totalInputTokens.toLocaleString();
  document.getElementById('statOutput').textContent = totalOutputTokens.toLocaleString();
  document.getElementById('statCost').textContent = '$' + ((totalInputTokens*3 + totalOutputTokens*15)/1e6).toFixed(4);
}

function setRunning(r){
  document.getElementById('btnSend').disabled = r;
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

async function sendMessage(){
  const input = document.getElementById('inputBox');
  const text = input.value.trim();
  if (!text && !currentFile) return;

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
    _append('<div style="text-align:center;color:#e53935;font-size:12px;padding:8px">' + escapeHtml(msg) + '</div>');
    setRunning(false);
    return;
  }

  clearFile();
  currentTaskId = data.task_id;
  currentSessionId = data.session_id;

  let aDiv = null, aText = '', pendingTool = null;

  currentEventSource = new EventSource('/api/chat/' + currentTaskId + '/stream');
  currentEventSource.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === 'text_delta'){
      removeThinking(); aText += ev.content;
      if (!aDiv) aDiv = appendAssistantMsg(aText);
      else { aDiv.querySelector('.msg-bubble').innerHTML = renderMarkdown(aText); document.getElementById('messages').scrollTop = 99999; }
    } else if (ev.type === 'tool_call'){
      removeThinking(); pendingTool = ev;
    } else if (ev.type === 'tool_result'){
      appendToolStep(pendingTool?.tool || ev.tool, ev.output); pendingTool = null; showThinking();
    } else if (ev.type === 'slow_think'){
      removeThinking(); appendSlowThink(ev.content); showThinking();
    } else if (ev.type === 'done'){
      removeThinking();
      totalInputTokens += (ev.usage?.input_tokens || 0);
      totalOutputTokens += (ev.usage?.output_tokens || 0);
      updateStats(); finishStream();
    } else if (ev.type === 'error' || ev.type === 'interrupted'){
      removeThinking();
      if (ev.message) _append('<div style="text-align:center;color:#e53935;font-size:12px;padding:8px">' + escapeHtml(ev.message) + '</div>');
      finishStream();
    }
  };
  currentEventSource.onerror = () => { removeThinking(); finishStream(); };
}

function handleKey(e){ if (e.key==='Enter' && !e.shiftKey){ e.preventDefault(); sendMessage(); } }
function autoResize(el){ el.style.height='auto'; el.style.height=Math.min(el.scrollHeight, 120) + 'px'; }

window.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(location.search);
  const sid = params.get('session');
  const aid = params.get('agent');
  if (aid) currentAgentId = aid;
  loadAgents().then(() => {
    if (sid) loadSession(sid);
    else loadSessions();
  });
});
