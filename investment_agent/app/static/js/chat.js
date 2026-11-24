let currentSessionId=null,currentTaskId=null,currentEventSource=null,totalInputTokens=0,totalOutputTokens=0,currentAgentId=null,currentModelId=null,currentContextMode='chat',currentCollaborationMode='agent',currentFile=null,currentStreamState=null;
let _shareMode=false,_shareExporting=false;
let allSessions=[],agentMap={},modelMap={},modelList=[];
let userScrolledUp=false, hasNewContentSinceScroll=false;

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const ALLOWED_EXTS = new Set(['.txt','.md','.pdf','.xlsx','.xls','.docx','.doc']);
const STREAM_RENDER_INTERVAL_MS = 60;
const DATA_PATH_RE = /data[/\\](?:[^/\\\s`'"<>|]+[/\\])+[^/\\\s`'"<>|]+[/\\]?/gi;
const TITLE_GENERATE_MAX_USER_MSGS = 3;
const _titleGenerating = new Set();
const _titleGenSeq = Object.create(null);
const _titleOverrides = Object.create(null);
/** Fork 后需在用户首次发送消息时强制重命名的 session_id */
const _forceTitleSessions = new Set();

let _drawerNavStack = [];
let _drawerEscBound = false;
const DRAWER_WIDTH_KEY = 'fileDrawerWidth';
const DRAWER_MIN_WIDTH = 320;
const DRAWER_MAX_WIDTH_RATIO = 0.92;
let _drawerResizing = false;
let _drawerCurrentFile = null;
/** 抽屉打开来源：'tree' 目录树 | 'chat' 对话路径（默认） */
let _drawerOpenSource = 'chat';
let _drawerOutsideBound = false;

const LEFT_SPLIT_KEY = 'leftPanelHistoryRatio_v3';
/** 会话约 40% / 文件约 60%：兼顾会话可扫性与文件树展开空间 */
const LEFT_SPLIT_DEFAULT = 0.4;
const LEFT_SPLIT_MIN_PX = 120;
let _leftSplitResizing = false;
let _chatFileLoadedPaths = Object.create(null);
let _chatFileActiveRow = null;
let _chatFileCount = 0;
const FILE_VIEW_KEY = 'chatFileViewMode';
let _chatFileViewMode = 'list'; // list | icons
let _chatFileRootNodes = [];
let _chatFileIconPath = '';
let _chatFileIconNodes = [];
let _chatFileActivePath = '';

function escapeHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

const DEFAULT_AGENT_AVATAR = '/static/img/avatar-agent.svg';
const DEFAULT_USER_AVATAR = '/static/img/avatar-user.svg';

function _agentAvatarSrc(agent){
  const path = agent && agent.avatar ? String(agent.avatar).replace(/^\/+/, '') : '';
  if (!path) return DEFAULT_AGENT_AVATAR;
  const version = agent.updated_at ? ('?v=' + encodeURIComponent(agent.updated_at)) : '';
  return '/data-files/' + path + version;
}

function _msgIdentityHtml(role){
  const isUser = role === 'user';
  const agent = !isUser && currentAgentId ? agentMap[currentAgentId] : null;
  const name = isUser ? '我' : ((agent && agent.name) || 'Agent');
  const src = isUser ? DEFAULT_USER_AVATAR : _agentAvatarSrc(agent);
  const fallback = isUser ? DEFAULT_USER_AVATAR : DEFAULT_AGENT_AVATAR;
  return '<div class="msg-meta">' +
    '<img class="msg-avatar" alt="" src="' + escapeHtml(src) + '" onerror="this.onerror=null;this.src=\'' + fallback + '\'">' +
    '<span class="msg-name">' + escapeHtml(name) + '</span>' +
  '</div>';
}

function _msgCopyBtnHtml(withShare, withUserExtras){
  const share = withShare
    ? '<button type="button" class="btn-share-msg" title="分享" aria-label="分享">' +
        '<svg width="16" height="16" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M240.49,103.52l-80-80A12,12,0,0,0,140,32V68.74c-25.76,3.12-53.66,15.89-76.75,35.47-29.16,24.74-47.32,56.69-51.14,90A16,16,0,0,0,39.67,207h0c10.46-11.14,47-45.74,100.33-50.42V192a12,12,0,0,0,20.48,8.48l80-80A12,12,0,0,0,240.49,103.52ZM164,163V144a12,12,0,0,0-12-12c-49,0-86.57,21.56-109.79,40.11,7.13-18.16,19.63-35.22,36.57-49.59C101.3,103.41,128.67,92,152,92a12,12,0,0,0,12-12V61l51,51Z"/></svg>' +
      '</button>'
    : '';
  const fork = withShare
    ? '<button type="button" class="btn-fork-msg" title="分叉为新会话" aria-label="分叉">' +
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/><path d="M12 8v2a4 4 0 0 1-4 4H8"/><path d="M12 10a4 4 0 0 0 4 4h0"/><path d="M8 16v2"/><path d="M16 16v2"/></svg>' +
      '</button>'
    : '';
  const userExtras = withUserExtras
    ? '<button type="button" class="btn-edit-msg" title="编辑并重跑" aria-label="编辑">' +
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>' +
      '</button>'
    : '';
  return '<div class="msg-actions">' +
    '<button type="button" class="btn-copy-msg" title="复制" aria-label="复制">' +
      '<svg class="icon-copy" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
      '<svg class="icon-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>' +
    '</button>' + userExtras + fork + share + '</div>';
}

function _shareCheckHtml(){
  return '<label class="share-check">' +
    '<input type="checkbox" class="share-check-input" aria-label="选择这条对话">' +
    '<span class="share-check-dot" aria-hidden="true"></span>' +
  '</label>';
}

function _setMsgCopyText(node, text){
  if (node) node.dataset.copyText = String(text == null ? '' : text);
}

function _messageCopyText(msg){
  if (!msg) return '';
  if (typeof msg.dataset.copyText === 'string') return msg.dataset.copyText;
  const body = msg.querySelector('.bubble-content') || msg.querySelector('.msg-bubble');
  if (!body) return '';
  const clone = body.cloneNode(true);
  clone.querySelectorAll('.think-process, .thinking-inline').forEach(el => el.remove());
  return (clone.innerText || '').replace(/\u00a0/g, ' ').trim();
}

function _copyViaTextarea(text){
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
  ta.remove();
  return ok;
}

async function copyMessage(btn){
  const msg = btn.closest('.msg');
  const text = _messageCopyText(msg);
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      ok = true;
    }
  } catch (_) {}
  if (!ok) ok = _copyViaTextarea(text);
  if (!ok) return;
  btn.classList.add('copied');
  btn.title = '已复制';
  btn.setAttribute('aria-label', '已复制');
  clearTimeout(btn._copyTimer);
  btn._copyTimer = setTimeout(function(){
    btn.classList.remove('copied');
    btn.title = '复制';
    btn.setAttribute('aria-label', '复制');
  }, 1500);
}

function _shareRows(){
  return Array.from(document.querySelectorAll('#messages .msg-row'));
}

function _selectedShareCount(){
  return document.querySelectorAll('#messages .share-check-input:checked').length;
}

function _updateShareCount(){
  const n = _selectedShareCount();
  const el = document.getElementById('shareCount');
  if (el && !_shareExporting) el.textContent = '已选 ' + n + ' 条';
  document.querySelectorAll('.share-dock-btn').forEach(function(btn){
    if (_shareExporting) return;
    btn.disabled = n === 0;
  });
}

function enterShareMode(msg){
  if (_shareExporting) return;
  const rows = _shareRows();
  rows.forEach(function(row){
    const input = row.querySelector('.share-check-input');
    if (input) input.checked = false;
  });
  const row = msg && msg.closest ? msg.closest('.msg-row') : null;
  if (!row) return;
  const input = row.querySelector('.share-check-input');
  if (input) input.checked = true;
  const idx = rows.indexOf(row);
  for (let i = idx - 1; i >= 0; i--) {
    const prev = rows[i].querySelector('.msg');
    if (prev && prev.classList.contains('user')) {
      const prevInput = rows[i].querySelector('.share-check-input');
      if (prevInput) prevInput.checked = true;
      break;
    }
  }
  _shareMode = true;
  const main = document.querySelector('.main');
  if (main) main.classList.add('share-mode');
  const messages = document.getElementById('messages');
  if (messages) messages.classList.add('share-mode');
  const header = document.getElementById('shareHeader');
  const dock = document.getElementById('shareDock');
  if (header) header.hidden = false;
  if (dock) dock.hidden = false;
  _updateShareCount();
  if (msg && msg.scrollIntoView) msg.scrollIntoView({ block: 'nearest' });
}

function exitShareMode(){
  if (_shareExporting) return;
  if (!_shareMode && !document.querySelector('.main.share-mode')) return;
  _shareMode = false;
  const main = document.querySelector('.main');
  if (main) main.classList.remove('share-mode');
  const messages = document.getElementById('messages');
  if (messages) messages.classList.remove('share-mode');
  const header = document.getElementById('shareHeader');
  const dock = document.getElementById('shareDock');
  if (header) header.hidden = true;
  if (dock) dock.hidden = true;
  document.querySelectorAll('#messages .share-check-input').forEach(function(input){
    input.checked = false;
  });
  _setShareBusy(false);
}

function _onShareKeydown(e){
  if (e.key !== 'Escape' || !_shareMode || _shareExporting) return;
  const drawer = document.getElementById('fileDrawer');
  if (drawer && drawer.classList.contains('open')) return;
  e.preventDefault();
  exitShareMode();
}

function _setShareBusy(busy){
  _shareExporting = !!busy;
  document.querySelectorAll('.share-dock-btn').forEach(function(btn){
    const label = btn.querySelector('.share-dock-label');
    if (busy) {
      btn.disabled = true;
      if (label) {
        if (!btn.dataset.label) btn.dataset.label = label.textContent;
        label.textContent = '生成中';
      }
    } else if (label && btn.dataset.label) {
      label.textContent = btn.dataset.label;
    }
  });
  if (!busy) _updateShareCount();
}

function _shareFilename(ext){
  const d = new Date();
  const p = function(n){ return String(n).padStart(2, '0'); };
  const stamp = d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '_' + p(d.getHours()) + p(d.getMinutes());
  return '对话分享_' + stamp + '.' + ext;
}

function _rasterizeImage(src, box){
  return new Promise(function(resolve){
    if (!src) { resolve(''); return; }
    if (String(src).indexOf('data:') === 0) { resolve(src); return; }
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = function(){
      try {
        const canvas = document.createElement('canvas');
        let w = img.naturalWidth || box || 64;
        let h = img.naturalHeight || box || 64;
        if (box) { w = box; h = box; }
        const maxEdge = 1600;
        if (w > maxEdge || h > maxEdge) {
          const ratio = Math.min(maxEdge / w, maxEdge / h);
          w = Math.max(1, Math.round(w * ratio));
          h = Math.max(1, Math.round(h * ratio));
        }
        canvas.width = Math.max(1, w);
        canvas.height = Math.max(1, h);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/png'));
      } catch (_) {
        resolve(src);
      }
    };
    img.onerror = function(){ resolve(src); };
    img.src = src;
  });
}

function _isSameOriginUrl(src){
  try {
    return new URL(src, window.location.origin).origin === window.location.origin;
  } catch (_) {
    return false;
  }
}

async function _buildShareSheet(){
  const sheet = document.createElement('div');
  sheet.className = 'share-export';
  const rows = _shareRows().filter(function(row){
    const input = row.querySelector('.share-check-input');
    return input && input.checked;
  });
  for (const row of rows) {
    const msg = row.querySelector('.msg');
    if (!msg) continue;
    const item = document.createElement('div');
    item.className = 'msg ' + (msg.classList.contains('user') ? 'user' : 'assistant');
    const meta = msg.querySelector('.msg-meta');
    if (meta) {
      const metaClone = meta.cloneNode(true);
      const avatar = metaClone.querySelector('.msg-avatar');
      if (avatar) {
        const png = await _rasterizeImage(avatar.currentSrc || avatar.src, 128);
        avatar.removeAttribute('onerror');
        if (png) avatar.src = png;
      }
      item.appendChild(metaClone);
    }
    const bubble = msg.querySelector('.msg-bubble');
    if (bubble) {
      const bubbleClone = bubble.cloneNode(true);
      bubbleClone.querySelectorAll('.path-chip').forEach(function(chip){
        const text = chip.querySelector('.path-text');
        const span = document.createElement('span');
        span.textContent = text ? text.textContent : (chip.textContent || '');
        chip.replaceWith(span);
      });
      bubbleClone.querySelectorAll('.think-process, .thinking-inline, .retry-area, .msg-actions').forEach(function(el){
        el.remove();
      });
      bubbleClone.querySelectorAll('button').forEach(function(el){ el.remove(); });
      const imgs = Array.from(bubbleClone.querySelectorAll('img'));
      for (const img of imgs) {
        const src = img.getAttribute('src') || '';
        if (!src || src.indexOf('data:') === 0 || !_isSameOriginUrl(src)) continue;
        const png = await _rasterizeImage(src);
        if (png) img.src = png;
      }
      item.appendChild(bubbleClone);
    }
    sheet.appendChild(item);
  }
  return sheet;
}

async function _downloadShareImage(sheet){
  if (!window.html2canvas) {
    alert('图片导出组件未加载，请刷新后重试');
    return;
  }
  await new Promise(function(resolve){
    requestAnimationFrame(function(){ requestAnimationFrame(resolve); });
  });
  const height = Math.ceil(sheet.scrollHeight);
  const width = Math.ceil(sheet.scrollWidth);
  const MAX = 16384;
  if (height < 1 || width < 1) throw new Error('empty share sheet');
  let scale = 2;
  if (height * scale > MAX || width * scale > MAX) {
    scale = Math.min(MAX / height, MAX / width, 2);
    scale = Math.floor(scale * 100) / 100;
  }
  if (scale < 1) {
    alert('选中的对话太长，无法生成图片。请少选几条后再试。');
    return;
  }
  const canvas = await window.html2canvas(sheet, {
    scale: scale,
    useCORS: true,
    backgroundColor: '#ffffff',
    logging: false,
  });
  const blob = await new Promise(function(resolve){ canvas.toBlob(resolve, 'image/png'); });
  if (!blob) throw new Error('png');
  _triggerBlobDownload(blob, _shareFilename('png'));
}

