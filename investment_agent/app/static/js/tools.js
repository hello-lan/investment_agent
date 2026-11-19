let instances = [];
let builtins = [];
let templateDefaults = null;

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function errorText(data) {
  if (!data) return '请求失败';
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map(item => item.msg || JSON.stringify(item)).join('；');
  }
  return data.error || '请求失败';
}

async function loadAll() {
  const [toolList, instanceList, templates] = await Promise.all([
    fetch('/api/tools').then(r => r.json()),
    fetch('/api/tools/instances').then(r => r.json()),
    fetch('/api/tools/templates').then(r => r.json()),
  ]);
  builtins = (toolList || []).filter(item => item.kind !== 'instance');
  instances = instanceList || [];
  templateDefaults = (templates.templates || [])[0] || null;
  renderInstances();
  renderBuiltins();
}

function renderInstances() {
  const box = document.getElementById('instanceList');
  if (!instances.length) {
    box.innerHTML = '<div class="empty">还没有检索配置，点击右上角新建</div>';
    return;
  }
  box.innerHTML = instances.map(item => `
    <div class="model-item">
      <div class="model-info">
        <div class="model-name">
          ${esc(item.display_name)}
          <span class="badge badge-openai">${esc(item.tool_name)}</span>
        </div>
        <div class="model-meta">${esc(item.base_url)}${esc(item.path)} · 超时 ${esc(item.timeout_seconds)} 秒</div>
      </div>
      <div class="model-actions">
        <button class="btn btn-test btn-sm" data-test="${esc(item.id)}">测试</button>
        <button class="btn btn-ghost btn-sm" data-edit="${esc(item.id)}">编辑</button>
        <button class="btn btn-danger btn-sm" data-delete="${esc(item.id)}">删除</button>
      </div>
    </div>
  `).join('');
}

function renderBuiltins() {
  const box = document.getElementById('builtinList');
  if (!builtins.length) {
    box.innerHTML = '<div class="empty">没有内置工具</div>';
    return;
  }
  box.innerHTML = builtins.map(item => `
    <div class="model-item">
      <div class="model-info">
        <div class="model-name">
          ${esc(item.name)}
          <span class="default-tag">${item.auto_bound ? '默认勾选，可取消' : '需在 Agent 中勾选'}</span>
        </div>
        <div class="model-meta">${esc(item.description || '')}</div>
      </div>
    </div>
  `).join('');
}

function blankParam() {
  return { key: '', source: 'llm', type: 'string', required: true, description: '', value: '' };
}

function renderParams(params) {
  const box = document.getElementById('paramList');
  const rows = params && params.length ? params : [blankParam()];
  box.innerHTML = rows.map(param => paramCard(param)).join('');
}

function paramCard(param) {
  const source = param.source === 'fixed' ? 'fixed' : 'llm';
  const type = param.type || 'string';
  const types = ['string', 'integer', 'number', 'boolean', 'array'].map(item => (
    `<option value="${item}" ${item === type ? 'selected' : ''}>${item}</option>`
  )).join('');
  const valuePlaceholder = type === 'array' ? '逗号分隔，如 a,b' : '固定值';
  return `
    <div class="param-card" data-source="${source}">
      <input type="text" class="p-key" placeholder="参数名" value="${esc(param.key)}">
      <select class="p-source">
        <option value="llm" ${source === 'llm' ? 'selected' : ''}>模型填写</option>
        <option value="fixed" ${source === 'fixed' ? 'selected' : ''}>固定值</option>
      </select>
      <select class="p-type">${types}</select>
      <div class="param-detail">
        <input type="text" class="p-desc llm-only" placeholder="写明含义；有取值范围或枚举请列出。模型可见" title="写明含义；有取值范围或枚举请列出。模型可见" value="${esc(param.description || '')}" ${source === 'fixed' ? 'hidden' : ''}>
        <input type="text" class="p-value fixed-only" placeholder="${valuePlaceholder}" value="${esc(param.value || '')}" ${source === 'llm' ? 'hidden' : ''}>
      </div>
      <label class="check-label llm-only" ${source === 'fixed' ? 'hidden' : ''}>
        <input type="checkbox" class="p-required" ${param.required ? 'checked' : ''}>必填
      </label>
      <button class="btn btn-danger btn-sm" type="button" data-remove="1">删除</button>
    </div>
  `;
}

function addParam() {
  document.getElementById('paramList').insertAdjacentHTML('beforeend', paramCard(blankParam()));
}

function readParams() {
  return Array.from(document.querySelectorAll('#paramList .param-card')).map(card => ({
    key: card.querySelector('.p-key').value.trim(),
    source: card.querySelector('.p-source').value,
    type: card.querySelector('.p-type').value,
    required: card.querySelector('.p-required').checked,
    description: card.querySelector('.p-desc').value.trim(),
    value: card.querySelector('.p-value').value,
  }));
}

