import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Controller,decisionFor} from '../core/controller.js';
import {sendRequest} from '../core/providers.js';
import {modelsRequest} from '../core/llm.js';
import {researchRequest} from '../core/research.js';
import {searchPolicy,PLANS,evaluateMandate} from '../core/mandate.js';
import {DISCLOSURE_VERSION,acceptConsent,getSettings,deleteAllData,appendTrace} from '../core/storage.js';
import {readHistory} from '../core/history.js';
import {detectAll} from '../core/signals.js';
import {usFromMs} from '../core/util.js';
import {productName,quoteArguments,quoteRequest,sanitizeQuote,parseQuoteRPC,summaryFacts,validateSummary,DISCLOSURE} from '../core/korea-quote.js';
import {renderQuoteCard} from '../core/quote-card.js';
const sample=JSON.parse(await readFile(new URL('../../browsing/web/fixtures/korea-quote-20261003-004400.json',import.meta.url),'utf8'));
class Store {
  constructor(value={}) {this.value=structuredClone(value);}
  async get(keys) {return Object.fromEntries((typeof keys==='string'?[keys]:keys).filter(k=>Object.hasOwn(this.value,k)).map(k=>[k,structuredClone(this.value[k])]));}
  async set(value) {Object.assign(this.value,structuredClone(value));}
  async clear() {this.value={};}
  async remove(key) {delete this.value[key];}
}
const settings=()=>({consent:{accepted:true,version:DISCLOSURE_VERSION},provider:'openai',providerKey:'FAKE_OPENAI_KEY',mandate:searchPolicy('allow'),destination:'US'});
const signal=()=>({kind:'korea_product',key:'PRIVATE_LOCAL_HASH',host:'global.oliveyoung.com',term:'Anua Heartleaf 77% Soothing Toner 250ml | OLIVE YOUNG Global',
  first_us:usFromMs(Date.UTC(2026,8,1)),last_us:usFromMs(Date.UTC(2026,8,2)),evidence:{visit_count:2,product:'Anua',url:'https://private.example/path'}});
const answer=content=>({choices:[{message:{content},finish_reason:'stop'}]});
const models={data:[{id:'gpt-5'},{id:'gpt-5-mini'}]};
const rpc=raw=>({jsonrpc:'2.0',id:1,result:{structuredContent:raw}});
const reply=value=>({ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>value});