async function _downloadSharePdf(sheet){
  if (!window.html2pdf) {
    alert('PDF 导出组件未加载，请刷新后重试');
    return;
  }
  const worker = window.html2pdf().set({
    margin: [12, 12, 12, 12],
    filename: _shareFilename('pdf'),
    image: { type: 'jpeg', quality: 0.95 },
    html2canvas: { scale: 2, logging: false, useCORS: true, backgroundColor: '#ffffff' },
    jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
    pagebreak: { mode: ['css', 'legacy'], avoid: '.msg' },
  }).from(sheet).save();
  if (worker && typeof worker.then === 'function') await worker;
}

async function _exportShare(kind){
  if (_shareExporting || !_shareMode) return;
  if (_selectedShareCount() === 0) return;
  _setShareBusy(true);
  let sheet = null;
  try {
    sheet = await _buildShareSheet();
    if (!sheet.firstElementChild) {
      alert('请至少选择一条对话');
      return;
    }
    const host = document.createElement('div');
    host.className = 'share-export-host';
    sheet.style.position = 'relative';
    sheet.style.left = '0';
    sheet.style.top = '0';
    host.appendChild(sheet);
    document.body.appendChild(host);
    if (kind === 'pdf') await _downloadSharePdf(sheet);
    else await _downloadShareImage(sheet);
  } catch (err) {
    console.error(err);
    alert('导出失败。对话太长或包含无法绘制的内容时，请少选几条后再试。');
  } finally {
    if (sheet) {
      const host = sheet.parentNode;
      if (host && host.classList && host.classList.contains('share-export-host')) host.remove();
      else if (sheet.parentNode) sheet.parentNode.removeChild(sheet);
    }
    _setShareBusy(false);
  }
}

function _initShareMode(){
  const cancel = document.getElementById('shareCancel');
  if (cancel) cancel.addEventListener('click', exitShareMode);
  const imageBtn = document.getElementById('shareImageBtn');
  const pdfBtn = document.getElementById('sharePdfBtn');
  if (imageBtn) imageBtn.addEventListener('click', function(){ _exportShare('image'); });
  if (pdfBtn) pdfBtn.addEventListener('click', function(){ _exportShare('pdf'); });
  document.addEventListener('keydown', _onShareKeydown);
  const messages = document.getElementById('messages');
  if (messages) {
    messages.addEventListener('change', function(e){
      if (e.target && e.target.classList && e.target.classList.contains('share-check-input')) {
        _updateShareCount();
      }
    });
  }
}

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
    thinkStepSeq: 0,
    thinkLive: true,
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

async function loadAgents(){
  try {
    const agents = await fetch('/api/agents').then(r => r.json());
    Object.keys(agentMap).forEach(k => { delete agentMap[k]; });
    agents.forEach((a) => { agentMap[a.id] = a; });
    renderComposerAgents();
    if (!agents.length) return agents;
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
}

function selectAgent(id, silent){
  currentAgentId = id;
  const agent = agentMap[id];
  renderComposerAgents();
  if (!agent) return;

  // 切换 Agent 时重置为该 Agent 绑定模型（默认）
  currentModelId = null;
  _refreshAgentModelUI();

  if (!silent) {
    exitShareMode();
    currentSessionId = null;
    document.getElementById('messages').innerHTML = _welcomeHtml();
    resetUsageStats();
    setUserMsgCount(0);
  }
  loadSessions();
}

function renderComposerAgents(){
  const el = document.getElementById('composerAgents');
  if (!el) return;
  const list = Object.values(agentMap)
    .filter(a => a && a.show_in_composer)
    .sort((a, b) => {
      const sa = Number(a.composer_sort) || 0;
      const sb = Number(b.composer_sort) || 0;
      if (sa !== sb) return sa - sb;
      return String(a.created_at || '').localeCompare(String(b.created_at || ''));
    });
  if (!list.length) {
    el.hidden = true;
    el.innerHTML = '';
    return;
  }
  el.hidden = false;
  el.innerHTML = list.map(a => {
    const active = a.id === currentAgentId;
    return '<button type="button" class="composer-agent-chip' + (active ? ' active' : '') +
      '" data-agent-id="' + escapeHtml(a.id) + '" aria-pressed="' + (active ? 'true' : 'false') + '">' +
      '<img alt="" src="' + escapeHtml(_agentAvatarSrc(a)) + '" onerror="this.onerror=null;this.src=\'' + DEFAULT_AGENT_AVATAR + '\'">' +
      '<span>' + escapeHtml(a.name || 'Agent') + '</span>' +
    '</button>';
  }).join('');
}

function _initComposerAgents(){
  const el = document.getElementById('composerAgents');
  if (!el) return;
  el.addEventListener('click', (e) => {
    const btn = e.target.closest('.composer-agent-chip');
    if (!btn) return;
    const id = btn.getAttribute('data-agent-id');
    if (!id || id === currentAgentId) return;
    selectAgent(id);
  });
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

const _SESSION_TZ = 'Asia/Shanghai'; // UTC+8

function _parseSessionDate(iso){
  const raw = String(iso || '').trim();
  if (!raw) return null;
  let d = new Date(raw);
  if (isNaN(d.getTime())) d = new Date(raw.replace(' ', 'T'));
  if (isNaN(d.getTime())) return null;
  return d;
}

function _sessionPartsInTz(d){
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: _SESSION_TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(d);
  const map = {};
  for (const p of parts) {
    if (p.type !== 'literal') map[p.type] = p.value;
  }
  return {
    year: map.year,
    month: map.month,
    day: map.day,
    hour: map.hour,
    minute: map.minute,
    dateKey: map.year + '-' + map.month + '-' + map.day,
  };
}

function _sessionGroupKey(iso){
  const d = _parseSessionDate(iso);
  if (!d) return 'earlier';
  const that = _sessionPartsInTz(d);
  const today = _sessionPartsInTz(new Date());
  const startThat = Date.UTC(+that.year, +that.month - 1, +that.day);
  const startToday = Date.UTC(+today.year, +today.month - 1, +today.day);
  const diffDays = Math.round((startToday - startThat) / 86400000);
  if (diffDays <= 0) return 'today';
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return 'week';
  if (diffDays < 30) return 'month';
  return 'earlier';
}

const _SESSION_GROUP_LABELS = {
  today: '今天',
  yesterday: '昨天',
  week: '近 7 天',
  month: '近 30 天',
  earlier: '更早',
};

function _formatSessionTime(iso){
  const raw = String(iso || '');
  const d = _parseSessionDate(iso);
  if (!d) return raw.slice(5, 16) || '';
  const p = _sessionPartsInTz(d);
  const group = _sessionGroupKey(iso);
  if (group === 'today' || group === 'yesterday') return p.hour + ':' + p.minute;
  return p.year + '-' + p.month + '-' + p.day;
}

function _renderSessionRow(s){
  const active = s.id === currentSessionId ? ' active' : '';
  const running = s.status === 'running';
  const naming = !running && _titleGenerating.has(s.id);
  const runningCls = running ? ' is-running' : (naming ? ' is-naming' : '');
  const spinner = running
    ? '<span class="running-spinner" aria-hidden="true"></span>'
    : (naming ? '<span class="running-spinner title-spinner" aria-hidden="true"></span>' : '');
  const title = _titleOverrides[s.id] || s.title || '未命名';
  const safeTitle = escapeHtml(title).replace(/"/g, '&quot;');
  const time = _formatSessionTime(s.created_at);
  return `<div class="session-row${active}${runningCls}" data-sid="${s.id}" role="button" tabindex="0" onclick="loadSession('${s.id}')" title="${safeTitle}">
    <div class="sess-title">${spinner}<span class="sess-title-text">${escapeHtml(title)}</span></div>
    <span class="sess-meta">${escapeHtml(time)}</span>
    <button type="button" class="btn-del" onclick="event.stopPropagation();deleteSession('${s.id}')" aria-label="删除会话" title="删除">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
    </button>
  </div>`;
}

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

  countEl.textContent = filtered.length ? String(filtered.length) : '';

  if (!filtered.length) {
    list.innerHTML = '<div class="history-empty">暂无历史会话</div>';
    return;
  }

  let html = '';
  let lastGroup = null;
  filtered.forEach(s => {
    const group = _sessionGroupKey(s.created_at);
    if (group !== lastGroup) {
      html += '<div class="history-group-label">' + _SESSION_GROUP_LABELS[group] + '</div>';
      lastGroup = group;
    }
    html += _renderSessionRow(s);
  });
  list.innerHTML = html;
}

function _userMsgCountEl(){
  let el = document.getElementById('userMsgCount');
  if (!el) {
    el = document.createElement('span');
    el.id = 'userMsgCount';
    el.hidden = true;
    el.textContent = '0';
    const main = document.querySelector('.main') || document.body;
    main.insertBefore(el, main.firstChild);
  }
  return el;
}

function getUserMsgCount(){
  const n = parseInt(_userMsgCountEl().textContent, 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function setUserMsgCount(n){
  const v = Math.max(0, Number(n) || 0);
  _userMsgCountEl().textContent = String(v);
}

function incrementUserMsgCount(){
  setUserMsgCount(getUserMsgCount() + 1);
}

function _countUserMessages(messages){
  return (messages || []).filter(m => m && m.role === 'user').length;
}

function _sessionRowEl(sid){
  return document.querySelector('.session-row[data-sid="' + sid + '"]');
}

function _setActiveSession(sid){
  document.querySelectorAll('.session-row.active').forEach(el => {
    if (!sid || el.getAttribute('data-sid') !== sid) el.classList.remove('active');
  });
  if (!sid) return;
  const row = _sessionRowEl(sid);
  if (row) row.classList.add('active');
}

function _updateHistoryCount(){
  const countEl = document.getElementById('historyCount');
  if (!countEl) return;
  const n = currentAgentId
    ? allSessions.filter(s => s.agent_id === currentAgentId).length
    : 0;
  countEl.textContent = n ? String(n) : '';
}

function _markSessionRunning(sid){
  const s = allSessions.find(x => x.id === sid);
  if (s) {
    s.status = 'running';
    if (currentTaskId) s.current_task_id = currentTaskId;
  }
  const row = _sessionRowEl(sid);
  if (!row) return;
  row.classList.add('is-running');
  row.classList.remove('is-naming');
  const titleEl = row.querySelector('.sess-title');
  if (!titleEl) return;
  const old = titleEl.querySelector('.running-spinner');
  if (old) old.remove();
  const spin = document.createElement('span');
  spin.className = 'running-spinner';
  spin.setAttribute('aria-hidden', 'true');
  titleEl.insertBefore(spin, titleEl.firstChild);
}

function _clearSessionRunning(sid){
  const s = allSessions.find(x => x.id === sid);
  if (s && s.status === 'running') {
    s.status = 'active';
    s.current_task_id = null;
  }
  const row = sid ? _sessionRowEl(sid) : null;
  if (!row) return;
  row.classList.remove('is-running');
  const spin = row.querySelector('.running-spinner:not(.title-spinner)');
  if (spin) spin.remove();
}

function _insertSessionRow(session){
  const list = document.getElementById('historyList');
  if (!list) return;
  const empty = list.querySelector('.history-empty');
  if (empty) empty.remove();

  let label = null;
  for (const el of list.children) {
    if (el.classList && el.classList.contains('history-group-label') && el.textContent === _SESSION_GROUP_LABELS.today) {
      label = el;
      break;
    }
  }
  if (!label) {
    label = document.createElement('div');
    label.className = 'history-group-label';
    label.textContent = _SESSION_GROUP_LABELS.today;
    list.prepend(label);
  }
  label.insertAdjacentHTML('afterend', _renderSessionRow(session));
  _updateHistoryCount();
}

function _ensureSessionRow(session){
  const idx = allSessions.findIndex(x => x.id === session.id);
  if (idx >= 0) Object.assign(allSessions[idx], session);
  else allSessions.unshift(session);
  const stored = allSessions.find(x => x.id === session.id) || session;
  if (currentAgentId && stored.agent_id && stored.agent_id !== currentAgentId) return;
  if (!_sessionRowEl(stored.id)) _insertSessionRow(stored);
}

function _activateSentSession(sessionId, previewText){
  const existing = allSessions.find(x => x.id === sessionId);
  if (existing) {
    existing.status = 'running';
    if (currentTaskId) existing.current_task_id = currentTaskId;
    _setActiveSession(sessionId);
    _markSessionRunning(sessionId);
    return;
  }
  const title = (previewText || '').trim().slice(0, 50) || '未命名';
  _ensureSessionRow({
    id: sessionId,
    agent_id: currentAgentId,
    title: title,
    status: 'running',
    current_task_id: currentTaskId,
    created_at: new Date().toISOString(),
    context_mode: currentContextMode,
  });
  _setActiveSession(sessionId);
}

function _markSessionNaming(sid){
  const row = _sessionRowEl(sid);
  if (!row || row.classList.contains('is-running')) return;
  row.classList.add('is-naming');
  const titleEl = row.querySelector('.sess-title');
  if (titleEl && !titleEl.querySelector('.title-spinner')) {
    const spin = document.createElement('span');
    spin.className = 'running-spinner title-spinner';
    spin.setAttribute('aria-hidden', 'true');
    titleEl.insertBefore(spin, titleEl.firstChild);
  }
}

function _clearSessionNaming(sid){
  const row = _sessionRowEl(sid);
  if (!row) return;
  row.classList.remove('is-naming');
  const spin = row.querySelector('.title-spinner');
  if (spin) spin.remove();
}

function _applySessionTitle(sid, title){
  _titleGenerating.delete(sid);
  const display = (title || '').trim() || '未命名';
  _titleOverrides[sid] = display;
  const s = allSessions.find(x => x.id === sid);
  if (s) s.title = display;
  const row = _sessionRowEl(sid);
  if (!row) return;
  row.classList.remove('is-naming');
  row.setAttribute('title', display);
  const textEl = row.querySelector('.sess-title-text');
  if (textEl) textEl.textContent = display;
  const spin = row.querySelector('.title-spinner');
  if (spin) spin.remove();
}

async function maybeGenerateSessionTitle(sessionId, opts){
  if (!sessionId) return;
  const force = !!(opts && opts.force);
  if (!force && getUserMsgCount() > TITLE_GENERATE_MAX_USER_MSGS) return;

  const seq = (_titleGenSeq[sessionId] || 0) + 1;
  _titleGenSeq[sessionId] = seq;
  _titleGenerating.add(sessionId);
  _markSessionNaming(sessionId);

  try {
    const res = await fetch('/api/sessions/' + encodeURIComponent(sessionId) + '/title', {
      method: 'POST',
    });
    if (_titleGenSeq[sessionId] !== seq) return;
    if (!res.ok) throw new Error('title http ' + res.status);
    const data = await res.json();
    _applySessionTitle(sessionId, data.title || '');
  } catch (e) {
    if (_titleGenSeq[sessionId] !== seq) return;
    _titleGenerating.delete(sessionId);
    _clearSessionNaming(sessionId);
  }
}

async function loadSession(sid){
  exitShareMode();
  // 如果有正在运行的 SSE 连接，先关闭
  _closeStreamConnection();

  currentSessionId = sid;
  _setActiveSession(sid);
  _showSpinner('messages', '加载会话中...');

  // 检查是否是运行中的会话
  const sessionData = allSessions.find(s => s.id === sid);
  if (sessionData && sessionData.context_mode === 'full') {
    currentContextMode = 'full';
    updateContextModeChip();
  } else if (sessionData) {
    currentContextMode = 'chat';
    updateContextModeChip();
  }
  if (sessionData) _syncCollaborationMode(sessionData.collaboration_mode);
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
      if (m.role === 'user') appendUserMsg(m.content, m.id);
      else if (m.role === 'assistant') appendAssistantMsg(m.content, m.id);
    });
    const sess = data.session || {};
    currentContextMode = sess.context_mode === 'full' ? 'full' : 'chat';
    updateContextModeChip();
    _syncCollaborationMode(sess.collaboration_mode);
    totalInputTokens = sess.input_tokens || 0;
    totalOutputTokens = sess.output_tokens || 0;
    updateStats();
    setRunning(false);
    setUserMsgCount(_countUserMessages(data.messages));
  } catch(e) {
    console.error('loadSession', e);
    setUserMsgCount(0);
  }
}

async function deleteSession(sid){
  if (!confirm('确认删除该会话？')) return;
  await fetch('/api/sessions/' + sid, {method:'DELETE'});
  if (currentSessionId === sid) {
    exitShareMode();
    currentSessionId = null;
    document.getElementById('messages').innerHTML = _welcomeHtml();
    resetUsageStats();
    setUserMsgCount(0);
    _syncCollaborationMode('agent');
  }
  loadSessions();
}

function newSession(){
  exitShareMode();
  _closeStreamConnection();
  currentSessionId = null;
  currentContextMode = 'chat';
  updateContextModeChip();
  _syncCollaborationMode('agent');
  document.getElementById('messages').innerHTML = _welcomeHtml();
  resetUsageStats();
  setUserMsgCount(0);
  setRunning(false);
  _setActiveSession(null);
}

/* ====== Chat ====== */

function _append(html){
  const c = document.getElementById('messages');
  const d = document.createElement('div');
  d.innerHTML = html;
  const node = d.firstElementChild || d;
  c.appendChild(node);
  c.scrollTop = c.scrollHeight;
  return node;
}

function _appendShareRow(msgHtml){
  const row = _append('<div class="msg-row">' + _shareCheckHtml() + msgHtml + '</div>');
  return row.querySelector('.msg') || row;
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
    alert('文件过大，最大支持 100MB');
    return false;
  }
  currentFile = file;
  const chip = document.getElementById('fileNameChip');
  const attachments = document.getElementById('composerAttachments');
  if (chip) chip.textContent = file.name + ' (' + Math.ceil(file.size/1024) + 'KB)';
  if (attachments) attachments.hidden = false;
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
  const attachments = document.getElementById('composerAttachments');
  if (chip) chip.textContent = '';
  if (attachments) attachments.hidden = true;
}

