// extension/tests/providers.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import {isPermitted,sendRequest} from '../core/providers.js';
import {chatRequest,modelsRequest} from '../core/llm.js';
import {researchRequest} from '../core/research.js';
import {quoteRequest} from '../core/korea-quote.js';
import {DISCLOSURE_VERSION} from '../core/storage.js';
const store={providers:['openai','anthropic']}, hack={providers:['nebius']};
const consented={async get(){return {consent:{accepted:true,version:DISCLOSURE_VERSION}};}};
test('allow list follows the build',()=>{
  assert.ok(isPermitted(chatRequest('openai',{model:'m',role:'skill',prompt:'p',maxTokens:1}),store));
  assert.ok(!isPermitted(chatRequest('nebius',{model:'m',role:'skill',prompt:'p',maxTokens:1}),store));
  assert.ok(isPermitted(modelsRequest('nebius'),hack));
  assert.ok(!isPermitted(modelsRequest('openai'),hack));
  assert.ok(isPermitted(researchRequest('a query'),store) && isPermitted(quoteRequest('Cuckoo rice cooker','US'),hack));
  assert.ok(!isPermitted({provider:'openai',url:'https://evil.example/v1/chat/completions',method:'POST',body:'{}'},store));
});
test('sendRequest blocks before fetch when not permitted and attaches adapter headers when permitted',async()=>{
  let calls=[];
  const fetchImpl=async(url,init)=>{calls.push({url,init});return {ok:true,status:200,headers:{get:()=>'application/json'},json:async()=>({choices:[{message:{content:'x'},finish_reason:'stop'}]})};};
  await assert.rejects(sendRequest(chatRequest('nebius',{model:'m',role:'skill',prompt:'p',maxTokens:1}),'FAKE_KEY',{storage:consented,fetchImpl,build:store}),/not permitted/);
  assert.equal(calls.length,0);
  await sendRequest(chatRequest('anthropic',{model:'m',role:'skill',prompt:'p',maxTokens:1}),'FAKE_KEY',{storage:consented,fetchImpl,build:store});
  assert.equal(calls[0].init.headers['x-api-key'],'FAKE_KEY'); assert.equal(calls[0].init.credentials,'omit'); assert.equal(calls[0].init.redirect,'error');
  assert.equal(calls[0].init.headers.Authorization,undefined);
});
test('KC requests carry no API key header',async()=>{
  let seen;
  const fetchImpl=async(url,init)=>{seen=init;return {ok:true,status:200,headers:{get:()=>'application/json'},json:async()=>({jsonrpc:'2.0',id:1,result:{structuredContent:{results:[]}}})};};
  const hits=await sendRequest(researchRequest('a query'),'',{storage:consented,fetchImpl,build:store});
  assert.deepEqual(hits,[]); assert.equal(seen.headers.Authorization,undefined); assert.equal(seen.headers['x-api-key'],undefined);
});
test('KC endpoint HTTP 429 becomes the distinct research rate limit without reading its body',async()=>{
  const {ResearchRateLimitError}=await import('../core/research.js');
  const raw={jsonrpc:'2.0',id:1,error:{code:-32000,message:'SERVER_PRIVATE_QUERY'}};
  let reads=0;
  await assert.rejects(sendRequest(researchRequest('a query'),'',{storage:consented,fetchImpl:async()=>({ok:false,status:429,json:async()=>{reads++;return raw;}})}),ResearchRateLimitError);
  assert.equal(reads,0);
});
