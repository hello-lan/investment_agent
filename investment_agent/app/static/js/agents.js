function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

let availableModels = [];
let availableSkills = [];
let availableTools = [];
let availableWorkflows = [];
let availableSubagents = [];

const FORBIDDEN_SUBAGENT_TOOLS = new Set(['DelegateTask', 'Subagent']);

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

async function loadWorkflowsCatalog() {
  try {
    availableWorkflows = await fetch('/api/workflows').then(r => r.json());
  } catch {
    availableWorkflows = [];
  }
  return availableWorkflows;
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
    loadWorkflowsCatalog(), loadSubagentsCatalog(),
  ]);
  const agents = await fetch('/api/agents').then(r => r.json());
  const grid = document.getElementById('agentGrid');
  if(!agents.length){
    grid.innerHTML='<div class="empty">暂无 Agent，点击右上角新建</div>';
    return;
  }
  grid.innerHTML = agents.map(a => `
    <div class="agent-card">
      <h3>${esc(a.name)}</h3>
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
    const toolPreview = tools.slice(0, 4).map(t => `<code>${esc(t)}</code>`).join('')
      + (tools.length > 4 ? `<code>+${tools.length - 4}</code>` : '');
    return `
    <div class="sa-row">
      <div class="sa-row-main">
        <div class="sa-row-title">${esc(s.name)}</div>
        <div class="sa-row-desc" title="${esc(s.description || '')}">${esc(s.description || '暂无描述')}</div>
        <div class="sa-row-meta">
          <span>模型 ${esc(modelNameById(s.model_id))}</span>
          <span>Tools ${tools.length}</span>
          <span>Skills ${skills.length}</span>
          ${toolPreview}
        </div>
      </div>
      <div class="actions">
        <button class="btn-ghost" onclick="viewSubagentMarkdown('${s.id}')">Markdown</button>
        <button class="btn btn-primary btn-sm" onclick="editSubagent('${s.id}')">编辑</button>
        <button class="btn btn-danger btn-sm" onclick="deleteSubagent('${s.id}')">删除</button>
      </div>
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

function renderWorkflowOptions(selectedId = '') {
  const select = document.getElementById('agentWorkflowSelect');
  if (!select) return;
  const options = ['<option value="">请选择 Workflow</option>'];
  (availableWorkflows || []).forEach(w => {
    options.push(`<option value="${esc(w.id)}" ${w.id === selectedId ? 'selected' : ''}>${esc(w.name)}</option>`);
  });
  select.innerHTML = options.join('');
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
    const isAuto = !forSubagent && t.auto_bound;
    let cls = 'skill-item';
    if (isAuto) {
      cls += ' selected disabled';
    } else if (selectedSet.has(t.name)) {
      cls += ' selected';
    }
    const badge = isAuto ? '<span class="skill-type-tag orch">默认</span>' : '';
    return `<div class="${cls}" data-skill="${esc(t.name)}" data-auto="${isAuto ? '1' : '0'}">
      <span class="skill-mark">&#10003;</span>
      <div class="skill-item-text">
        <span>${badge}${esc(t.name)}</span>
        <span class="skill-deps">${esc(t.description || '')}</span>
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
    return `<div class="${cls}" data-skill="${esc(s.id)}">
      <span class="skill-mark">&#10003;</span>
      <div class="skill-item-text">
        <span>${esc(s.name)}</span>
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
  if (!toggle || !fields) return;
  fields.classList.toggle('hidden', !toggle.checked);
}

function updateLoopModeUI() {
  const mode = document.getElementById('agentLoopMode').value || 'dual_loop';
  const slowThinkRow = document.getElementById('agentSlowThinkRow');
  const slowThink = document.getElementById('agentSlowThink');
  const workflowRow = document.getElementById('agentWorkflowRow');
  const workflowSelect = document.getElementById('agentWorkflowSelect');
  const enabledModes = new Set(['dual_loop', 'plan_execute']);
  const disabled = !enabledModes.has(mode);
  slowThink.disabled = disabled;
  slowThinkRow.style.opacity = disabled ? '0.55' : '1';
  if (workflowRow) workflowRow.style.display = mode === 'workflow' ? '' : 'none';
  if (workflowSelect) workflowSelect.disabled = mode !== 'workflow';
}

function fillEngineFields(cfg) {
  const maxSteps = document.getElementById('agentMaxSteps');
  const slowThink = document.getElementById('agentSlowThink');
  const loopMode = document.getElementById('agentLoopMode');
  const tokenBudget = document.getElementById('agentTokenBudget');
  const loopThreshold = document.getElementById('agentLoopThreshold');
  const maxSubagentDepth = document.getElementById('agentMaxSubagentDepth');
  const maxParallel = document.getElementById('agentMaxParallelSubagents');
  const workflowSelect = document.getElementById('agentWorkflowSelect');
  const runtimeCompressionToggle = document.getElementById('agentRuntimeCompressionEnabled');

  if (!cfg) {
    maxSteps.value = 30;
    document.getElementById('agentMaxStepsVal').textContent = '30';
    slowThink.value = 3;
    loopMode.value = 'dual_loop';
    document.getElementById('agentSlowThinkVal').textContent = '3';
    tokenBudget.value = '';
    loopThreshold.value = 3;
    document.getElementById('agentLoopVal').textContent = '3';
    maxSubagentDepth.value = 3;
    document.getElementById('agentMaxSubagentDepthVal').textContent = '3';
    if (maxParallel) {
      maxParallel.value = 3;
      document.getElementById('agentMaxParallelSubagentsVal').textContent = '3';
    }
    document.getElementById('agentPlanningMaxTokens').value = '';
    document.getElementById('agentOffloadThreshold').value = '';
    document.getElementById('agentOffloadStrategy').value = 'truncate';
    document.getElementById('agentOffloadSummaryChars').value = '';
    document.getElementById('agentTrimTokenThreshold').value = '';
    if (runtimeCompressionToggle) runtimeCompressionToggle.checked = false;
    if (workflowSelect) workflowSelect.value = '';
    updateRuntimeCompressionUI();
    updateLoopModeUI();
    return;
  }

  maxSteps.value = cfg.max_steps ?? 30;
  document.getElementById('agentMaxStepsVal').textContent = cfg.max_steps ?? 30;
  slowThink.value = cfg.slow_think_interval ?? 3;
  // 旧 react_subagent 映射为 react
  let mode = cfg.loop_mode || 'dual_loop';
  if (mode === 'react_subagent') mode = 'react';
  loopMode.value = mode;
  document.getElementById('agentSlowThinkVal').textContent = cfg.slow_think_interval ?? 3;
  tokenBudget.value = cfg.token_budget ?? '';
  loopThreshold.value = cfg.loop_detection_threshold ?? 3;
  document.getElementById('agentLoopVal').textContent = cfg.loop_detection_threshold ?? 3;
  maxSubagentDepth.value = cfg.max_subagent_depth ?? 3;
  document.getElementById('agentMaxSubagentDepthVal').textContent = cfg.max_subagent_depth ?? 3;
  if (maxParallel) {
    maxParallel.value = cfg.max_parallel_subagents ?? 3;
    document.getElementById('agentMaxParallelSubagentsVal').textContent = cfg.max_parallel_subagents ?? 3;
  }
  document.getElementById('agentPlanningMaxTokens').value = cfg.planning_max_tokens ?? '';
  document.getElementById('agentOffloadThreshold').value = cfg.offload_threshold ?? '';
  document.getElementById('agentOffloadStrategy').value = cfg.offload_summary_strategy || 'truncate';
  document.getElementById('agentOffloadSummaryChars').value = cfg.offload_summary_chars ?? '';
  document.getElementById('agentTrimTokenThreshold').value = cfg.context_trim_token_threshold ?? '';
  if (runtimeCompressionToggle) {
    runtimeCompressionToggle.checked = cfg.runtime_context_compression_enabled !== false;
  }
  if (workflowSelect) workflowSelect.value = cfg.workflow_id || '';
  updateRuntimeCompressionUI();
  updateLoopModeUI();
}

function openModal(agent){
  const compressConfig = normalizeCompressConfig(agent?.compress_config);
  const engineConfig = normalizeEngineConfig(agent?.engine_config);
  document.getElementById('modalTitle').textContent = agent ? '编辑 Agent' : '新建 Agent';
  document.getElementById('agentId').value = agent?.id || '';
  document.getElementById('agentName').value = agent?.name || '';
  document.getElementById('agentDesc').value = agent?.description || '';
  document.getElementById('agentPrompt').value = agent?.system_prompt || '';
  document.getElementById('agentModel').innerHTML = buildModelOptions(agent?.model_id || '');
  document.getElementById('agentTemp').value = agent?.temperature ?? 0.7;
  document.getElementById('agentMaxTokens').value = agent?.max_tokens || 4096;
  renderWorkflowOptions(engineConfig?.workflow_id || '');
  fillContextFields(compressConfig);
  fillEngineFields(engineConfig);
  renderSkillOptions(normalizeList(agent?.skills));
  renderToolOptions(normalizeList(agent?.tools));
  renderMountedSubagentOptions(normalizeList(agent?.subagents));
  switchTab('skills');
  switchCtxTab('preflight');
  document.getElementById('modalOverlay').classList.add('open');
}

function closeModal(){
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
  const engineLoopThreshold = parseInt(document.getElementById('agentLoopThreshold').value) || 3;
  const maxSubagentDepth = parseInt(document.getElementById('agentMaxSubagentDepth').value) || 3;
  const maxParallelSubagents = parseInt(document.getElementById('agentMaxParallelSubagents').value) || 3;
  const planningMaxTokens = toNullableInt(document.getElementById('agentPlanningMaxTokens').value);

  const offloadThreshold = toNullableInt(document.getElementById('agentOffloadThreshold').value);
  const offloadStrategy = document.getElementById('agentOffloadStrategy').value;
  const offloadSummaryChars = toNullableInt(document.getElementById('agentOffloadSummaryChars').value);
  const trimTokenThreshold = toNullableInt(document.getElementById('agentTrimTokenThreshold').value);
  const runtimeCompressionEnabled = document.getElementById('agentRuntimeCompressionEnabled').checked;

  const workflowId = (document.getElementById('agentWorkflowSelect')?.value || '').trim();

  const engineConfig = {
    max_steps: engineMaxSteps,
    slow_think_interval: engineSlowThink,
    loop_mode: engineLoopMode,
    workflow_id: workflowId || null,
    token_budget: engineTokenBudget,
    loop_detection_threshold: engineLoopThreshold,
    runtime_context_compression_enabled: runtimeCompressionEnabled,
    context_trim_token_threshold: trimTokenThreshold,
    max_subagent_depth: maxSubagentDepth,
    max_parallel_subagents: maxParallelSubagents,
    planning_max_tokens: planningMaxTokens,
    offload_threshold: offloadThreshold,
    offload_summary_strategy: offloadStrategy,
    offload_summary_chars: offloadSummaryChars,
  };

  if (engineLoopMode === 'workflow' && !workflowId) {
    alert('Workflow 模式下请选择一个 Workflow');
    return;
  }

  const body = {
    name,
    description: document.getElementById('agentDesc').value,
    system_prompt: document.getElementById('agentPrompt').value,
    model_id: document.getElementById('agentModel').value,
    temperature: parseFloat(document.getElementById('agentTemp').value),
    max_tokens: parseInt(document.getElementById('agentMaxTokens').value),
    skills: selectedSkills(),
    tools: selectedTools(),
    subagents: selectedMountedSubagents(),
    compress_config: compressConfig,
    engine_config: engineConfig,
  };

  const url = id ? `/api/agents/${id}` : '/api/agents';
  const method = id ? 'PUT' : 'POST';
  await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  closeModal();
  loadAgents();
}

// ── Subagent CRUD / Markdown ─────────────────────────────────────

let saCurrentView = 'form';

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
  };
}