function appendUserMsg(text, messageId){
  const w = document.getElementById('welcome'); if (w) w.remove();
  const idAttr = messageId ? ' data-message-id="' + escapeHtml(String(messageId)) + '"' : '';
  const node = _appendShareRow(
    '<div class="msg user"' + idAttr + '>' +
      _msgIdentityHtml('user') +
      '<div class="msg-bubble">' + linkifyDataPaths(escapeHtml(text)) + '</div>' +
      _msgCopyBtnHtml(false, true) +
    '</div>'
  );
  _setMsgCopyText(node, text);
  if (messageId) node.dataset.messageId = String(messageId);
  return node;
}

function updateUserMsgBubble(node, text){
  if (!node) return;
  const bubble = node.querySelector('.msg-bubble');
  if (!bubble) return;
  bubble.innerHTML = linkifyDataPaths(escapeHtml(text));
  _setMsgCopyText(node, text);
}

function appendAssistantMsg(md, messageId){
  const idAttr = messageId ? ' data-message-id="' + escapeHtml(String(messageId)) + '"' : '';
  const node = _appendShareRow(
    '<div class="msg assistant"' + idAttr + '>' +
      _msgIdentityHtml('assistant') +
      '<div class="msg-bubble">' + renderMarkdown(md) + '</div>' +
      _msgCopyBtnHtml(true) +
    '</div>'
  );
  _setMsgCopyText(node, md);
  if (messageId) node.dataset.messageId = String(messageId);
  return node;
}

function _createReplyBlock(){
  const row = document.createElement('div');
  row.className = 'msg-row';
  row.innerHTML =
    _shareCheckHtml() +
    '<div class="msg assistant">' +
    _msgIdentityHtml('assistant') +
    '<div class="msg-bubble">' +
      '<div class="bubble-content">' +
        '<div class="thinking-inline"><span></span><span></span><span></span></div>' +
      '</div>' +
      '<div class="think-process" style="display:none">' +
        '<div class="think-header" style="display:none">' +
          '<span class="think-spinner"></span>' +
          '<span class="think-header-text"></span>' +
        '</div>' +
        '<div class="think-summary" style="display:none"></div>' +
        '<div class="think-steps"></div>' +
      '</div>' +
    '</div>' +
    _msgCopyBtnHtml(true) +
    '<div class="retry-area" style="display:none">' +
      '<button class="btn-retry" onclick="retryTask()">🔄 重试</button>' +
    '</div></div>';
  document.getElementById('messages').appendChild(row);
  const container = row.querySelector('.msg');
  return {
    container,
    bodyEl: container.querySelector('.bubble-content'),
    thinkEl: container.querySelector('.think-process'),
    headerEl: container.querySelector('.think-header'),
    headerTextEl: container.querySelector('.think-header-text'),
    stepsEl: container.querySelector('.think-steps'),
    summaryEl: container.querySelector('.think-summary'),
    retryEl: container.querySelector('.retry-area'),
  };
}

/* ---- Live Step Ledger ---- */

const _TOOL_LABELS = {
  get_stock_info: '查询股票信息',
  get_stock_price: '查询股价',
  get_income_statement: '获取利润表',
  get_balance_sheet: '获取资产负债表',
  get_cash_flow: '获取现金流量表',
  get_valuation: '获取估值数据',
  get_financial_indicators: '获取财务指标',
  get_stock_realtime: '查询实时行情',
  get_market_index: '查询市场指数',
  run_command: '执行命令',
  run_python_script: '运行 Python 脚本',
  read_file: '读取文件',
  write_file: '写入文件',
  list_files: '列出文件',
  search_text: '搜索文本',
  Skill: '运行技能',
  propose_plan: '提交计划',
};

const _THINK_DETAIL_TRUNCATE = 120;

function _parseToolInput(raw){
  if (raw == null) return null;
  if (typeof raw === 'object') return raw;
  const text = String(raw).trim();
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    return (parsed && typeof parsed === 'object') ? parsed : { value: text };
  } catch (_) {
    return { value: text };
  }
}

function _toolLabel(toolName){
  const name = String(toolName || '');
  if (_TOOL_LABELS[name]) return _TOOL_LABELS[name];
  if (name.startsWith('retrieve_') || name.startsWith('http_')) return '检索: ' + name;
  return name || '工具调用';
}

function _pickInputField(obj, keys){
  if (!obj || typeof obj !== 'object') return '';
  for (let i = 0; i < keys.length; i++) {
    const v = obj[keys[i]];
    if (v == null || v === '') continue;
    if (Array.isArray(v)) return v.map(String).filter(Boolean).join(', ');
    return String(v);
  }
  return '';
}

function _summarizeToolInput(toolName, rawInput){
  const obj = _parseToolInput(rawInput);
  if (!obj) return '';
  const name = String(toolName || '');
  let summary = '';
  if (name === 'run_command') {
    summary = _pickInputField(obj, ['command', 'cmd', 'value']);
  } else if (name === 'run_python_script') {
    summary = _pickInputField(obj, ['script_path', 'path', 'script', 'value']);
  } else if (name === 'Skill') {
    summary = _pickInputField(obj, ['name', 'skill', 'skill_name', 'value']);
  } else if (name === 'read_file' || name === 'write_file' || name === 'list_files') {
    summary = _pickInputField(obj, ['path', 'file_path', 'directory', 'value']);
  } else if (name === 'search_text') {
    summary = _pickInputField(obj, ['query', 'pattern', 'path', 'value']);
  } else if (name === 'propose_plan') {
    summary = _pickInputField(obj, ['overview', 'title', 'path', 'value']);
  } else {
    summary = _pickInputField(obj, [
      'symbol', 'stock_code', 'code', 'ts_code', 'name',
      'path', 'query', 'command', 'prompt', 'value',
    ]);
    if (!summary) {
      const keys = Object.keys(obj);
      if (keys.length === 1) summary = String(obj[keys[0]]);
    }
  }
  summary = String(summary || '').replace(/\s+/g, ' ').trim();
  if (summary.length > 80) summary = summary.slice(0, 80) + '…';
  return summary;
}

function _formatDuration(ms){
  if (ms == null || isNaN(ms) || ms < 0) return '';
  if (ms < 1000) return ms + 'ms';
  const sec = ms / 1000;
  if (sec < 60) return (sec < 10 ? sec.toFixed(1) : Math.round(sec)) + 's';
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return m + 'm' + (s ? s + 's' : '');
}

function _statusIcon(status, kind){
  if (kind === 'slow_think') return '💭';
  if (status === 'running') return '⏳';
  if (status === 'error') return '✗';
  return '✓';
}

function _detailHtml(detail, idx){
  if (!detail) return '';
  const text = String(detail);
  const isLong = text.length > _THINK_DETAIL_TRUNCATE;
  const shortText = escapeHtml(text.slice(0, _THINK_DETAIL_TRUNCATE));
  const fullText = escapeHtml(text);
  if (isLong) {
    return '<div class="step-detail-row">' +
      '<span class="step-detail step-detail-expandable" data-step="' + idx + '">' +
      '<span class="step-detail-short">' + shortText + '...</span>' +
      '<span class="step-detail-full" style="display:none">' + fullText + '</span>' +
      '</span>' +
      '<button type="button" class="step-toggle-btn" onclick="_toggleStepDetail(this)">展开</button>' +
      '</div>';
  }
  return '<div class="step-detail-row"><span class="step-detail">' + shortText + '</span></div>';
}

function _stepRowHtml(step, idx, isSub){
  const cls = 'think-step' +
    (isSub ? ' think-step-sub' : '') +
    ' is-' + (step.status || 'done');
  const icon = _statusIcon(step.status, step.kind);
  const spinner = step.status === 'running'
    ? '<span class="think-spinner think-spinner-sm"></span>'
    : '';
  const input = step.inputSummary
    ? '<span class="step-input">' + escapeHtml(step.inputSummary) + '</span>'
    : '';
  const dur = (step.status !== 'running' && step.durationMs != null)
    ? '<span class="step-duration">' + escapeHtml(_formatDuration(step.durationMs)) + '</span>'
    : '';
  const detail = step.status === 'running'
    ? ''
    : _detailHtml(step.detail, idx);
  let childrenHtml = '';
  if (step.children && step.children.length) {
    childrenHtml = '<div class="think-step-children">' +
      step.children.map(function(child, cIdx){
        return _stepRowHtml(child, idx + '-' + cIdx, true);
      }).join('') +
      '</div>';
  }
  return '<div class="' + cls + '" data-step-id="' + step.id + '">' +
    '<div class="think-step-main">' +
      spinner +
      '<span class="step-icon">' + icon + '</span>' +
      '<span class="step-label">' + escapeHtml(step.label) + '</span>' +
      input + dur +
    '</div>' +
    detail +
    childrenHtml +
    '</div>';
}

function _countThinkSteps(steps){
  let n = 0;
  (steps || []).forEach(function(s){
    n += 1;
    if (s.children) n += s.children.length;
  });
  return n;
}

function _sumThinkDuration(steps){
  let total = 0;
  (steps || []).forEach(function(s){
    if (s.durationMs != null) total += s.durationMs;
    (s.children || []).forEach(function(c){
      if (c.durationMs != null) total += c.durationMs;
    });
  });
  return total;
}

function _findRunningStep(steps, toolName){
  const list = steps || [];
  for (let i = list.length - 1; i >= 0; i--) {
    const s = list[i];
    if (s.status === 'running' && (!toolName || s.tool === toolName)) return s;
  }
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].status === 'running') return list[i];
  }
  return null;
}

function _findDelegateParent(steps, delegateId){
  const list = steps || [];
  if (delegateId) {
    for (let i = list.length - 1; i >= 0; i--) {
      const s = list[i];
      if (s.delegateId === delegateId || s.kind === 'delegate') return s;
    }
  }
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].status === 'running') return list[i];
  }
  return list.length ? list[list.length - 1] : null;
}

function _ensureThinkVisible(block){
  if (!block || !block.thinkEl) return;
  block.thinkEl.style.display = '';
  if (block.stepsEl) block.stepsEl.style.display = '';
}

