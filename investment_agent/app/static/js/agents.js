function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

let availableModels = [];
let availableSkills = [];

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

async function loadAgents(){
  await Promise.all([loadModels(), loadSkillsCatalog()]);
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
    box.innerHTML = '<span class="hint">暂无可挂载 Skill</span>';
    return;
  }
  const selectedSet = new Set(selected || []);
  box.innerHTML = availableSkills.map(s => {
    const checked = selectedSet.has(s.name) ? 'checked' : '';
    return `<label style="display:inline-flex;align-items:center;gap:4px;font-size:13px;padding:2px 6px;border:1px solid #e4e4e4;border-radius:999px;background:#fff;">
      <input type="checkbox" name="agentSkill" value="${esc(s.name)}" ${checked}>
      <span>${esc(s.name)}</span>
    </label>`;
  }).join('');
}

function selectedSkills() {
  return Array.from(document.querySelectorAll('input[name="agentSkill"]:checked')).map(i => i.value);
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

function fillCompressFields(cfg) {
  const enabled = document.getElementById('agentCompressEnabled');
  const recentKeep = document.getElementById('agentCompressRecentKeep');
  const maxChars = document.getElementById('agentCompressMaxChars');
  const totalBudget = document.getElementById('agentCompressTotalBudget');

  if (!cfg) {
    enabled.value = 'inherit';
    recentKeep.value = '';
    maxChars.value = '';
    totalBudget.value = '';
    return;
  }

  if (cfg.enabled === true) enabled.value = 'true';
  else if (cfg.enabled === false) enabled.value = 'false';
  else enabled.value = 'inherit';

  recentKeep.value = cfg.recent_keep ?? '';
  maxChars.value = cfg.max_chars_per_msg ?? '';
  totalBudget.value = cfg.total_budget_chars ?? '';
}

function openModal(agent){
  const compressConfig = normalizeCompressConfig(agent?.compress_config);
  document.getElementById('modalTitle').textContent = agent ? '编辑 Agent' : '新建 Agent';
  document.getElementById('agentId').value = agent?.id || '';
  document.getElementById('agentName').value = agent?.name || '';
  document.getElementById('agentDesc').value = agent?.description || '';
  document.getElementById('agentPrompt').value = agent?.system_prompt || '';
  document.getElementById('agentModel').innerHTML = buildModelOptions(agent?.model_id || '');
  document.getElementById('agentTemp').value = agent?.temperature ?? 0.7;
  document.getElementById('agentMaxTokens').value = agent?.max_tokens || 4096;
  fillCompressFields(compressConfig);
  renderSkillOptions(agent?.skills || []);
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

  const compressEnabled = document.getElementById('agentCompressEnabled').value;
  const compressRecentKeep = toNullableInt(document.getElementById('agentCompressRecentKeep').value);
  const compressMaxChars = toNullableInt(document.getElementById('agentCompressMaxChars').value);
  const compressTotalBudget = toNullableInt(document.getElementById('agentCompressTotalBudget').value);

  let compressConfig = null;
  if (
    compressEnabled !== 'inherit' ||
    compressRecentKeep !== null ||
    compressMaxChars !== null ||
    compressTotalBudget !== null
  ) {
    compressConfig = {};
    if (compressEnabled !== 'inherit') {
      compressConfig.enabled = compressEnabled === 'true';
    }
    if (compressRecentKeep !== null) {
      compressConfig.recent_keep = compressRecentKeep;
    }
    if (compressMaxChars !== null) {
      compressConfig.max_chars_per_msg = compressMaxChars;
    }
    if (compressTotalBudget !== null) {
      compressConfig.total_budget_chars = compressTotalBudget;
    }
  }

  const body = {
    name,
    description: document.getElementById('agentDesc').value,
    system_prompt: document.getElementById('agentPrompt').value,
    model_id: document.getElementById('agentModel').value,
    temperature: parseFloat(document.getElementById('agentTemp').value),
    max_tokens: parseInt(document.getElementById('agentMaxTokens').value),
    skills: selectedSkills(),
    compress_config: compressConfig,
  };

  const url = id ? `/api/agents/${id}` : '/api/agents';
  const method = id ? 'PUT' : 'POST';
  await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  closeModal();
  loadAgents();
}

window.addEventListener('DOMContentLoaded', loadAgents);
