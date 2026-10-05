import test from 'node:test'; import assert from 'node:assert/strict';
import * as api from '../core/match.js';
import {quote,rpc} from './helpers.js';
const {matchRequest,checkoutRequest,validRequest,sanitizeQuote}=api;
const base='https://concierge.youngji.kim/api/commerce/v1';
test('matchRequest sends only name, brand, destination',()=>{
 const r=matchRequest({name:'Anua Toner 250ml',brand:'Anua',destination:'GB',url:'https://private.example',price:99});
 assert.deepEqual(r,{kind:'match',url:base+'/matches',method:'POST',body:JSON.stringify({name:'Anua Toner 250ml',brand:'Anua',destination:'GB'})});
 assert.equal(validRequest(r),true); assert.ok(Object.isFrozen(r));
 assert.doesNotMatch(r.body,/jsonrpc|tools\/call|params/);
});
test('validRequest rejects tampered shapes at every level',()=>{
 const r=matchRequest({name:'Anua Toner',destination:'US'});
 for(const t of [{...r,url:'https://evil.example/api/commerce/v1/matches'},{...r,headers:{}},{...r,body:r.body.replace('"US"','"US","url":"https://x"')},{...r,url:base+'/checkout'},{...r,kind:'other'},{...r,method:'GET'},{...r,url:base+'/matches?extra=1'},{...r,body:JSON.stringify(rpc({name:'Anua Toner',destination:'US'}))},{...r,body:r.body.replace('"name":"Anua Toner"','"name":"https://x"')}]) assert.equal(validRequest(t),false);
});
test('names, brands, destinations and fresh are validated',()=>{
 for(const name of ['x','http product','www.x','x'.repeat(201)]) assert.throws(()=>matchRequest({name,destination:'US'}));
 assert.throws(()=>matchRequest({name:'Toner',destination:'UK'})); assert.throws(()=>matchRequest({name:'Toner',destination:'GB',brand:'x'.repeat(81)}));
 assert.throws(()=>matchRequest({name:'Toner',destination:'GB',fresh:'true'}));
 assert.deepEqual(JSON.parse(matchRequest({name:'Toner',destination:'GB',fresh:true}).body),{name:'Toner',destination:'GB',fresh:true});
});
test('checkout args and payment URLs are restricted',()=>{
 for(const method of ['card','paypal']) {
  const input={quoteToken:'FAKE_TOKEN_12345',email:'buyer@example.com',name:'Buyer',method};
  const r=checkoutRequest({...input,url:'https://private.example',returnUrl:'https://extra.example'});
  assert.deepEqual(r,{kind:'checkout',url:base+'/checkout',method:'POST',body:JSON.stringify(input)});
  assert.ok(validRequest(r));
  assert.equal(validRequest({...r,body:JSON.stringify({...input,extra:'private'})}),false);
 }
 for(const method of [undefined,null,'stripe','cash','',false]) assert.throws(()=>checkoutRequest({quoteToken:'FAKE_TOKEN_12345',email:'buyer@example.com',name:'Buyer',method}));
 for(const url of ['http://checkout.stripe.com/a','https://evil.example/pay','https://checkout.stripe.com.evil.test/a','https://user@checkout.stripe.com/a','https://checkout.stripe.com:444/a','https://www.paypal.com.evil.test/a','https://paypal.com/a','javascript:alert(1)','https://www.paypal.com@evil.test/a']) assert.throws(()=>api.parseCheckoutResponse({method:'card',url}),e=>e.code==='malformed');
 for(const [method,url] of [['card','https://checkout.stripe.com/c/pay/cs_x'],['paypal','https://www.paypal.com/checkoutnow?token=FAKE'],['paypal','https://www.sandbox.paypal.com/checkoutnow?token=FAKE']]) {
  assert.deepEqual(api.parseCheckoutResponse({method,url,orderId:'FAKE_ORDER',secret:'discard'}),{method,url,orderId:'FAKE_ORDER'});
  assert.deepEqual(api.parseCheckoutResponse({method,url}),{method,url});
 }
 for(const raw of [null,{},rpc({checkoutUrl:'https://checkout.stripe.com/c/pay/cs_x'}),{method:'cash',url:'https://checkout.stripe.com/c/pay/cs_x'},{method:'card',url:'https://checkout.stripe.com/c/pay/cs_x',orderId:42}]) assert.throws(()=>api.parseCheckoutResponse(raw),e=>e.code==='malformed');
 assert.throws(()=>checkoutRequest({quoteToken:'short',email:'bad',name:'',method:'card'}));
});
test('parseMatchResponse accepts verdict null and optional token',()=>{
 const q=quote(); delete q.quoteToken; delete q.quoteExpiresAt;
 assert.equal(api.parseMatchResponse({kind:'same',quote:q}).quote.verdict,null);
 assert.equal(sanitizeQuote(quote({item:{title:'see https://listing.example',priceKrw:1,link:'javascript:alert(1)'}})).item.link,null);
});
test('alternatives keep at most two and never preserve arbitrary fields',()=>{
 const r=api.parseMatchResponse({kind:'alternatives',items:Array.from({length:3},()=>({title:'Toner',why:'Heartleaf toner',quote:quote({secret:'discard'})}))});
 assert.equal(r.items.length,2); assert.equal(r.items[0].quote.secret,undefined);
});
test('RPC envelopes, invalid amounts, malformed results fail closed',()=>{
 for(const raw of [{kind:'same',quote:quote({totalCost:-1})},{kind:'same',quote:{}},{kind:'unknown'},{result:{isError:true}},{kind:'alternatives',items:[]},rpc({kind:'none',message:'No listing'}),null]) assert.throws(()=>api.parseMatchResponse(raw),e=>e.code==='malformed');
 for(const kind of ['unavailable','rate_limited']) assert.throws(()=>api.parseMatchResponse({kind,message:'private'}),e=>e.code===kind&&!e.message.includes('private'));
 for(const kind of ['none','cant_ship']) assert.equal(api.parseMatchResponse({kind,message:'No listing'}).kind,kind);
});
test('product fields with embedded identity are rejected before they leave the device',()=>{
 assert.throws(()=>matchRequest({name:'Personal order buyer@example.com',destination:'US'}));
 assert.throws(()=>matchRequest({name:'Toner',brand:'buyer@example.com',destination:'US'}));
});
test('checkout response URLs must be strings rather than URL-coercible values',()=>{
 for(const url of [['https://checkout.stripe.com/c/pay/FAKE'],{toString:()=> 'https://www.paypal.com/pay'},42]) {
  assert.throws(()=>api.parseCheckoutResponse({method:'card',url}),e=>e.code==='malformed');
 }
});
test('display fields parse leniently and never break an older response',async()=>{
 const {parseMatchResponse}=await import('../core/match.js');const {quote}=await import('./helpers.js');
 const same=parseMatchResponse({kind:'same',quote:quote(),titleEn:' LANEIGE Water Sleeping Mask 70ml ',matchPercent:95.6,size:{value:70,unit:'ml'},source:{brand:'LANEIGE',typeEn:'Sleeping mask',size:{value:70,unit:'ml'}}});
 assert.equal(same.titleEn,'LANEIGE Water Sleeping Mask 70ml');assert.equal(same.matchPercent,96);assert.deepEqual(same.source,{brand:'LANEIGE',typeEn:'Sleeping mask',size:{value:70,unit:'ml'}});
 const bad=parseMatchResponse({kind:'same',quote:quote(),titleEn:42,matchPercent:140,size:{value:-1,unit:'ml'},source:'x'});
 assert.deepEqual([bad.titleEn,bad.matchPercent,bad.size,bad.source],[null,null,null,{brand:null,typeEn:null,size:null}]);
 const old=parseMatchResponse({kind:'alternatives',items:[{title:'Toner',why:'x',quote:quote()}]});
 assert.deepEqual([old.items[0].titleEn,old.items[0].sameBrand,old.items[0].sameType,old.items[0].size],[null,null,null,null]);
 const alt=parseMatchResponse({kind:'alternatives',source:{brand:'Anua'},items:[{title:'Toner',why:'x',quote:quote(),titleEn:'Round Lab Toner 200ml',sameBrand:false,sameType:true,size:{value:200,unit:'ml'}}]});
 assert.deepEqual([alt.items[0].sameBrand,alt.items[0].sameType,alt.items[0].size.value,alt.source.brand],[false,true,200,'Anua']);
});
