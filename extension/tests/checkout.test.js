import test from 'node:test';import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';
import {documentFake} from './dom.js';
const snapshot={title:'Anua Toner 250ml',currency:'USD',totalCost:32,payNow:{total:30},dutyOnDelivery:{estimate:2}};
async function setup(reply={ok:true}) {
 const {initCheckout}=await import('../checkout.js');
 const doc=documentFake(),messages=[];
 for(const id of ['summary','checkoutForm','email','name','card','paypal','notice']) {const n=doc.createElement('div');n.id=id;doc.body.append(n);}
 const chrome={runtime:{sendMessage:async m=>{messages.push(m);return m.type==='checkout_snapshot'?{snapshot,seller:'Munteok'}:typeof reply==='function'?reply(m):reply;}}};
 await initCheckout({doc,chrome,location:{search:'?h=opaque-handle&c=0'}});
 return {doc,messages,id:id=>doc.getElementById(id)};
}
const submit=(a,method)=>a.id('checkoutForm').listeners.submit({preventDefault(){},submitter:method?a.id(method):null});
test('checkout shows the snapshot and sends buyer fields only in the buy message',async()=>{
 const a=await setup();assert.match(a.id('summary').textContent,/Anua Toner 250ml/);assert.match(a.id('summary').textContent,/32\.00/);
 assert.match(a.id('summary').textContent,/\+ est\. duty on delivery/);assert.match(a.id('summary').textContent,/Munteok/);
 a.id('email').value='buyer@example.com';a.id('name').value='Buyer Identity';await submit(a,'card');
 assert.deepEqual(a.messages,[{type:'checkout_snapshot',handle:'opaque-handle',choice:0},{type:'buy',handle:'opaque-handle',choice:0,email:'buyer@example.com',name:'Buyer Identity',method:'card'}]);
 assert.equal(a.id('email').value,'');assert.equal(a.id('name').value,'');
 await submit(a,'paypal');assert.equal(a.messages.length,2);
});
test('checkout stops on a changed quote and asks to re-check from the shop',async()=>{
 const a=await setup({error:'changed'});a.id('email').value='buyer@example.com';a.id('name').value='Buyer';await submit(a,'card');
 assert.match(a.id('notice').textContent,/Price changed — check again/);assert.equal(a.id('card').disabled,true);assert.equal(a.id('paypal').disabled,true);
});
test('checkout HTML provides extension-origin inputs and ships in the build',async()=>{
 const html=await readFile(new URL('../checkout.html',import.meta.url),'utf8');
 assert.match(html,/type="email"/);assert.match(html,/autocomplete="name"/);
 assert.match(html,/<button[^>]*id="card"[^>]*type="submit"[^>]*>Pay by card<\/button>/);
 assert.match(html,/<button[^>]*id="paypal"[^>]*type="submit"[^>]*>Pay with PayPal<\/button>/);
 assert.match(html,/If the item is out of stock in Korea, we refund you in full\./);
 const build=await readFile(new URL('../scripts/build.mjs',import.meta.url),'utf8');assert.match(build,/'checkout.html','checkout.js'/);
});
test('checkout without a selected method sends nothing and preserves buyer inputs',async()=>{
 const a=await setup();a.id('email').value='buyer@example.com';a.id('name').value='Buyer';
 await submit(a);assert.equal(a.messages.length,1);assert.equal(a.id('email').value,'buyer@example.com');
 assert.match(a.id('notice').textContent,/Choose card or PayPal/);
});
test('PayPal selection is explicit and double submits send only one buy message',async()=>{
 let finish;const pending=new Promise(resolve=>{finish=resolve;});const a=await setup(()=>pending);
 a.id('email').value='buyer@example.com';a.id('name').value='Buyer';
 const first=submit(a,'paypal');await submit(a,'card');
 assert.equal(a.messages.length,2);assert.equal(a.messages[1].method,'paypal');
 assert.equal(a.id('card').disabled,true);assert.equal(a.id('paypal').disabled,true);
 finish({ok:true});await first;
});
test('checkout rate limits show retry guidance and re-enable both payment choices',async()=>{
 const a=await setup({kind:'rate_limited'});a.id('email').value='buyer@example.com';a.id('name').value='Buyer';
 await submit(a,'paypal');assert.match(a.id('notice').textContent,/Too many checks\. Try again in a few minutes\./);
 assert.equal(a.id('card').disabled,false);assert.equal(a.id('paypal').disabled,false);
 assert.equal(a.id('email').value,'');assert.equal(a.id('name').value,'');
});
