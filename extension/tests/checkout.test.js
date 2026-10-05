import test from 'node:test';import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';
import {documentFake} from './dom.js';
const snapshot={title:'Anua Toner 250ml',currency:'USD',totalCost:32,payNow:{total:30,itemKrw:18000,shippingKrw:18000,serviceFeeKrw:4000,paymentFeeKrw:2000,fxRate:1400},dutyOnDelivery:{estimate:2}};
const NOW=Date.parse('2026-10-05T09:00:00Z');
async function setup(reply={ok:true},shown={snapshot,expiresAt:'2026-10-05T09:29:41Z',seller:'Munteok',destination:'US'}) {
 const {initCheckout}=await import('../checkout.js');
 const doc=documentFake(),messages=[],timers=[];
 for(const id of ['summary','checkoutForm','email','name','methodCard','methodPaypal','pay','switchMethod','provider','error','notice','expiry']) {const n=doc.createElement('div');n.id=id;doc.body.append(n);}
 doc.getElementById('methodCard').checked=true;
 const chrome={runtime:{sendMessage:async m=>{messages.push(m);return m.type==='checkout_snapshot'?shown:typeof reply==='function'?reply(m):reply;}}};
 await initCheckout({doc,chrome,location:{search:'?h=opaque-handle&c=0'},now:()=>NOW,setInterval:fn=>{timers.push(fn);return timers.length;},clearInterval:()=>{}});
 return {doc,messages,timers,id:id=>doc.getElementById(id)};
}
const submit=a=>a.id('checkoutForm').listeners.submit({preventDefault(){}});
const fill=a=>{a.id('email').value='buyer@example.com';a.id('name').value='Buyer Identity';};
test('receipt shows KRW lines, pay now with rate, estimated duty and estimated total',async()=>{
 const a=await setup(),text=a.id('summary').textContent;
 for(const s of ['Korea → United States','Anua Toner 250ml','Sold by Munteok','International shipping','₩18,000','₩4,000','₩2,000','$1 = ₩1,400','$30.00','Estimated duty · pay on delivery','$2.00','Estimated total','$32.00']) assert.ok(text.includes(s),s);
 assert.doesNotMatch(text,/Delivered|EMS/);
 assert.equal(a.id('expiry').textContent,'Quote expires in 29:41');assert.equal(a.id('pay').disabled,false);
});
test('buyer fields and the chosen method go only in the buy message and stay filled',async()=>{
 const a=await setup();fill(a);await submit(a);
 assert.deepEqual(a.messages,[{type:'checkout_snapshot',handle:'opaque-handle',choice:0},{type:'buy',handle:'opaque-handle',choice:0,email:'buyer@example.com',name:'Buyer Identity',method:'card'}]);
 assert.equal(a.id('pay').textContent,'Opening Stripe…');
});
test('PayPal selection changes the opening label, the switch link and the buy method',async()=>{
 let finish;const pending=new Promise(r=>{finish=r;});const a=await setup(()=>pending);
 a.id('methodCard').checked=false;a.id('methodPaypal').checked=true;await a.id('methodPaypal').fire('change');
 assert.equal(a.id('switchMethod').textContent,'Use card instead');
 fill(a);const first=submit(a);await submit(a);
 assert.equal(a.messages.length,2);assert.equal(a.messages[1].method,'paypal');assert.equal(a.id('pay').textContent,'Opening PayPal…');assert.equal(a.id('pay').disabled,true);
 finish({ok:true});await first;
});
test('a failure keeps the details, says nothing was charged and offers the other method',async()=>{
 const a=await setup({kind:'unavailable'});fill(a);await submit(a);
 assert.equal(a.id('error').textContent,"Couldn't open the payment page. You haven't been charged.");assert.equal(a.id('error').hidden,false);
 assert.equal(a.id('pay').textContent,'Try again');assert.equal(a.id('pay').disabled,false);
 assert.equal(a.id('email').value,'buyer@example.com');assert.equal(a.id('switchMethod').hidden,false);assert.equal(a.id('switchMethod').textContent,'Use PayPal instead');
 await a.id('switchMethod').fire();assert.equal(a.id('methodPaypal').checked,true);assert.equal(a.id('switchMethod').textContent,'Use card instead');
});
test('rate limits show retry guidance without offering a method switch',async()=>{
 const a=await setup({kind:'rate_limited'});fill(a);await submit(a);
 assert.equal(a.id('error').textContent,'Too many checks. Try again in a few minutes.');assert.equal(a.id('switchMethod').hidden,true);assert.equal(a.id('pay').disabled,false);
});
test('a repriced quote at load shows old and new pay now before any input',async()=>{
 const a=await setup(undefined,{snapshot:{...snapshot,totalCost:35,payNow:{...snapshot.payNow,total:33}},previous:snapshot,expiresAt:'2026-10-05T09:30:00Z',seller:'Munteok',destination:'US'});
 const text=a.id('summary').textContent;assert.match(text,/Price changed · Pay now \$30\.00 → \$33\.00/);assert.match(text,/\$35\.00/);
});
test('a repriced Buy re-renders the new price and waits for the buyer to continue',async()=>{
 const a=await setup({error:'changed',previous:snapshot,snapshot:{...snapshot,totalCost:36,payNow:{...snapshot.payNow,total:34}}});fill(a);await submit(a);
 assert.match(a.id('summary').textContent,/\$30\.00 → \$34\.00/);assert.equal(a.id('pay').textContent,'Continue to payment');assert.equal(a.id('pay').disabled,false);
});
test('a vanished offer ends with a single way back to the shop',async()=>{
 const a=await setup({error:'changed'});fill(a);await submit(a);
 assert.match(a.id('notice').textContent,/Price changed\. Go back to the shop and check again/);assert.equal(a.id('pay').disabled,true);assert.equal(a.id('checkoutForm').hidden,true);
 const b=await setup(undefined,{error:'changed'});assert.match(b.id('notice').textContent,/Price changed/);assert.equal(b.id('checkoutForm').hidden,true);
});
test('the quote clock counts down and says when it has expired',async()=>{
 const {initCheckout}=await import('../checkout.js');let t=NOW;const doc=documentFake(),timers=[];
 for(const id of ['summary','checkoutForm','email','name','methodCard','methodPaypal','pay','switchMethod','provider','error','notice','expiry']) {const n=doc.createElement('div');n.id=id;doc.body.append(n);}
 const chrome={runtime:{sendMessage:async()=>({snapshot,expiresAt:'2026-10-05T09:00:05Z',destination:'US'})}};
 await initCheckout({doc,chrome,location:{search:'?h=h&c=same'},now:()=>t,setInterval:fn=>{timers.push(fn);return 1;},clearInterval:()=>{}});
 assert.equal(doc.getElementById('expiry').textContent,'Quote expires in 0:05');t+=6000;timers[0]();
 assert.match(doc.getElementById('expiry').textContent,/Quote expired/);
});
test('checkout HTML: extension-origin inputs, one pay button, methods, trust lines and contact',async()=>{
 const html=await readFile(new URL('../checkout.html',import.meta.url),'utf8');
 assert.match(html,/type="email"/);assert.match(html,/autocomplete="name"/);
 assert.match(html,/<button id="pay" type="submit"[^>]*>Continue to payment<\/button>/);
 assert.match(html,/type="radio" name="method" id="methodCard" value="card" checked/);assert.match(html,/type="radio" name="method" id="methodPaypal" value="paypal"/);
 assert.match(html,/Out of stock in Korea\? Full refund\./);assert.match(html,/Card<small>Secure page by Stripe<\/small>/);assert.match(html,/PayPal<small>Sign in to PayPal<\/small>/);assert.match(html,/beforehand never sees your card details\./);
 assert.match(html,/href="mailto:support@munteok\.com"/);
 const build=await readFile(new URL('../scripts/build.mjs',import.meta.url),'utf8');assert.match(build,/'checkout.html','checkout.js'/);
});
