// extension/scripts/build.mjs
import {writeFile,mkdir,cp,rm} from 'node:fs/promises';
import {PRESETS} from '../core/presets.js';
import {KC_ENDPOINT} from '../core/korea-quote.js';
const root=new URL('../',import.meta.url);
export const TARGETS=Object.freeze({
  store:{target:'store',providers:['openai','anthropic'],defaultProvider:'openai',effectiveDate:'2026-10-15'},
  hackathon:{target:'hackathon',providers:['nebius'],defaultProvider:'nebius',effectiveDate:'2026-10-15'},
});
const origin=u=>new URL(u).origin;
export function manifestFor(target) {
  const t=TARGETS[target]; if (!t) throw new Error('Unknown target');
  const hosts=[...new Set([...t.providers.flatMap(p=>[origin(PRESETS[p].chat.url),origin(PRESETS[p].models.url)]),origin(KC_ENDPOINT)])];
  return {manifest_version:3,name:'Beforehand',version:'0.2.0',minimum_chrome_version:'102',
    description:'Turn local browsing patterns into useful next steps. Review every outgoing request before you run it.',
    permissions:['history','storage'],host_permissions:hosts.map(h=>h+'/*'),
    action:{default_popup:'popup.html',default_title:'Beforehand'},options_page:'options.html',
    content_security_policy:{extension_pages:`script-src 'self'; object-src 'none'; connect-src ${hosts.join(' ')}`}};
}
const SHIP=['popup.html','popup.js','options.html','options.js','privacy.html','style.css','core','LICENSE','NOTICE','PRIVACY.md'];
export async function build(target) {
  const manifest=manifestFor(target);
  const out=new URL(`dist/${target}/`,root);
  await rm(out,{recursive:true,force:true}); await mkdir(out,{recursive:true});
  for (const f of SHIP) await cp(new URL(f,root),new URL(f,out),{recursive:true});
  await writeFile(new URL('manifest.json',out),JSON.stringify(manifest,null,2)+'\n');
  const {providers,...config}=TARGETS[target];
  const source=`export const BUILD = Object.freeze({...${JSON.stringify(config)},providers:Object.freeze(${JSON.stringify(providers)})});\n`;
  await writeFile(new URL('core/build-config.js',out),source);
}
if (import.meta.url===`file://${process.argv[1]}`) {
  const arg=process.argv[2] ?? 'all';
  for (const t of arg==='all' ? Object.keys(TARGETS) : [arg]) await build(t);
  await writeFile(new URL('manifest.json',root),JSON.stringify(manifestFor('store'),null,2)+'\n');
}