function formatSubagentMarkdown(item) {
  const tools = normalizeList(item?.tools).join(', ');
  const skills = normalizeList(item?.skills).join(', ');
  const model = modelIdToMarkdownValue(item?.model_id || '');
  const body = (item?.system_prompt || '').replace(/^\n+/, '');
  return [
    '---',
    `name: ${yamlEscape(item?.name || '')}`,
    `description: ${yamlEscape(item?.description || '')}`,
    `tools: ${tools}`,
    `skills: ${skills}`,
    `model: ${model}`,
    '---',
    body,
  ].join('\n');
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
    } else {
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
  document.getElementById('subagentModalTitle').textContent = item?.id ? '编辑 Subagent' : '新建 Subagent';
  applySubagentForm(item || {});
  document.getElementById('subagentMarkdown').value = formatSubagentMarkdown(item || {});
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
  saCurrentView = 'form';
}

async function editSubagent(id) {
  const item = await fetch(`/api/subagents/${id}`).then(r => r.json());
  openSubagentModal(item, {view: 'form'});
}

async function viewSubagentMarkdown(id) {
  const item = await fetch(`/api/subagents/${id}`).then(r => r.json());
  openSubagentModal(item, {view: 'markdown'});
}

async function deleteSubagent(id) {
  if (!confirm('确认删除该 Subagent？')) return;
  const resp = await fetch(`/api/subagents/${id}`, {method: 'DELETE'});
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    alert(err.detail || '删除失败');
    return;
  }
  loadSubagentGrid();
  loadSubagentsCatalog();
}

async function saveSubagent() {
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
  };

  const url = data.id ? `/api/subagents/${data.id}` : '/api/subagents';
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
  updateRuntimeCompressionUI();
  loadAgents();
});