function _updateThinkHeader(block, s){
  if (!block || !block.headerEl) return;
  if (!s.thinkLive) {
    block.headerEl.style.display = 'none';
    return;
  }
  const steps = s.thinkSteps || [];
  const n = _countThinkSteps(steps);
  const running = _findRunningStep(steps);
  let text = '执行中 · ' + n + ' 步';
  if (running) {
    text += ' · ' + running.label;
    if (running.inputSummary) text += ' ' + running.inputSummary;
  }
  block.headerEl.style.display = '';
  if (block.headerTextEl) block.headerTextEl.textContent = text;
}

function _renderThinkSteps(block, s){
  if (!block || !block.stepsEl) return;
  const steps = s.thinkSteps || [];
  block.stepsEl.innerHTML = steps.map(function(step, idx){
    return _stepRowHtml(step, idx, false);
  }).join('');
  block.stepsEl.scrollTop = block.stepsEl.scrollHeight;
}

function _renderThinkLive(block, s){
  if (!block) return;
  _ensureThinkVisible(block);
  if (block.summaryEl) block.summaryEl.style.display = 'none';
  block.thinkEl.classList.remove('collapsed');
  _updateThinkHeader(block, s);
  _renderThinkSteps(block, s);
  if (!userScrolledUp) scrollToBottom();
}

function _startThinkStep(block, s, opts){
  opts = opts || {};
  s.thinkStepSeq = (s.thinkStepSeq || 0) + 1;
  const step = {
    id: s.thinkStepSeq,
    status: 'running',
    kind: opts.kind || 'tool',
    tool: opts.tool || '',
    icon: opts.icon || '',
    label: opts.label || _toolLabel(opts.tool),
    inputSummary: opts.inputSummary || '',
    detail: opts.detail || '',
    durationMs: null,
    startedAt: Date.now(),
    delegateId: opts.delegateId || null,
    children: [],
  };
  s.thinkSteps.push(step);
  s.thinkLive = true;
  _renderThinkLive(block, s);
  return step;
}

function _finishThinkStep(block, s, opts){
  opts = opts || {};
  const step = _findRunningStep(s.thinkSteps, opts.tool);
  if (!step) {
    // 兜底：没有 running 步时补一条已完成记录
    s.thinkStepSeq = (s.thinkStepSeq || 0) + 1;
    s.thinkSteps.push({
      id: s.thinkStepSeq,
      status: opts.error ? 'error' : 'done',
      kind: opts.kind || 'tool',
      tool: opts.tool || '',
      label: opts.label || _toolLabel(opts.tool),
      inputSummary: opts.inputSummary || '',
      detail: opts.detail || '',
      durationMs: opts.durationMs != null ? opts.durationMs : null,
      startedAt: Date.now(),
      children: [],
    });
  } else {
    step.status = opts.error ? 'error' : 'done';
    if (opts.detail != null) step.detail = String(opts.detail);
    if (opts.durationMs != null) step.durationMs = opts.durationMs;
    else if (step.startedAt) step.durationMs = Date.now() - step.startedAt;
    if (opts.delegateId) step.delegateId = opts.delegateId;
  }
  _renderThinkLive(block, s);
}

function _startSubThinkStep(block, s, opts){
  opts = opts || {};
  const parent = _findDelegateParent(s.thinkSteps, opts.delegateId);
  if (!parent) {
    return _startThinkStep(block, s, {
      kind: 'sub_tool',
      tool: opts.tool,
      label: _toolLabel(opts.tool),
      inputSummary: opts.inputSummary || '',
      delegateId: opts.delegateId,
    });
  }
  if (opts.delegateId) parent.delegateId = opts.delegateId;
  if (!parent.children) parent.children = [];
  s.thinkStepSeq = (s.thinkStepSeq || 0) + 1;
  const child = {
    id: s.thinkStepSeq,
    status: 'running',
    kind: 'sub_tool',
    tool: opts.tool || '',
    label: _toolLabel(opts.tool),
    inputSummary: opts.inputSummary || '',
    detail: '',
    durationMs: null,
    startedAt: Date.now(),
    delegateId: opts.delegateId || null,
  };
  parent.children.push(child);
  s.thinkLive = true;
  _renderThinkLive(block, s);
  return child;
}

function _finishSubThinkStep(block, s, opts){
  opts = opts || {};
  const parent = _findDelegateParent(s.thinkSteps, opts.delegateId);
  let child = null;
  if (parent && parent.children && parent.children.length) {
    for (let i = parent.children.length - 1; i >= 0; i--) {
      const c = parent.children[i];
      if (c.status === 'running' && (!opts.tool || c.tool === opts.tool)) {
        child = c;
        break;
      }
    }
    if (!child) {
      for (let i = parent.children.length - 1; i >= 0; i--) {
        if (parent.children[i].status === 'running') {
          child = parent.children[i];
          break;
        }
      }
    }
  }
  if (!child) {
    _finishThinkStep(block, s, opts);
    return;
  }
  child.status = opts.error ? 'error' : 'done';
  if (opts.detail != null) child.detail = String(opts.detail);
  if (opts.durationMs != null) child.durationMs = opts.durationMs;
  else if (child.startedAt) child.durationMs = Date.now() - child.startedAt;
  _renderThinkLive(block, s);
}

function _collapseThink(block, thinkSteps){
  const steps = thinkSteps || [];
  const n = _countThinkSteps(steps);
  if (!n) { if (block.thinkEl) block.thinkEl.style.display = 'none'; return; }

  _ensureThinkVisible(block);
  if (block.headerEl) block.headerEl.style.display = 'none';
  if (block.summaryEl) block.summaryEl.style.display = '';

  // 将仍在 running 的步骤标记为中断态，避免结束后仍转圈
  steps.forEach(function(step){
    if (step.status === 'running') {
      step.status = 'done';
      if (step.startedAt && step.durationMs == null) {
        step.durationMs = Date.now() - step.startedAt;
      }
    }
    (step.children || []).forEach(function(child){
      if (child.status === 'running') {
        child.status = 'done';
        if (child.startedAt && child.durationMs == null) {
          child.durationMs = Date.now() - child.startedAt;
        }
      }
    });
  });

  block.stepsEl.innerHTML = steps.map(function(step, idx){
    return _stepRowHtml(step, idx, false);
  }).join('');

  const totalMs = _sumThinkDuration(steps);
  const durText = totalMs > 0 ? ' · ' + _formatDuration(totalMs) : '';
  block.summaryEl.innerHTML = '思考过程 (' + n + '步)' + durText + ' <span class="think-arrow">▼</span>';
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

function updateStats(){
  const inputEl = document.getElementById('statInput');
  const outputEl = document.getElementById('statOutput');
  if (inputEl) inputEl.textContent = totalInputTokens.toLocaleString();
  if (outputEl) outputEl.textContent = totalOutputTokens.toLocaleString();
}

function _isRunning(){
  const stop = document.getElementById('btnStop');
  return !!(stop && stop.style.display === 'flex');
}

function _syncCollaborationMode(mode){
  currentCollaborationMode = mode === 'plan' ? 'plan' : 'agent';
  updateCollabModeUI();
}

function updateCollabModeUI(){
  const running = _isRunning();
  const label = document.getElementById('collabModeLabel');
  if (label) label.textContent = currentCollaborationMode === 'plan' ? '规划' : '执行';
  const trigger = document.getElementById('collabModeTrigger');
  if (trigger) trigger.disabled = running;
  document.querySelectorAll('#collabMode .collab-mode-option').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === currentCollaborationMode);
  });
  if (running) closeCollabMenu();
  document.querySelectorAll('.plan-card-btn').forEach(btn => { btn.disabled = running; });
}

function toggleCollabMenu(event){
  if (event) event.stopPropagation();
  if (_isRunning()) return;
  const menu = document.getElementById('collabModeMenu');
  const trigger = document.getElementById('collabModeTrigger');
  if (!menu) return;
  const willOpen = menu.hidden;
  menu.hidden = !willOpen;
  if (trigger) trigger.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
}

function closeCollabMenu(){
  const menu = document.getElementById('collabModeMenu');
  const trigger = document.getElementById('collabModeTrigger');
  if (menu) menu.hidden = true;
  if (trigger) trigger.setAttribute('aria-expanded', 'false');
}

document.addEventListener('click', (event) => {
  const root = document.getElementById('collabMode');
  if (root && !root.contains(event.target)) closeCollabMenu();
});

async function setCollaborationMode(mode){
  closeCollabMenu();
  if (mode !== 'agent' && mode !== 'plan') return;
  if (_isRunning() || mode === currentCollaborationMode) return;
  currentCollaborationMode = mode;
  updateCollabModeUI();
  if (!currentSessionId) return;
  try {
    await fetch('/api/sessions/' + encodeURIComponent(currentSessionId) + '/collaboration-mode', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode}),
    });
  } catch (e) {
    console.error('setCollaborationMode', e);
  }
}

function setRunning(r){
  document.getElementById('btnSend').style.display = r ? 'none' : 'flex';
  document.getElementById('btnStop').style.display = r ? 'flex' : 'none';
  const messages = document.getElementById('messages');
  if (messages) messages.classList.toggle('is-running', !!r);
  document.querySelectorAll('.btn-edit-msg').forEach(btn => {
    btn.disabled = !!r;
  });
  updateCollabModeUI();
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
  setRunning(false);
  if (currentSessionId) _clearSessionRunning(currentSessionId);
}

function stopTask(){
  if (currentTaskId) fetch('/api/chat/' + currentTaskId + '/interrupt', {method:'POST'});
  _closeStreamConnection();
  removeThinking(); setRunning(false);
  if (currentSessionId) _clearSessionRunning(currentSessionId);
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
    _setMsgCopyText(b.container, s.aText);
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
    const toolName = ev.tool || '';
    const inputSummary = _summarizeToolInput(toolName, ev.input);
    let label = _toolLabel(toolName);
    if (toolName === 'Skill' && inputSummary) label = '运行技能: ' + inputSummary;
    _startThinkStep(b, s, {
      kind: 'tool',
      tool: toolName,
      label: label,
      inputSummary: toolName === 'Skill' ? '' : inputSummary,
    });
  } else if (ev.type === 'tool_result'){
    const b = _ensureBlock(s, setState);
    const toolName = (s.pendingTool && s.pendingTool.tool) || ev.tool || '';
    const output = ev.output != null ? String(ev.output) : '';
    const isError = /^(Tool error:|错误：|子任务执行错误:)/.test(output) ||
      output.indexOf("Tool '") === 0;
    _finishThinkStep(b, s, {
      tool: toolName,
      detail: output,
      durationMs: ev.duration_ms,
      error: isError,
      delegateId: ev.delegate_id || null,
    });
    s.pendingTool = null;
  } else if (ev.type === 'slow_think'){
    const b = _ensureBlock(s, setState);
    const spin = b.bodyEl.querySelector('.thinking-inline');
    if (spin) spin.remove();
    _startThinkStep(b, s, {
      kind: 'slow_think',
      tool: 'slow_think',
      label: '策略复盘',
      detail: '',
    });
    _finishThinkStep(b, s, {
      tool: 'slow_think',
      detail: ev.content || '',
      kind: 'slow_think',
    });
  } else if (ev.type === 'sub_tool_call' || (typeof ev.type === 'string' && /(?:^|_)sub_tool_call$/.test(ev.type))){
    const b = _ensureBlock(s, setState);
    const spin = b.bodyEl.querySelector('.thinking-inline');
    if (spin) spin.remove();
    const toolName = ev.tool || '';
    _startSubThinkStep(b, s, {
      tool: toolName,
      inputSummary: _summarizeToolInput(toolName, ev.input),
      delegateId: ev.delegate_id || null,
    });
  } else if (ev.type === 'sub_tool_result' || (typeof ev.type === 'string' && /(?:^|_)sub_tool_result$/.test(ev.type))){
    const b = _ensureBlock(s, setState);
    const toolName = ev.tool || '';
    const output = ev.output != null ? String(ev.output) : '';
    const isError = /^(Tool error:|错误：|子任务执行错误:)/.test(output);
    _finishSubThinkStep(b, s, {
      tool: toolName,
      detail: output,
      durationMs: ev.duration_ms,
      error: isError,
      delegateId: ev.delegate_id || null,
    });
  } else if (ev.type === 'plan_ready'){
    _renderPlanCard(_ensureBlock(s, setState), ev);
  } else if (ev.type === 'done'){
    _finalizeAssistantRender(s);
    const b = s.replyBlock;
    if (b) {
      const spin = b.bodyEl.querySelector('.thinking-inline');
      if (spin) spin.remove();
      s.thinkLive = false;
      _collapseThink(b, s.thinkSteps);
      if (ev.message_id) b.container.dataset.messageId = String(ev.message_id);
    } else { removeThinking(); }
    totalInputTokens += (ev.usage?.input_tokens || 0);
    totalOutputTokens += (ev.usage?.output_tokens || 0);
    updateStats(); finishStream();
    maybeGenerateSessionTitle(currentSessionId);
  } else if (ev.type === 'interrupted'){
    _finalizeAssistantRender(s);
    removeThinking();
    if (ev.message) _append('<div class="msg-info">' + escapeHtml(ev.message) + '</div>');
    const b = s.replyBlock;
    s.thinkLive = false;
    if (b) _collapseThink(b, s.thinkSteps);
    finishStream();
  } else if (ev.type === 'error'){
    _finalizeAssistantRender(s);
    removeThinking();
    const b = s.replyBlock;
    s.thinkLive = false;
    if (b) _collapseThink(b, s.thinkSteps);
    // 显示错误信息
    const errorEl = _append('<div class="stream-error msg-error">' + escapeHtml(ev.message || '执行出错') + '</div>');
    // 显示重试按钮
    _showRetryButton(b, errorEl);
    finishStream();
  }
}

