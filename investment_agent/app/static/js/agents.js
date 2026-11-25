function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

let availableModels = [];
let availableSkills = [];
let availableTools = [];
let availableSubagents = [];

const FORBIDDEN_SUBAGENT_TOOLS = new Set(['Subagent']);
const DEFAULT_AGENT_AVATAR = '/static/img/avatar-agent.svg';
const AVATAR_MAX_BYTES = 2 * 1024 * 1024;
const AVATAR_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);

let pendingAvatarFile = null;
let pendingAvatarClear = false;
let currentAvatarPath = '';
let avatarObjectUrl = null;

function agentAvatarSrc(agent) {
  const path = agent && agent.avatar ? String(agent.avatar).replace(/^\/+/, '') : '';
  if (!path) return DEFAULT_AGENT_AVATAR;
  const version = agent.updated_at ? ('?v=' + encodeURIComponent(agent.updated_at)) : '';
  return '/data-files/' + path + version;
}

function revokeAvatarPreview() {
  if (avatarObjectUrl) {
    URL.revokeObjectURL(avatarObjectUrl);
    avatarObjectUrl = null;
  }
}

function showAvatarPreview(src) {
  const img = document.getElementById('agentAvatarPreview');
  if (img) img.src = src || DEFAULT_AGENT_AVATAR;
}

function pickAvatar() {
  const input = document.getElementById('agentAvatarInput');
  if (input) input.click();
}

function onAvatarSelected(e) {
  const file = e?.target?.files?.[0] || null;
  if (e?.target) e.target.value = '';
  if (!file) return;
  if (!AVATAR_TYPES.has(file.type)) {
    alert('仅支持 PNG、JPEG、WebP、GIF');
    return;
  }
  if (file.size > AVATAR_MAX_BYTES) {
    alert('头像不能超过 2MB');
    return;
  }
  pendingAvatarFile = file;
  pendingAvatarClear = false;
  revokeAvatarPreview();
  avatarObjectUrl = URL.createObjectURL(file);
  showAvatarPreview(avatarObjectUrl);
}

function resetAvatar() {
  pendingAvatarFile = null;
  pendingAvatarClear = true;
  revokeAvatarPreview();
  const input = document.getElementById('agentAvatarInput');
  if (input) input.value = '';
  showAvatarPreview(DEFAULT_AGENT_AVATAR);
}

function modelNameById(id) {
  if (!id) return '继承主 Agent';
  const m = availableModels.find(x => x.id === id);
  return m ? m.name : (id || '未设置模型');
}

function normalizeList(value) {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

async function loadModels() {
  const data = await fetch('/api/settings/models').then(r => r.json());
  availableModels = data.list || [];
  return availableModels;
}

async function loadSkillsCatalog() {
  availableSkills = await fetch('/api/skills').then(r => r.json());
  return availableSkills;
}

async function loadToolsCatalog() {
  availableTools = await fetch('/api/tools').then(r => r.json());
  return availableTools;
}

async function loadSubagentsCatalog() {
  try {
    availableSubagents = await fetch('/api/subagents').then(r => r.json());
  } catch {
    availableSubagents = [];
  }
  return availableSubagents;
}

function switchPage(page) {
  document.querySelectorAll('.page-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.page === page);
  });
  document.getElementById('pageAgents').classList.toggle('active', page === 'agents');
  document.getElementById('pageSubagents').classList.toggle('active', page === 'subagents');
  if (page === 'subagents') loadSubagentGrid();
}

async function loadAgents(){
  await Promise.all([
    loadModels(), loadSkillsCatalog(), loadToolsCatalog(),
    loadSubagentsCatalog(),
  ]);
  const agents = await fetch('/api/agents').then(r => r.json());
  const grid = document.getElementById('agentGrid');
  if(!agents.length){
    grid.innerHTML='<div class="empty">暂无 Agent，点击右上角新建</div>';
    return;
  }
  grid.innerHTML = agents.map(a => `
    <div class="agent-card">
      <div class="agent-card-head">
        <img class="agent-card-avatar" src="${esc(agentAvatarSrc(a))}" alt="" onerror="this.onerror=null;this.src='${DEFAULT_AGENT_AVATAR}'">
        <h3>${esc(a.name)}${a.show_in_composer ? '<span class="agent-shortcut-tag">快捷</span>' : ''}</h3>
      </div>
      <div class="desc">${esc(a.description||'暂无描述')}</div>
      <div class="meta">模型：${esc(modelNameById(a.model_id))} · Subagent：${normalizeList(a.subagents).length}</div>
      <div class="actions">
        <button class="btn btn-primary btn-sm" onclick="editAgent('${a.id}')">编辑</button>
        <button class="btn btn-danger btn-sm" onclick="deleteAgent('${a.id}')">删除</button>
        <button class="btn btn-success btn-sm" onclick="location.href='/?agent=${a.id}'">对话</button>
      </div>
    </div>`).join('');
}

