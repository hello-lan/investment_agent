function esc(s){return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

let workflowList = [];

const DEFAULT_WORKFLOW = {
  version: '1.0',
  nodes: [
    {
      id: 'collect',
      type: 'subagent',
      task: '收集目标文件中的关键数据',
      targets: ['/absolute/path/to/file.md'],
      expected_output: '输出关键摘录',
      depends_on: [],
      input_from: [],
    },
    {
      id: 'summarize',
      type: 'assistant',
      task: '基于上游结果给出总结',
      depends_on: ['collect'],
      input_from: ['collect'],
    },
  ],
};

function prettyJson(obj){
  return JSON.stringify(obj, null, 2);
}

async function loadWorkflows(){
  const container = document.getElementById('workflowListContainer');
  container.innerHTML = '<div style="text-align:center;color:#999;padding:20px;font-size:13px;">加载中...</div>';
  try {
    workflowList = await fetch('/api/workflows').then(r => r.json());
  } catch (e) {
    container.innerHTML = '<div style="text-align:center;color:#c62828;padding:20px;font-size:13px;">加载失败</div>';
    return;
  }

  if (!workflowList.length) {
    container.innerHTML = '<div style="text-align:center;color:#999;padding:20px;font-size:13px;">暂无 Workflow，点击右上角新建</div>';
    return;
  }

  container.innerHTML = workflowList.map(w => `
    <div class="workflow-item">
      <div class="workflow-info">
        <div class="workflow-name">${esc(w.name)}</div>
        <div class="workflow-desc">${esc(w.description || '暂无描述')}</div>
        <div class="workflow-meta">
          <span>ID: ${esc(w.id)}</span>
          <span>版本: ${esc(w.version || '-')}</span>
          <span>节点数: ${esc(w.node_count ?? 0)}</span>
          <span>更新时间: ${esc((w.updated_at || '').replace('T', ' ').slice(0, 16))}</span>
        </div>
      </div>
      <div class="workflow-actions">
        <button class="btn btn-primary btn-sm" onclick="editWorkflow('${w.id}')">编辑</button>
        <button class="btn btn-danger btn-sm" onclick="deleteWorkflow('${w.id}')">删除</button>
      </div>
    </div>
  `).join('');
}

function openWorkflowModal(workflow){
  document.getElementById('workflowModalTitle').textContent = workflow ? '编辑 Workflow' : '新建 Workflow';
  document.getElementById('workflowEditId').value = workflow?.id || '';
  document.getElementById('workflowName').value = workflow?.name || '';
  document.getElementById('workflowDesc').value = workflow?.description || '';
  const definition = workflow?.definition ? JSON.parse(workflow.definition) : DEFAULT_WORKFLOW;
  document.getElementById('workflowDefinition').value = prettyJson(definition);
  clearValidation();
  document.getElementById('workflowModalOverlay').classList.add('open');
}

function closeWorkflowModal(){
  document.getElementById('workflowModalOverlay').classList.remove('open');
}

function clearValidation(){
  const box = document.getElementById('workflowValidation');
  box.className = 'validation-box';
  box.textContent = '';
}

function setValidation(ok, message){
  const box = document.getElementById('workflowValidation');
  box.className = 'validation-box ' + (ok ? 'ok' : 'error');
  box.textContent = message;
}

function parseDefinitionInput(){
  const raw = document.getElementById('workflowDefinition').value.trim();
  if (!raw) throw new Error('请输入 Workflow JSON');
  return JSON.parse(raw);
}

async function validateWorkflowDefinition(){
  let definition;
  try {
    definition = parseDefinitionInput();
  } catch (e) {
    setValidation(false, 'JSON 解析失败：' + e.message);
    return false;
  }

  const res = await fetch('/api/workflows/validate', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({definition}),
  });
  const data = await res.json();
  if (!res.ok) {
    setValidation(false, data.detail || '校验失败');
    return false;
  }
  setValidation(true, `校验通过\n版本：${data.version}\n节点数：${data.node_count}`);
  document.getElementById('workflowDefinition').value = prettyJson(data.definition);
  return true;
}

async function editWorkflow(id){
  const workflow = await fetch(`/api/workflows/${id}`).then(r => r.json());
  openWorkflowModal(workflow);
}

async function saveWorkflow(){
  const id = document.getElementById('workflowEditId').value;
  const name = document.getElementById('workflowName').value.trim();
  if (!name) {
    alert('请输入 Workflow 名称');
    return;
  }

  let definition;
  try {
    definition = parseDefinitionInput();
  } catch (e) {
    setValidation(false, 'JSON 解析失败：' + e.message);
    return;
  }

  const body = {
    name,
    description: document.getElementById('workflowDesc').value.trim(),
    definition,
  };

  const url = id ? `/api/workflows/${id}` : '/api/workflows';
  const method = id ? 'PUT' : 'POST';
  const res = await fetch(url, {
    method,
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    setValidation(false, data.detail || '保存失败');
    return;
  }

  closeWorkflowModal();
  loadWorkflows();
}

async function deleteWorkflow(id){
  if (!confirm('确认删除该 Workflow？')) return;
  await fetch(`/api/workflows/${id}`, {method:'DELETE'});
  loadWorkflows();
}

window.addEventListener('DOMContentLoaded', loadWorkflows);