function _renderPlanCard(block, ev){
  if (!block || !block.container) return;
  const old = block.container.querySelector('.plan-card');
  if (old) old.remove();
  const overview = ev.overview || '计划已提交';
  const path = ev.path || '';
  const card = document.createElement('div');
  card.className = 'plan-card';
  card.innerHTML =
    '<div class="plan-card-kicker">计划已提交</div>' +
    '<div class="plan-card-overview">' + escapeHtml(overview) + '</div>' +
    (path
      ? '<button type="button" class="plan-card-preview" title="预览计划">' +
          '<svg class="plan-card-preview-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8"/><path d="M8 17h5"/></svg>' +
          '<span class="plan-card-preview-name">' + escapeHtml(path) + '</span>' +
          '<span class="plan-card-preview-hint">预览</span>' +
        '</button>'
      : '') +
    '<div class="plan-card-actions">' +
      '<button type="button" class="plan-card-btn plan-card-approve">批准并执行</button>' +
      '<button type="button" class="plan-card-btn plan-card-continue">继续规划</button>' +
    '</div>';
  const bubble = block.container.querySelector('.msg-bubble');
  (bubble || block.container).appendChild(card);
  const preview = card.querySelector('.plan-card-preview');
  if (preview) preview.addEventListener('click', () => previewPlan(path));
  card.querySelector('.plan-card-approve').addEventListener('click', approvePlan);
  card.querySelector('.plan-card-continue').addEventListener('click', continuePlanning);
  updateCollabModeUI();
  scrollToBottom(true);
}

function previewPlan(path){
  const display = String(path || '').replace(/\\/g, '/').trim();
  if (!display) return;
  openPathInDrawer(_toApiPath(display), 'markdown', 'chat');
}

function continuePlanning(){
  const input = document.getElementById('inputBox');
  if (input) input.focus();
}

async function approvePlan(){
  if (!currentSessionId || _isRunning()) return;
  setRunning(true);
  showThinking();
  let data;
  try {
    const res = await fetch('/api/sessions/' + encodeURIComponent(currentSessionId) + '/approve-plan', {method:'POST'});
    data = await res.json();
    if (!res.ok || !data.task_id) {
      const detail = data && data.detail;
      throw new Error(typeof detail === 'string' ? detail : '批准失败');
    }
  } catch (e) {
    removeThinking();
    setRunning(false);
    _append('<div class="msg-error">' + escapeHtml(e.message || '批准失败') + '</div>');
    return;
  }
  _syncCollaborationMode('agent');
  const message = data.message || '已批准计划，开始执行。';
  const approveUserNode = appendUserMsg(message, data.message_id);
  if (data.message_id && approveUserNode) approveUserNode.dataset.messageId = data.message_id;
  currentTaskId = data.task_id;
  currentSessionId = data.session_id || currentSessionId;
  incrementUserMsgCount();
  _activateSentSession(currentSessionId, message);
  currentStreamState = _createStreamState(null);
  _connectToStream(currentTaskId, {
    getState: () => currentStreamState,
    setState: (updates) => Object.assign(currentStreamState, updates),
  });
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
      _msgIdentityHtml('assistant') +
      '<div class="retry-area">' +
        '<button class="btn-retry" onclick="retryTask()">🔄 重试</button>' +
      '</div>';
    document.getElementById('messages').appendChild(container);
    container._errorEl = errorEl;
    // 记录为当前 replyBlock 以便 retryTask 找到
    window._orphanRetryContainer = container;
  }
}

/* ====== 重试 / 编辑重跑 / Fork ====== */

function _startStreamFromTask(taskId){
  removeThinking();
  currentTaskId = taskId;
  const replyBlock = _createReplyBlock();
  currentStreamState = _createStreamState(replyBlock);
  _connectToStream(currentTaskId, {
    getState: () => currentStreamState,
    setState: (updates) => Object.assign(currentStreamState, updates),
  });
}

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

    _startStreamFromTask(data.task_id);

  } catch(e) {
    removeThinking();
    _append('<div class="msg-error">重试请求失败: ' + escapeHtml(e.message) + '</div>');
    setRunning(false);
  }
}

let _editingMsgNode = null;

function _exitMsgEdit(restore){
  if (!_editingMsgNode) return;
  const node = _editingMsgNode;
  _editingMsgNode = null;
  const editBox = node.querySelector('.msg-edit-box');
  if (!editBox) return;
  const original = editBox.dataset.originalText || '';
  editBox.remove();
  let bubble = node.querySelector('.msg-bubble');
  if (!bubble) {
    bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    const actions = node.querySelector('.msg-actions');
    if (actions) node.insertBefore(bubble, actions);
    else node.appendChild(bubble);
  } else {
    bubble.style.display = '';
  }
  const text = restore ? original : (node.dataset.copyText || original);
  bubble.innerHTML = linkifyDataPaths(escapeHtml(text));
  _setMsgCopyText(node, text);
  const actions = node.querySelector('.msg-actions');
  if (actions) actions.style.display = '';
}

function beginEditUserMsg(msgNode){
  if (!msgNode || !msgNode.classList.contains('user')) return;
  if (document.getElementById('messages')?.classList.contains('is-running')) return;
  if (!msgNode.dataset.messageId) {
    _append('<div class="msg-error">该消息缺少 ID，请刷新会话后再编辑</div>');
    return;
  }
  if (_editingMsgNode && _editingMsgNode !== msgNode) _exitMsgEdit(true);

  const bubble = msgNode.querySelector('.msg-bubble');
  if (!bubble || msgNode.querySelector('.msg-edit-box')) return;
  const original = msgNode.dataset.copyText || bubble.innerText || '';

  bubble.style.display = 'none';
  const actions = msgNode.querySelector('.msg-actions');
  if (actions) actions.style.display = 'none';

  const editBox = document.createElement('div');
  editBox.className = 'msg-edit-box';
  editBox.dataset.originalText = original;
  editBox.innerHTML =
    '<textarea class="msg-edit-textarea" rows="3"></textarea>' +
    '<div class="msg-edit-actions">' +
      '<button type="button" class="btn-edit-cancel">取消</button>' +
      '<button type="button" class="btn-edit-send">发送</button>' +
    '</div>';
  if (actions) msgNode.insertBefore(editBox, actions);
  else msgNode.appendChild(editBox);

  const ta = editBox.querySelector('.msg-edit-textarea');
  ta.value = original;
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);
  _editingMsgNode = msgNode;
}

function _removeMsgRowsAfter(msgNode){
  const row = msgNode.closest('.msg-row') || msgNode;
  let next = row.nextElementSibling;
  while (next) {
    const remove = next;
    next = next.nextElementSibling;
    if (remove.id === 'btnScrollDown' || remove.id === 'welcome') continue;
    remove.remove();
  }
}

async function confirmEditUserMsg(msgNode){
  if (!msgNode || !currentSessionId) return;
  const editBox = msgNode.querySelector('.msg-edit-box');
  const ta = editBox && editBox.querySelector('.msg-edit-textarea');
  const text = (ta && ta.value || '').trim();
  if (!text) {
    alert('消息内容不能为空');
    return;
  }
  const messageId = msgNode.dataset.messageId;
  if (!messageId) {
    alert('该消息缺少 ID，请刷新会话后再编辑');
    return;
  }

  _removeMsgRowsAfter(msgNode);
  if (editBox) editBox.remove();
  let bubble = msgNode.querySelector('.msg-bubble');
  if (!bubble) {
    bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    const actions = msgNode.querySelector('.msg-actions');
    if (actions) msgNode.insertBefore(bubble, actions);
    else msgNode.appendChild(bubble);
  }
  bubble.style.display = '';
  bubble.innerHTML = linkifyDataPaths(escapeHtml(text));
  _setMsgCopyText(msgNode, text);
  const actions = msgNode.querySelector('.msg-actions');
  if (actions) actions.style.display = '';
  _editingMsgNode = null;

  document.querySelectorAll('.retry-area').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.stream-error').forEach(el => el.remove());

  showThinking(); setRunning(true);
  resetUsageStats();

  try {
    const body = {session_id: currentSessionId, message_id: messageId, message: text};
    if (currentModelId) body.model_id = currentModelId;
    const res = await fetch('/api/chat/edit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!data?.task_id){
      removeThinking();
      const msg = data?.detail || data?.error || '编辑重跑失败';
      _append('<div class="msg-error">' + escapeHtml(typeof msg === 'string' ? msg : JSON.stringify(msg)) + '</div>');
      setRunning(false);
      return;
    }
    setUserMsgCount(_countUserMessages(
      Array.from(document.querySelectorAll('#messages .msg.user')).map(() => ({role: 'user'}))
    ));
    _startStreamFromTask(data.task_id);
  } catch(e) {
    removeThinking();
    _append('<div class="msg-error">编辑重跑失败: ' + escapeHtml(e.message) + '</div>');
    setRunning(false);
  }
}

async function forkSessionAtMsg(msgNode){
  if (!msgNode || !currentSessionId) return;
  const messageId = msgNode.dataset.messageId;
  if (!messageId) {
    _append('<div class="msg-error">该消息缺少 ID，请刷新会话后再分叉</div>');
    return;
  }
  try {
    const res = await fetch('/api/sessions/' + encodeURIComponent(currentSessionId) + '/fork', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message_id: messageId}),
    });
    const data = await res.json();
    if (!res.ok || !data?.session_id) {
      const msg = data?.detail || data?.error || '分叉失败';
      _append('<div class="msg-error">' + escapeHtml(typeof msg === 'string' ? msg : JSON.stringify(msg)) + '</div>');
      return;
    }
    _forceTitleSessions.add(data.session_id);
    await loadSessions();
    await loadSession(data.session_id);
  } catch(e) {
    _append('<div class="msg-error">分叉失败: ' + escapeHtml(e.message) + '</div>');
  }
}

/* ====== 重连运行中的任务 ====== */

async function reconnectToTask(sessionId, taskId){
  exitShareMode();
  currentSessionId = sessionId;
  currentTaskId = taskId;
  _setActiveSession(sessionId);

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
      if (m.role === 'user') appendUserMsg(m.content, m.id);
      else if (m.role === 'assistant') appendAssistantMsg(m.content, m.id);
    });
    setUserMsgCount(_countUserMessages(data.messages));
  } catch(e) {
    console.error('reconnectToTask: load messages failed', e);
    setUserMsgCount(0);
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

  _markSessionRunning(sessionId);
}

/* ====== 快捷命令 ====== */

const SLASH_COMMANDS = [
  { name: '/clear', desc: '新建对话', run: () => newSession() },
  { name: '/agent', desc: '切换 Agent', run: () => openAgentPicker() },
  { name: '/model', desc: '切换模型', run: () => openModelPicker() },
  { name: '/context', desc: '切换上下文回放', run: () => openContextPicker() },
];

let _slashMatches = [];
let _slashIndex = 0;
let _slashOpen = false;
let _slashMode = 'commands'; // 'commands' | 'agents' | 'models' | 'context'
let _agentPickerItems = [];
let _modelPickerItems = [];
let _contextPickerItems = [];

