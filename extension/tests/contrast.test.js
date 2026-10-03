import test from 'node:test'; import assert from 'node:assert/strict'; import {readFile} from 'node:fs/promises';
const lum=h=>{const c=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255).map(x=>x<=.03928?x/12.92:((x+.055)/1.055)**2.4);return .2126*c[0]+.7152*c[1]+.0722*c[2];};
const ratio=(a,b)=>{const [x,y]=[lum(a),lum(b)].sort((p,q)=>q-p);return (x+.05)/(y+.05);};
for(const file of ['style.css','core/card.js']) {
 const source=await readFile(new URL('../'+file,import.meta.url),'utf8'),tokens={};
 for(const m of source.matchAll(/--([\w-]+):light-dark\((#[0-9a-f]{6}),(#[0-9a-f]{6})\)/gi)) tokens[m[1]]={light:m[2],dark:m[3]};
 for(const mode of ['light','dark']) for(const [fg,bg,min] of [['ink','bg',4.5],['bg','ink',4.5],['mute','bg',4.5],['on-accent','accent',4.5],['ink','bg',3],['accent','bg',3]]) test(`${file} ${mode}: ${fg}/${bg} ≥ ${min}`,()=>assert.ok(ratio(tokens[fg][mode],tokens[bg][mode])>=min));
}