async function loadSubagentGrid() {
  await Promise.all([loadModels(), loadSkillsCatalog(), loadToolsCatalog(), loadSubagentsCatalog()]);
  const grid = document.getElementById('subagentGrid');
  if (!availableSubagents.length) {
    grid.innerHTML = '<div class="empty">暂无 Subagent，点击右上角新建</div>';
    return;
  }
  grid.innerHTML = availableSubagents.map(s => {
    const tools = normalizeList(s.tools);
    const skills = normalizeList(s.skills);
    const toolPreview = tools.slice(0, 4).map(t => `<code>${esc(toolLabel(t))}</code>`).join('')
      + (tools.length > 4 ? `<code>+${tools.length - 4}</code>` : '');
    const idAttr = esc(s.id);
    const builtinTag = s.builtin
      ? '<span class="skill-type-tag builtin">内置</span>'
      : '';
    const actions = s.builtin
      ? `<button class="btn-ghost" onclick="viewSubagentMarkdown('${idAttr}')">查看</button>`
      : `<button class="btn-ghost" onclick="viewSubagentMarkdown('${idAttr}')">Markdown</button>
         <button class="btn btn-primary btn-sm" onclick="editSubagent('${idAttr}')">编辑</button>
         <button class="btn btn-danger btn-sm" onclick="deleteSubagent('${idAttr}')">删除</button>`;
    return `
    <div class="sa-row">
      <div class="sa-row-main">
        <div class="sa-row-title">${builtinTag}${esc(s.name)}</div>
        <div class="sa-row-desc" title="${esc(s.description || '')}">${esc(s.description || '暂无描述')}</div>
        <div class="sa-row-meta">
          <span>模型 ${esc(modelNameById(s.model_id))}</span>
          <span>Tools ${tools.length}</span>
          <span>Skills ${skills.length}</span>
          ${toolPreview}
        </div>
      </div>
      <div class="actions">${actions}</div>
    </div>`;
  }).join('');
}

function buildModelOptions(selectedId, {allowInherit = false} = {}) {
  const options = [];
  if (allowInherit) {
    options.push(`<option value="" ${!selectedId ? 'selected' : ''}>（继承主 Agent）</option>`);
  }
  if (!availableModels.length && !allowInherit) {
    return '<option value="">（请先在设置页添加模型）</option>';
  }
  availableModels.forEach(m => {
    options.push(`<option value="${esc(m.id)}" ${m.id === selectedId ? 'selected' : ''}>${esc(m.name)}</option>`);
  });
  return options.join('');
}

function renderSkillOptions(selected = [], boxId = 'agentSkills') {
  const box = document.getElementById(boxId);
  if (!availableSkills.length) {
    box.innerHTML = '<div style="padding:12px;text-align:center;"><span class="hint">暂无可挂载 Skill</span></div>';
    return;
  }
  const selectedSet = new Set(selected || []);
  box.innerHTML = availableSkills.map(s => {
    const cls = selectedSet.has(s.name) ? 'skill-item selected' : 'skill-item';
    const typeTag = s.type === 'orch'
      ? '<span class="skill-type-tag orch">orch</span>'
      : '';
    const depInfo = (s.depends_on && s.depends_on.length)
      ? `<span class="skill-deps">含 ${s.depends_on.length} 个子流程: ${esc(s.depends_on.join(', '))}</span>`
      : '';
    return `<div class="${cls}" data-skill="${esc(s.name)}" data-type="${esc(s.type||'atomic')}">
      <span class="skill-mark">&#10003;</span>
      <div class="skill-item-text">
        <span>${typeTag}${esc(s.name)}</span>
        ${depInfo}
      </div>
    </div>`;
  }).join('');
}

function toolLabel(name) {
  const found = (availableTools || []).find(t => t.name === name);
  return found && found.label ? found.label : name;
}

function initialToolSelection(agent) {
  if (agent && agent.id) return normalizeList(agent.tools);
  return (availableTools || []).filter(t => t.auto_bound).map(t => t.name);
}

function renderToolOptions(selected = [], boxId = 'agentTools', {forSubagent = false} = {}) {
  const box = document.getElementById(boxId);
  let tools = availableTools || [];
  if (forSubagent) {
    tools = tools.filter(t => !FORBIDDEN_SUBAGENT_TOOLS.has(t.name));
  }
  if (!tools.length) {
    box.innerHTML = '<div style="padding:12px;text-align:center;"><span class="hint">暂无可用工具</span></div>';
    return;
  }
  const selectedSet = new Set(selected || []);
  box.innerHTML = tools.map(t => {
    const cls = selectedSet.has(t.name) ? 'skill-item selected' : 'skill-item';
    const title = t.label || t.name;
    const sub = t.label
      ? `${t.name}${t.description ? ' · ' + t.description : ''}`
      : (t.description || '');
    return `<div class="${cls}" data-skill="${esc(t.name)}">
      <span class="skill-mark">&#10003;</span>
      <div class="skill-item-text">
        <span>${esc(title)}</span>
        <span class="skill-deps">${esc(sub)}</span>
      </div>
    </div>`;
  }).join('');
}

function renderMountedSubagentOptions(selected = []) {
  const box = document.getElementById('agentSubagents');
  if (!availableSubagents.length) {
    box.innerHTML = '<div style="padding:12px;text-align:center;"><span class="hint">暂无 Subagent 定义，请先在「Subagent 定义」页创建</span></div>';
    return;
  }
  const selectedSet = new Set(selected || []);
  box.innerHTML = availableSubagents.map(s => {
    const cls = selectedSet.has(s.id) ? 'skill-item selected' : 'skill-item';
    const builtinTag = s.builtin
      ? '<span class="skill-type-tag builtin">内置</span>'
      : '';
    return `<div class="${cls}" data-skill="${esc(s.id)}">
      <span class="skill-mark">&#10003;</span>
      <div class="skill-item-text">
        <span>${builtinTag}${esc(s.name)}</span>
        <span class="skill-deps">${esc(s.description || '')}</span>
      </div>
    </div>`;
  }).join('');
}

