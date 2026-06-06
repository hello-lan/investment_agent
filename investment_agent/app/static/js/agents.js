function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

let availableModels = [];
let availableSkills = [];
let availableTools = [];

function modelNameById(id) {
  const m = availableModels.find(x => x.id === id);
  return m ? m.name : (id || '未设置模型');
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

async function loadAgents(){
  await Promise.all([loadModels(), loadSkillsCatalog(), loadToolsCatalog()]);
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
      <div class="meta">模型：${esc(modelNameById(a.model_id))}</div>
      <div class="actions">
        <button class="btn btn-primary btn-sm" onclick="editAgent('${a.id}')">编辑</button>
        <button class="btn btn-danger btn-sm" onclick="deleteAgent('${a.id}')">删除</button>
        <button class="btn btn-success btn-sm" onclick="location.href='/?agent=${a.id}'">对话</button>
      </div>
    </div>`).join('');
}

function buildModelOptions(selectedId) {
  if (!availableModels.length) {
    return '<option value="">（请先在设置页添加模型）</option>';
  }
  return availableModels.map(m =>
    `<option value="${esc(m.id)}" ${m.id === selectedId ? 'selected' : ''}>${esc(m.name)}</option>`
  ).join('');
}

function renderSkillOptions(selected = []) {
  const box = document.getElementById('agentSkills');
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

function renderToolOptions(selected = []) {
  const box = document.getElementById('agentTools');
  if (!availableTools.length) {
    box.innerHTML = '<div style="padding:12px;text-align:center;"><span class="hint">暂无可用工具</span></div>';
    return;
  }
  const selectedSet = new Set(selected || []);
  box.innerHTML = availableTools.map(t => {
    const isAuto = t.auto_bound;
    let cls = 'skill-item';
    if (isAuto) {
      cls += ' selected disabled';
    } else if (selectedSet.has(t.name)) {
      cls += ' selected';
    }
    return `<div class="${cls}" data-skill="${esc(t.name)}" data-auto="${isAuto ? '1' : '0'}">
      <span class="skill-mark">&#10003;</span>
      <div class="skill-item-text">
        <span>${esc(t.name)}</span>
        <span class="skill-deps">${esc(t.description)}</span>
      </div>
    </div>`;
  }).join('');
}

function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === (tabName === 'skills' ? 'agentSkills' : 'agentTools'));
  });
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

function selectedSkills() {
  return Array.from(document.querySelectorAll('#agentSkills .skill-item.selected')).map(el => el.dataset.skill);
}

function selectedTools() {
  return Array.from(document.querySelectorAll('#agentTools .skill-item.selected:not(.disabled)')).map(el => el.dataset.skill);
}

function toNullableInt(value) {
  if (value === '' || value == null) return null;
  const n = parseInt(value, 10);
  return Number.isFinite(n) ? n : null;
}

function normalizeCompressConfig(raw) {
  if (!raw) return null;
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }
  return raw;
}

function normalizeEngineConfig(raw) {
  if (!raw) return null;
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
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

function fillEngineFields(cfg) {
  const maxSteps = document.getElementById('agentMaxSteps');
  const slowThink = document.getElementById('agentSlowThink');
  const tokenBudget = document.getElementById('agentTokenBudget');
  const loopThreshold = document.getElementById('agentLoopThreshold');
  const maxSubagentDepth = document.getElementById('agentMaxSubagentDepth');

  if (!cfg) {
    maxSteps.value = 30;
    document.getElementById('agentMaxStepsVal').textContent = '30';
    slowThink.value = 3;
    document.getElementById('agentSlowThinkVal').textContent = '3';
    tokenBudget.value = '';
    loopThreshold.value = 3;
    document.getElementById('agentLoopVal').textContent = '3';
    maxSubagentDepth.value = 3;
    document.getElementById('agentMaxSubagentDepthVal').textContent = '3';
    document.getElementById('agentOffloadThreshold').value = '';
    document.getElementById('agentOffloadStrategy').value = 'truncate';
    document.getElementById('agentOffloadSummaryChars').value = '';
    return;
  }

  maxSteps.value = cfg.max_steps ?? 30;
  document.getElementById('agentMaxStepsVal').textContent = cfg.max_steps ?? 30;
  slowThink.value = cfg.slow_think_interval ?? 3;
  document.getElementById('agentSlowThinkVal').textContent = cfg.slow_think_interval ?? 3;
  tokenBudget.value = cfg.token_budget ?? '';
  loopThreshold.value = cfg.loop_detection_threshold ?? 3;
  document.getElementById('agentLoopVal').textContent = cfg.loop_detection_threshold ?? 3;
  maxSubagentDepth.value = cfg.max_subagent_depth ?? 3;
  document.getElementById('agentMaxSubagentDepthVal').textContent = cfg.max_subagent_depth ?? 3;
  document.getElementById('agentOffloadThreshold').value = cfg.offload_threshold ?? '';
  document.getElementById('agentOffloadStrategy').value = cfg.offload_summary_strategy || 'truncate';
  document.getElementById('agentOffloadSummaryChars').value = cfg.offload_summary_chars ?? '';
  document.getElementById('agentTrimTokenThreshold').value = cfg.context_trim_token_threshold ?? '';
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
  fillContextFields(compressConfig);
  fillEngineFields(engineConfig);
  renderSkillOptions(agent?.skills || []);
  renderToolOptions(agent?.tools || []);
  switchTab('skills');
  switchCtxTab('preflight');
  document.getElementById('modalOverlay').classList.add('open');
}

function closeModal(){
  document.getElementById('modalOverlay').classList.remove('open');
}

async function editAgent(id){
  const agent = await fetch(`/api/agents/${id}`).then(r => r.json());
  try {
    agent.skills = JSON.parse(agent.skills || '[]');
  } catch {
    agent.skills = [];
  }
  try {
    agent.tools = JSON.parse(agent.tools || '[]');
  } catch {
    agent.tools = [];
  }
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
  const engineTokenBudget = toNullableInt(document.getElementById('agentTokenBudget').value);
  const engineLoopThreshold = parseInt(document.getElementById('agentLoopThreshold').value) || 3;
  const maxSubagentDepth = parseInt(document.getElementById('agentMaxSubagentDepth').value) || 3;

  const offloadThreshold = toNullableInt(document.getElementById('agentOffloadThreshold').value);
  const offloadStrategy = document.getElementById('agentOffloadStrategy').value;
  const offloadSummaryChars = toNullableInt(document.getElementById('agentOffloadSummaryChars').value);
  const trimTokenThreshold = toNullableInt(document.getElementById('agentTrimTokenThreshold').value);

  const engineConfig = {
    max_steps: engineMaxSteps,
    slow_think_interval: engineSlowThink,
    token_budget: engineTokenBudget,
    loop_detection_threshold: engineLoopThreshold,
    context_trim_token_threshold: trimTokenThreshold,
    max_subagent_depth: maxSubagentDepth,
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
    max_tokens: parseInt(document.getElementById('agentMaxTokens').value),
    skills: selectedSkills(),
    tools: selectedTools(),
    compress_config: compressConfig,
    engine_config: engineConfig,
  };

  const url = id ? `/api/agents/${id}` : '/api/agents';
  const method = id ? 'PUT' : 'POST';
  await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  closeModal();
  loadAgents();
}

window.addEventListener('DOMContentLoaded', loadAgents);
