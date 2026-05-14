const BADGE = {
  anthropic: '<span class="badge badge-anthropic">Anthropic</span>',
  openai_compat: '<span class="badge badge-openai">OpenAI 兼容</span>',
};

let modelList = [];
let defaultModelId = '';

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

async function loadAll() {
  const models = await fetch('/api/settings/models').then(r => r.json());
  modelList = models.list || [];
  defaultModelId = models.default || '';

  renderModelList();
}

function renderModelList() {
  const container = document.getElementById('modelListContainer');
  if (!modelList.length) {
    container.innerHTML = '<div style="text-align:center;color:#999;padding:20px;font-size:13px;">暂无模型，点击右上角添加</div>';
    return;
  }
  container.innerHTML = modelList.map(m => `
    <div class="model-item ${m.id === defaultModelId ? 'is-default' : ''}">
      ${BADGE[m.type] || BADGE.openai_compat}
      <div class="model-info">
        <div class="model-name">
          ${esc(m.name)}
          ${m.id === defaultModelId ? '<span class="default-tag">默认</span>' : ''}
        </div>
        <div class="model-meta">
          ${m.base_url ? esc(m.base_url) + ' · ' : ''}model: ${esc(m.model)}
        </div>
      </div>
      <div class="model-actions">
        ${m.id !== defaultModelId ? `<button class="btn btn-ghost btn-sm" onclick="setDefault('${esc(m.id)}')">设为默认</button>` : ''}
        <button class="btn btn-test btn-sm" onclick="testModel('${esc(m.id)}')">测试</button>
        <button class="btn btn-ghost btn-sm" onclick="openModal('${esc(m.id)}')">编辑</button>
        <button class="btn btn-danger btn-sm" onclick="deleteModel('${esc(m.id)}')">删除</button>
      </div>
    </div>
  `).join('');
}

async function setDefault(id) {
  await fetch('/api/settings/models/default', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({model_id: id}),
  });
  defaultModelId = id;
  renderModelList();
}

function openModal(id) {
  const m = id ? modelList.find(x => x.id === id) : null;
  document.getElementById('modalTitle').textContent = m ? '编辑模型' : '添加模型';
  document.getElementById('mEditId').value = m?.id || '';
  document.getElementById('mId').value = m?.id || '';
  document.getElementById('mId').disabled = !!m;
  document.getElementById('mName').value = m?.name || '';
  document.getElementById('mType').value = m?.type || 'openai_compat';
  document.getElementById('mModel').value = m?.model || '';
  document.getElementById('mKey').value = '';
  document.getElementById('mKey').placeholder = m?.api_key ? '已设置（输入新值覆盖）' : 'sk-...';
  document.getElementById('mBaseUrl').value = m?.base_url || '';
  toggleBaseUrl();
  document.getElementById('modalOverlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modalOverlay').classList.remove('open');
}

function toggleBaseUrl() {
  const type = document.getElementById('mType').value;
  document.getElementById('baseUrlRow').classList.toggle('hidden', type === 'anthropic');
}

async function saveModel() {
  const editId = document.getElementById('mEditId').value;
  const body = {
    id: document.getElementById('mId').value.trim(),
    name: document.getElementById('mName').value.trim(),
    type: document.getElementById('mType').value,
    model: document.getElementById('mModel').value.trim(),
    api_key: document.getElementById('mKey').value || '***',
    base_url: document.getElementById('mBaseUrl').value.trim(),
  };
  if (!body.name || !body.model) { alert('请填写名称和模型名'); return; }

  let res;
  if (editId) {
    res = await fetch(`/api/settings/models/${editId}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
  } else {
    res = await fetch('/api/settings/models', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
  }
  const data = await res.json();
  if (data.error) { alert(data.error); return; }
  closeModal();
  loadAll();
}

async function deleteModel(id) {
  if (!confirm('确认删除该模型？')) return;
  await fetch(`/api/settings/models/${id}`, {method: 'DELETE'});
  loadAll();
}

async function testModel(id) {
  const m = modelList.find(x => x.id === id);
  if (!m) return;
  const btn = event.target;
  btn.textContent = '测试中...'; btn.disabled = true;
  try {
    const res = await fetch('/api/settings/models/test', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({model_id: id}),
    });
    const data = await res.json();
    btn.textContent = data.ok ? '✓ 连通' : '✗ 失败';
    btn.style.background = data.ok ? '#e8f5e9' : '#ffebee';
    btn.style.color = data.ok ? '#2e7d32' : '#c62828';
  } catch(e) {
    btn.textContent = '✗ 失败';
  }
  setTimeout(() => { btn.textContent = '测试'; btn.disabled = false; btn.style = ''; }, 3000);
}

window.addEventListener('DOMContentLoaded', loadAll);