function switchTab(tabName) {
  const map = { skills: 'agentSkills', tools: 'agentTools', subagents: 'agentSubagents' };
  document.querySelectorAll('#modalOverlay .tab-btn[data-tab]').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabName);
  });
  Object.entries(map).forEach(([key, id]) => {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('active', key === tabName);
  });
}

function switchSaTab(tabName) {
  document.querySelectorAll('#subagentModalOverlay .tab-btn[data-sa-tab]').forEach(b => {
    b.classList.toggle('active', b.dataset.saTab === tabName);
  });
  document.getElementById('subagentTools').classList.toggle('active', tabName === 'tools');
  document.getElementById('subagentSkills').classList.toggle('active', tabName === 'skills');
}

function switchCtxTab(tabName) {
  document.querySelectorAll('.ctx-tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.ctxTab === tabName);
  });
  document.querySelectorAll('.ctx-tab-panel').forEach(p => {
    p.classList.toggle('active', p.dataset.ctxTab === tabName);
  });
}

document.addEventListener('click', function(e) {
  const item = e.target.closest('.skill-item');
  if (!item) return;
  if (item.classList.contains('disabled')) return;
  item.classList.toggle('selected');
});

function selectedIn(boxId) {
  return Array.from(document.querySelectorAll(`#${boxId} .skill-item.selected:not(.disabled)`))
    .map(el => el.dataset.skill);
}

function selectedSkills() { return selectedIn('agentSkills'); }
function selectedTools() { return selectedIn('agentTools'); }
function selectedMountedSubagents() { return selectedIn('agentSubagents'); }
function selectedSaTools() { return selectedIn('subagentTools'); }
function selectedSaSkills() { return selectedIn('subagentSkills'); }

function toNullableInt(value) {
  if (value === '' || value == null) return null;
  const n = parseInt(value, 10);
  return Number.isFinite(n) ? n : null;
}

function toNullableBoolSelect(value) {
  if (value === '' || value == null) return null;
  if (value === true || value === 'true') return true;
  if (value === false || value === 'false') return false;
  return null;
}

function boolSelectValue(value) {
  if (value === true) return 'true';
  if (value === false) return 'false';
  return '';
}

function collectSubagentBlockFromAgentForm() {
  const block = {};
  const tokenBudget = toNullableInt(document.getElementById('agentSubagentTokenBudget')?.value);
  const maxSingleTurn = toNullableInt(document.getElementById('agentSubagentMaxSingleTurnOutputTokens')?.value);
  const compression = toNullableBoolSelect(document.getElementById('agentSubagentCompression')?.value);
  const trimThreshold = toNullableInt(document.getElementById('agentSubagentTrimThreshold')?.value);
  if (tokenBudget !== null) block.token_budget = tokenBudget;
  if (maxSingleTurn !== null) block.max_single_turn_output_tokens = maxSingleTurn;
  if (compression !== null) block.runtime_context_compression_enabled = compression;
  if (trimThreshold !== null) block.context_trim_token_threshold = trimThreshold;
  return block;
}

function fillAgentSubagentBlock(cfg) {
  const sub = (cfg && typeof cfg.subagent === 'object' && cfg.subagent) ? cfg.subagent : {};
  const tokenEl = document.getElementById('agentSubagentTokenBudget');
  const maxSingleTurnEl = document.getElementById('agentSubagentMaxSingleTurnOutputTokens');
  const compressionEl = document.getElementById('agentSubagentCompression');
  const trimEl = document.getElementById('agentSubagentTrimThreshold');
  if (tokenEl) {
    tokenEl.value = sub.token_budget ?? cfg?.subagent_token_budget ?? '';
  }
  if (maxSingleTurnEl) {
    maxSingleTurnEl.value = sub.max_single_turn_output_tokens ?? '';
  }
  if (compressionEl) {
    compressionEl.value = boolSelectValue(sub.runtime_context_compression_enabled);
  }
  if (trimEl) trimEl.value = sub.context_trim_token_threshold ?? '';
  updateAgentSubagentCompressionUI();
}

function collectSaRuntimeConfig() {
  const cfg = {};
  const tokenBudget = toNullableInt(document.getElementById('saRuntimeTokenBudget')?.value);
  const maxSingleTurn = toNullableInt(document.getElementById('saRuntimeMaxSingleTurnOutputTokens')?.value);
  const compression = toNullableBoolSelect(document.getElementById('saRuntimeCompression')?.value);
  const trimThreshold = toNullableInt(document.getElementById('saRuntimeTrimThreshold')?.value);
  const offloadThreshold = toNullableInt(document.getElementById('saRuntimeOffloadThreshold')?.value);
  const offloadStrategy = (document.getElementById('saRuntimeOffloadStrategy')?.value || '').trim();
  const offloadSummaryChars = toNullableInt(document.getElementById('saRuntimeOffloadSummaryChars')?.value);
  if (tokenBudget !== null) cfg.token_budget = tokenBudget;
  if (maxSingleTurn !== null) cfg.max_single_turn_output_tokens = maxSingleTurn;
  if (compression !== null) cfg.runtime_context_compression_enabled = compression;
  if (trimThreshold !== null) cfg.context_trim_token_threshold = trimThreshold;
  if (offloadThreshold !== null) cfg.offload_threshold = offloadThreshold;
  if (offloadStrategy) cfg.offload_summary_strategy = offloadStrategy;
  if (offloadSummaryChars !== null) cfg.offload_summary_chars = offloadSummaryChars;
  return cfg;
}

