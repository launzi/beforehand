import test from 'node:test';
import assert from 'node:assert/strict';
import {Controller,decisionFor} from '../core/controller.js';
import {searchPolicy,normalizeMandate,mandateDigest} from '../core/mandate.js';
import {minimizeSignal,triageVerdict,formatEvidence} from '../core/agent.js';
import {sendRequest} from '../core/providers.js';
import {modelsRequest,chatText,parseModels,resolveRole} from '../core/llm.js';
import {KC_ENDPOINT} from '../core/korea-quote.js';
const HACK={target:'hackathon',providers:['nebius'],defaultProvider:'nebius'};
const NEBIUS_CHAT='https://api.tokenfactory.nebius.com/v1/chat/completions', NEBIUS_MODELS='https://api.tokenfactory.nebius.com/v1/models';
import {getSettings,appendTrace,readTrace,TRACE_LIMIT,DISCLOSURE_VERSION,migrateSettings,secretValues} from '../core/storage.js';
import {readHistory,searchTerm,classifyHost} from '../core/history.js';
import {detectAll} from '../core/signals.js';
import {usFromMs,isoToUs,dateFromUs} from '../core/util.js';
import {scrubText} from '../core/scrub.js';
export class MemoryStorage {
  constructor(value={}) { this.value=structuredClone(value); this.failWrites=false; }
  async get(keys) {
    if (typeof keys === 'string') keys=[keys];
    return Object.fromEntries(keys.filter(k=>Object.hasOwn(this.value,k)).map(k=>[k,structuredClone(this.value[k])]));
  }
  async set(values) { if (this.failWrites) throw new Error('storage write failed'); Object.assign(this.value,structuredClone(values)); }
  async remove(key) { delete this.value[key]; }
  async clear() { this.value={}; }
}
const models=[{id:'nvidia/nemotron-ultra-long-latest'},{id:'nvidia/nemotron-ultra'},{id:'nvidia/nemotron-nano'}];
const settings=()=>({consent:{accepted:true,version:DISCLOSURE_VERSION},provider:'nebius',providerKey:'NEBIUS_TEST_SECRET',mandate:searchPolicy('allow'),excludedHosts:[]});
const signal=(kind='new_entry')=>({kind,key:'local-signal-hash',host:kind==='unresolved'?null:'example.com',term:kind==='unresolved'?'portable synthesizer comparison':null,
  first_us:usFromMs(Date.UTC(2026,8,1,10)),last_us:usFromMs(Date.UTC(2026,8,3,11)),
  evidence:kind==='unresolved'?{term:'portable synthesizer comparison',search_count:2,follow_through_counts:[0,1],distinct_days:2,low_follow_through:true,repeat_across_days:true}
  :{onboarding_paths:['/users/register/private-ID?token=SECRET'],first_visit_us:usFromMs(Date.UTC(2026,8,1,10)),visit_count:2}});
