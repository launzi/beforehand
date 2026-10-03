import {renderSettings} from './core/settings-ui.js';
import {readTrace} from './core/storage.js';
export async function initPopup({doc,chrome}) {
 await renderSettings({doc,chrome,root:doc.getElementById('controls')});
 const recent=doc.getElementById('recent');recent.replaceChildren();
 const entries=(await readTrace(chrome.storage.local)).filter(e=>e.kind==='match_result').slice(-5).reverse();
 for(const e of entries){const p=doc.createElement('p');p.textContent=`${e.shop ?? 'Shop'} · ${e.result.replaceAll('_',' ')}`;recent.append(p);}
 if(!entries.length){const p=doc.createElement('p');p.textContent='No checks yet.';recent.append(p);}
}
if(globalThis.document && globalThis.chrome?.storage) void initPopup({doc:document,chrome});