function fillSaRuntimeConfig(runtimeConfig) {
  const cfg = runtimeConfig && typeof runtimeConfig === 'object' ? runtimeConfig : {};
  const set = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.value = value ?? '';
  };
  set('saRuntimeTokenBudget', cfg.token_budget);
  set(
    'saRuntimeMaxSingleTurnOutputTokens',
    cfg.max_single_turn_output_tokens,
  );
  const compressionEl = document.getElementById('saRuntimeCompression');
  if (compressionEl) compressionEl.value = boolSelectValue(cfg.runtime_context_compression_enabled);
  set('saRuntimeTrimThreshold', cfg.context_trim_token_threshold);
  set('saRuntimeOffloadThreshold', cfg.offload_threshold);
  set('saRuntimeOffloadStrategy', cfg.offload_summary_strategy || '');
  set('saRuntimeOffloadSummaryChars', cfg.offload_summary_chars);
  updateSaRuntimeCompressionUI();
}

function extractRuntimeConfigFromFields(fields) {
  const cfg = {};
  const tokenBudget = toNullableInt(fields.token_budget ?? fields.subagent_token_budget);
  const maxSingleTurn = toNullableInt(
    fields.max_single_turn_output_tokens,
  );
  const compression = toNullableBoolSelect(fields.runtime_context_compression_enabled);
  const trimThreshold = toNullableInt(fields.context_trim_token_threshold);
  const offloadThreshold = toNullableInt(fields.offload_threshold);
  const offloadStrategy = String(fields.offload_summary_strategy || '').trim();
  const offloadSummaryChars = toNullableInt(fields.offload_summary_chars);
  if (tokenBudget !== null) cfg.token_budget = tokenBudget;
  if (maxSingleTurn !== null) cfg.max_single_turn_output_tokens = maxSingleTurn;
  if (compression !== null) cfg.runtime_context_compression_enabled = compression;
  if (trimThreshold !== null) cfg.context_trim_token_threshold = trimThreshold;
  if (offloadThreshold !== null) cfg.offload_threshold = offloadThreshold;
  if (offloadStrategy) cfg.offload_summary_strategy = offloadStrategy;
  if (offloadSummaryChars !== null) cfg.offload_summary_chars = offloadSummaryChars;
  return cfg;
}

function normalizeCompressConfig(raw) {
  if (!raw) return null;
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch { return null; }
  }
  return raw;
}

function normalizeEngineConfig(raw) {
  if (!raw) return null;
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch { return null; }
  }
  return raw;
}

function fillContextFields(cfg) {
  const elCtxSysBudget = document.getElementById('agentCtxSystemBudget');
  if (!cfg) {
    elCtxSysBudget.value = '';
    return;
  }
  const budget = cfg.budget || {};
  elCtxSysBudget.value = budget.system_max_tokens ?? '';
}

function updateRuntimeCompressionUI() {
  const toggle = document.getElementById('agentRuntimeCompressionEnabled');
  const fields = document.getElementById('runtimeCompressionFields');
  const offload = document.getElementById('offloadOptions');
  if (!toggle || !fields) return;
  const compressionOn = !!toggle.checked;
  fields.classList.toggle('hidden', !compressionOn);
  if (offload) {
    // trim=0 时压缩实际不生效，卸载配置无意义
    const trimVal = toNullableInt(document.getElementById('agentTrimTokenThreshold')?.value);
    const offloadUseful = compressionOn && trimVal !== 0;
    offload.classList.toggle('hidden', !offloadUseful);
  }
}

function updateAgentSubagentCompressionUI() {
  const compressionEl = document.getElementById('agentSubagentCompression');
  const trimRow = document.getElementById('agentSubagentTrimRow');
  if (!compressionEl || !trimRow) return;
  // 强制关闭压缩时，安全阈值无效
  trimRow.classList.toggle('hidden', compressionEl.value === 'false');
}

function updateAgentSubagentDepthUI() {
  const depthEl = document.getElementById('agentMaxSubagentDepth');
  const activeFields = document.getElementById('agentSubagentActiveFields');
  if (!depthEl || !activeFields) return;
  const depth = parseInt(depthEl.value, 10) || 0;
  activeFields.classList.toggle('hidden', depth <= 0);
  if (depth > 0) updateAgentSubagentCompressionUI();
}

function updateSaRuntimeCompressionUI() {
  const compressionEl = document.getElementById('saRuntimeCompression');
  const dependent = document.getElementById('saCompressionDependentFields');
  const offload = document.getElementById('saOffloadFields');
  if (!compressionEl || !dependent) return;
  const compressionOff = compressionEl.value === 'false';
  dependent.classList.toggle('hidden', compressionOff);
  if (offload && !compressionOff) {
    const trimVal = toNullableInt(document.getElementById('saRuntimeTrimThreshold')?.value);
    offload.classList.toggle('hidden', trimVal === 0);
  } else if (offload) {
    offload.classList.add('hidden');
  }
}

function updateLoopModeUI() {
  const mode = document.getElementById('agentLoopMode').value || 'dual_loop';
  const slowThinkRow = document.getElementById('agentSlowThinkRow');
  const slowThink = document.getElementById('agentSlowThink');
  const slowThinkUseful = mode === 'dual_loop';
  if (slowThink) slowThink.disabled = !slowThinkUseful;
  if (slowThinkRow) {
    slowThinkRow.classList.toggle('hidden', !slowThinkUseful);
    slowThinkRow.style.opacity = '1';
  }
}

