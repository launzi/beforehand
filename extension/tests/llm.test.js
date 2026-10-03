// extension/tests/llm.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import {modelsRequest,parseModels,resolveRole,chatRequest,chatText,authHeaders,LLMError} from '../core/llm.js';
test('openai: chat completions body, bearer auth, no /no_think',()=>{
  const r=chatRequest('openai',{model:'gpt-5-mini',role:'skill',prompt:' hi ',system:'S',maxTokens:300});
  assert.equal(r.url,'https://api.openai.com/v1/chat/completions');
  const b=JSON.parse(r.body);
  assert.deepEqual(b.messages,[{role:'system',content:'S'},{role:'user',content:'hi'}]);
  assert.equal(b.max_completion_tokens,300); assert.equal(b.stream,false); assert.ok(!r.body.includes('/no_think'));
  assert.deepEqual(authHeaders('openai','FAKE_KEY'),{Authorization:'Bearer FAKE_KEY'});
});
test('anthropic: messages body with top-level system and browser-access headers',()=>{
  const r=chatRequest('anthropic',{model:'claude-haiku-4-5',role:'skill',prompt:'hi',system:'S',maxTokens:300});
  const b=JSON.parse(r.body);
  assert.equal(b.system,'S'); assert.deepEqual(b.messages,[{role:'user',content:'hi'}]); assert.equal(b.max_tokens,300);
  assert.deepEqual(authHeaders('anthropic','FAKE_KEY'),{'x-api-key':'FAKE_KEY','anthropic-version':'2023-06-01','anthropic-dangerous-direct-browser-access':'true'});
});
test('nebius keeps /no_think for skill role and not for triage',()=>{
  const skill=JSON.parse(chatRequest('nebius',{model:'nvidia/nemotron-nano',role:'skill',prompt:'p',system:'S',maxTokens:10}).body);
  assert.equal(skill.messages[0].content,'S\n\n/no_think'); assert.equal(skill.max_tokens,10);
  const tri=JSON.parse(chatRequest('nebius',{model:'nvidia/nemotron-ultra',role:'triage',prompt:'p',system:'S',maxTokens:10}).body);
  assert.equal(tri.messages[0].content,'S');
});
test('models: parse and resolve by preference order; no silent fallback',()=>{
  assert.deepEqual(modelsRequest('anthropic'),{provider:'anthropic',url:'https://api.anthropic.com/v1/models',method:'GET',body:null});
  const ids=parseModels('openai',{data:[{id:'gpt-4.1-mini'},{id:'gpt-5-mini'},{id:'gpt-5'}]});
  assert.equal(resolveRole('openai',ids,'skill'),'gpt-5-mini');
  assert.equal(resolveRole('openai',ids,'triage'),'gpt-5');
  assert.throws(()=>resolveRole('openai',['davinci'],'triage'),LLMError);
  assert.throws(()=>parseModels('openai',{data:'x'}),LLMError);
});
test('chatText rejects empty or truncated-empty answers for every provider',()=>{
  assert.equal(chatText('openai',{choices:[{message:{content:'ok'},finish_reason:'stop'}]}),'ok');
  assert.throws(()=>chatText('openai',{choices:[{message:{content:''},finish_reason:'length'}]}),LLMError);
  assert.equal(chatText('anthropic',{content:[{type:'text',text:'a'},{type:'text',text:'b'}],stop_reason:'end_turn'}),'ab');
  assert.throws(()=>chatText('anthropic',{content:[],stop_reason:'max_tokens'}),LLMError);
  assert.throws(()=>chatText('nebius',{choices:[{message:{content:'  '},finish_reason:'stop'}]}),LLMError);
});
test('blank prompt is rejected',()=>{
  assert.throws(()=>chatRequest('openai',{model:'m',role:'skill',prompt:'  ',maxTokens:1}),LLMError);
});