function hideSlashMenu(){
  _slashOpen = false;
  _slashMatches = [];
  _slashIndex = 0;
  _slashMode = 'commands';
  _agentPickerItems = [];
  _modelPickerItems = [];
  _contextPickerItems = [];
  if (_atOpen) return;
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

  if (_slashMode === 'agents' || _slashMode === 'models' || _slashMode === 'context') return;
  if (_atOpen) hideAtMenu();

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
  hideAtMenu();

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
  hideAtMenu();

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

const CONTEXT_MODE_OPTIONS = [
  { id: 'chat', name: '可见对话', desc: '只回放问题和回复' },
  { id: 'full', name: '完整轨迹', desc: '回放工具调用和结果' },
];

function updateContextModeChip(){
  const el = document.getElementById('contextModeLabel');
  if (!el) return;
  const opt = CONTEXT_MODE_OPTIONS.find(o => o.id === currentContextMode) || CONTEXT_MODE_OPTIONS[0];
  el.textContent = '上下文回放 - ' + opt.name;
}

function _renderContextPicker(){
  const menu = document.getElementById('slashMenu');
  if (!menu) return;
  const hint = '<div class="slash-menu-hint">选择上下文回放, ↑↓选择，Enter确认</div>';
  _slashIndex = Math.max(0, Math.min(_slashIndex, _contextPickerItems.length - 1));
  menu.innerHTML = hint + _contextPickerItems.map((item, i) => {
    const active = i === _slashIndex ? ' active' : '';
    const currentMark = item.id === currentContextMode
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

function openContextPicker(){
  const input = document.getElementById('inputBox');
  if (input){ input.value = ''; autoResize(input); }
  hideAtMenu();
  _slashMode = 'context';
  _contextPickerItems = CONTEXT_MODE_OPTIONS.slice();
  _slashMatches = [];
  const idx = _contextPickerItems.findIndex(it => it.id === currentContextMode);
  _slashIndex = idx >= 0 ? idx : 0;
  _renderContextPicker();
  if (input) input.focus();
}

async function confirmContextPicker(){
  const item = _contextPickerItems[_slashIndex] || _contextPickerItems[0];
  const input = document.getElementById('inputBox');
  if (input){ input.value = ''; autoResize(input); }
  hideSlashMenu();
  if (!item || item.id === currentContextMode) return;
  await applyContextMode(item.id);
}

async function applyContextMode(mode){
  if (mode !== 'chat' && mode !== 'full') return;
  if (mode === currentContextMode) return;
  currentContextMode = mode;
  updateContextModeChip();
  if (currentSessionId) {
    try {
      const res = await fetch('/api/sessions/' + encodeURIComponent(currentSessionId) + '/context', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: mode }),
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
    } catch (e) {
      _append('<div class="msg-error">切换上下文失败: ' + escapeHtml(e.message) + '</div>');
      return;
    }
  }
  const note = mode === 'full'
    ? '已切换为完整轨迹，之后的提问会带上工具调用和结果'
    : '已切换为可见对话，之后的提问只带上问题和回复';
  _append('<div class="msg-info">' + escapeHtml(note) + '</div>');
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
  if (_slashMode === 'context') {
    if (idx < 0 || idx >= _contextPickerItems.length) return;
    _slashIndex = idx;
    confirmContextPicker();
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
  if (cmd.name === '/agent' || cmd.name === '/model' || cmd.name === '/context') {
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
  if (cmd.name === '/context') {
    openContextPicker();
    return;
  }
  hideSlashMenu();
  cmd.run();
}

function onInputBoxInput(el){
  autoResize(el);
  if (_slashMode === 'agents' || _slashMode === 'models' || _slashMode === 'context') {
    const v = el.value;
    if (!v || v[0] !== '/') {
      hideSlashMenu();
      updateAtMenu();
      if (_atOpen) return;
      updateSlashMenu();
      return;
    }
    return;
  }
  const atToken = _atQueryFromInput(el.value, el.selectionStart);
  if (atToken) {
    updateAtMenu();
    return;
  }
  if (_atOpen || _atDismissed) hideAtMenu();
  else _clearAtDismissed();
  updateSlashMenu();
}

function _moveSlashSelection(delta){
  if (!_slashOpen) return;
  let count = _slashMatches.length;
  if (_slashMode === 'agents') count = _agentPickerItems.length;
  else if (_slashMode === 'models') count = _modelPickerItems.length;
  else if (_slashMode === 'context') count = _contextPickerItems.length;
  if (!count) return;
  _slashIndex = (_slashIndex + delta + count) % count;
  const menu = document.getElementById('slashMenu');
  if (!menu) return;
  menu.querySelectorAll('.slash-item').forEach((el, i) => {
    el.classList.toggle('active', i === _slashIndex);
  });
}

/* ====== @ 文件路径提及 ====== */

const AT_MAX_RESULTS = 30;

let _atOpen = false;
let _atMatches = [];
let _atIndex = 0;
let _atToken = null;
let _atDismissed = false;
let _atDismissedTokenStart = -1;
let _atFileIndex = null;
let _atFileIndexPromise = null;
let _atUpdateSeq = 0;

function _clearAtDismissed(){
  _atDismissed = false;
  _atDismissedTokenStart = -1;
}

function _atQueryFromInput(value, cursorPos){
  if (!value) return null;
  const cursor = typeof cursorPos === 'number' ? cursorPos : value.length;
  if (cursor < 1) return null;

  let start = cursor;
  while (start > 0 && !/\s/.test(value[start - 1])) start--;
  if (value[start] !== '@') return null;
  if (start > 0 && !/\s/.test(value[start - 1])) return null;

  let end = start + 1;
  while (end < value.length && !/\s/.test(value[end])) end++;

  const query = value.slice(start + 1, cursor);
  return { start, end, query, cursor };
}

function _flattenFileTree(nodes, out){
  const list = out || [];
  if (!Array.isArray(nodes)) return list;
  for (const n of nodes) {
    if (!n || !n.path) continue;
    const path = String(n.path).replace(/\\/g, '/');
    const type = n.type === 'dir' ? 'dir' : 'file';
    list.push({
      name: n.name || path.split('/').pop() || path,
      path,
      type,
    });
    if (type === 'dir' && Array.isArray(n.children) && n.children.length) {
      _flattenFileTree(n.children, list);
    }
  }
  return list;
}

async function _ensureAtFileIndex(){
  if (_atFileIndex) return _atFileIndex;
  if (_atFileIndexPromise) return _atFileIndexPromise;
  _atFileIndexPromise = fetch('/api/files/tree')
    .then(res => {
      if (!res.ok) throw new Error('load failed');
      return res.json();
    })
    .then(tree => {
      _atFileIndex = _flattenFileTree(tree);
      return _atFileIndex;
    })
    .catch(err => {
      _atFileIndexPromise = null;
      throw err;
    });
  return _atFileIndexPromise;
}

function _scoreAtMatch(entry, query){
  const q = String(query || '').toLowerCase();
  if (!q) return 0;
  const name = String(entry.name || '').toLowerCase();
  const path = String(entry.path || '').toLowerCase();
  if (name === q) return 1000;
  if (name.startsWith(q)) return 800;
  if (name.includes(q)) return 500;
  if (path.startsWith(q)) return 350;
  if (path.includes(q)) return 200;
  return 0;
}

function _getAtMatches(index, query){
  const q = String(query || '').replace(/\\/g, '/');
  if (!index || !index.length) return [];

  if (!q) {
    return index
      .filter(e => e.path && !e.path.includes('/'))
      .slice()
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
        return a.name.localeCompare(b.name, 'zh');
      })
      .slice(0, AT_MAX_RESULTS);
  }

  if (q.includes('/')) {
    const qLower = q.toLowerCase();
    const scored = [];
    for (const e of index) {
      const path = e.path.toLowerCase();
      const withSlash = e.type === 'dir' ? path + '/' : path;
      if (!path.startsWith(qLower) && !withSlash.startsWith(qLower)) continue;
      scored.push(e);
    }
    scored.sort((a, b) => {
      const da = a.path.split('/').length;
      const db = b.path.split('/').length;
      if (da !== db) return da - db;
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
      return a.path.localeCompare(b.path, 'zh');
    });
    return scored.slice(0, AT_MAX_RESULTS);
  }

  const scored = [];
  for (const e of index) {
    const score = _scoreAtMatch(e, q);
    if (score > 0) scored.push({ entry: e, score });
  }
  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (a.entry.path.length !== b.entry.path.length) {
      return a.entry.path.length - b.entry.path.length;
    }
    return a.entry.path.localeCompare(b.entry.path, 'zh');
  });
  return scored.slice(0, AT_MAX_RESULTS).map(s => s.entry);
}

function hideAtMenu(opts){
  const dismiss = !!(opts && opts.dismiss);
  if (dismiss) {
    const input = document.getElementById('inputBox');
    const token = _atToken || (input && _atQueryFromInput(input.value, input.selectionStart));
    if (token) {
      _atDismissed = true;
      _atDismissedTokenStart = token.start;
    }
  } else {
    _clearAtDismissed();
  }
  _atOpen = false;
  _atMatches = [];
  _atIndex = 0;
  _atToken = null;
  if (_slashOpen) return;
  const menu = document.getElementById('slashMenu');
  if (menu){ menu.style.display = 'none'; menu.innerHTML = ''; }
}

function _atDisplayPath(entry){
  const p = 'data/' + entry.path.replace(/\\/g, '/');
  return entry.type === 'dir' ? p + '/' : p;
}

function _renderAtMenu(matches, opts){
  const menu = document.getElementById('slashMenu');
  if (!menu) return;
  const hint = '<div class="slash-menu-hint">↑↓选择，Tab/Enter确认，Esc取消</div>';
  if (opts && opts.loading) {
    menu.innerHTML = hint + '<div class="slash-item slash-item-empty">加载文件列表…</div>';
    menu.style.display = '';
    _atOpen = true;
    _slashOpen = false;
    return;
  }
  if (opts && opts.error) {
    menu.innerHTML = hint +
      '<div class="slash-item slash-item-empty">无法加载文件列表</div>';
    menu.style.display = '';
    _atOpen = true;
    _slashOpen = false;
    return;
  }
  if (!matches.length) {
    hideAtMenu();
    return;
  }

  if (_atMatches.length !== matches.length ||
      _atMatches.some((m, i) => m.path !== matches[i].path || m.type !== matches[i].type)) {
    _atIndex = 0;
  } else {
    _atIndex = Math.max(0, Math.min(_atIndex, matches.length - 1));
  }
  _atMatches = matches;
  _atOpen = true;
  _slashOpen = false;

  menu.innerHTML = hint + matches.map((e, i) => {
    const active = i === _atIndex ? ' active' : '';
    const kind = e.type === 'dir' ? '文件夹' : '文件';
    const display = _atDisplayPath(e);
    const base = e.name + (e.type === 'dir' ? '/' : '');
    const parent = e.path.includes('/')
      ? 'data/' + e.path.slice(0, e.path.lastIndexOf('/') + 1)
      : 'data/';
    return `<div class="slash-item at-item${active}" role="option" data-idx="${i}"` +
      ` onclick="selectAtItem(${i})">` +
      `<span class="slash-item-name at-item-name">${escapeHtml(base)}</span>` +
      `<span class="slash-item-desc at-item-path" title="${escapeHtml(display)}">${escapeHtml(parent)}</span>` +
      `<span class="at-item-kind">${kind}</span></div>`;
  }).join('');
  menu.style.display = '';

  const activeEl = menu.querySelector('.slash-item.active');
  if (activeEl && typeof activeEl.scrollIntoView === 'function') {
    activeEl.scrollIntoView({ block: 'nearest' });
  }
}

async function updateAtMenu(){
  const input = document.getElementById('inputBox');
  const menu = document.getElementById('slashMenu');
  if (!input || !menu) return;

  const token = _atQueryFromInput(input.value, input.selectionStart);
  if (!token) {
    if (_atOpen) hideAtMenu();
    else _clearAtDismissed();
    return;
  }

  if (_atDismissed && token.start === _atDismissedTokenStart) {
    if (_atOpen) hideAtMenu({ dismiss: true });
    return;
  }
  if (_atDismissed && token.start !== _atDismissedTokenStart) {
    _clearAtDismissed();
  }

  _atToken = token;
  hideSlashMenu();

  const seq = ++_atUpdateSeq;
  if (!_atFileIndex) {
    _renderAtMenu([], { loading: true });
  }

  let index;
  try {
    index = await _ensureAtFileIndex();
  } catch (_) {
    if (seq !== _atUpdateSeq) return;
    const still = _atQueryFromInput(input.value, input.selectionStart);
    if (!still || still.start !== token.start) return;
    _atToken = still;
    _renderAtMenu([], { error: true });
    return;
  }
  if (seq !== _atUpdateSeq) return;

  const still = _atQueryFromInput(input.value, input.selectionStart);
  if (!still || still.start !== token.start) return;
  if (_atDismissed && still.start === _atDismissedTokenStart) return;

  _atToken = still;
  const matches = _getAtMatches(index, still.query);
  if (!matches.length) {
    // 无匹配：隐藏面板，不抑制，方便回退字符后再次出现
    hideAtMenu();
    return;
  }
  _renderAtMenu(matches);
}

function selectAtItem(idx){
  if (idx < 0 || idx >= _atMatches.length) return;
  _atIndex = idx;
  confirmAtItem();
}

function confirmAtItem(){
  const input = document.getElementById('inputBox');
  if (!input || !_atMatches.length) return;
  const entry = _atMatches[_atIndex] || _atMatches[0];
  const token = _atToken || _atQueryFromInput(input.value, input.selectionStart);
  if (!token || !entry) return;

  const insert = '`' + _atDisplayPath(entry) + '`';
  const before = input.value.slice(0, token.start);
  const after = input.value.slice(token.end);
  input.value = before + insert + after;
  const caret = before.length + insert.length;
  autoResize(input);
  hideAtMenu();
  input.focus();
  input.setSelectionRange(caret, caret);
}

function _moveAtSelection(delta){
  if (!_atOpen || !_atMatches.length) return;
  _atIndex = (_atIndex + delta + _atMatches.length) % _atMatches.length;
  const menu = document.getElementById('slashMenu');
  if (!menu) return;
  menu.querySelectorAll('.slash-item').forEach((el, i) => {
    el.classList.toggle('active', i === _atIndex);
  });
  const activeEl = menu.querySelector('.slash-item.active');
  if (activeEl && typeof activeEl.scrollIntoView === 'function') {
    activeEl.scrollIntoView({ block: 'nearest' });
  }
}

/* ====== 发送消息 ====== */

async function sendMessage(){
  const input = document.getElementById('inputBox');
  const text = input.value.trim();
  if (!text && !currentFile) return;

  const contextDirect = text.match(/^\/context(?:\s+(chat|full))?$/);
  if (contextDirect) {
    const inputBox = document.getElementById('inputBox');
    if (inputBox) { inputBox.value = ''; autoResize(inputBox); }
    hideSlashMenu();
    if (contextDirect[1]) applyContextMode(contextDirect[1]);
    else openContextPicker();
    return;
  }

  const slashCmd = SLASH_COMMANDS.find(c => c.name === text);
  if (slashCmd){
    executeSlashCommand(slashCmd);
    return;
  }

  userScrolledUp = false;
  hasNewContentSinceScroll = false;
  _updateScrollButton();

  const hadFile = !!currentFile;
  const displayText = hadFile
    ? (text || '(无文本问题)') + '\n\n[已上传文件] ' + currentFile.name
    : text;
  input.value = ''; autoResize(input);
  hideAtMenu();
  hideSlashMenu();
  const userMsgNode = appendUserMsg(displayText);
  showThinking(); setRunning(true);

  let data;
  if (hadFile){
    const fd = new FormData();
    if (currentSessionId) fd.append('session_id', currentSessionId);
    if (currentAgentId) fd.append('agent_id', currentAgentId);
    if (currentModelId) fd.append('model_id', currentModelId);
    fd.append('context_mode', currentContextMode);
    fd.append('collaboration_mode', currentCollaborationMode);
    fd.append('message', text);
    fd.append('file', currentFile);
    const res = await fetch('/api/chat',{ method:'POST', body:fd });
    data = await res.json();
  } else {
    const payload = {session_id: currentSessionId, message: text, agent_id: currentAgentId, context_mode: currentContextMode, collaboration_mode: currentCollaborationMode};
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

  if (data.uploaded_path){
    const finalText = text
      ? text + '\n\n`' + data.uploaded_path + '`'
      : '`' + data.uploaded_path + '`';
    updateUserMsgBubble(userMsgNode, finalText);
  }
  if (data.message_id && userMsgNode) {
    userMsgNode.dataset.messageId = data.message_id;
  }

  clearFile();
  currentTaskId = data.task_id;
  currentSessionId = data.session_id;
  incrementUserMsgCount();
  _activateSentSession(data.session_id, text);

  if (_forceTitleSessions.has(data.session_id)) {
    _forceTitleSessions.delete(data.session_id);
    maybeGenerateSessionTitle(data.session_id, { force: true });
  }

  currentStreamState = _createStreamState(null);

  _connectToStream(currentTaskId, {
    getState: () => currentStreamState,
    setState: (updates) => Object.assign(currentStreamState, updates),
  });
}

function handleKey(e){
  if (e.key === 'Tab' && e.shiftKey && !_atOpen && !_slashOpen) {
    e.preventDefault();
    setCollaborationMode(currentCollaborationMode === 'plan' ? 'agent' : 'plan');
    return;
  }
  if (_atOpen){
    if (e.key === 'ArrowDown'){ e.preventDefault(); _moveAtSelection(1); return; }
    if (e.key === 'ArrowUp'){ e.preventDefault(); _moveAtSelection(-1); return; }
    if (e.key === 'Escape'){ e.preventDefault(); hideAtMenu({ dismiss: true }); return; }
    if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)){
      e.preventDefault();
      confirmAtItem();
      return;
    }
    if (e.key === ' ' || e.code === 'Space'){
      // 插入空格并结束提及，保留已输入的 @… 原文
      hideAtMenu();
      return;
    }
  }
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
    } else if (_slashMode === 'context'){
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)){
        e.preventDefault();
        confirmContextPicker();
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
  if (input){ input.value = text; autoResize(input); hideAtMenu(); hideSlashMenu(); input.focus(); }
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

/* ====== 文件拖拽上传 / 文件树路径拖入输入框 ====== */

let _dragCounter = 0;
let _treePathDragging = false;
let _treeDragPath = '';
let _treeDragGhost = null;

function _treeNodeDisplayPath(node){
  const path = String((node && node.path) || '').replace(/\\/g, '/');
  if (!path) return node && node.type === 'dir' ? 'data/' : 'data';
  return _atDisplayPath({ path: path, type: node.type === 'dir' ? 'dir' : 'file' });
}

function _isPathDropTarget(el){
  if (!el || !el.closest) return false;
  return !!(el.closest('#inputBox') || el.closest('.composer') || el.closest('.input-area'));
}

function _setComposerPathDragOver(on){
  const composer = document.querySelector('.composer');
  if (!composer) return;
  composer.classList.toggle('drag-path-over', !!on);
}

function _clearTreePathDrag(){
  _treePathDragging = false;
  _treeDragPath = '';
  document.body.classList.remove('tree-path-dragging');
  _setComposerPathDragOver(false);
  if (_treeDragGhost) {
    _treeDragGhost.remove();
    _treeDragGhost = null;
  }
}

function _ensureTreeDragGhost(displayPath){
  if (_treeDragGhost) return _treeDragGhost;
  const ghost = document.createElement('div');
  ghost.className = 'tree-path-drag-ghost';
  ghost.textContent = displayPath;
  ghost.setAttribute('aria-hidden', 'true');
  document.body.appendChild(ghost);
  _treeDragGhost = ghost;
  return ghost;
}

function _moveTreeDragGhost(clientX, clientY){
  const ghost = _treeDragGhost;
  if (!ghost) return;
  ghost.style.transform = 'translate(' + (clientX + 12) + 'px, ' + (clientY + 12) + 'px)';
}

function _insertPathIntoInput(displayPath){
  const input = document.getElementById('inputBox');
  if (!input || !displayPath) return;
  const insertBare = String(displayPath).replace(/\\/g, '/');
  const insert = '`' + insertBare + '`';
  const start = typeof input.selectionStart === 'number' ? input.selectionStart : input.value.length;
  const end = typeof input.selectionEnd === 'number' ? input.selectionEnd : start;
  const before = input.value.slice(0, start);
  const after = input.value.slice(end);
  let text = insert;
  if (before && !/\s$/.test(before)) text = ' ' + text;
  if (after && !/^\s/.test(after)) text = text + ' ';
  input.value = before + text + after;
  const caret = before.length + text.length;
  autoResize(input);
  input.focus();
  input.setSelectionRange(caret, caret);
}

function _suppressNextClick(el){
  const suppress = function(e){
    e.preventDefault();
    e.stopImmediatePropagation();
    el.removeEventListener('click', suppress, true);
  };
  el.addEventListener('click', suppress, true);
}

function _bindTreePathDrag(el, node){
  if (!el || !node || !node.path || el._pathDragBound) return;
  el._pathDragBound = true;
  el.classList.add('tree-path-draggable');

  el.addEventListener('pointerdown', function(e){
    if (e.button !== 0 || e.target.closest('.arrow')) return;
    if (_treePathDragging) _clearTreePathDrag();

    const display = _treeNodeDisplayPath(node);
    const startX = e.clientX;
    const startY = e.clientY;
    const pointerId = e.pointerId;
    let dragging = false;
    let moved = false;

    function onMove(ev){
      if (ev.pointerId !== pointerId) return;
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (!dragging) {
        if ((dx * dx + dy * dy) < 25) return;
        dragging = true;
        moved = true;
        _treePathDragging = true;
        _treeDragPath = display;
        document.body.classList.add('tree-path-dragging');
        el.classList.add('dragging');
        _ensureTreeDragGhost(display);
        _moveTreeDragGhost(ev.clientX, ev.clientY);
      }
      if (!dragging) return;
      _moveTreeDragGhost(ev.clientX, ev.clientY);
      // 临时隐藏幽灵，避免挡住 elementFromPoint
      if (_treeDragGhost) _treeDragGhost.style.visibility = 'hidden';
      const under = document.elementFromPoint(ev.clientX, ev.clientY);
      if (_treeDragGhost) _treeDragGhost.style.visibility = '';
      _setComposerPathDragOver(_isPathDropTarget(under));
    }

    function onUp(ev){
      if (ev.pointerId !== pointerId) return;
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', onUp, true);
      window.removeEventListener('pointercancel', onUp, true);
      el.classList.remove('dragging');

      if (!dragging) {
        _clearTreePathDrag();
        return;
      }

      if (_treeDragGhost) _treeDragGhost.style.visibility = 'hidden';
      const under = document.elementFromPoint(ev.clientX, ev.clientY);
      const dropOk = _isPathDropTarget(under);
      const path = _treeDragPath || display;
      _clearTreePathDrag();
      if (moved) _suppressNextClick(el);
      if (dropOk && path) _insertPathIntoInput(path);
    }

    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
    window.addEventListener('pointercancel', onUp, true);
  });
}

function _initPathDropToInput(){
  // 路径拖入由 pointer 拖拽在 pointerup 时直接插入；此处无需 HTML5 drop。
}

function _initDragDrop(){
  const main = document.querySelector('.main');
  if (!main || main._dragBound) return;
  main._dragBound = true;

  main.addEventListener('dragenter', function(e){
    e.preventDefault();
    if (_treePathDragging) return;
    _dragCounter++;
    main.classList.add('drag-over');
  });

  main.addEventListener('dragleave', function(e){
    e.preventDefault();
    if (_treePathDragging) {
      _dragCounter = 0;
      main.classList.remove('drag-over');
      return;
    }
    _dragCounter--;
    if (_dragCounter <= 0){
      _dragCounter = 0;
      main.classList.remove('drag-over');
    }
  });

  main.addEventListener('dragover', function(e){
    e.preventDefault();
    if (_treePathDragging) {
      main.classList.remove('drag-over');
    }
  });

  main.addEventListener('drop', function(e){
    e.preventDefault();
    _dragCounter = 0;
    main.classList.remove('drag-over');
    if (_treePathDragging) return;
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
  const row = btn.closest('.step-detail-row') || btn.parentElement;
  const shortEl = row.querySelector('.step-detail-short');
  const fullEl = row.querySelector('.step-detail-full');
  if (!shortEl || !fullEl) return;
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

function _setDrawerOpenSource(source){
  _drawerOpenSource = source === 'tree' ? 'tree' : 'chat';
  document.body.classList.toggle('file-drawer-from-tree', _drawerOpenSource === 'tree');
}

function _onDrawerOutsideClick(e){
  if (_drawerOpenSource !== 'tree') return;
  const els = _drawerEls();
  if (!els.drawer || !els.drawer.classList.contains('open')) return;
  if (e.target.closest('#fileDrawer')) return;
  if (e.target.closest('#filesPanel')) return;
  closeFileDrawer();
}

function _bindDrawerOutsideClick(){
  if (_drawerOutsideBound) return;
  _drawerOutsideBound = true;
  // 延后绑定，避免打开抽屉的同一次点击立刻触发关闭
  window.setTimeout(function(){
    if (!_drawerOutsideBound) return;
    document.addEventListener('click', _onDrawerOutsideClick);
  }, 0);
}

function _unbindDrawerOutsideClick(){
  if (!_drawerOutsideBound) return;
  document.removeEventListener('click', _onDrawerOutsideClick);
  _drawerOutsideBound = false;
}

function openFileDrawer(){
  const els = _drawerEls();
  if (!els.drawer || !els.overlay) return;
  _applyDrawerWidth();
  document.body.classList.add('file-drawer-open');
  document.body.classList.toggle('file-drawer-from-tree', _drawerOpenSource === 'tree');
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
  if (_drawerOpenSource === 'tree') _bindDrawerOutsideClick();
  else _unbindDrawerOutsideClick();
}

function closeFileDrawer(){
  const els = _drawerEls();
  if (!els.drawer || !els.overlay) return;
  els.overlay.classList.remove('open');
  els.drawer.classList.remove('open');
  els.drawer.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('file-drawer-open', 'file-drawer-from-tree');
  _drawerOpenSource = 'chat';
  _unbindDrawerOutsideClick();
  window.setTimeout(function(){
    if (!els.drawer.classList.contains('open')) els.overlay.hidden = true;
  }, 220);
  _drawerNavStack = [];
  _clearDrawerToolbar();
  _clearChatFileTreeActive();
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
  _syncChatFileTreeActive(path, kind);
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
      _syncChatFileTreeActive(path, 'folder');
    }
  } catch (err) {
    _setDrawerHeader(path.split('/').pop() || '预览', path);
    _drawerShowError(err.message || '加载失败');
  }
}

function openPathInDrawer(apiPath, ftype, source){
  _drawerNavStack = [];
  _setDrawerOpenSource(source || 'chat');
  _syncChatFileTreeActive(apiPath, ftype);
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
      const shareBtn = e.target.closest('.btn-share-msg');
      if (shareBtn && messages.contains(shareBtn)) {
        e.preventDefault();
        e.stopPropagation();
        enterShareMode(shareBtn.closest('.msg'));
        return;
      }
      if (_shareMode) {
        const bubble = e.target.closest('.msg-bubble');
        if (bubble && messages.contains(bubble)) {
          e.preventDefault();
          e.stopPropagation();
          const row = bubble.closest('.msg-row');
          const input = row && row.querySelector('.share-check-input');
          if (input) {
            input.checked = !input.checked;
            _updateShareCount();
          }
        }
        return;
      }
      const copyBtn = e.target.closest('.btn-copy-msg');
      if (copyBtn && messages.contains(copyBtn)) {
        e.preventDefault();
        e.stopPropagation();
        copyMessage(copyBtn);
        return;
      }
      const editBtn = e.target.closest('.btn-edit-msg');
      if (editBtn && messages.contains(editBtn)) {
        e.preventDefault();
        e.stopPropagation();
        if (editBtn.disabled) return;
        beginEditUserMsg(editBtn.closest('.msg.user'));
        return;
      }
      const forkBtn = e.target.closest('.btn-fork-msg');
      if (forkBtn && messages.contains(forkBtn)) {
        e.preventDefault();
        e.stopPropagation();
        forkSessionAtMsg(forkBtn.closest('.msg.assistant'));
        return;
      }
      const editCancel = e.target.closest('.btn-edit-cancel');
      if (editCancel && messages.contains(editCancel)) {
        e.preventDefault();
        e.stopPropagation();
        _exitMsgEdit(true);
        return;
      }
      const editSend = e.target.closest('.btn-edit-send');
      if (editSend && messages.contains(editSend)) {
        e.preventDefault();
        e.stopPropagation();
        confirmEditUserMsg(editSend.closest('.msg.user'));
        return;
      }
      const chip = e.target.closest('.path-chip');
      if (!chip || !messages.contains(chip)) return;
      e.preventDefault();
      e.stopPropagation();
      openPathInDrawer(chip.dataset.path || '', chip.dataset.ftype || '', 'chat');
    });
  }
}

