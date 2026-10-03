// Dependency-free DOM harness: exercises shipped event handlers, not a real Chrome load.
import test from 'node:test';
import {DISCLOSURE_VERSION} from '../core/storage.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
class Element {
  constructor(tag,owner) { this.tagName=tag.toLowerCase();this.owner=owner;this.children=[];this.dataset={};this.listeners={};this.hidden=false;this.disabled=false;this.textContent='';this.value=''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; }
  remove() { this.removed=true; }
  scrollIntoView() {}
  addEventListener(type,fn) { this.listeners[type]=fn; }
  async fire(type='click') { if (!this.disabled) return this.listeners[type]?.({preventDefault(){}}); }
  click() { this.owner.lastClicked=this; }
}
async function environment(stem,initial={}) {
  const html=await readFile(new URL(`../${stem}.html`,import.meta.url),'utf8');
  const ids=new Map(),all=[];
  const document={createElement(tag){const e=new Element(tag,document);all.push(e);return e;},getElementById:id=>ids.get(id),
    querySelectorAll:tag=>all.filter(e=>e.tagName===tag&&!e.removed)};
  document.body=document.createElement('body');
  for (const m of html.matchAll(/<([\w]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const e=document.createElement(m[1]);e.hidden=/\bhidden\b/.test(m[2]);ids.set(m[3],e);
  }
  const data=structuredClone(initial),storage={
    async get(keys){return Object.fromEntries((typeof keys==='string'?[keys]:keys).filter(k=>Object.hasOwn(data,k)).map(k=>[k,structuredClone(data[k])]));},
    async set(values){Object.assign(data,structuredClone(values));},async remove(key){delete data[key];},
    async clear(){for(const k of Object.keys(data))delete data[k];},async setAccessLevel(value){assert.equal(value.accessLevel,'TRUSTED_CONTEXTS');},
  };
  const saved={document:globalThis.document,chrome:globalThis.chrome,window:globalThis.window,fetch:globalThis.fetch};
  let network=0,historyReads=0;
  const now=Date.now();
  globalThis.document=document;globalThis.window={open(){},confirm:()=>true};
  globalThis.chrome={storage:{local:storage},runtime:{openOptionsPage:async()=>{},getURL:p=>'chrome-extension://test/'+p},history:{
    search:async()=>{historyReads++;return [{url:'https://example.com/signup/private-ID?token=SECRET',title:'PRIVATE TITLE'}];},
    getVisits:async()=>[{visitId:'1',visitTime:now-86400000}],
  }};
  globalThis.fetch=async(url,request)=>{
    network++;
    assert.equal(url,'https://api.tokenfactory.nebius.com/v1/models');assert.equal(request.method,'GET');
    return {ok:true,json:async()=>({data:[{id:'nvidia/nemotron-ultra'},{id:'nvidia/nemotron-nano'}]})};
  };
  return {ids,all,data,storage,document,get network(){return network;},get historyReads(){return historyReads;},restore(){Object.assign(globalThis,saved);}};
}
test('Popup first-use, local Scan, policy cards and exact pre-Run request preview work without network',async()=>{
  const env=await environment('popup',{nebiusKey:'test-nebius-secret'});
  try {
    await import('../popup.js?ui-smoke');
    assert.equal(env.ids.get('onboarding').hidden,false);assert.equal(env.historyReads,0);assert.equal(env.network,0);
    await env.ids.get('accept').fire();assert.deepEqual(env.data.consent,{accepted:true,version:DISCLOSURE_VERSION});assert.equal(env.ids.get('mainControls').hidden,false);
    await env.ids.get('scan').fire();assert.equal(env.historyReads,1);assert.equal(env.network,0);
    assert.equal(env.ids.get('signals').children.length,1);assert.equal(env.data.trace[0].kind,'mandate_decision');
    const button=env.all.find(e=>e.textContent==='Preview request');assert.ok(button);await button.fire();
    assert.equal(env.network,0);assert.equal(env.ids.get('preview').hidden,false);assert.equal(env.ids.get('body').textContent,'(No request body)');
    await env.ids.get('run').fire();assert.equal(env.network,1);
    const body=env.ids.get('body').textContent;assert.equal(JSON.parse(body).max_tokens,8192);
    assert.ok(!body.includes('private-ID'));assert.ok(!body.includes('PRIVATE TITLE'));assert.ok(!body.includes('test-nebius-secret'));
    await env.ids.get('cancel').fire();assert.equal(env.ids.get('preview').hidden,true);assert.equal(env.network,1);
    await env.ids.get('revoke').fire();assert.deepEqual(env.data,{});assert.equal(env.ids.get('onboarding').hidden,false);
    const reads=env.historyReads;await env.ids.get('scan').fire();assert.equal(env.historyReads,reads);assert.equal(env.network,1);
  } finally {env.restore();}
});
test('Options save, search hold, excluded hosts and deletion use local storage only',async()=>{
  const env=await environment('options');
  try {
    await import('../options.js?ui-smoke');
    env.ids.get('nebius').value='MY_PRIVATE_TEST_KEY';env.ids.get('policy').value='hold';env.ids.get('excluded').value='example.com\nexample.com';
    await env.ids.get('form').fire('submit');
    // Form submission starts an async local save; drain microtasks before observing it.
    await new Promise(resolve=>setTimeout(resolve,0));
    assert.equal(env.data.nebiusKey,'MY_PRIVATE_TEST_KEY');assert.deepEqual(env.data.mandate.require_confirmation,['research_briefing','commerce.quote']);
    assert.deepEqual(env.data.excludedHosts,['example.com']);assert.equal(env.network,0);assert.equal(env.historyReads,0);
    assert.ok(!env.ids.get('status').textContent.includes('MY_PRIVATE_TEST_KEY'));
    await env.storage.set({trace:[{kind:'test',ts:new Date().toISOString()}]});await env.ids.get('clearTrace').fire();assert.equal(env.data.trace,undefined);
    await env.ids.get('clearAll').fire();assert.equal(env.data.nebiusKey,undefined);assert.equal(env.ids.get('nebius').value,'');assert.equal(env.network,0);
  } finally {env.restore();}
});
