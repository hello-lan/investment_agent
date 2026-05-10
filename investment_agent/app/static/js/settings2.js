async function saveEngine() {
  const body = {
    max_steps: parseInt(document.getElementById('maxSteps').value),
    slow_think_interval: parseInt(document.getElementById('slowThink').value),
    token_budget: parseInt(document.getElementById('tokenBudget').value),
    loop_detection_threshold: parseInt(document.getElementById('loopThreshold').value),
  };
  const res = await fetch('/api/settings/engine', {
    method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  showMsg('engineMsg', res.ok, res.ok ? '已保存' : '保存失败');
}

async function saveTools() {
  const body = {tushare_token: document.getElementById('tushareToken').value || '***'};
  const res = await fetch('/api/settings/tools', {
    method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  showMsg('toolsMsg', res.ok, res.ok ? '已保存' : '保存失败');
}

function showMsg(id, ok, text) {
  const el = document.getElementById(id);
  el.className = 'inline-msg ' + (ok ? 'success' : 'error');
  el.textContent = text;
  el.style.display = 'inline';
  setTimeout(() => { el.style.display = 'none'; }, 3000);
}

window.addEventListener('DOMContentLoaded', loadAll);