/* ====== 左栏：历史 / 文件 分割与文件树 ====== */

const FOLDER_ICON_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>';

function _mountChatFileGlyph(el, entry){
  if (entry && entry.type === 'dir') {
    el.classList.add('icon-folder');
    el.innerHTML = FOLDER_ICON_SVG;
    return;
  }
  el.textContent = _chatFileIcon(entry);
}

function _chatFileIcon(entry){
  const ext = entry.ext || _pathExt(entry.name || '');
  if (ext === '.pdf') return '📄';
  if (ext === '.md' || ext === '.markdown') return '📝';
  if (ext === '.html' || ext === '.htm') return '🌐';
  if (ext === '.json') return '{ }';
  if (ext === '.py') return '🐍';
  if (ext === '.log') return '📋';
  return '📃';
}

function _updateChatFileCount(){
  const el = document.getElementById('chatFileCount');
  if (!el) return;
  el.textContent = _chatFileCount > 0 ? (_chatFileCount + ' 个') : '';
}

function _clearChatFileTreeActive(){
  if (_chatFileActiveRow) {
    _chatFileActiveRow.classList.remove('active');
    _chatFileActiveRow = null;
  }
  _chatFileActivePath = '';
}

function _setChatFileTreeActiveRow(row){
  if (_chatFileActiveRow) _chatFileActiveRow.classList.remove('active');
  _chatFileActiveRow = row || null;
  if (_chatFileActiveRow) {
    _chatFileActiveRow.classList.add('active');
    _chatFileActivePath = _chatFileActiveRow.dataset.path || '';
  } else {
    _chatFileActivePath = '';
  }
}