for(const consent of [undefined,{accepted:false,version:DISCLOSURE_VERSION},{accepted:true,version:DISCLOSURE_VERSION-1}]) {
  test(`Consent missing/stale/withdrawn blocks every network and history sink: ${JSON.stringify(consent)}`,async()=>{
    const storage=new Store({...settings(),onboarded:true,consent});let network=0,reads=0;
    const fetchImpl=async()=>{network++;return reply({});};
    for(const request of [modelsRequest('openai'),researchRequest('synthetic'),quoteRequest('Anua toner')])
      await assert.rejects(sendRequest(request,'FAKE_KEY',{storage,fetchImpl}),/current disclosure/);
    await assert.rejects(readHistory({search:async()=>{reads++;return[];}},{storage}),/current disclosure/);
    await assert.rejects(new Controller(storage,fetchImpl).prepare(signal()),/disclosure/);
    assert.equal(network,0);assert.equal(reads,0);
    assert.equal((await getSettings(storage)).onboarded,false);
  });
}
test('I agree records the exact version; withdrawal empties all local storage',async()=>{
  const storage=new Store({providerKey:'FAKE_KEY',trace:[{kind:'old'}]});await acceptConsent(storage);
  assert.deepEqual(storage.value.consent,{accepted:true,version:DISCLOSURE_VERSION});
  await deleteAllData(storage);assert.deepEqual(storage.value,{});
  await assert.rejects(appendTrace(storage,{kind:'late'}),/current disclosure/);assert.deepEqual(storage.value,{});
});
for(const mode of ['allow','hold','deny']) test(`Commerce quote ${mode} and checkout always denied`,async()=>{
  const s=settings();s.mandate=searchPolicy(mode);s.tavilyKey='';
  assert.equal((await decisionFor(signal(),s)).verdict,mode);
  const result=await evaluateMandate(s.mandate,signal(),{...PLANS.korea_product,action_kind:'commerce.checkout'});
  assert.equal(result.verdict,'deny');assert.equal(result.reason,'Checkout is out of scope for this build');
});
test('Quote stages preview the exact minimal body, strip tokens, and require separate Run for interpretation',async()=>{
  const storage=new Store(settings()),calls=[];
  const dirty=structuredClone(sample);dirty.quoteToken='OPAQUE_SECRET';dirty.payNow.quoteToken='NESTED_SECRET';
  const replies=[models,answer('ACT'),rpc(dirty),answer("It's cheaper to buy locally. Your estimated total is USD 65.27 versus a local price of USD 17.85.")];
  const c=new Controller(storage,async(url,init)=>{calls.push({url,...init});return reply(replies.shift());});
  await c.prepare(signal());assert.equal(calls.length,0);
  await c.run();await c.run();assert.equal(c.pending.stage,'quote');assert.equal(calls.length,2);
  const expected={jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'quote_korea_product',arguments:{product:'Anua Heartleaf 77% Soothing Toner 250ml',destination:'US'}}};
  assert.deepEqual(JSON.parse(c.pending.request.body),expected);
  const result=await c.run();assert.equal(result.quote.totalCost,65.27);assert.equal(c.pending.stage,'skill');assert.equal(calls.length,3);
  assert.deepEqual(JSON.parse(calls[2].body),expected);assert.equal(calls[2].headers.Authorization,undefined);
  assert.equal(calls[2].headers.Accept,'application/json, text/event-stream');assert.equal(calls[2].redirect,'error');assert.equal(calls[2].credentials,'omit');
  const wire=calls.map(c=>c.body||'').join('')+c.pending.request.body;
  for(const privateField of ['PRIVATE_LOCAL_HASH','https://private.example','first_us','last_us','quoteToken','OPAQUE_SECRET','NESTED_SECRET','next_steps']) assert.ok(!wire.includes(privateField),privateField);
  const final=await c.run();assert.match(final.text,/^It's cheaper to buy locally/);
  for(const forbidden of ['quoteToken','OPAQUE_SECRET','NESTED_SECRET','next_steps','fulfilment']) assert.ok(!JSON.stringify({result,final,storage:storage.value}).includes(forbidden));
});
test('Revocation during quote discards the late response without resurrecting storage',async()=>{
  const storage=new Store(settings());let release;
  const inFlight=sendRequest(quoteRequest('Anua toner'),'',{storage,fetchImpl:async()=>{
    await new Promise(resolve=>release=resolve);return reply(rpc(sample));
  }});
  while(!release) await new Promise(resolve=>setTimeout(resolve,0));
  await deleteAllData(storage);release();await assert.rejects(inFlight,/current disclosure/);assert.deepEqual(storage.value,{});
});
test('Destination changes invalidate an approved preview',async()=>{
  const storage=new Store(settings()),c=new Controller(storage,()=>{throw Error('must not call');});
  await c.prepare(signal());await storage.set({destination:'JP'});await assert.rejects(c.run(),/Settings changed/);
});
for(const [raw,message] of [
  [{error:{code:-32000,message:'Rate limit exceeded'}},/Rate limit exceeded/],
  [{error:{code:-32000,message:'koreaPriceKrw required'}},/price not found/],
  [{result:{isError:true,content:[{type:'text',text:'price not found'}]}},/price not found/],
  [{result:{structuredContent:{error:'price not found'}}},/price not found/],
  [{result:{}},/Malformed/],
]) test(`Quote error is explicit: ${JSON.stringify(raw)}`,()=>assert.throws(()=>parseQuoteRPC(raw),message));
test('HTTP rate limit and SSE quote response are supported',async()=>{
  const storage=new Store(settings());
  await assert.rejects(sendRequest(quoteRequest('Anua toner'),'',{storage,fetchImpl:async()=>({ok:false,status:429})}),/Rate limit exceeded/);
  const q=await sendRequest(quoteRequest('Anua toner'),'',{storage,fetchImpl:async()=>({ok:true,status:200,headers:{get:()=> 'text/event-stream'},
    text:async()=>`event: message\r\ndata: ${JSON.stringify(rpc(sample))}\r\n\r\n`})});
  assert.equal(q.totalCost,65.27);assert.ok(!JSON.stringify(q).includes('quoteToken'));
});
test('The network sink rejects extra quote arguments and alternate tool names',async()=>{
  for(const alter of [r=>r.params.arguments.koreaUrl='https://private.test',r=>r.params.name='some_other_tool',r=>r.params.arguments.product='a']) {
    const req=quoteRequest('Anua toner'),raw=JSON.parse(req.body);alter(raw);let calls=0;
    await assert.rejects(sendRequest({...req,body:JSON.stringify(raw)},'',{storage:new Store(settings()),fetchImpl:async()=>{calls++;}}),/not permitted/);assert.equal(calls,0);
  }
});
test('Product scrubbing preserves brands and removes URLs, site labels and identifiers',()=>{
  assert.equal(productName('MUSINSA STANDARD T-Shirt | MUSINSA'),'MUSINSA STANDARD T-Shirt');
  const product=productName('Toner demo@example.com token=SECRET https://private.test | OLIVE YOUNG Global');
  for(const forbidden of ['demo@example.com','SECRET','https://','OLIVE YOUNG'])assert.ok(!product.includes(forbidden));
  assert.throws(()=>quoteArguments('toner','AU'));assert.throws(()=>quoteArguments('a'));
});
test('Real history adapter retains only scrubbed product title and detects repeated views',async()=>{
  const now=Date.UTC(2026,9,1),storage=new Store(settings());
  const url='https://global.oliveyoung.com/product/detail?prdtNo=GA230518738';
  const history={search:async()=>[{url,title:'Anua toner | OLIVE YOUNG Global'}],getVisits:async()=>[
    {visitTime:now-86400000},{visitTime:now-2*86400000}]};
  const result=await readHistory(history,{storage,now});
  assert.equal(result.data.urls[0].product,'Anua toner');assert.ok(!JSON.stringify(result.data).includes('OLIVE'));
  assert.equal((await detectAll(result.data,result.options)).filter(s=>s.kind==='korea_product').length,1);
  const excluded=await readHistory(history,{storage,now,excludedHosts:['oliveyoung.com']});
  assert.equal((await detectAll(excluded.data,excluded.options)).length,0);
});
class Node {
  constructor(tag) {this.tag=tag;this.children=[];this.textContent='';this.dataset={};this.style={setProperty(){}};}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children=nodes;}
}
const flatten=node=>node.textContent+'\n'+node.children.map(flatten).join('\n');
test('Quote card renders exact amounts, duty sources, unknown verdict, warnings and conflict disclosure with no token',()=>{
  const raw=structuredClone(sample);raw.verdict='future_unknown_verdict';
  const quote=sanitizeQuote(raw),root=new Node('main');renderQuoteCard(root,quote,{createElement:tag=>new Node(tag)});
  const rendered=flatten(root);
  for(const value of ['future_unknown_verdict','$65.27','₩16,127','2.089235915388495','91 FR 47318',DISCLOSURE])assert.ok(rendered.includes(value),value);
  assert.ok(!rendered.includes('quoteToken'));assert.ok(!rendered.includes('REDACTED'));assert.ok(!rendered.includes('start checkout'));
  assert.equal(root.children[0].children.filter(n=>n.tag==='button').length,0);
});
test('Invented summary numbers and concealed buy_local verdict are rejected',()=>{
  const q=sanitizeQuote(sample);assert.throws(()=>validateSummary("It's cheaper to buy locally. Price is 9.99.",q),/unsupported number/);
  assert.throws(()=>validateSummary('Try the concierge.',q),/cheaper local/);
  assert.ok(!JSON.stringify(summaryFacts(q)).includes('link'));
});
