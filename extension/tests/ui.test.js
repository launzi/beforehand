import test from 'node:test'; import assert from 'node:assert/strict'; import {readFile,readdir} from 'node:fs/promises';
import {initWelcome,renderDisclosure} from '../welcome.js'; import {initPopup} from '../popup.js'; import {initOptions} from '../options.js';
import {Store,consent} from './helpers.js'; import {documentFake,all} from './dom.js'; import {DISCLOSURE} from '../core/disclosure.js';
function ui(ids,data={}) {
 const doc=documentFake();for(const id of ids){const el=doc.createElement('div');el.id=id;doc.body.append(el);}
 const tabs=[],storage=new Store(data),chrome={storage:{local:storage},tabs:{query:async()=>[{}],create:async v=>tabs.push(v)},runtime:{getURL:p=>'chrome-extension://id/'+p}};
 return {doc,chrome,storage,tabs,id:id=>doc.getElementById(id)};
}
test('welcome renders the exact approved text with safe nodes and both choices accept v4',async()=>{
 const doc=documentFake(),root=doc.createElement('div');renderDisclosure(root,doc);assert.equal(root.textContent,DISCLOSURE);
 for(const auto of [true,false]) {
  const e=ui(['disclosure','enable','notNow','welcomeActions','complete','shops']);await initWelcome({doc:e.doc,chrome:e.chrome});await e.id(auto?'enable':'notNow').fire();
  assert.equal(e.storage.data.consent.version,5);assert.equal(e.storage.data.autoCheck,auto);assert.match(e.id('complete').textContent,/You're set/);assert.equal(all(e.id('shops')).filter(n=>n.tagName==='h3').length,5); // China ships but has no supported shop
 }
});
test('popup tolerates unavailable tab URL and persists global/destination controls',async()=>{
 const e=ui(['controls','version'],{...consent(),autoCheck:true});await initPopup({doc:e.doc,chrome:e.chrome});
 assert.match(e.id('controls').textContent,/Open a supported shop/);
 const toggle=e.doc.getElementById('autoEverywhere');toggle.checked=false;await toggle.fire('change');assert.equal(e.storage.data.autoCheck,false);
 const select=e.doc.getElementById('destination');select.value='GB';await select.fire('change');assert.equal(e.storage.data.destination,'GB');
});
test('popup site switch controls the real tab shop with the reviewed labels',async()=>{
 const e=ui(['controls','version'],{...consent(),autoCheck:true});
 e.chrome.tabs.query=async()=>[{url:'https://www.amazon.com/dp/example'}];e.chrome.runtime.getManifest=()=>({version:'1.2.0'});await initPopup({doc:e.doc,chrome:e.chrome});
 for(const t of ['amazon.com','Show Korea prices on this shop','Check automatically','Off: only when you click','Deliver to']) assert.ok(e.id('controls').textContent.includes(t),t);
 assert.equal(e.id('version').textContent,'v1.2.0');
 const toggle=e.doc.getElementById('autoShop');toggle.checked=false;await toggle.fire('change');assert.deepEqual(e.storage.data.disabledShops,['amazon.com']);
});
test('settings page lists shops without a current-shop row and states the data scope',async()=>{
 const e=ui(['controls','shopControls','exportLog','deleteLog','deleteAll','notice'],{...consent()});
 await initOptions({doc:e.doc,chrome:e.chrome,download:()=>{}});
 assert.doesNotMatch(e.id('controls').textContent,/Open a supported shop/);assert.match(e.id('shopControls').textContent,/amazon\.com/);
 const html=await readFile(new URL('../options.html',import.meta.url),'utf8');
 assert.match(html,/Turn off and delete my data/);assert.match(html,/Orders and payments aren't affected\./);assert.match(html,/mailto:support@munteok\.com/);
});
test('options export, delete log and delete-all use local data and reopen welcome',async()=>{
 const e=ui(['controls','shopControls','exportLog','deleteLog','deleteAll','notice'],{...consent(),trace:[{kind:'match_result',shop:'amazon.com',result:'same',ts:new Date().toISOString()}]});
 const exported=[];await initOptions({doc:e.doc,chrome:e.chrome,download:(data,name)=>exported.push({data,name})});
 await e.id('exportLog').fire();assert.equal(JSON.parse(exported[0].data).length,1);assert.match(exported[0].name,/beforehand-log-\d{8}-\d{6}\.json/);
 await e.id('deleteLog').fire();assert.equal(e.storage.data.trace,undefined);
 await e.id('deleteAll').fire();assert.deepEqual(e.storage.data,{});assert.deepEqual(e.tabs,[{url:'chrome-extension://id/welcome.html'}]);
});
test('shipped UI avoids HTML injection, eval and extra network sinks',async()=>{
 const files=['checkout.js','welcome.js','popup.js','options.js','content.js','background.js',...(await readdir(new URL('../core/',import.meta.url))).filter(f=>f.endsWith('.js')).map(f=>'core/'+f)];
 for(const file of files){const source=await readFile(new URL('../'+file,import.meta.url),'utf8');assert.doesNotMatch(source,/innerHTML|eval\(|new Function/);if(file!=='core/sink.js')assert.doesNotMatch(source,/\bfetch\(/);}
});
test('welcome labels the manual consent choice Only when I click',async()=>{
 const html=await readFile(new URL('../welcome.html',import.meta.url),'utf8');
 assert.match(html,/<button id="notNow"[^>]*>Only when I click<\/button>/);assert.doesNotMatch(html,/>Not now</);
});
