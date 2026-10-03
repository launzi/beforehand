import test from 'node:test'; import assert from 'node:assert/strict';
import {sendRequest} from '../core/sink.js'; import {matchRequest} from '../core/match.js'; import {Store,consent,response,rpc} from './helpers.js';
const req=()=>matchRequest({name:'Anua Toner',destination:'US'});
test('sink refuses before consent and never fetches',async t=>{const f=t.mock.fn(); await assert.rejects(sendRequest(req(),{storage:new Store(),fetchImpl:f})); assert.equal(f.mock.callCount(),0);});
test('sink maps 429 to rate_limited',async()=>{await assert.rejects(sendRequest(req(),{storage:new Store(consent()),fetchImpl:async()=>({status:429})}),e=>e.code==='rate_limited');});
test('sink rejects mutations before network and omits credentials/referrer',async t=>{
 const f=t.mock.fn(async()=>response({kind:'none',message:'No listing'})); const storage=new Store(consent());
 await assert.rejects(sendRequest({...req(),url:'https://evil.test'},{storage,fetchImpl:f})); assert.equal(f.mock.callCount(),0);
 await sendRequest(req(),{storage,fetchImpl:f}); const init=f.mock.calls[0].arguments[1];
 assert.equal(init.credentials,'omit'); assert.equal(init.redirect,'error'); assert.equal(init.cache,'no-store'); assert.equal(init.referrerPolicy,'no-referrer');
});
test('sink parses SSE and rejects consent revoked while in flight',async()=>{
 const storage=new Store(consent());
 const r=await sendRequest(req(),{storage,fetchImpl:async()=>({ok:true,headers:{get:()=> 'text/event-stream'},text:async()=>`event: message\ndata: ${JSON.stringify(rpc({kind:'none',message:'No listing'}))}\n\n`})}); assert.equal(r.kind,'none');
 await assert.rejects(sendRequest(req(),{storage,fetchImpl:async()=>{await storage.clear();return response({kind:'none',message:'No listing'});}}));
});
test('sink contains transport and parsing failures',async()=>{
 for(const f of [async()=>{throw Error('private network error');},async()=>({ok:false,status:500}),async()=>({ok:true,json:async()=>{throw Error('bad JSON');}})]) await assert.rejects(sendRequest(req(),{storage:new Store(consent()),fetchImpl:f}),e=>['unavailable','malformed'].includes(e.code));
});
test('revocation and re-acceptance cannot revive an old response',async()=>{
 const {acceptConsent,deleteAllData}=await import('../core/storage.js'); const storage=new Store(); await acceptConsent(storage,{autoCheck:true});
 await assert.rejects(sendRequest(req(),{storage,fetchImpl:async()=>{await deleteAllData(storage);await acceptConsent(storage,{autoCheck:true});return response({kind:'none',message:'No listing'});}}));
});
