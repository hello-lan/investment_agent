function esc(s){return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

async function loadSkills(){
  const skills = await fetch('/api/skills').then(r => r.json());
  const grid = document.getElementById('skillGrid');
  if(!skills.length){
    grid.innerHTML = '<div class="empty">暂无可用 Skill</div>';
    return;
  }

  grid.innerHTML = skills.map(s => `
    <div class="skill-card">
      <div class="skill-title">
        <div class="skill-name">${esc(s.name)}</div>
      </div>
      <div class="skill-desc">${esc(s.description)}</div>
      <div class="tool-tags">${(s.tools || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>
      <div class="status">Schema: ${esc(s.schema_name)}</div>
    </div>
  `).join('');
}

window.addEventListener('DOMContentLoaded', loadSkills);
