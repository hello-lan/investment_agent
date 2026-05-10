let currentSessionId=null,currentTaskId=null,currentEventSource=null,totalInputTokens=0,totalOutputTokens=0,currentAgentId=null;

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
    return {
      href: args[0].href || '',
      title: args[0].title || '',
      text: args[0].text || '',
    };
  }
  return {
    href: args[0] || '',
    title: args[1] || '',
    text: args[2] || '',
  };
}

function _normalizeImageArgs(args){
  if (args.length === 1 && args[0] && typeof args[0] === 'object') {
    return {
      href: args[0].href || '',
      title: args[0].title || '',
      text: args[0].text || '',
    };
  }
  return {
    href: args[0] || '',
    title: args[1] || '',
    text: args[2] || '',
  };
}

function renderMarkdown(t){
  const src = String(t || '');

  if (!window.marked || !window.DOMPurify) {
    return escapeHtml(src).replace(/\n/g, '<br>');
  }

  try {
    marked.setOptions({
      gfm: true,
      breaks: false,
      headerIds: false,
      mangle: false,
    });

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
    return DOMPurify.sanitize(raw, {
      USE_PROFILES: { html: true },
    });
  } catch (_) {
    return escapeHtml(src).replace(/\n/g, '<br>');
  }
}

async function loadSessions(){
  const sessions=await fetch('/api/sessions').then(r=>r.json());
  const list=document.getElementById('sessionList');
  list.innerHTML='';
  sessions.forEach(s=>{
    const d=document.createElement('div');
    d.className='session-item'+(s.id===currentSessionId?' active':'');
    d.innerHTML=`<div class="title">${escapeHtml(s.title||'未命名')}</div><div class="time">${(s.created_at||'').slice(0,16)}</div>`;
    d.onclick=()=>loadSession(s.id);
    list.appendChild(d);
  });
}

async function loadSession(sid){
  currentSessionId=sid;
  const data=await fetch(`/api/sessions/${sid}`).then(r=>r.json());
  const c=document.getElementById('messages');
  c.innerHTML='';
  (data.messages||[]).forEach(m=>{
    if(m.role==='user')appendUserMsg(m.content);
    else if(m.role==='assistant')appendAssistantMsg(m.content);
  });
  loadSessions();
}

function newSession(){
  currentSessionId=null;
  document.getElementById('messages').innerHTML='<div id="welcome" style="text-align:center;color:#999;margin-top:60px;font-size:14px;">输入股票代码或公司名称，开始分析</div>';
  totalInputTokens=0;totalOutputTokens=0;updateStats();loadSessions();
}

function _append(html){
  const c=document.getElementById('messages');
  const d=document.createElement('div');
  d.innerHTML=html;c.appendChild(d);c.scrollTop=c.scrollHeight;
  return d;
}

function appendUserMsg(text){
  const w=document.getElementById('welcome');if(w)w.remove();
  _append(`<div class="msg user"><div class="msg-bubble">${escapeHtml(text)}</div></div>`);
}

function appendAssistantMsg(md){
  return _append(`<div class="msg assistant"><div class="msg-bubble">${renderMarkdown(md)}</div></div>`);
}

function appendToolStep(name,output){
  _append(`<div class="tool-step"><span class="tool-name">🔧 ${escapeHtml(name)}</span><div class="tool-result">${escapeHtml((output||'').slice(0,300))}</div></div>`);
}

function appendSlowThink(content){
  _append(`<div class="slow-think">💭 <strong>策略复盘：</strong>${escapeHtml(content)}</div>`);
}

function showThinking(){
  removeThinking();
  _append('<div id="thinking" class="thinking"><span></span><span></span><span></span></div>');
}

function removeThinking(){const el=document.getElementById('thinking');if(el)el.remove();}

function updateStats(){
  document.getElementById('statInput').textContent=totalInputTokens.toLocaleString();
  document.getElementById('statOutput').textContent=totalOutputTokens.toLocaleString();
  document.getElementById('statCost').textContent='$'+((totalInputTokens*3+totalOutputTokens*15)/1e6).toFixed(4);
}

function setRunning(r){
  document.getElementById('btnSend').disabled=r;
  document.getElementById('btnStop').style.display=r?'inline-block':'none';
}

function finishStream(){
  if(currentEventSource){currentEventSource.close();currentEventSource=null;}
  setRunning(false);loadSessions();
}

function stopTask(){
  if(currentTaskId)fetch(`/api/chat/${currentTaskId}/interrupt`,{method:'POST'});
  if(currentEventSource){currentEventSource.close();currentEventSource=null;}
  removeThinking();setRunning(false);
}

async function sendMessage(){
  const input=document.getElementById('inputBox');
  const text=input.value.trim();if(!text)return;
  input.value='';autoResize(input);
  appendUserMsg(text);showThinking();setRunning(true);

  const data=await fetch('/api/chat',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({session_id:currentSessionId,message:text,agent_id:currentAgentId}),
  }).then(r=>r.json());

  currentTaskId=data.task_id;
  currentSessionId=data.session_id;

  let aDiv=null,aText='',pendingTool=null;

  currentEventSource=new EventSource(`/api/chat/${currentTaskId}/stream`);
  currentEventSource.onmessage=(e)=>{
    const ev=JSON.parse(e.data);
    if(ev.type==='text_delta'){
      removeThinking();aText+=ev.content;
      if(!aDiv)aDiv=appendAssistantMsg(aText);
      else{aDiv.querySelector('.msg-bubble').innerHTML=renderMarkdown(aText);document.getElementById('messages').scrollTop=99999;}
    }else if(ev.type==='tool_call'){
      removeThinking();pendingTool=ev;
    }else if(ev.type==='tool_result'){
      appendToolStep(pendingTool?.tool||ev.tool,ev.output);pendingTool=null;showThinking();
    }else if(ev.type==='slow_think'){
      removeThinking();appendSlowThink(ev.content);showThinking();
    }else if(ev.type==='done'){
      removeThinking();
      totalInputTokens+=(ev.usage?.input_tokens||0);
      totalOutputTokens+=(ev.usage?.output_tokens||0);
      updateStats();finishStream();
    }else if(ev.type==='error'||ev.type==='interrupted'){
      removeThinking();
      if(ev.message)_append(`<div style="text-align:center;color:#e53935;font-size:12px;padding:8px">${escapeHtml(ev.message)}</div>`);
      finishStream();
    }
  };
  currentEventSource.onerror=()=>{removeThinking();finishStream();};
}

function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}}
function autoResize(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,120)+'px';}

window.addEventListener('DOMContentLoaded',()=>{
  const params = new URLSearchParams(location.search);
  const sid = params.get('session');
  currentAgentId = params.get('agent');
  if(sid)loadSession(sid);
  if(currentAgentId){
    const banner = document.createElement('div');
    banner.style.cssText = 'font-size:12px;color:#666;padding:8px 20px;background:#fff;border-bottom:1px solid #eee;';
    banner.textContent = `当前Agent: ${currentAgentId}`;
    const main = document.querySelector('.main');
    main.insertBefore(banner, document.getElementById('messages'));
  }
  loadSessions();
});
