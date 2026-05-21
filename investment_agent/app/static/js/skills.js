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
      const typeTag = s.type === 'orch'
        ? '<span class="tag tag-orch">orch</span> '
        : '';
      const depInfo = (s.depends_on && s.depends_on.length)
        ? ' <span class="skill-deps-inline">(' + s.depends_on.length + ' 个子流程: ' + esc(s.depends_on.join(', ')) + ')</span>'
        : '';
      return '<tr>' +
        '<td class="col-name">' + typeTag + name + '</td>' +
        '<td class="col-desc">' + desc + depInfo + '</td>' +
        '</tr>';
    }).join('');
  } catch(e) {
    console.error('loadSkills error:', e);
    const tbody = document.getElementById('skillTbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="2" class="empty">加载失败: ' + esc(e.message) + '</td></tr>';
  }
}

window.addEventListener('DOMContentLoaded', loadSkills);
