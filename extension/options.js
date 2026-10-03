import {renderSettings} from './core/settings-ui.js';
import {readTrace,deleteTrace,deleteAllData} from './core/storage.js';
function downloadLog(doc,data,name) {
 const url=URL.createObjectURL(new Blob([data],{type:'application/json'})),a=doc.createElement('a');a.href=url;a.download=name;doc.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export async function initOptions({doc,chrome,download=(data,name)=>downloadLog(doc,data,name)}) {
 const id=name=>doc.getElementById(name),storage=chrome.storage.local;
 await renderSettings({doc,chrome,root:id('controls'),shopRoot:id('shopControls')});
 const action=(name,fn)=>id(name).addEventListener('click',async()=>{id(name).disabled=true;try{await fn();}catch{id('notice').textContent='Could not complete the action. Please try again.';}finally{id(name).disabled=false;}});
 action('exportLog',async()=>{const trace=await readTrace(storage),stamp=new Date().toISOString().replace(/[-:]/g,'').replace('T','-').slice(0,15);download(JSON.stringify(trace,null,2),`beforehand-log-${stamp}.json`);id('notice').textContent='Log exported.';});
 action('deleteLog',async()=>{await deleteTrace(storage);id('notice').textContent='Log deleted.';});
 action('deleteAll',async()=>{await deleteAllData(storage);id('notice').textContent='All local data deleted. Auto-check is off.';await renderSettings({doc,chrome,root:id('controls'),shopRoot:id('shopControls')});await chrome.tabs.create({url:chrome.runtime.getURL('welcome.html')});});
}
if(globalThis.document && globalThis.chrome?.storage) void initOptions({doc:document,chrome});