function fillEngineFields(cfg) {
  const maxSteps = document.getElementById('agentMaxSteps');
  const slowThink = document.getElementById('agentSlowThink');
  const loopMode = document.getElementById('agentLoopMode');
  const tokenBudget = document.getElementById('agentTokenBudget');
  const loopThreshold = document.getElementById('agentLoopThreshold');
  const maxSubagentDepth = document.getElementById('agentMaxSubagentDepth');
  const maxParallel = document.getElementById('agentMaxParallelSubagents');
  const runtimeCompressionToggle = document.getElementById('agentRuntimeCompressionEnabled');

  if (!cfg) {
    maxSteps.value = 30;
    document.getElementById('agentMaxStepsVal').textContent = '30';
    slowThink.value = 3;
    loopMode.value = 'dual_loop';
    document.getElementById('agentSlowThinkVal').textContent = '3';
    tokenBudget.value = '';
    fillAgentSubagentBlock(null);
    loopThreshold.value = 3;
    document.getElementById('agentLoopVal').textContent = '3';
    maxSubagentDepth.value = 3;
    document.getElementById('agentMaxSubagentDepthVal').textContent = '3';
    if (maxParallel) {
      maxParallel.value = 3;
      document.getElementById('agentMaxParallelSubagentsVal').textContent = '3';
    }
    document.getElementById('agentOffloadThreshold').value = '';
    document.getElementById('agentOffloadStrategy').value = 'truncate';
    document.getElementById('agentOffloadSummaryChars').value = '';
    document.getElementById('agentTrimTokenThreshold').value = '';
    if (runtimeCompressionToggle) runtimeCompressionToggle.checked = false;
    updateRuntimeCompressionUI();
    updateLoopModeUI();
    updateAgentSubagentDepthUI();
    return;
  }

  maxSteps.value = cfg.max_steps ?? 30;
  document.getElementById('agentMaxStepsVal').textContent = cfg.max_steps ?? 30;
  slowThink.value = cfg.slow_think_interval ?? 3;
  // 旧 react_subagent 映射为 react
  let mode = cfg.loop_mode || 'dual_loop';
  if (mode === 'react_subagent') mode = 'react';
  if (mode === 'workflow' || mode === 'plan_execute') mode = 'dual_loop';
  loopMode.value = mode;
  document.getElementById('agentSlowThinkVal').textContent = cfg.slow_think_interval ?? 3;
  tokenBudget.value = cfg.token_budget ?? '';
  fillAgentSubagentBlock(cfg);
  loopThreshold.value = cfg.loop_detection_threshold ?? 3;
  document.getElementById('agentLoopVal').textContent = cfg.loop_detection_threshold ?? 3;
  maxSubagentDepth.value = cfg.max_subagent_depth ?? 3;
  document.getElementById('agentMaxSubagentDepthVal').textContent = cfg.max_subagent_depth ?? 3;
  if (maxParallel) {
    maxParallel.value = cfg.max_parallel_subagents ?? 3;
    document.getElementById('agentMaxParallelSubagentsVal').textContent = cfg.max_parallel_subagents ?? 3;
  }
  document.getElementById('agentOffloadThreshold').value = cfg.offload_threshold ?? '';
  document.getElementById('agentOffloadStrategy').value = cfg.offload_summary_strategy || 'truncate';
  document.getElementById('agentOffloadSummaryChars').value = cfg.offload_summary_chars ?? '';
  document.getElementById('agentTrimTokenThreshold').value = cfg.context_trim_token_threshold ?? '';
  if (runtimeCompressionToggle) {
    runtimeCompressionToggle.checked = cfg.runtime_context_compression_enabled !== false;
  }
  updateRuntimeCompressionUI();
  updateLoopModeUI();
  updateAgentSubagentDepthUI();
}

function openModal(agent){
  const compressConfig = normalizeCompressConfig(agent?.compress_config);
  const engineConfig = normalizeEngineConfig(agent?.engine_config);
  document.getElementById('modalTitle').textContent = agent ? '编辑 Agent' : '新建 Agent';
  document.getElementById('agentId').value = agent?.id || '';
  pendingAvatarFile = null;
  pendingAvatarClear = false;
  currentAvatarPath = agent?.avatar || '';
  revokeAvatarPreview();
  const avatarInput = document.getElementById('agentAvatarInput');
  if (avatarInput) avatarInput.value = '';
  showAvatarPreview(agentAvatarSrc(agent));
  document.getElementById('agentName').value = agent?.name || '';
  document.getElementById('agentDesc').value = agent?.description || '';
  document.getElementById('agentShowInComposer').checked = !!agent?.show_in_composer;
  document.getElementById('agentComposerSort').value = agent?.composer_sort ?? 0;
  toggleComposerSort();
  document.getElementById('agentPrompt').value = agent?.system_prompt || '';
  document.getElementById('agentModel').innerHTML = buildModelOptions(agent?.model_id || '');
  document.getElementById('agentTemp').value = agent?.temperature ?? 0.7;
  document.getElementById('agentMaxSingleTurnOutputTokens').value =
    agent?.max_single_turn_output_tokens || 4096;
  fillContextFields(compressConfig);
  fillEngineFields(engineConfig);
  renderSkillOptions(normalizeList(agent?.skills));
  renderToolOptions(initialToolSelection(agent));
  renderMountedSubagentOptions(normalizeList(agent?.subagents));
  switchTab('skills');
  switchCtxTab('preflight');
  document.getElementById('modalOverlay').classList.add('open');
}

function toggleComposerSort(){
  const on = document.getElementById('agentShowInComposer').checked;
  document.getElementById('agentComposerSortRow').classList.toggle('hidden', !on);
}

function closeModal(){
  revokeAvatarPreview();
  document.getElementById('modalOverlay').classList.remove('open');
}

