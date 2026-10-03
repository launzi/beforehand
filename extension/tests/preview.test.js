// extension/tests/preview.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import {describeRequest} from '../core/preview.js';
import {quoteRequest} from '../core/korea-quote.js';
import {researchRequest} from '../core/research.js';
import {chatRequest} from '../core/llm.js';
test('quote preview: destination KC, sends product and country, never lists URLs and times',()=>{
  const d=describeRequest(quoteRequest('Cuckoo rice cooker 6-cup','US'));
  assert.equal(d.destination.kind,'quote'); assert.equal(d.destination.host,'concierge.youngji.kim');
  assert.deepEqual(d.sends,[{field:'product',value:'Cuckoo rice cooker 6-cup'},{field:'destination',value:'US'}]);
  assert.ok(d.never.includes('product URL') && d.never.includes('visit times'));
});
test('research preview sends only the query',()=>{
  assert.deepEqual(describeRequest(researchRequest('portable synthesizer')).sends,[{field:'query',value:'portable synthesizer'}]);
});
test('ai preview names the provider and shows the prompt as the sent field',()=>{
  const d=describeRequest(chatRequest('anthropic',{model:'claude-haiku-4-5',role:'skill',prompt:'Summarize: x',system:'S',maxTokens:5}));
  assert.equal(d.destination.kind,'ai'); assert.equal(d.destination.label,'Claude');
  assert.ok(d.sends.some(s=>s.field==='prompt' && s.value.includes('Summarize')));
});
test('preview refuses a request whose body leaks a never item',()=>{
  const leaky=chatRequest('openai',{model:'gpt-5-mini',role:'skill',prompt:'visited the page at 2026-10-01T10:00:00Z',maxTokens:5});
  assert.throws(()=>describeRequest(leaky),/Preview invariant violated: visit times/);
});
test('AI skill prompts may carry public search-result URLs after research',()=>{
  const ok=chatRequest('openai',{model:'gpt-5-mini',role:'skill',prompt:'Hits:\n1. Review\n   https://review.example/item\n   snippet',maxTokens:5});
  assert.equal(describeRequest(ok).destination.kind,'ai');
});

test('KC URL leaks and timestamps anywhere in a body prevent preview',()=>{
  const q=quoteRequest('Cuckoo rice cooker','US'), raw=JSON.parse(q.body);
  raw.params.arguments.product='Cuckoo https://private.example/item';
  assert.throws(()=>describeRequest({...q,body:JSON.stringify(raw)}),/Preview invariant violated: product URL/);
  const r=researchRequest('portable synth'), body=JSON.parse(r.body);
  body.params.arguments.query='see https://private.example';
  assert.throws(()=>describeRequest({...r,body:JSON.stringify(body)}),/Preview invariant violated: URLs/);
  const ai=chatRequest('anthropic',{model:'m',role:'skill',prompt:'p',system:'Visited 2026-10-01T10:00:00Z',maxTokens:5});
  assert.throws(()=>describeRequest(ai),/Preview invariant violated: visit times/);
});
