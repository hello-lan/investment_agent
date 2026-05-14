function esc(s){return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

async function loadSkills(){
  try {
    const res = await fetch('/api/skills');
    const skills = await res.json();
    const tbody = document.getElementById('skillTbody');
    if (!tbody) return;

    if (!skills || !skills.length){
      tbody.innerHTML = '<tr><td colspan="2" class="empty">暂无可用 Skill</td></tr>';
      return;
    }

    tbody.innerHTML = skills.map(s => {
      const name = esc(s.name || '');
      const desc = esc(s.description || '');
      return '<tr>' +
        '<td class="col-name">' + name + '</td>' +
        '<td class="col-desc">' + desc + '</td>' +
        '</tr>';
    }).join('');
  } catch(e) {
    console.error('loadSkills error:', e);
    const tbody = document.getElementById('skillTbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="2" class="empty">加载失败: ' + esc(e.message) + '</td></tr>';
  }
}

window.addEventListener('DOMContentLoaded', loadSkills);
