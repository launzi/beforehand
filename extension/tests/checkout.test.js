import test from 'node:test';import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';
import {documentFake} from './dom.js';
const snapshot={title:'Anua Toner 250ml',currency:'USD',totalCost:32,payNow:{total:30},dutyOnDelivery:{estimate:2}};
async function setup(reply={ok:true}) {
 const {initCheckout}=await import('../checkout.js');
 const doc=documentFake(),messages=[];
 for(const id of ['summary','checkoutForm','email','name','continue','notice']) {const n=doc.createElement('div');n.id=id;doc.body.append(n);}
 const chrome={runtime:{sendMessage:async m=>{messages.push(m);return m.type==='checkout_snapshot'?{snapshot,seller:'Munteok'}:reply;}}};
 await initCheckout({doc,chrome,location:{search:'?h=opaque-handle&c=0'}});
 return {doc,messages,id:id=>doc.getElementById(id)};
}
test('checkout shows the snapshot and sends buyer fields only in the buy message',async()=>{
 const a=await setup();assert.match(a.id('summary').textContent,/Anua Toner 250ml/);assert.match(a.id('summary').textContent,/32\.00/);
 assert.match(a.id('summary').textContent,/\+ est\. duty on delivery/);assert.match(a.id('summary').textContent,/Munteok/);
 a.id('email').value='buyer@example.com';a.id('name').value='Buyer Identity';await a.id('checkoutForm').fire('submit');
 assert.deepEqual(a.messages,[{type:'checkout_snapshot',handle:'opaque-handle',choice:0},{type:'buy',handle:'opaque-handle',choice:0,email:'buyer@example.com',name:'Buyer Identity'}]);
 assert.equal(a.id('email').value,'');assert.equal(a.id('name').value,'');
 await a.id('checkoutForm').fire('submit');assert.equal(a.messages.length,2);
});
test('checkout stops on a changed quote and asks to re-check from the shop',async()=>{
 const a=await setup({error:'changed'});a.id('email').value='buyer@example.com';a.id('name').value='Buyer';await a.id('checkoutForm').fire('submit');
 assert.match(a.id('notice').textContent,/Price changed — check again/);assert.equal(a.id('continue').disabled,true);
});
test('checkout HTML provides extension-origin inputs and ships in the build',async()=>{
 const html=await readFile(new URL('../checkout.html',import.meta.url),'utf8');
 assert.match(html,/type="email"/);assert.match(html,/autocomplete="name"/);assert.match(html,/Continue to payment/);
 const build=await readFile(new URL('../scripts/build.mjs',import.meta.url),'utf8');assert.match(build,/'checkout.html','checkout.js'/);
});
