// extension/tests/research.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import {researchRequest,validResearchRequest,parseResearchRPC,ResearchError,ResearchRateLimitError} from '../core/research.js';
import {KC_ENDPOINT} from '../core/korea-quote.js';
test('research request is a strict JSON-RPC call to KC with only a scrubbed query',()=>{
  const r=researchRequest('portable synthesizer comparison');
  assert.equal(r.url,KC_ENDPOINT); assert.equal(r.provider,'kc');
  assert.deepEqual(JSON.parse(r.body),{jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'research_briefing',arguments:{query:'portable synthesizer comparison'}}});
  assert.ok(validResearchRequest(r));
});
test('validator rejects extra fields, URLs, long or blank queries',()=>{
  const body=q=>({provider:'kc',url:KC_ENDPOINT,method:'POST',body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'research_briefing',arguments:q}})});
  assert.equal(validResearchRequest(body({query:'ok query',extra:1})),false);
  assert.equal(validResearchRequest(body({query:'see https://x.example/a'})),false);
  assert.equal(validResearchRequest(body({query:'x'.repeat(201)})),false);
  assert.equal(validResearchRequest(body({query:' '})),false);
  assert.throws(()=>researchRequest('https://x.example'),ResearchError);
});
test('parser accepts structuredContent or single text block, caps at 5, drops non-https links',()=>{
  const items=Array.from({length:7},(_,i)=>({title:'t'+i,url:'https://r.example/'+i,snippet:'s'}));
  assert.equal(parseResearchRPC({result:{structuredContent:{results:items}}}).length,5);
  const one=parseResearchRPC({result:{content:[{type:'text',text:JSON.stringify({results:[{title:'a',url:'javascript:alert(1)',snippet:'b'}]})}]}});
  assert.equal(one[0].url,'');
  assert.throws(()=>parseResearchRPC({error:{code:-32000,message:'Rate limit exceeded'}}),/Research unavailable/);
  assert.throws(()=>parseResearchRPC({result:{isError:true,content:[]}}),/Research unavailable/);
});
for (const encoding of ['structuredContent','text']) for (const code of ['rate_limited','research_unavailable','unknown']) {
  test(`business error ${code} in ${encoding} wins over results and hides server text`,()=>{
    const data={error:code,message:'SERVER_MESSAGE_PRIVATE_QUERY',results:[]};
    const result=encoding==='structuredContent' ? {structuredContent:data,content:[{type:'text',text:JSON.stringify(data)}]}
      : {content:[{type:'text',text:JSON.stringify(data)}]};
    assert.throws(()=>parseResearchRPC({result}),error=>{
      assert.ok(error instanceof ResearchError);
      assert.equal(error instanceof ResearchRateLimitError,code==='rate_limited');
      assert.equal(error.message,code==='rate_limited'?'Rate limit exceeded':'Research unavailable');
      return true;
    });
  });
}
test('input validation isError is unavailable even with apparent results or a rate code',()=>{
  assert.throws(()=>parseResearchRPC({result:{isError:true,structuredContent:{error:'rate_limited',results:[]},content:[{type:'text',text:'SERVER_PRIVATE_QUERY'}]}}),
    error=>error instanceof ResearchError && !(error instanceof ResearchRateLimitError) && error.message==='Research unavailable');
});
