// Dependency-free DOM harness: exercises shipped event handlers, not a real Chrome load.
import test from 'node:test';
import {DISCLOSURE_VERSION} from '../core/storage.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
class Element {
  constructor(tag,owner) { this.tagName=tag.toLowerCase();this.owner=owner;this.children=[];this.dataset={};this.listeners={};this.hidden=false;this.disabled=false;this.textContent='';this.value='';this.style={setProperty(){}}; }
  get checked() {return this._checked ?? false;}
  set checked(value) {if(value && this.name) for(const el of this.owner.getElementsByName(this.name)) el._checked=false;this._checked=value;}
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; }
  remove() { this.removed=true; }
  setAttribute(name,value) { this[name]=value; }
  scrollIntoView() {}
  addEventListener(type,fn) { this.listeners[type]=fn; }
  async fire(type='click') { if (!this.disabled) return this.listeners[type]?.({preventDefault(){}}); }
  click() { this.owner.lastClicked=this; }
}
async function environment(stem,initial={}) {
  const html=await readFile(new URL(`../${stem}.html`,import.meta.url),'utf8');
  const ids=new Map(),all=[];
  const document={createElement(tag){const e=new Element(tag,document);all.push(e);return e;},createElementNS(ns,tag){return document.createElement(tag);},getElementById:id=>ids.get(id),
    getElementsByName:name=>all.filter(e=>e.name===name&&!e.removed),
    querySelectorAll:tag=>all.filter(e=>e.tagName===tag&&!e.removed)};
  document.body=document.createElement('body');
  for (const m of html.matchAll(/<([\w]+)\b([^>]*)>/g)) {
    const attrs=Object.fromEntries([...m[2].matchAll(/([\w-]+)="([^"]*)"/g)].map(x=>[x[1],x[2]]));
    if (!attrs.id && !attrs.name) continue;
    const e=document.createElement(m[1]);Object.assign(e,attrs);e.hidden=/\bhidden\b/.test(m[2]);
    if(attrs.id) ids.set(attrs.id,e);
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
    assert.equal(url,'https://api.openai.com/v1/models');assert.equal(request.method,'GET');
    return {ok:true,json:async()=>({data:[{id:'gpt-5'},{id:'gpt-5-mini'}]})};
  };
  return {ids,all,data,storage,document,id:x=>ids.get(x),byName:name=>document.getElementsByName(name),get network(){return network;},get historyReads(){return historyReads;},restore(){Object.assign(globalThis,saved);}};
}
test('Popup first-use, local Scan, policy cards and exact pre-Run request preview work without network',async()=>{
  const env=await environment('popup',{provider:'openai',providerKey:'OPENAI_TEST_SECRET'});
  try {
    await import('../popup.js?ui-smoke');
    assert.equal(env.ids.get('onboarding').hidden,false);assert.equal(env.historyReads,0);assert.equal(env.network,0);
    await env.ids.get('accept').fire();assert.deepEqual(env.data.consent,{accepted:true,version:DISCLOSURE_VERSION});assert.equal(env.ids.get('mainControls').hidden,false);
    await env.ids.get('scan').fire();assert.equal(env.historyReads,1);assert.equal(env.network,0);
    assert.equal(env.ids.get('signals').children.length,1);assert.equal(env.data.trace[0].kind,'mandate_decision');
    const button=env.all.find(e=>e.textContent==='Preview request');assert.ok(button);await button.fire();
    assert.equal(env.network,0);assert.equal(env.ids.get('preview').hidden,false);assert.equal(env.ids.get('body').textContent,'(No request body)');
    assert.ok(env.ids.get('sends').children.some(e=>e.tagName==='dt'));
    assert.ok(env.ids.get('never').children.some(e=>e.tagName==='li'));assert.equal(env.ids.get('run').disabled,false);
    await env.ids.get('run').fire();assert.equal(env.network,1);
    const body=env.ids.get('body').textContent;assert.equal(JSON.parse(body).max_completion_tokens,8192);
    assert.ok(!body.includes('private-ID'));assert.ok(!body.includes('PRIVATE TITLE'));assert.ok(!body.includes('OPENAI_TEST_SECRET'));
    await env.ids.get('cancel').fire();assert.equal(env.ids.get('preview').hidden,true);assert.equal(env.network,1);
    await env.ids.get('revoke').fire();assert.deepEqual(env.data,{});assert.equal(env.ids.get('onboarding').hidden,false);
    const reads=env.historyReads;await env.ids.get('scan').fire();assert.equal(env.historyReads,reads);assert.equal(env.network,1);
  } finally {env.restore();}
});
test('Options save, search hold, excluded hosts and deletion use local storage only',async()=>{
  const env=await environment('options');
  try {
    await import('../options.js?ui-smoke');
    env.ids.get('providerKey').value='MY_PRIVATE_TEST_KEY';env.byName('policy').find(r=>r.value==='hold').checked=true;env.ids.get('excluded').value='example.com\nexample.com';
    await env.ids.get('form').fire('submit');
    // Form submission starts an async local save; drain microtasks before observing it.
    await new Promise(resolve=>setTimeout(resolve,0));
    assert.equal(env.data.providerKey,'MY_PRIVATE_TEST_KEY');assert.deepEqual(env.data.mandate.require_confirmation,['research_briefing','commerce.quote']);
    assert.deepEqual(env.data.excludedHosts,['example.com']);assert.equal(env.network,0);assert.equal(env.historyReads,0);
    assert.ok(!env.ids.get('status').textContent.includes('MY_PRIVATE_TEST_KEY'));
    await env.storage.set({trace:[{kind:'test',ts:new Date().toISOString()}]});await env.ids.get('clearTrace').fire();assert.equal(env.data.trace,undefined);
    await env.ids.get('clearAll').fire();assert.equal(env.data.providerKey,undefined);assert.equal(env.ids.get('providerKey').value,'');assert.equal(env.network,0);
  } finally {env.restore();}
});

test('settings exposes only build providers and saves provider/key without a Tavily field',async()=>{
  const env=await environment('options',{consent:{accepted:true,version:DISCLOSURE_VERSION},provider:'openai',providerKey:'FAKE_OLD'});
  try {
    await import('../options.js?provider-settings');
    const html=await readFile(new URL('../options.html',import.meta.url),'utf8');assert.ok(!/tavily/i.test(html));
    const radios=env.byName('provider');assert.deepEqual(radios.map(r=>r.value),['openai','anthropic']);
    radios[1].checked=true;await radios[1].fire('change');assert.equal(env.id('providerKey').value,'');
    assert.match(env.id('keyHelp').textContent,/Anthropic/);
    env.id('providerKey').value=' FAKE_ANTHROPIC ';await env.id('form').fire('submit');
    assert.equal(env.data.provider,'anthropic');assert.equal(env.data.providerKey,'FAKE_ANTHROPIC');assert.equal(env.data.tavilyKey,undefined);
    await env.id('toggleKey').fire();assert.equal(env.id('providerKey').type,'text');
    await env.id('toggleKey').fire();assert.equal(env.id('providerKey').type,'password');
    assert.equal(env.network,0);assert.equal(env.historyReads,0);
  } finally {env.restore();}
});
test('settings deletion needs confirmation and cancelled deletion preserves all data',async()=>{
  const env=await environment('options',{provider:'openai',providerKey:'FAKE_KEY',trace:[{kind:'test',ts:new Date().toISOString()}]});
  try {
    await import('../options.js?delete-settings');let confirmations=0;
    globalThis.window.confirm=message=>{assert.match(message,/cannot be undone/);confirmations++;return false;};
    const before=structuredClone(env.data);await env.id('clearTrace').fire();await env.id('clearAll').fire();
    assert.equal(confirmations,2);assert.deepEqual(env.data,before);
    globalThis.window.confirm=()=>true;await env.id('clearTrace').fire();assert.equal(env.data.trace,undefined);
    await env.id('clearAll').fire();assert.deepEqual(env.data,{});assert.equal(env.id('providerKey').value,'');
  } finally {env.restore();}
});
test('Popup displays a monochrome icon and Try later for a research rate limit',async()=>{
  const {Controller}=await import('../core/controller.js');
  const {ResearchRateLimitError}=await import('../core/research.js');
  const env=await environment('popup',{provider:'openai',providerKey:'FAKE_KEY',consent:{accepted:true,version:DISCLOSURE_VERSION}});
  const run=Controller.prototype.run;
  try {
    Controller.prototype.run=async()=>{throw new ResearchRateLimitError();};
    await import('../popup.js?rate-limit-ui');
    env.id('run').disabled=false;await env.id('run').fire();
    const error=env.id('error');assert.equal(error.className,'hold');
    assert.equal(error.children[0].tagName,'svg');assert.equal(error.children[0]['aria-hidden'],'true');
    assert.equal(error.children[1].textContent,'Try later');
    assert.equal(env.id('status').textContent,'');assert.equal(env.network,0);
    assert.equal(env.id('run').disabled,true);
  } finally {Controller.prototype.run=run;env.restore();}
});
