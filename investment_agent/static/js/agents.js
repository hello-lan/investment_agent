function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

let availableModels = [];

async function loadModels() {
  const data = await fetch('/api/settings/models').then(r => r.json());
  availableModels = data.list || [];
  return availableModels;
}

async function loadAgents(){
  await loadModels();
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
      <div class="meta">${esc(a.model_provider||'')} · ${esc(a.model_name||'')}</div>
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

function openModal(agent){
  document.getElementById('modalTitle').textContent = agent ? '编辑 Agent' : '新建 Agent';
  document.getElementById('agentId').value = agent?.id || '';
  document.getElementById('agentName').value = agent?.name || '';
  document.getElementById('agentDesc').value = agent?.description || '';
  document.getElementById('agentPrompt').value = agent?.system_prompt || '';
  document.getElementById('agentModel').innerHTML = buildModelOptions(agent?.model_name || '');
  document.getElementById('agentTemp').value = agent?.temperature ?? 0.7;
  document.getElementById('agentMaxTokens').value = agent?.max_tokens || 4096;
  document.getElementById('modalOverlay').classList.add('open');
}

function closeModal(){
  document.getElementById('modalOverlay').classList.remove('open');
}

async function editAgent(id){
  const agent = await fetch(`/api/agents/${id}`).then(r => r.json());
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

  const selectedModelId = document.getElementById('agentModel').value;
  const selectedModel = availableModels.find(m => m.id === selectedModelId);

  const body = {
    name,
    description: document.getElementById('agentDesc').value,
    system_prompt: document.getElementById('agentPrompt').value,
    model_provider: selectedModel?.type || 'anthropic',
    model_name: selectedModelId,
    temperature: parseFloat(document.getElementById('agentTemp').value),
    max_tokens: parseInt(document.getElementById('agentMaxTokens').value),
    skills: [],
  };

  const url = id ? `/api/agents/${id}` : '/api/agents';
  const method = id ? 'PUT' : 'POST';
  await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  closeModal();
  loadAgents();
}

window.addEventListener('DOMContentLoaded', loadAgents);