const answer=(text,finish_reason='stop')=>({choices:[{message:{content:text},finish_reason}]});
function fakeFetch(queue,calls=[]) {
  return async(url,init)=>{
    calls.push({url,...init});
    assert.ok([NEBIUS_CHAT,NEBIUS_MODELS,KC_ENDPOINT].includes(url));
    assert.equal(init.redirect,'error'); assert.equal(init.credentials,'omit');
    assert.ok(queue.length,'Unexpected automatic request');
    const next=queue.shift();
    if (next instanceof Error) throw next;
    return {ok:true,status:200,json:async()=>next};
  };
}
test('Explicit Run gates model discovery, triage and skill; preview bytes equal wire bytes; no keys in trace',async()=>{
  const calls=[],storage=new MemoryStorage(settings()),c=new Controller(storage,fakeFetch([{data:models},answer('ACT'),answer('You visited a setup page. You could check your next setup step.')],calls),HACK);
  await c.prepare(signal()); assert.equal(calls.length,0); assert.equal(c.pending.stage,'models');
  assert.equal(c.pending.request.body,null);
  await c.run(); assert.equal(calls.length,1); assert.equal(c.pending.stage,'triage');
  const triage=c.pending.request.body;
  assert.equal(JSON.parse(triage).max_tokens,8192); assert.equal(JSON.parse(triage).model,'nvidia/nemotron-ultra');
  assert.ok(!triage.includes('/no_think')); assert.ok(!triage.includes('private-ID')); assert.ok(!triage.includes('local-signal-hash'));
  await c.run(); assert.equal(calls.length,2); assert.equal(calls[1].body,triage); assert.equal(c.pending.stage,'skill');
  const skill=c.pending.request.body; assert.equal(JSON.parse(skill).max_tokens,2248); assert.ok(skill.includes('/no_think'));
  const result=await c.run(); assert.equal(calls.length,3); assert.equal(calls[2].body,skill); assert.equal(result.status,'complete'); assert.equal(c.pending,null);
  const trace=JSON.stringify(storage.value.trace);
  assert.ok(!trace.includes('NEBIUS_TEST_SECRET')); assert.ok(!trace.includes('Authorization'));
  assert.ok(trace.includes('request_completed')); await assert.rejects(c.run(),/Prepare/);
});
test('Research requires separate Run for KC and a new preview before search hits leave for Nano',async()=>{
  const calls=[],storage=new MemoryStorage(settings()),c=new Controller(storage,fakeFetch([{data:models},answer('ACT'),{jsonrpc:'2.0',id:1,result:{structuredContent:{results:[{title:'Device review',url:'https://review.example/item?token=SECRET#private',snippet:'Contact demo@example.com about this device.'}]}}},answer('You compared devices. You could check the review.')],calls),HACK);
  await c.prepare(signal('unresolved')); await c.run(); await c.run();
  assert.equal(calls.length,2); assert.equal(c.pending.stage,'search');
  const query=c.pending.request.body; assert.deepEqual(JSON.parse(query).params,{name:'research_briefing',arguments:{query:'portable synthesizer comparison'}});
  await c.run(); assert.equal(calls.length,3); assert.equal(calls[2].body,query); assert.equal(c.pending.stage,'skill');
  assert.ok(c.pending.request.body.includes('Device review')); assert.ok(!c.pending.request.body.includes('demo@example.com'));
  assert.ok(!c.pending.request.body.includes('?token=')); assert.equal(JSON.parse(c.pending.request.body).max_tokens,2348);
  await c.run(); assert.equal(calls.length,4);
});
for (const mode of ['hold','deny']) test(`${mode} blocks all external calls before and after preparation`,async()=>{
  const values=settings(); values.mandate=searchPolicy(mode);
  const calls=[],storage=new MemoryStorage(values),c=new Controller(storage,fakeFetch([],calls),HACK);
  await assert.rejects(c.prepare(signal('unresolved')),new RegExp(mode)); assert.equal(calls.length,0);
  await storage.set({mandate:searchPolicy('allow')}); await c.prepare(signal('unresolved'));
  await storage.set({mandate:searchPolicy(mode)}); await assert.rejects(c.run(),/Settings changed/); assert.equal(calls.length,0);
});
test('Missing Tavily key leaves hold intact, while non-search skill is allowed',async()=>{
  const values=settings(); values.tavilyKey=''; values.mandate=searchPolicy('hold');
  assert.equal((await decisionFor(signal('unresolved'),values)).verdict,'hold');
  assert.equal((await decisionFor(signal(),values)).verdict,'allow');
});
for (const change of [{consent:null},{providerKey:'FAKE_NEW_KEY'},{provider:'openai'},{excludedHosts:['example.com']}]) test(`Changing settings invalidates prepared request: ${Object.keys(change)[0]}`,async()=>{
  const calls=[],storage=new MemoryStorage(settings()),c=new Controller(storage,fakeFetch([],calls),HACK);
  await c.prepare(signal()); await storage.set(change); await assert.rejects(c.run(),/Settings changed/); assert.equal(calls.length,0);
});
test('No consent or provider key fails before any network call',async()=>{
  for (const change of [{consent:null},{providerKey:''}]) {
    const calls=[],c=new Controller(new MemoryStorage({...settings(),...change}),fakeFetch([],calls),HACK);
    await assert.rejects(c.prepare(signal())); assert.equal(calls.length,0);
  }
});
test('Triage SKIP, NOT ACT, FACT and malformed answers never invoke a skill',async()=>{
  for (const reply of ['SKIP','NOT ACT','FACT','SKIP because ACT is not useful','ACT\nextra']) {
    const calls=[],c=new Controller(new MemoryStorage(settings()),fakeFetch([{data:models},answer(reply)],calls),HACK);
    await c.prepare(signal()); await c.run(); const r=await c.run(); assert.equal(r.status,'SKIP'); assert.equal(c.pending,null); assert.equal(calls.length,2);
  }
  assert.equal(triageVerdict('ACT: useful comparison'),true);
});
test('Nemotron null/empty content errors match Python; nonempty length remains accepted',()=>{
  assert.throws(()=>chatText('nebius',answer(null,'length')),/truncated/);
  assert.throws(()=>chatText('nebius',answer(null)),/empty answer/);
  assert.throws(()=>chatText('nebius',{choices:[]}),/Malformed/);
  assert.throws(()=>chatText('nebius',answer({bad:1})),/Malformed/);
  assert.equal(chatText('nebius',answer('partial text','length')),'partial text');
});
test('Provider failures are explicit, single-use, and never leak keys or provider error bodies',async()=>{
  const calls=[],storage=new MemoryStorage(settings()),c=new Controller(storage,fakeFetch([new Error('NEBIUS_TEST_SECRET')],calls),HACK);
  await c.prepare(signal()); await assert.rejects(c.run(),/Provider network request failed/);
  assert.equal(c.pending,null); assert.equal(calls.length,1); assert.ok(!JSON.stringify(storage.value.trace).includes('NEBIUS_TEST_SECRET'));
  await assert.rejects(sendRequest(modelsRequest('nebius'),'secret',{storage:new MemoryStorage(settings()),build:HACK,fetchImpl:async()=>({ok:false,status:401,json:()=>{throw Error('must not read body')}})}),/HTTP 401/);
});
test('Failed audit write blocks fetch',async()=>{
  const calls=[],storage=new MemoryStorage(settings()),c=new Controller(storage,fakeFetch([],calls),HACK);
  await c.prepare(signal()); storage.failWrites=true; await assert.rejects(c.run(),/storage write failed/); assert.equal(calls.length,0);
});
test('No duplicate request during concurrent Run clicks',async()=>{
  let resolve;
  const calls=[],storage=new MemoryStorage(settings()),c=new Controller(storage,async(...args)=>{calls.push(args);await new Promise(r=>resolve=r);return {ok:true,json:async()=>({data:models})};},HACK);
  await c.prepare(signal()); const first=c.run();
  while (!resolve) await new Promise(r=>setTimeout(r,0));
  await assert.rejects(c.run(),/Prepare/); resolve(); await first; assert.equal(calls.length,1);
});
test('Network destination and redirects are restricted; timeout errors do not echo credentials',async()=>{
  await assert.rejects(sendRequest({...modelsRequest('nebius'),url:'https://evil.example'},'key',{storage:new MemoryStorage(settings()),build:HACK,fetchImpl:()=>{throw Error('must not run')}}),/not permitted/);
  await assert.rejects(sendRequest(modelsRequest('nebius'),'key',{storage:new MemoryStorage(settings()),build:HACK,timeoutMs:1,fetchImpl:(_,init)=>new Promise((_,reject)=>init.signal.addEventListener('abort',()=>reject(Error('key'))))}),/timed out/);
});
test('Shortest matching model selection mirrors Python; missing model has no fallback',()=>{
  assert.equal(resolveRole('nebius',parseModels('nebius',models),'triage'),'nvidia/nemotron-ultra'); assert.throws(()=>resolveRole('nebius',[],'triage'),/No model/);
});
test('Mandate storage validation fails closed',async()=>{
  for (const input of [null,{},[],{...searchPolicy('allow'),allow_search:'true'},{...searchPolicy('allow'),extra:1}]) assert.ok(normalizeMandate(input).error);
  const m=normalizeMandate({...searchPolicy('allow'),allowed_skills:[' Unresolved ','unresolved']}); assert.deepEqual(m.allowed_skills,['unresolved']);
  assert.equal(await mandateDigest(m),await mandateDigest({...m,allowed_skills:['unresolved']}));
  assert.ok((await getSettings(new MemoryStorage({mandate:null}))).mandate.error);
});
test('Trace retains at most 500 records for 30 days and removes expired entries',async()=>{
  const now=Date.UTC(2026,9,3),storage=new MemoryStorage({...settings(),trace:[{ts:'2020-01-01T00:00:00Z',kind:'old'},...Array.from({length:505},()=>({ts:new Date(now).toISOString(),kind:'kept'}))]});
  await appendTrace(storage,{kind:'latest'},now); assert.equal(storage.value.trace.length,TRACE_LIMIT); assert.equal(storage.value.trace.at(-1).kind,'latest');
  assert.equal((await readTrace(storage,now+31*86400000)).length,0);
});
test('Outbound minimization removes credentials, path IDs, exact times and stable hashes',()=>{
  const s=signal(); const safe=minimizeSignal(s),body=JSON.stringify(safe);
  assert.ok(!body.includes('private-ID')); assert.ok(!body.includes('SECRET')); assert.ok(!body.includes(s.key));
  assert.notEqual(safe.first_us,s.first_us); assert.equal(dateFromUs(safe.first_us),'2026-09-01');
  assert.equal(minimizeSignal({...s,host:'192.168.1.2'}).host,'[private host removed]');
  const term=scrubText('demo@example.com token=secret +82 10 1234 5678 https://example.com/private');
  for (const raw of ['demo@example.com','token=secret','1234','https://']) assert.ok(!term.includes(raw));
});
test('Known API key strings occurring in history are removed before preview and trace',async()=>{
  const s=signal('unresolved');s.term='NEBIUS_TEST_SECRET';
  const c=new Controller(new MemoryStorage(settings()),fakeFetch([{data:models}]),HACK);
  await c.prepare(s); await c.run(); assert.ok(!c.pending.request.body.includes('NEBIUS_TEST_SECRET'));
});
test('Date precision survives the 2^53 boundary and KST midnight',()=>{
  const at=isoToUs('2026-10-02T15:00:00.000000Z');
  assert.equal(dateFromUs(at-1n,true),'2026-10-02'); assert.equal(dateFromUs(at,true),'2026-10-03');
  assert.equal(isoToUs('2026-10-02T15:00:00.123456Z')-at,123456n);
  assert.equal(formatEvidence({last_visit_us:(at-1n).toString()},true),'  last visit: 2026-10-02');
});
test('History adapter uses only history search/getVisits, no titles/raw URL retention',async()=>{
  const now=Date.UTC(2026,9,3), url='https://www.google.com/search?q=portable+synth&token=SECRET';
  const calls=[];
  const fake={search:async o=>{calls.push(o);return [{url,title:'PRIVATE TITLE'}]},getVisits:async()=>[
    {visitId:'1',visitTime:now-86400000},{visitId:'2',visitTime:now-2*86400000},{visitId:'old',visitTime:now-100*86400000}]};
  const result=await readHistory(fake,{storage:new MemoryStorage(settings()),build:HACK,now});assert.equal(result.data.visits.length,2);assert.equal(result.data.searches.length,1);
  assert.equal(result.data.searches[0].term,'portable synth'); assert.equal(result.data.searches[0].first_seen_utc,'2026-10-01T00:00:00Z');
  assert.ok(!JSON.stringify(result.data).includes('PRIVATE TITLE'));assert.ok(!JSON.stringify(result.data).includes('token=SECRET'));
  const signals=await detectAll(result.data,result.options);assert.equal(signals.filter(s=>s.kind==='unresolved').length,1);
  const excluded=await readHistory(fake,{storage:new MemoryStorage(settings()),build:HACK,now,excludedHosts:['google.com']});assert.equal(excluded.data.searches.length,0);
  assert.deepEqual(await detectAll(excluded.data,excluded.options),[]);
});
test('History search saturation splits time windows and fails explicitly if still saturated',async()=>{
  let calls=0;
  const fake={search:async()=>++calls===1 ? Array.from({length:1000},()=>({url:'https://example.com'})) : [], getVisits:async()=>[]};
  await readHistory(fake,{storage:new MemoryStorage(settings()),build:HACK,now:Date.UTC(2026,9,3)});assert.equal(calls,3);
  const saturated={...fake,search:async()=>Array.from({length:1000},()=>({url:'https://example.com'}))};
  await assert.rejects(readHistory(saturated,{storage:new MemoryStorage(settings()),build:HACK,now:Date.UTC(2026,9,3),lookbackDays:1/86400000}),/limit reached/);
});
test('Unsupported URL parsing and search engines are explicit; domain suffix matching respects labels',()=>{
  assert.equal(searchTerm(new URL('https://evilgoogle.com/search?q=private')),null);
  assert.equal(searchTerm(new URL('https://search.naver.com/search.naver?query=hello')),'hello');
  assert.deepEqual(classifyHost({'example.com':['test','restricted']},'sub.EXAMPLE.com:443'),['test','restricted']);
  assert.deepEqual(classifyHost({'example.com':['test','restricted']},'notexample.com'),['unknown','none']);
});
test('A scan made before exclusions changed cannot prepare a stale signal',async()=>{
  const storage=new MemoryStorage(settings()),c=new Controller(storage,fakeFetch([]),HACK);
  await storage.set({excludedHosts:['example.com']});
  await assert.rejects(c.prepare(signal(),[]),/Excluded websites changed/);
});
test('Malformed and empty provider responses become failed audit events, never suggestions',async()=>{
  for (const response of [{choices:[]},answer(null,'length')]) {
    const storage=new MemoryStorage(settings()),c=new Controller(storage,fakeFetch([{data:models},response]),HACK);
    await c.prepare(signal());await c.run();await assert.rejects(c.run());
    assert.equal(c.pending,null);assert.equal(storage.value.trace.at(-1).kind,'request_failed');
  }
});
test('History records colliding after URL scrub match Python URL/time and search deduplication',async()=>{
  const now=Date.UTC(2026,9,3),fake={search:async()=>[
    {url:'https://www.google.com/search?q=hello&token=first'},
    {url:'https://www.google.com/search?q=hello&token=other'}],
    getVisits:async({url})=>[{visitId:url.includes('first')?'1':'2',visitTime:now-10000}]};
  const result=await readHistory(fake,{storage:new MemoryStorage(settings()),build:HACK,now});assert.equal(result.data.urls.length,1);assert.equal(result.data.visits.length,1);assert.equal(result.data.searches.length,1);
});
test('Audit boundary redacts known keys even in an invalid policy reason',async()=>{
  const storage=new MemoryStorage({...settings(),tavilyKey:'TAVILY_TEST_SECRET'});
  await appendTrace(storage,{kind:'mandate_decision',reason:'Invalid mandate: NEBIUS_TEST_SECRET',nested:{message:'TAVILY_TEST_SECRET'}});
  const trace=JSON.stringify(storage.value.trace);assert.ok(!trace.includes('NEBIUS_TEST_SECRET'));assert.ok(!trace.includes('TAVILY_TEST_SECRET'));
});
for (const deletion of ['trace','all']) test(`Deleting ${deletion} while a request is running does not resurrect its trace`,async()=>{
  let respond;
  const storage=new MemoryStorage(settings());
  const c=new Controller(storage,async()=>{await new Promise(resolve=>respond=resolve);return {ok:true,json:async()=>({data:models})};},HACK);
  await c.prepare(signal());const running=c.run();
  while (!respond) await new Promise(resolve=>setTimeout(resolve,0));
  if (deletion==='all') await storage.clear(); else await storage.remove('trace');
  respond();await assert.rejects(running,/audit record was cleared|current disclosure/);assert.equal(c.pending,null);assert.equal(storage.value.trace,undefined);
});

