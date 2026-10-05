import test from 'node:test'; import assert from 'node:assert/strict';
import {sendRequest} from '../core/sink.js'; import {matchRequest,checkoutRequest} from '../core/match.js'; import {Store,consent,response,rpc} from './helpers.js';
const req=()=>matchRequest({name:'Anua Toner',destination:'US'});
test('sink refuses before consent and never fetches',async t=>{const f=t.mock.fn(); await assert.rejects(sendRequest(req(),{storage:new Store(),fetchImpl:f})); assert.equal(f.mock.callCount(),0);});
test('sink maps 429 to rate_limited',async()=>{
 for(const request of [req(),checkoutRequest({quoteToken:'FAKE_TOKEN_12345',email:'buyer@example.com',name:'Buyer',method:'paypal'})]) {
  await assert.rejects(sendRequest(request,{storage:new Store(consent()),fetchImpl:async()=>({status:429,json:async()=>{throw Error('must not parse rate-limit body');}})}),e=>e.code==='rate_limited' && e.message==='Too many checks. Try again in a few minutes.');
 }
});
test('sink rejects mutations before network and omits credentials/referrer',async t=>{
 const f=t.mock.fn(async()=>response({kind:'none',message:'No listing'})); const storage=new Store(consent());
 await assert.rejects(sendRequest({...req(),url:'https://evil.test'},{storage,fetchImpl:f})); assert.equal(f.mock.callCount(),0);
 await sendRequest(req(),{storage,fetchImpl:f}); const init=f.mock.calls[0].arguments[1];
 assert.equal(init.credentials,'omit'); assert.equal(init.redirect,'error'); assert.equal(init.cache,'no-store'); assert.equal(init.referrerPolicy,'no-referrer');
 assert.deepEqual(init.headers,{'Content-Type':'application/json',Accept:'application/json'});
});
test('sink parses plain JSON and rejects consent revoked while in flight',async()=>{
 const storage=new Store(consent());
 const r=await sendRequest(req(),{storage,fetchImpl:async()=>response({kind:'none',message:'No listing'})}); assert.equal(r.kind,'none');
 await assert.rejects(sendRequest(req(),{storage,fetchImpl:async()=>({ok:true,headers:{get:()=> 'text/event-stream'},text:async()=>`event: message\ndata: ${JSON.stringify(rpc({kind:'none',message:'No listing'}))}\n\n`})}),e=>e.code==='malformed');
 await assert.rejects(sendRequest(req(),{storage,fetchImpl:async()=>{await storage.clear();return response({kind:'none',message:'No listing'});}}));
});
test('partner API errors never return payment links or server details',async()=>{
 const checkout=checkoutRequest({quoteToken:'FAKE_TOKEN_12345',email:'buyer@example.com',name:'Buyer',method:'paypal'});
 for(const status of [400,422,502]) await assert.rejects(sendRequest(checkout,{storage:new Store(consent()),fetchImpl:async()=>({ok:false,status,json:async()=>({message:'private',method:'paypal',url:'https://www.paypal.com/pay'})})}),e=>e.code==='unavailable' && !e.message.includes('private'));
});
test('sink permits only exact partner paths and validated POST bodies',async t=>{
 const f=t.mock.fn();
 for(const url of ['https://concierge.youngji.kim/api/mcp','https://concierge.youngji.kim/api/commerce/v1/matches/','https://concierge.youngji.kim/api/commerce/v1/curation/events','https://concierge.youngji.kim/api/commerce/v1/quotes']) {
  await assert.rejects(sendRequest({...req(),url},{storage:new Store(consent()),fetchImpl:f}),e=>e.code==='malformed');
 }
 await assert.rejects(sendRequest({...req(),method:'GET'},{storage:new Store(consent()),fetchImpl:f}),e=>e.code==='malformed');
 assert.equal(f.mock.callCount(),0);
});
test('sink contains transport and parsing failures',async()=>{
 for(const f of [async()=>{throw Error('private network error');},async()=>({ok:false,status:500}),async()=>({ok:true,json:async()=>{throw Error('bad JSON');}})]) await assert.rejects(sendRequest(req(),{storage:new Store(consent()),fetchImpl:f}),e=>['unavailable','malformed'].includes(e.code));
});
test('revocation and re-acceptance cannot revive an old response',async()=>{
 const {acceptConsent,deleteAllData}=await import('../core/storage.js'); const storage=new Store(); await acceptConsent(storage,{autoCheck:true});
 await assert.rejects(sendRequest(req(),{storage,fetchImpl:async()=>{await deleteAllData(storage);await acceptConsent(storage,{autoCheck:true});return response({kind:'none',message:'No listing'});}}));
});