async function editAgent(id){
  const agent = await fetch(`/api/agents/${id}`).then(r => r.json());
  agent.skills = normalizeList(agent.skills);
  agent.tools = normalizeList(agent.tools);
  agent.subagents = normalizeList(agent.subagents);
  openModal(agent);
}

async function deleteAgent(id){
  if(!confirm('确认删除该 Agent？')) return;
  await fetch(`/api/agents/${id}`, {method:'DELETE'});
  loadAgents();
}

async function saveAgent(){
  const id = document.getElementById('agentId').value;
  const name = document.getElementById('agentName').value.trim();
  if(!name){alert('请输入 Agent 名称'); return;}

  const ctxSysBudget = toNullableInt(document.getElementById('agentCtxSystemBudget').value);

  let compressConfig = null;
  if (ctxSysBudget !== null) {
    compressConfig = { budget: { system_max_tokens: ctxSysBudget } };
  }

  const engineMaxSteps = parseInt(document.getElementById('agentMaxSteps').value) || 30;
  const engineSlowThink = parseInt(document.getElementById('agentSlowThink').value) || 3;
  const engineLoopMode = document.getElementById('agentLoopMode').value || 'dual_loop';
  const engineTokenBudget = toNullableInt(document.getElementById('agentTokenBudget').value);
  const subagentBlock = collectSubagentBlockFromAgentForm();
  const engineSubagentTokenBudget = subagentBlock.token_budget ?? null;
  const engineLoopThreshold = parseInt(document.getElementById('agentLoopThreshold').value) || 3;
  const maxSubagentDepth = parseInt(document.getElementById('agentMaxSubagentDepth').value) || 3;
  const maxParallelSubagents = parseInt(document.getElementById('agentMaxParallelSubagents').value) || 3;

  const offloadThreshold = toNullableInt(document.getElementById('agentOffloadThreshold').value);
  const offloadStrategy = document.getElementById('agentOffloadStrategy').value;
  const offloadSummaryChars = toNullableInt(document.getElementById('agentOffloadSummaryChars').value);
  const trimTokenThreshold = toNullableInt(document.getElementById('agentTrimTokenThreshold').value);
  const runtimeCompressionEnabled = document.getElementById('agentRuntimeCompressionEnabled').checked;

  const engineConfig = {
    max_steps: engineMaxSteps,
    slow_think_interval: engineSlowThink,
    loop_mode: engineLoopMode,
    token_budget: engineTokenBudget,
    subagent_token_budget: engineSubagentTokenBudget,
    subagent: Object.keys(subagentBlock).length ? subagentBlock : null,
    loop_detection_threshold: engineLoopThreshold,
    runtime_context_compression_enabled: runtimeCompressionEnabled,
    context_trim_token_threshold: trimTokenThreshold,
    max_subagent_depth: maxSubagentDepth,
    max_parallel_subagents: maxParallelSubagents,
    offload_threshold: offloadThreshold,
    offload_summary_strategy: offloadStrategy,
    offload_summary_chars: offloadSummaryChars,
  };

  const body = {
    name,
    description: document.getElementById('agentDesc').value,
    system_prompt: document.getElementById('agentPrompt').value,
    model_id: document.getElementById('agentModel').value,
    temperature: parseFloat(document.getElementById('agentTemp').value),
    max_single_turn_output_tokens: parseInt(document.getElementById('agentMaxSingleTurnOutputTokens').value),
    skills: selectedSkills(),
    tools: selectedTools(),
    subagents: selectedMountedSubagents(),
    compress_config: compressConfig,
    engine_config: engineConfig,
    avatar: pendingAvatarClear ? '' : currentAvatarPath,
    show_in_composer: document.getElementById('agentShowInComposer').checked,
    composer_sort: parseInt(document.getElementById('agentComposerSort').value, 10) || 0,
  };

  const url = id ? `/api/agents/${id}` : '/api/agents';
  const method = id ? 'PUT' : 'POST';
  const res = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  if (!res.ok) {
    let detail = '保存失败';
    try {
      const err = await res.json();
      if (err && typeof err.detail === 'string') detail = err.detail;
    } catch (_) {}
    alert(detail);
    return;
  }
  const data = await res.json();
  const savedId = id || data.id;
  if (pendingAvatarFile && savedId) {
    const fd = new FormData();
    fd.append('file', pendingAvatarFile);
    const up = await fetch(`/api/agents/${savedId}/avatar`, {method: 'POST', body: fd});
    if (!up.ok) {
      let detail = '头像上传失败';
      try {
        const err = await up.json();
        if (err && typeof err.detail === 'string') detail = err.detail;
      } catch (_) {}
      alert(detail);
    }
  }
  closeModal();
  loadAgents();
}

// ── Subagent CRUD / Markdown ─────────────────────────────────────

let saCurrentView = 'form';
let saReadonly = false;

function setSaModalReadonly(readonly) {
  saReadonly = !!readonly;
  const overlay = document.getElementById('subagentModalOverlay');
  const fields = [
    'subagentName', 'subagentDesc', 'subagentPrompt', 'subagentModel',
    'subagentMarkdown',
    'saRuntimeTokenBudget', 'saRuntimeMaxSingleTurnOutputTokens',
    'saRuntimeCompression', 'saRuntimeTrimThreshold',
    'saRuntimeOffloadThreshold', 'saRuntimeOffloadSummaryChars',
    'saRuntimeOffloadStrategy',
  ];
  fields.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = saReadonly;
  });
  overlay.querySelectorAll('#subagentTools .skill-item, #subagentSkills .skill-item')
    .forEach(el => {
      if (saReadonly) el.classList.add('disabled');
      else el.classList.remove('disabled');
    });
  const saveBtn = document.getElementById('subagentSaveBtn');
  if (saveBtn) saveBtn.style.display = saReadonly ? 'none' : '';
  const cancelBtn = overlay.querySelector('.modal-footer .btn-cancel');
  if (cancelBtn) cancelBtn.textContent = saReadonly ? '关闭' : '取消';
}

