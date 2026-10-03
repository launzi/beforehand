// extension/scripts/md.mjs — build-time only. Supports the constructs PRIVACY.md uses: #..###, paragraphs, - lists, | tables, **bold**, `code`, [text](https://…).
const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const inline=s=>esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
  .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,(_,t,u)=>/^https:\/\//.test(u.replace(/&amp;/g,'&')) ? `<a href="${u}" rel="noopener noreferrer">${t}</a>` : t);
export function renderMarkdown(md) {
  const out=[], lines=md.replace(/\r\n/g,'\n').split('\n');
  for (let i=0;i<lines.length;) {
    const l=lines[i];
    if (!l.trim()) { i++; continue; }
    const h=/^(#{1,3})\s+(.*)$/.exec(l);
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (/^- /.test(l)) { const items=[]; while (i<lines.length && /^- /.test(lines[i])) items.push(`<li>${inline(lines[i++].slice(2))}</li>`); out.push(`<ul>${items.join('')}</ul>`); continue; }
    if (/^\|/.test(l)) {
      const rows=[]; while (i<lines.length && /^\|/.test(lines[i])) rows.push(lines[i++]);
      const cells=r=>r.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());
      const [head,,...body]=rows;
      out.push(`<table><thead><tr>${cells(head).map(c=>`<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${body.map(r=>`<tr>${cells(r).map(c=>`<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    const para=[]; while (i<lines.length && lines[i].trim() && !/^(#{1,3}\s|- |\|)/.test(lines[i])) para.push(lines[i++]);
    out.push(`<p>${inline(para.join(' '))}</p>`);
  }
  return out.join('\n');
}
