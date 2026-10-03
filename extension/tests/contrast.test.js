// extension/tests/contrast.test.js — WCAG 2.2 relative luminance; self-contained (public repo cannot depend on private tools).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const css=await readFile(new URL('../style.css',import.meta.url),'utf8');
const tokens={};
for (const m of css.matchAll(/--([\w-]+):light-dark\((#[0-9a-f]{6}),(#[0-9a-f]{6})\)/gi)) tokens[m[1]]={light:m[2],dark:m[3]};
const lum=h=>{const c=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255).map(x=>x<=0.03928?x/12.92:((x+0.055)/1.055)**2.4);return .2126*c[0]+.7152*c[1]+.0722*c[2];};
const ratio=(a,b)=>{const [x,y]=[lum(a),lum(b)].sort((p,q)=>q-p);return (x+0.05)/(y+0.05);};
const PAIRS=[['ink','bg',4.5],['mute','bg',4.5],['accent','bg',4.5],['on-accent','accent',4.5],['allow','bg',4.5],['hold','bg',4.5],['deny','bg',4.5],['line','bg',1.0]];
for (const mode of ['light','dark']) for (const [fg,bg,min] of PAIRS) test(`${mode}: ${fg} on ${bg} ≥ ${min}`,()=>{
  assert.ok(tokens[fg] && tokens[bg],`missing token ${fg}/${bg}`);
  assert.ok(ratio(tokens[fg][mode],tokens[bg][mode])>=min,`${fg}/${bg} ${mode} = ${ratio(tokens[fg][mode],tokens[bg][mode]).toFixed(2)}`);
});
test('retired muted gray is gone',()=>{ assert.ok(!/#8a8270/i.test(css)); });