function yamlEscape(value) {
  const text = String(value ?? '');
  if (!text) return '';
  if (/[:#\[\]{},&*!|>'"%@`]/.test(text) || /^\s|\s$/.test(text) || text.includes('\n')) {
    return JSON.stringify(text);
  }
  return text;
}

function modelIdToMarkdownValue(modelId) {
  if (!modelId) return '';
  const m = availableModels.find(x => x.id === modelId);
  // 优先写可读模型名；解析时再映射回 id
  return m ? m.name : modelId;
}

function resolveModelIdFromMarkdown(raw) {
  const value = String(raw || '').trim();
  if (!value) return '';
  const byId = availableModels.find(x => x.id === value);
  if (byId) return byId.id;
  const byName = availableModels.find(x => x.name === value);
  return byName ? byName.id : value;
}

function collectSubagentForm() {
  return {
    id: document.getElementById('subagentId').value || '',
    name: document.getElementById('subagentName').value.trim(),
    description: document.getElementById('subagentDesc').value.trim(),
    system_prompt: document.getElementById('subagentPrompt').value,
    model_id: document.getElementById('subagentModel').value || '',
    tools: selectedSaTools(),
    skills: selectedSaSkills(),
    runtime_config: collectSaRuntimeConfig(),
  };
}

function formatSubagentMarkdown(item) {
  const tools = normalizeList(item?.tools).join(', ');
  const skills = normalizeList(item?.skills).join(', ');
  const model = modelIdToMarkdownValue(item?.model_id || '');
  const body = (item?.system_prompt || '').replace(/^\n+/, '');
  const lines = [
    '---',
    `name: ${yamlEscape(item?.name || '')}`,
    `description: ${yamlEscape(item?.description || '')}`,
    `tools: ${tools}`,
    `skills: ${skills}`,
    `model: ${model}`,
  ];
  const rc = item?.runtime_config && typeof item.runtime_config === 'object' ? item.runtime_config : {};
  if (rc.token_budget != null) lines.push(`token_budget: ${rc.token_budget}`);
  if (rc.max_single_turn_output_tokens != null) {
    lines.push(`max_single_turn_output_tokens: ${rc.max_single_turn_output_tokens}`);
  }
  if (rc.runtime_context_compression_enabled != null) {
    lines.push(`runtime_context_compression_enabled: ${rc.runtime_context_compression_enabled}`);
  }
  if (rc.context_trim_token_threshold != null) {
    lines.push(`context_trim_token_threshold: ${rc.context_trim_token_threshold}`);
  }
  if (rc.offload_threshold != null) lines.push(`offload_threshold: ${rc.offload_threshold}`);
  if (rc.offload_summary_strategy) {
    lines.push(`offload_summary_strategy: ${rc.offload_summary_strategy}`);
  }
  if (rc.offload_summary_chars != null) {
    lines.push(`offload_summary_chars: ${rc.offload_summary_chars}`);
  }
  lines.push('---', body);
  return lines.join('\n');
}

function parseCsvList(raw) {
  if (!raw) return [];
  // 支持 [a, b] 或 a, b
  let text = String(raw).trim();
  if (text.startsWith('[') && text.endsWith(']')) {
    text = text.slice(1, -1);
  }
  return text.split(',').map(s => s.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
}

function unquoteYamlScalar(raw) {
  let text = String(raw ?? '').trim();
  if ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'"))) {
    try {
      if (text.startsWith('"')) return JSON.parse(text);
    } catch {}
    return text.slice(1, -1);
  }
  return text;
}

function parseSubagentMarkdown(md) {
  const text = String(md || '').replace(/^\uFEFF/, '');
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) {
    throw new Error('Markdown 需包含 YAML frontmatter（以 --- 包裹）');
  }
  const front = match[1];
  const body = (match[2] || '').replace(/^\r?\n/, '');
  const fields = {};
  front.split(/\r?\n/).forEach(line => {
    const m = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
    if (!m) return;
    fields[m[1].toLowerCase()] = unquoteYamlScalar(m[2]);
  });
  return {
    name: fields.name || '',
    description: fields.description || '',
    tools: parseCsvList(fields.tools),
    skills: parseCsvList(fields.skills),
    model_id: resolveModelIdFromMarkdown(fields.model || fields.model_id || ''),
    runtime_config: extractRuntimeConfigFromFields(fields),
    system_prompt: body,
  };
}

function applySubagentForm(item) {
  document.getElementById('subagentId').value = item?.id || '';
  document.getElementById('subagentName').value = item?.name || '';
  document.getElementById('subagentDesc').value = item?.description || '';
  document.getElementById('subagentPrompt').value = item?.system_prompt || '';
  document.getElementById('subagentModel').innerHTML = buildModelOptions(item?.model_id || '', {allowInherit: true});
  renderToolOptions(normalizeList(item?.tools), 'subagentTools', {forSubagent: true});
  renderSkillOptions(normalizeList(item?.skills), 'subagentSkills');
  fillSaRuntimeConfig(item?.runtime_config || {});
  switchSaTab('tools');
}

function syncFormToMarkdown() {
  const data = collectSubagentForm();
  document.getElementById('subagentMarkdown').value = formatSubagentMarkdown(data);
}

