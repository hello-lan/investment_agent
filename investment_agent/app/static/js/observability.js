let timer = null;
let isLoading = false;

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function getFilters() {
  return {
    session_id: document.getElementById('sessionId').value.trim(),
    task_id: document.getElementById('taskId').value.trim(),
    limit: parseInt(document.getElementById('limit').value || '100'),
  };
}

function buildQuery(filters) {
  const p = new URLSearchParams();
  if (filters.session_id) p.set('session_id', filters.session_id);
  if (filters.task_id) p.set('task_id', filters.task_id);
  if (filters.limit) p.set('limit', String(filters.limit));
  return p.toString();
}

function renderTraces(rows) {
  const tbody = document.querySelector('#traceTable tbody');
  tbody.innerHTML = (rows || []).map(r => `
    <tr>
      <td>${esc((r.created_at || '').slice(0, 19).replace('T', ' '))}</td>
      <td>${esc(r.agent_name)}</td>
      <td>${esc(r.session_id)}</td>
      <td>${esc(r.task_id)}</td>
      <td>${esc(r.step ?? '')}</td>
      <td>${esc(r.event_type)}</td>
      <td>${esc(r.model)}</td>
      <td>${esc(r.input_tokens)}</td>
      <td>${esc(r.output_tokens)}</td>
      <td class="obs-pre">${esc(r.detail)}</td>
    </tr>
  `).join('');
}

async function loadData() {
  if (isLoading) return;
  if (document.visibilityState !== 'visible') return;
  isLoading = true;
  try {
    const q = buildQuery(getFilters());
    const traces = await fetch(`/api/observability/traces?${q}`).then(r => r.json());
    renderTraces(traces);
    document.getElementById('lastUpdated').textContent = `最后更新：${new Date().toLocaleTimeString()}`;
  } finally {
    isLoading = false;
  }
}

function resetTimer() {
  if (timer) clearInterval(timer);
  const auto = document.getElementById('autoRefresh').value;
  if (auto === 'on') {
    timer = setInterval(loadData, 5000);
  }
}

window.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    loadData();
  }
});

window.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btnRefresh').addEventListener('click', loadData);
  document.getElementById('autoRefresh').addEventListener('change', resetTimer);
  document.getElementById('sessionId').addEventListener('change', loadData);
  document.getElementById('taskId').addEventListener('change', loadData);
  document.getElementById('limit').addEventListener('change', loadData);
  resetTimer();
  loadData();
});