function _syncChatFileTreeActive(apiPath, ftype){
  const tree = document.getElementById('chatFileTree');
  if (!tree) return;
  const path = String(apiPath || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  if (!path || ftype === 'folder') {
    _clearChatFileTreeActive();
    return;
  }
  _chatFileActivePath = path;
  const selector = _chatFileViewMode === 'icons'
    ? '.file-icon-item[data-type="file"]'
    : '.tree-row[data-type="file"]';
  let found = null;
  tree.querySelectorAll(selector).forEach(function(row){
    if (row.dataset.path === path) found = row;
  });
  if (found) _setChatFileTreeActiveRow(found);
  else {
    if (_chatFileActiveRow) _chatFileActiveRow.classList.remove('active');
    _chatFileActiveRow = null;
  }
}

function _readFileViewMode(){
  try {
    const v = localStorage.getItem(FILE_VIEW_KEY);
    return v === 'icons' ? 'icons' : 'list';
  } catch (_) {
    return 'list';
  }
}

function _saveFileViewMode(mode){
  try { localStorage.setItem(FILE_VIEW_KEY, mode); } catch (_) {}
}

function _updateFilesViewChrome(){
  const tree = document.getElementById('chatFileTree');
  const nav = document.getElementById('filesIconNav');
  const back = document.getElementById('filesIconBack');
  const pathEl = document.getElementById('filesIconPath');
  const listBtn = document.getElementById('filesViewList');
  const iconsBtn = document.getElementById('filesViewIcons');
  if (tree) {
    tree.classList.toggle('view-list', _chatFileViewMode === 'list');
    tree.classList.toggle('view-icons', _chatFileViewMode === 'icons');
  }
  if (listBtn) {
    listBtn.classList.toggle('active', _chatFileViewMode === 'list');
    listBtn.setAttribute('aria-pressed', _chatFileViewMode === 'list' ? 'true' : 'false');
  }
  if (iconsBtn) {
    iconsBtn.classList.toggle('active', _chatFileViewMode === 'icons');
    iconsBtn.setAttribute('aria-pressed', _chatFileViewMode === 'icons' ? 'true' : 'false');
  }
  if (nav) {
    if (_chatFileViewMode === 'icons') {
      nav.hidden = false;
      if (pathEl) pathEl.textContent = _chatFileIconPath ? ('data/' + _chatFileIconPath) : 'data/';
      if (back) back.disabled = !_chatFileIconPath;
    } else {
      nav.hidden = true;
    }
  }
}

function _createChatFileRow(node, level){
  const div = document.createElement('div');
  div.className = 'tree-item';

  const row = document.createElement('div');
  row.className = 'tree-row';
  row.style.paddingLeft = (10 + level * 14) + 'px';
  row.dataset.path = node.path || '';
  row.dataset.type = node.type || '';
  if (_chatFileActivePath && node.type === 'file' && node.path === _chatFileActivePath) {
    row.classList.add('active');
    _chatFileActiveRow = row;
  }

  const arrow = document.createElement('span');
  arrow.className = 'arrow';

  const icon = document.createElement('span');
  icon.className = 'icon';
  _mountChatFileGlyph(icon, node);

  const name = document.createElement('span');
  name.className = 'name';
  name.textContent = node.name || '';
  name.title = node.name || '';

  const size = document.createElement('span');
  size.className = 'size';

  row.appendChild(arrow);
  row.appendChild(icon);
  row.appendChild(name);
  row.appendChild(size);
  div.appendChild(row);
  _bindTreePathDrag(row, node);

  if (node.type === 'dir') {
    arrow.textContent = '▶';
    const childrenEl = document.createElement('div');
    childrenEl.className = 'tree-children';
    div.appendChild(childrenEl);

    const loadingEl = document.createElement('div');
    loadingEl.className = 'tree-loading';
    loadingEl.textContent = '加载中...';
    loadingEl.style.display = 'none';
    loadingEl.style.paddingLeft = (10 + (level + 1) * 14) + 'px';
    childrenEl.appendChild(loadingEl);

    row.addEventListener('click', function(e){
      e.stopPropagation();
      const isOpen = childrenEl.classList.contains('open');
      if (isOpen) {
        childrenEl.classList.remove('open');
        arrow.classList.remove('open');
        loadingEl.style.display = 'none';
        return;
      }
      if (_chatFileLoadedPaths[node.path]) {
        childrenEl.classList.add('open');
        arrow.classList.add('open');
        return;
      }
      if (node.hasChildren) {
        arrow.classList.add('open');
        loadingEl.style.display = 'block';
        _loadChatFileChildren(node.path, childrenEl, loadingEl, level + 1);
        return;
      }
      _chatFileLoadedPaths[node.path] = true;
      childrenEl.classList.add('open');
      arrow.classList.add('open');
    });
  }

  if (node.type === 'file') {
    size.textContent = _formatSize(node.size);
    row.addEventListener('click', function(e){
      e.stopPropagation();
      _setChatFileTreeActiveRow(row);
      openPathInDrawer(node.path, _inferPathFtype(node.name || node.path || ''), 'tree');
    });
  }

  return div;
}

function _createChatFileIconItem(node){
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'file-icon-item';
  btn.dataset.path = node.path || '';
  btn.dataset.type = node.type || '';
  btn.title = node.name || '';
  if (_chatFileActivePath && node.type === 'file' && node.path === _chatFileActivePath) {
    btn.classList.add('active');
    _chatFileActiveRow = btn;
  }

  const glyph = document.createElement('span');
  glyph.className = 'file-icon-glyph';
  _mountChatFileGlyph(glyph, node);

  const name = document.createElement('span');
  name.className = 'file-icon-name';
  name.textContent = node.name || '';

  btn.appendChild(glyph);
  btn.appendChild(name);
  _bindTreePathDrag(btn, node);

  btn.addEventListener('click', function(e){
    e.stopPropagation();
    if (node.type === 'dir') {
      _openChatFileIconDir(node.path || '', node.name || '');
      return;
    }
    _setChatFileTreeActiveRow(btn);
    openPathInDrawer(node.path, _inferPathFtype(node.name || node.path || ''), 'tree');
  });

  return btn;
}

function _loadChatFileChildren(dirPath, childrenEl, loadingEl, level){
  fetch('/api/files/children?path=' + encodeURIComponent(dirPath || ''))
    .then(function(res){
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    })
    .then(function(nodes){
      _chatFileLoadedPaths[dirPath] = true;
      loadingEl.style.display = 'none';
      (nodes || []).forEach(function(n){
        if (n.type === 'file') _chatFileCount += 1;
      });
      _updateChatFileCount();
      (nodes || []).forEach(function(node){
        childrenEl.appendChild(_createChatFileRow(node, level));
      });
      childrenEl.classList.add('open');
    })
    .catch(function(err){
      loadingEl.style.display = 'block';
      loadingEl.textContent = '加载失败: ' + (err.message || '未知错误');
      loadingEl.style.color = 'var(--c-danger)';
    });
}

function _renderChatFileListView(nodes){
  const tree = document.getElementById('chatFileTree');
  if (!tree) return;
  tree.innerHTML = '';
  _chatFileActiveRow = null;
  if (!nodes || !nodes.length) {
    tree.innerHTML = '<div class="files-empty">暂无文件</div>';
    return;
  }
  nodes.forEach(function(node){
    tree.appendChild(_createChatFileRow(node, 0));
  });
}

function _renderChatFileIconView(nodes){
  const tree = document.getElementById('chatFileTree');
  if (!tree) return;
  tree.innerHTML = '';
  _chatFileActiveRow = null;
  _chatFileIconNodes = nodes || [];
  if (!_chatFileIconNodes.length) {
    tree.innerHTML = '<div class="files-empty">该目录为空</div>';
    _updateFilesViewChrome();
    return;
  }
  _chatFileIconNodes.forEach(function(node){
    tree.appendChild(_createChatFileIconItem(node));
  });
  _updateFilesViewChrome();
}

function _recountVisibleFiles(nodes){
  _chatFileCount = 0;
  (nodes || []).forEach(function(n){
    if (n.type === 'file') _chatFileCount += 1;
  });
  _updateChatFileCount();
}

function _renderChatFileTree(nodes){
  _chatFileRootNodes = nodes || [];
  _recountVisibleFiles(_chatFileRootNodes);
  if (_chatFileViewMode === 'icons') {
    _chatFileIconPath = '';
    _renderChatFileIconView(_chatFileRootNodes);
  } else {
    _renderChatFileListView(_chatFileRootNodes);
  }
  _updateFilesViewChrome();
}

function _openChatFileIconDir(dirPath, dirName){
  const tree = document.getElementById('chatFileTree');
  if (!tree) return;
  tree.innerHTML = '<div class="files-empty">加载中...</div>';
  _updateFilesViewChrome();
  fetch('/api/files/children?path=' + encodeURIComponent(dirPath || ''))
    .then(function(res){
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    })
    .then(function(nodes){
      _chatFileIconPath = String(dirPath || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
      _recountVisibleFiles(nodes);
      _renderChatFileIconView(nodes);
    })
    .catch(function(err){
      tree.innerHTML = '<div class="files-empty">加载失败: ' + escapeHtml(err.message || '') + '</div>';
    });
}

function _chatFileIconGoBack(){
  if (!_chatFileIconPath) return;
  const parts = _chatFileIconPath.split('/').filter(Boolean);
  parts.pop();
  const parent = parts.join('/');
  if (!parent) {
    _chatFileIconPath = '';
    _recountVisibleFiles(_chatFileRootNodes);
    _renderChatFileIconView(_chatFileRootNodes);
    return;
  }
  _openChatFileIconDir(parent, parts[parts.length - 1] || '');
}

function setChatFileViewMode(mode){
  const next = mode === 'icons' ? 'icons' : 'list';
  if (next === _chatFileViewMode) return;
  _chatFileViewMode = next;
  _saveFileViewMode(next);
  _chatFileLoadedPaths = Object.create(null);
  if (_chatFileViewMode === 'icons') {
    _chatFileIconPath = '';
    _renderChatFileIconView(_chatFileRootNodes);
  } else {
    _renderChatFileListView(_chatFileRootNodes);
  }
  _updateFilesViewChrome();
  if (_chatFileActivePath) _syncChatFileTreeActive(_chatFileActivePath, 'file');
}

function _initFilesViewToggle(){
  _chatFileViewMode = _readFileViewMode();
  _updateFilesViewChrome();
  const listBtn = document.getElementById('filesViewList');
  const iconsBtn = document.getElementById('filesViewIcons');
  const back = document.getElementById('filesIconBack');
  if (listBtn) listBtn.addEventListener('click', function(){ setChatFileViewMode('list'); });
  if (iconsBtn) iconsBtn.addEventListener('click', function(){ setChatFileViewMode('icons'); });
  if (back) back.addEventListener('click', function(){ _chatFileIconGoBack(); });
}

function initChatFileTree(){
  const tree = document.getElementById('chatFileTree');
  if (!tree) return;
  _initFilesViewToggle();
  _chatFileLoadedPaths = Object.create(null);
  tree.innerHTML = '<div class="files-empty">加载中...</div>';
  fetch('/api/files/children')
    .then(function(res){
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    })
    .then(function(data){ _renderChatFileTree(data); })
    .catch(function(err){
      tree.innerHTML = '<div class="files-empty">加载失败: ' + escapeHtml(err.message || '') + '</div>';
    });
}

function _clampHistoryRatio(ratio, panelHeight){
  let r = Number(ratio);
  if (!isFinite(r)) r = LEFT_SPLIT_DEFAULT;
  const h = panelHeight || 0;
  if (h > LEFT_SPLIT_MIN_PX * 2 + 4) {
    const minR = LEFT_SPLIT_MIN_PX / h;
    const maxR = 1 - (LEFT_SPLIT_MIN_PX + 4) / h;
    r = Math.min(maxR, Math.max(minR, r));
  } else {
    r = Math.min(0.8, Math.max(0.2, r));
  }
  return r;
}

function _readHistoryRatio(){
  try {
    const raw = localStorage.getItem(LEFT_SPLIT_KEY);
    if (raw == null) return LEFT_SPLIT_DEFAULT;
    return _clampHistoryRatio(parseFloat(raw));
  } catch (_) {
    return LEFT_SPLIT_DEFAULT;
  }
}

function _applyLeftSplitRatio(ratio){
  const panel = document.querySelector('.left-panel');
  const history = document.getElementById('historyPanel');
  const files = document.getElementById('filesPanel');
  const resizer = document.getElementById('leftSplitResizer');
  if (!panel || !history || !files) return;
  const panelH = panel.getBoundingClientRect().height;
  const resizerH = resizer ? (resizer.offsetHeight || 4) : 4;
  const usable = Math.max(0, panelH - resizerH);
  const r = _clampHistoryRatio(ratio, usable || panelH);
  const historyH = Math.round(r * usable);
  history.style.flex = '0 0 ' + historyH + 'px';
  files.style.flex = '1 1 auto';
  return r;
}

function _initLeftSplitResize(){
  const panel = document.querySelector('.left-panel');
  const history = document.getElementById('historyPanel');
  const resizer = document.getElementById('leftSplitResizer');
  if (!panel || !history || !resizer) return;

  _applyLeftSplitRatio(_readHistoryRatio());

  function onMove(e){
    if (!_leftSplitResizing) return;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    const rect = panel.getBoundingClientRect();
    const resizerH = resizer.offsetHeight || 4;
    const usable = Math.max(1, rect.height - resizerH);
    const ratio = (clientY - rect.top) / usable;
    _applyLeftSplitRatio(ratio);
    if (e.cancelable) e.preventDefault();
  }

  function onUp(){
    if (!_leftSplitResizing) return;
    _leftSplitResizing = false;
    panel.classList.remove('is-split-resizing');
    document.body.classList.remove('left-split-resizing');
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    document.removeEventListener('touchmove', onMove);
    document.removeEventListener('touchend', onUp);
    const rect = panel.getBoundingClientRect();
    const hRect = history.getBoundingClientRect();
    const resizerH = resizer.offsetHeight || 4;
    const usable = Math.max(1, rect.height - resizerH);
    const ratio = _clampHistoryRatio(hRect.height / usable, usable);
    _applyLeftSplitRatio(ratio);
    try { localStorage.setItem(LEFT_SPLIT_KEY, String(ratio)); } catch (_) {}
  }

  function onDown(e){
    if (e.button != null && e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    _leftSplitResizing = true;
    panel.classList.add('is-split-resizing');
    document.body.classList.add('left-split-resizing');
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.addEventListener('touchmove', onMove, { passive: false });
    document.addEventListener('touchend', onUp);
  }

  resizer.addEventListener('mousedown', onDown);
  resizer.addEventListener('touchstart', onDown, { passive: false });

  window.addEventListener('resize', function(){
    _applyLeftSplitRatio(_readHistoryRatio());
  });
}

/* ====== 页面初始化 ====== */

window.addEventListener('DOMContentLoaded', () => {
  _initScrollListener();
  _initDragDrop();
  _initPathDropToInput();
  _initFileDrawer();
  _initShareMode();
  _initLeftSplitResize();
  _initComposerAgents();
  initChatFileTree();
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