function syncMarkdownToForm() {
  const parsed = parseSubagentMarkdown(document.getElementById('subagentMarkdown').value);
  const id = document.getElementById('subagentId').value;
  applySubagentForm({ ...parsed, id });
}

function switchSaView(view) {
  if (view === saCurrentView) return;
  try {
    if (view === 'markdown') {
      syncFormToMarkdown();
    } else if (!saReadonly) {
      syncMarkdownToForm();
    }
  } catch (e) {
    alert(e.message || 'Markdown 解析失败');
    return;
  }
  saCurrentView = view;
  document.querySelectorAll('.sa-view-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.saView === view);
  });
  document.getElementById('saPanelForm').classList.toggle('active', view === 'form');
  document.getElementById('saPanelMarkdown').classList.toggle('active', view === 'markdown');
}

function openSubagentModal(item, {view = 'form'} = {}) {
  const isBuiltin = !!item?.builtin;
  if (isBuiltin) {
    document.getElementById('subagentModalTitle').textContent = '查看内置 Subagent';
  } else {
    document.getElementById('subagentModalTitle').textContent = item?.id ? '编辑 Subagent' : '新建 Subagent';
  }
  applySubagentForm(item || {});
  document.getElementById('subagentMarkdown').value = formatSubagentMarkdown(item || {});
  setSaModalReadonly(isBuiltin);
  saCurrentView = view === 'markdown' ? 'markdown' : 'form';
  document.querySelectorAll('.sa-view-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.saView === saCurrentView);
  });
  document.getElementById('saPanelForm').classList.toggle('active', saCurrentView === 'form');
  document.getElementById('saPanelMarkdown').classList.toggle('active', saCurrentView === 'markdown');
  document.getElementById('subagentModalOverlay').classList.add('open');
}

function closeSubagentModal() {
  document.getElementById('subagentModalOverlay').classList.remove('open');
  setSaModalReadonly(false);
  saCurrentView = 'form';
}

function subagentApiPath(id) {
  return `/api/subagents/${encodeURIComponent(id)}`;
}

async function editSubagent(id) {
  const item = await fetch(subagentApiPath(id)).then(r => r.json());
  if (item?.builtin) {
    openSubagentModal(item, {view: 'form'});
    return;
  }
  openSubagentModal(item, {view: 'form'});
}

async function viewSubagentMarkdown(id) {
  const item = await fetch(subagentApiPath(id)).then(r => r.json());
  openSubagentModal(item, {view: item?.builtin ? 'form' : 'markdown'});
}

async function deleteSubagent(id) {
  if (!confirm('确认删除该 Subagent？')) return;
  const resp = await fetch(subagentApiPath(id), {method: 'DELETE'});
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    alert(err.detail || '删除失败');
    return;
  }
  loadSubagentGrid();
  loadSubagentsCatalog();
}

async function saveSubagent() {
  if (saReadonly) return;
  // Markdown 模式下先同步回表单
  if (saCurrentView === 'markdown') {
    try {
      syncMarkdownToForm();
      saCurrentView = 'form';
      document.querySelectorAll('.sa-view-tab').forEach(b => {
        b.classList.toggle('active', b.dataset.saView === 'form');
      });
      document.getElementById('saPanelForm').classList.add('active');
      document.getElementById('saPanelMarkdown').classList.remove('active');
    } catch (e) {
      alert(e.message || 'Markdown 解析失败');
      return;
    }
  }

  const data = collectSubagentForm();
  if (data.id && String(data.id).startsWith('builtin:')) {
    alert('内置 Subagent 不可保存');
    return;
  }
  if (!data.name) { alert('请输入名称'); return; }
  if (!data.description) { alert('请输入描述'); return; }
  if (!data.system_prompt.trim()) { alert('请输入系统提示词'); return; }

  const body = {
    name: data.name,
    description: data.description,
    system_prompt: data.system_prompt.trim(),
    model_id: data.model_id || '',
    tools: data.tools,
    skills: data.skills,
    runtime_config: data.runtime_config || {},
  };

  const url = data.id ? subagentApiPath(data.id) : '/api/subagents';
  const method = data.id ? 'PUT' : 'POST';
  const resp = await fetch(url, {
    method,
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    alert(err.detail || '保存失败');
    return;
  }
  closeSubagentModal();
  loadSubagentGrid();
  await loadSubagentsCatalog();
}

window.addEventListener('DOMContentLoaded', () => {
  const loopMode = document.getElementById('agentLoopMode');
  if (loopMode) {
    loopMode.addEventListener('change', updateLoopModeUI);
  }
  const runtimeCompressionToggle = document.getElementById('agentRuntimeCompressionEnabled');
  if (runtimeCompressionToggle) {
    runtimeCompressionToggle.addEventListener('change', updateRuntimeCompressionUI);
  }
  const trimThreshold = document.getElementById('agentTrimTokenThreshold');
  if (trimThreshold) {
    trimThreshold.addEventListener('input', updateRuntimeCompressionUI);
  }
  const subagentCompression = document.getElementById('agentSubagentCompression');
  if (subagentCompression) {
    subagentCompression.addEventListener('change', updateAgentSubagentCompressionUI);
  }
  const maxSubagentDepth = document.getElementById('agentMaxSubagentDepth');
  if (maxSubagentDepth) {
    maxSubagentDepth.addEventListener('input', updateAgentSubagentDepthUI);
  }
  updateRuntimeCompressionUI();
  updateAgentSubagentDepthUI();
  updateSaRuntimeCompressionUI();
  loadAgents();
});