function openModal(id) {
  const overlay = document.getElementById('modalOverlay');
  document.getElementById('testResult').textContent = '';
  if (!id) {
    document.getElementById('modalTitle').textContent = '新建检索工具';
    document.getElementById('editId').value = '';
    document.getElementById('displayName').value = '';
    document.getElementById('toolName').value = '';
    document.getElementById('description').value = '';
    document.getElementById('baseUrl').value = 'http://127.0.0.1:8100';
    const defaults = templateDefaults && templateDefaults.defaults;
    document.getElementById('path').value = (defaults && defaults.path) || '/retrieve';
    document.getElementById('timeout').value = (defaults && defaults.timeout_seconds) || 90;
    renderParams((defaults && defaults.params) || []);
  } else {
    const item = instances.find(row => row.id === id);
    if (!item) return;
    document.getElementById('modalTitle').textContent = '编辑检索工具';
    document.getElementById('editId').value = item.id;
    document.getElementById('displayName').value = item.display_name;
    document.getElementById('toolName').value = item.tool_name;
    document.getElementById('description').value = item.description || '';
    document.getElementById('baseUrl').value = item.base_url;
    document.getElementById('path').value = item.path || '/retrieve';
    document.getElementById('timeout').value = item.timeout_seconds || 90;
    renderParams(item.params || []);
  }
  overlay.classList.add('open');
}

function closeModal() {
  document.getElementById('modalOverlay').classList.remove('open');
}

function payloadFromForm() {
  return {
    display_name: document.getElementById('displayName').value.trim(),
    tool_name: document.getElementById('toolName').value.trim(),
    description: document.getElementById('description').value.trim(),
    base_url: document.getElementById('baseUrl').value.trim(),
    path: document.getElementById('path').value.trim() || '/retrieve',
    timeout_seconds: Number(document.getElementById('timeout').value || 90),
    params: readParams(),
  };
}

async function saveInstance() {
  const id = document.getElementById('editId').value;
  const res = await fetch(id ? `/api/tools/instances/${id}` : '/api/tools/instances', {
    method: id ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payloadFromForm()),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert(errorText(data));
    return;
  }
  closeModal();
  await loadAll();
}

async function testConnection(baseUrl) {
  const url = baseUrl || document.getElementById('baseUrl').value.trim();
  const target = document.getElementById('testResult');
  if (target && !baseUrl) target.textContent = '正在连接…';
  const res = await fetch('/api/tools/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ base_url: url }),
  });
  const data = await res.json().catch(() => ({}));
  let text = '连接失败';
  if (data.ok) {
    text = `连接成功（${data.status_code}）${data.body ? ' ' + data.body : ''}`;
  } else if (data.error) {
    text = data.error;
  } else if (data.status_code) {
    text = `服务返回 ${data.status_code}${data.body ? ' ' + data.body : ''}`;
  }
  if (baseUrl) {
    alert(text);
    return;
  }
  if (target) target.textContent = text;
}

async function deleteInstance(id) {
  const item = instances.find(row => row.id === id);
  const name = item ? item.display_name : id;
  if (!confirm(`删除「${name}」？已勾选它的 Agent 在下次保存时会去掉这个工具。`)) return;
  const res = await fetch(`/api/tools/instances/${id}`, { method: 'DELETE' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    alert(errorText(data));
    return;
  }
  await loadAll();
}

document.getElementById('paramList').addEventListener('change', event => {
  const card = event.target.closest('.param-card');
  if (!card) return;
  const sourceSelect = event.target.closest('.p-source');
  if (sourceSelect) {
    const fixed = sourceSelect.value === 'fixed';
    card.dataset.source = sourceSelect.value;
    card.querySelectorAll('.llm-only').forEach(el => { el.hidden = fixed; });
    card.querySelectorAll('.fixed-only').forEach(el => { el.hidden = !fixed; });
  }
  if (event.target.closest('.p-type') || sourceSelect) {
    const valueInput = card.querySelector('.p-value');
    valueInput.placeholder = card.querySelector('.p-type').value === 'array' ? '逗号分隔，如 a,b' : '固定值';
  }
});

document.getElementById('paramList').addEventListener('click', event => {
  const button = event.target.closest('[data-remove]');
  if (!button) return;
  const cards = document.querySelectorAll('#paramList .param-card');
  if (cards.length <= 1) {
    alert('至少保留一个请求参数。');
    return;
  }
  button.closest('.param-card').remove();
});

document.getElementById('instanceList').addEventListener('click', event => {
  const edit = event.target.closest('[data-edit]');
  if (edit) {
    openModal(edit.dataset.edit);
    return;
  }
  const remove = event.target.closest('[data-delete]');
  if (remove) {
    deleteInstance(remove.dataset.delete);
    return;
  }
  const test = event.target.closest('[data-test]');
  if (test) {
    const item = instances.find(row => row.id === test.dataset.test);
    if (item) testConnection(item.base_url);
  }
});

document.getElementById('modalOverlay').addEventListener('click', event => {
  if (event.target.id === 'modalOverlay') closeModal();
});

loadAll();