test('migrateSettings moves legacy Nebius only into the hackathon build and drops both legacy keys',async()=>{
  const s=new MemoryStorage({nebiusKey:'FAKE_OLD',tavilyKey:'FAKE_TAVILY'});
  await migrateSettings(s,HACK);
  assert.deepEqual([s.value.provider,s.value.providerKey,s.value.nebiusKey,s.value.tavilyKey],['nebius','FAKE_OLD',undefined,undefined]);
  const t=new MemoryStorage({nebiusKey:'FAKE_OLD',tavilyKey:'FAKE_TAVILY'});
  await migrateSettings(t,{providers:['openai','anthropic'],defaultProvider:'openai'});
  assert.deepEqual([t.value.provider,t.value.providerKey,t.value.nebiusKey,t.value.tavilyKey],['openai','',undefined,undefined]);
  await migrateSettings(s,HACK);assert.equal(s.value.providerKey,'FAKE_OLD');
});
test('research needs only mandate permission, with no Tavily key',async()=>{
  assert.equal((await decisionFor(signal('unresolved'),{mandate:searchPolicy('allow')})).verdict,'allow');
  assert.equal((await decisionFor(signal('unresolved'),{mandate:searchPolicy('hold')})).verdict,'hold');
});
test('migration redacts existing traces before erasing legacy keys',async()=>{
  const s=new MemoryStorage({...settings(),nebiusKey:'FAKE_OLD',tavilyKey:'FAKE_TAVILY',trace:[{reason:'FAKE_OLD FAKE_TAVILY',nested:{value:'NEBIUS_TEST_SECRET'}}]});
  assert.equal((await secretValues(s)).length,3);
  await migrateSettings(s,HACK);
  for(const key of ['FAKE_OLD','FAKE_TAVILY','NEBIUS_TEST_SECRET']) assert.ok(!JSON.stringify(s.value.trace).includes(key));
  assert.equal(s.value.providerKey,'NEBIUS_TEST_SECRET');
});

test('model discovery is refreshed when the selected provider or key changes',async()=>{
  const storage=new MemoryStorage({...settings(),provider:'openai',providerKey:'FAKE_OPENAI'});
  const calls=[];
  const c=new Controller(storage,async(url)=>{calls.push(url);return {ok:true,json:async()=>({data:[{id:'gpt-5'},{id:'gpt-5-mini'}]})};});
  await c.prepare(signal());await c.run();c.cancel();
  await storage.set({provider:'anthropic',providerKey:'FAKE_ANTHROPIC'});
  await c.prepare(signal());assert.equal(c.pending.stage,'models');assert.match(c.pending.request.url,/api.anthropic.com/);
  assert.equal(calls.length,1);
});
test('a missing role model fails the audited request without a follow-up request',async()=>{
  const storage=new MemoryStorage(settings()),calls=[],c=new Controller(storage,fakeFetch([{data:[{id:'unrelated-model'}]}],calls),HACK);
  await c.prepare(signal());await assert.rejects(c.run(),/No model for role triage/);
  assert.equal(c.pending,null);assert.equal(calls.length,1);assert.equal(storage.value.trace.at(-1).kind,'request_failed');
});
