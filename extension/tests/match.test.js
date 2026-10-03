import test from 'node:test'; import assert from 'node:assert/strict';
import {matchRequest,checkoutRequest,validRequest,parseMatchRPC,parseCheckoutRPC,sanitizeQuote} from '../core/match.js';
import {quote,rpc} from './helpers.js';
test('matchRequest sends only name, brand, destination',()=>{
 const r=matchRequest({name:'Anua Toner 250ml',brand:'Anua',destination:'GB',url:'https://private.example',price:99});
 assert.deepEqual(JSON.parse(r.body).params.arguments,{name:'Anua Toner 250ml',brand:'Anua',destination:'GB'}); assert.equal(validRequest(r),true); assert.ok(Object.isFrozen(r));
});
test('validRequest rejects tampered shapes at every level',()=>{
 const r=matchRequest({name:'Anua Toner',destination:'US'});
 for(const t of [{...r,url:'https://evil.example/api/mcp'},{...r,headers:{}},{...r,body:r.body.replace('"US"','"US","url":"https://x"')},{...r,body:r.body.replace('match_korea_product','place_order')},{...r,body:r.body.replace('"id":1','"id":2')},{...r,body:r.body.replace('"name":"Anua Toner"','"name":"https://x"')}]) assert.equal(validRequest(t),false);
});
test('names, brands, destinations and fresh are validated',()=>{
 for(const name of ['x','http product','www.x','x'.repeat(201)]) assert.throws(()=>matchRequest({name,destination:'US'}));
 assert.throws(()=>matchRequest({name:'Toner',destination:'UK'})); assert.throws(()=>matchRequest({name:'Toner',destination:'GB',brand:'x'.repeat(81)}));
 assert.equal(JSON.parse(matchRequest({name:'Toner',destination:'GB',fresh:true}).body).params.arguments.fresh,true);
});
test('checkout args and Stripe URL are restricted',()=>{
 assert.ok(validRequest(checkoutRequest({quoteToken:'FAKE_TOKEN_12345',email:'buyer@example.com',name:'Buyer'})));
 for(const url of ['http://checkout.stripe.com/a','https://evil.example/pay','https://checkout.stripe.com.evil.test/a','https://user@checkout.stripe.com/a']) assert.throws(()=>parseCheckoutRPC(rpc({checkoutUrl:url})));
 assert.equal(parseCheckoutRPC(rpc({checkoutUrl:'https://checkout.stripe.com/c/pay/cs_x'})).checkoutUrl,'https://checkout.stripe.com/c/pay/cs_x');
 assert.throws(()=>checkoutRequest({quoteToken:'short',email:'bad',name:''}));
});
test('parseMatchRPC accepts verdict null and optional token',()=>{
 const q=quote(); delete q.quoteToken; delete q.quoteExpiresAt;
 assert.equal(parseMatchRPC(rpc({kind:'same',quote:q})).quote.verdict,null);
 assert.equal(sanitizeQuote(quote({item:{title:'see https://listing.example',priceKrw:1,link:'javascript:alert(1)'}})).item.link,null);
});
test('alternatives keep at most two and never preserve arbitrary fields',()=>{
 const r=parseMatchRPC(rpc({kind:'alternatives',items:Array.from({length:3},()=>({title:'Toner',why:'Heartleaf toner',quote:quote({secret:'discard'})}))}));
 assert.equal(r.items.length,2); assert.equal(r.items[0].quote.secret,undefined);
});
test('RPC errors, invalid amounts, malformed results fail closed',()=>{
 for(const raw of [rpc({kind:'same',quote:quote({totalCost:-1})}),rpc({kind:'same',quote:{}}),rpc({kind:'unknown'}),{result:{isError:true}},rpc({kind:'alternatives',items:[]})]) assert.throws(()=>parseMatchRPC(raw));
 for(const kind of ['unavailable','rate_limited']) assert.throws(()=>parseMatchRPC(rpc({kind,message:'private'})),e=>e.code===kind&&!e.message.includes('private'));
 assert.equal(parseMatchRPC({result:{content:[{type:'text',text:JSON.stringify({kind:'none',message:'No listing'})}]}}).kind,'none');
});
