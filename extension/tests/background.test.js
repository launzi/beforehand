import test from 'node:test'; import assert from 'node:assert/strict';
import {createBackground} from '../background.js';
import {acceptConsent,deleteAllData,appendTrace,readTrace,DAILY_AUTO_LIMIT} from '../core/storage.js';
import {Store,consent,quote,response} from './helpers.js';
const sender={url:'https://www.amazon.com/dp/item',tab:{id:1,url:'https://www.amazon.com/dp/item'},frameId:0,documentId:'doc-a'};
const product={name:'Anua Toner 250ml',brand:'Anua'};
const match={type:'match',product,manual:false};
const buy={type:'buy',choice:'same',email:'buyer@example.com',name:'Buyer Identity'};
function env(data={...consent(),autoCheck:true},replies=[{kind:'same',quote:quote()}],clock=()=>Date.parse('2026-10-03T09:00:00Z')) {
 const storage=new Store(data),session=new Store(),calls=[],tabs=[],updates=[],notifications=[],access=[];
 session.setAccessLevel=async value=>access.push(value);
 const chrome={storage:{local:storage,session},tabs:{create:async x=>{tabs.push(x);return {id:100+tabs.length};},update:async(id,x)=>updates.push({id,...x}),sendMessage:async(...args)=>notifications.push(args)},runtime:{getURL:x=>'chrome-extension://id/'+x}};
 const fetchImpl=async(url,init)=>{calls.push(JSON.parse(init.body));return response(replies.shift());};
 return {storage,session,access,calls,tabs,updates,notifications,chrome,clock,bg:createBackground({chrome,fetchImpl,now:clock})};
}
async function openCheckout(bg,a,handle,source=sender,choice='same') {
 const opened=await bg.onMessage({type:'open_checkout',handle,choice},source);
 if(!opened.ok)return {error:opened};
 return {url:a.tabs.at(-1).url,tab:{id:100+a.tabs.length},frameId:0,documentId:'checkout-doc'};
}
async function buyFrom(bg,a,handle,source=sender,choice='same',extra={}) {
 const page=await openCheckout(bg,a,handle,source,choice);
 return page.error ?? bg.onMessage({...buy,handle,choice,...extra},page);
}
test('no network before consent and auto off still permits manual',async()=>{
 const a=env({}); assert.equal((await a.bg.onMessage(match,sender)).kind,'unavailable'); assert.equal(a.calls.length,0);
 const b=env({...consent(),autoCheck:false}); assert.equal((await b.bg.onMessage(match,sender)).kind,'unavailable');
 assert.equal((await b.bg.onMessage({...match,manual:true},sender)).kind,'same'); assert.equal(b.calls.length,1);
});
test('sender host is authoritative, including invalid scheme and disabled shops',async()=>{
 const a=env({...consent(),autoCheck:true,disabledShops:['amazon.com']});
 await a.bg.onMessage({...match,host:'walmart.com'},sender); assert.equal(a.calls.length,0);
 for(const url of ['http://amazon.com','https://evilamazon.com','chrome-extension://id/popup.html']) await a.bg.onMessage(match,{url});
 assert.equal(a.calls.length,0);
});
test('second identical lookup uses cache and disk contains no tokens',async()=>{
 const a=env(); const [first,second]=await Promise.all([a.bg.onMessage(match,sender),a.bg.onMessage(match,sender)]);
 assert.equal(first.kind,'same'); assert.equal(second.kind,'same'); assert.equal(a.calls.length,1);
 assert.doesNotMatch(JSON.stringify(a.storage.data),/FAKE_QUOTE_TOKEN|quoteToken|quoteExpiresAt/);
 const resumed=createBackground({chrome:a.chrome,fetchImpl:async()=>{throw Error('cache miss');},now:a.clock});
 assert.equal((await resumed.onMessage(match,sender)).kind,'same');
});
test('Buy with expired token refreshes then opens Stripe',async()=>{
 const a=env(undefined,[{kind:'same',quote:quote({quoteExpiresAt:'2026-10-03T09:00:30Z'})},{kind:'same',quote:quote({quoteToken:'FAKE_NEW_TOKEN_12345'})},{checkoutUrl:'https://checkout.stripe.com/c/pay/cs_x'}]);
 const {handle}=await a.bg.onMessage(match,sender); assert.deepEqual(await buyFrom(a.bg,a,handle),{ok:true});
 assert.equal(a.calls[1].params.arguments.fresh,true); assert.equal(a.calls[2].params.name,'start_bestseller_checkout');
 assert.equal(a.calls[2].params.arguments.quoteToken,'FAKE_NEW_TOKEN_12345'); assert.deepEqual(a.updates,[{id:101,url:'https://checkout.stripe.com/c/pay/cs_x'}]);
 assert.doesNotMatch(JSON.stringify(a.storage.data),/Buyer Identity|buyer@example|quoteToken/);
});
test('Buy refresh after worker restart and changed alternatives cannot buy another item',async()=>{
 const items=[{title:'Toner',why:'Toner',quote:quote()}];
 const a=env(undefined,[{kind:'alternatives',items},{kind:'alternatives',items:[{...items[0],quote:quote({item:{title:'Different item',priceKrw:1,link:null}})}]}]);
 const {handle}=await a.bg.onMessage(match,sender);
 const resumed=createBackground({chrome:a.chrome,fetchImpl:async(url,init)=>{a.calls.push(JSON.parse(init.body));return response({kind:'alternatives',items:[{...items[0],quote:quote({item:{title:'Different item',priceKrw:1,link:null}})}]});}});
 assert.deepEqual(await buyFrom(resumed,a,handle,sender,0),{error:'changed'}); assert.equal(a.updates.length,0);
});
test('daily auto limit pauses only auto checks and cached requests spend no quota',async()=>{
 const date=new Date(Date.parse('2026-10-03T09:00:00Z')),day=[date.getFullYear(),date.getMonth()+1,date.getDate()].join('-');
 const a=env({...consent(),autoCheck:true,autoCount:{day,count:DAILY_AUTO_LIMIT}});
 assert.equal((await a.bg.onMessage(match,sender)).kind,'paused'); assert.equal(a.calls.length,0);
 assert.equal((await a.bg.onMessage({...match,manual:true},sender)).kind,'same');
 assert.equal((await a.bg.onMessage(match,sender)).kind,'same'); assert.equal(a.calls.length,1);
});
test('onInstalled opens welcome for install and stale consent updates only',async()=>{
 const a=env({consent:{accepted:true,version:3},providerKey:'FAKE_OLD_KEY'});
 await a.bg.onInstalled({reason:'install'}); await a.bg.onInstalled({reason:'update'});
 await acceptConsent(a.storage,{autoCheck:false}); await a.bg.onInstalled({reason:'update'});
 assert.equal(a.tabs.length,2); assert.equal(a.tabs[0].url,'chrome-extension://id/welcome.html'); assert.equal(a.storage.data.providerKey,undefined);
});
test('deleting all data during fetch prevents cache/trace resurrection',async()=>{
 const a=env(); const bg=createBackground({chrome:a.chrome,fetchImpl:async()=>{await deleteAllData(a.storage);return response({kind:'same',quote:quote()});}});
 assert.equal((await bg.onMessage(match,sender)).kind,'unavailable'); assert.deepEqual(a.storage.data,{});
});
test('trace retention and field allowlist discard identity and tokens',async()=>{
 const s=new Store(consent());
 for(let i=0;i<505;i++) await appendTrace(s,{kind:'match_result',result:'same',shop:'amazon.com',email:'buyer@example.com',quoteToken:'fake',name:'identity'},Date.now());
 const trace=await readTrace(s); assert.equal(trace.length,500); assert.doesNotMatch(JSON.stringify(trace),/buyer@example|quoteToken|identity/);
 assert.equal((await readTrace(s,Date.now()+31*86400000)).length,0);
});
test('status chooses shop country and explicit destination override',async()=>{
 const a=env(); assert.equal((await a.bg.onMessage({type:'status'},{url:'https://www.boots.com/p'})).destination,'GB');
 await a.storage.set({destination:'JP'}); assert.equal((await a.bg.onMessage({type:'status'},sender)).destination,'JP');
});
test('switching off while preparing the trace prevents the outgoing request',async()=>{
 const a=env();const set=a.storage.set.bind(a.storage);
 a.storage.set=async value=>{await set(value);if(value.trace?.at(-1)?.kind==='match_sent')await set({autoCheck:false});};
 assert.equal((await a.bg.onMessage(match,sender)).kind,'unavailable');assert.equal(a.calls.length,0);
});
test('trace generation permits the current request and refuses a deleted generation',async()=>{
 const {deleteTrace}=await import('../core/storage.js');const s=new Store(consent());
 await appendTrace(s,{kind:'match_result',shop:'amazon.com',result:'same'},Date.now(),null);assert.equal((await readTrace(s)).length,1);
 await deleteTrace(s);await appendTrace(s,{kind:'match_result',shop:'amazon.com',result:'same'},Date.now(),null);assert.equal((await readTrace(s)).length,0);
});

test('display handles are unique, document-bound and never expose or persist tokens',async()=>{
 const a=env(),first=await a.bg.onMessage(match,sender),second=await a.bg.onMessage(match,sender);
 assert.equal(typeof first.handle,'string');assert.notEqual(first.handle,second.handle);
 assert.doesNotMatch(JSON.stringify([first,second,a.storage.data,a.session.data]),/quoteToken|quoteExpiresAt|FAKE_QUOTE/);
 assert.deepEqual(a.access,[{accessLevel:'TRUSTED_CONTEXTS'}]);
 for(const foreign of [{...sender,tab:{...sender.tab,id:2}},{...sender,documentId:'doc-b'}]) {
  assert.deepEqual(await buyFrom(a.bg,a,first.handle,foreign),{error:'changed'});
 }
 assert.equal(a.calls.length,1);
});
test('two tabs never buy the other tabs refreshed quote or mutate their snapshots',async()=>{
 let time=Date.parse('2026-10-03T09:00:00Z');
 const original=quote({quoteExpiresAt:'2026-10-03T09:30:00Z'});
 const changed=quote({item:{title:'Different item',priceKrw:18000,link:'https://shop.example/other'},totalCost:50,quoteToken:'FAKE_OTHER_TAB_TOKEN'});
 const a=env(undefined,[{kind:'same',quote:original},{kind:'same',quote:changed},{kind:'same',quote:quote({quoteToken:'FAKE_TAB_A_REFRESH'})},{checkoutUrl:'https://checkout.stripe.com/c/pay/a'}],()=>time);
 const tabB={...sender,tab:{...sender.tab,id:2},documentId:'doc-b'};
 const cardA=await a.bg.onMessage(match,sender),cardB=await a.bg.onMessage(match,tabB);
 const snapshots=structuredClone(a.session.data);
 time+=31*60000;
 assert.deepEqual(await buyFrom(a.bg,a,cardB.handle,tabB),{error:'changed'});
 // A gets its own matching fresh token, never the valid token B.
 assert.deepEqual(await buyFrom(a.bg,a,cardA.handle),{ok:true});
 assert.equal(a.calls.at(-1).params.arguments.quoteToken,'FAKE_TAB_A_REFRESH');
 for(const h of [cardA.handle,cardB.handle])assert.deepEqual(a.session.data.snapshots[h].snapshot,snapshots.snapshots[h].snapshot);
});
test('refresh compares all six snapshot fields including equal-total payment split',async()=>{
 const changes=[{item:{...quote().item,title:'Other toner'}},{item:{...quote().item,link:'https://shop.example/other'}},{currency:'GBP'},{totalCost:33},{payNow:{...quote().payNow,total:29}},{dutyOnDelivery:{...quote().dutyOnDelivery,estimate:3}}];
 for(const change of changes) {
  const a=env(undefined,[{kind:'same',quote:quote({quoteExpiresAt:'2026-10-03T09:00:30Z'})},{kind:'same',quote:quote(change)}]);
  const {handle}=await a.bg.onMessage(match,sender);
  assert.deepEqual(await buyFrom(a.bg,a,handle),{error:'changed'});
  assert.equal(a.calls.length,2);assert.equal(a.updates.length,0);
 }
});
test('worker restart refreshes a session snapshot with the same product and country',async()=>{
 const a=env(),{handle}=await a.bg.onMessage(match,sender),calls=[];
 const resumed=createBackground({chrome:a.chrome,fetchImpl:async(url,init)=>{
  const rpc=JSON.parse(init.body);calls.push(rpc);return response(rpc.params.name==='match_korea_product'?{kind:'same',quote:quote()}:{checkoutUrl:'https://checkout.stripe.com/c/pay/restart'});
 }});
 assert.deepEqual(await buyFrom(resumed,a,handle,sender,'same',{product:{name:'Ignored product'}}),{ok:true});
 assert.deepEqual(calls[0].params.arguments,{...product,destination:'US',fresh:true});
});
test('session snapshots are bounded at 200 and evicted handles cannot buy',async()=>{
 const a=env(),first=await a.bg.onMessage(match,sender);
 for(let i=0;i<200;i++)await a.bg.onMessage(match,sender);
 assert.equal(Object.keys(a.session.data.snapshots).length,200);
 assert.deepEqual(await buyFrom(a.bg,a,first.handle),{error:'changed'});
});

test('refreshing one alternative never authorizes a changed sibling choice',async()=>{
 const items=[{title:'First',why:'Toner',quote:quote()},{title:'Second',why:'Toner',quote:quote()}];
 const a=env(undefined,[{kind:'alternatives',items}]);
 const {handle}=await a.bg.onMessage(match,sender);
 const replies=[{kind:'alternatives',items:[items[0],{...items[1],quote:quote({totalCost:99})}]},{checkoutUrl:'https://checkout.stripe.com/c/pay/first'}];
 const resumed=createBackground({chrome:a.chrome,fetchImpl:async()=>response(replies.shift())});
 assert.deepEqual(await buyFrom(resumed,a,handle,sender,0),{ok:true});
 assert.deepEqual(await buyFrom(resumed,a,handle,sender,1),{error:'changed'});
});

test('only the registered extension checkout tab can read its snapshot or buy',async()=>{
 const a=env(undefined,[{kind:'same',quote:quote()},{checkoutUrl:'https://checkout.stripe.com/c/pay/exact-tab'}]);
 const {handle}=await a.bg.onMessage(match,sender),page=await openCheckout(a.bg,a,handle);
 assert.equal(page.url,`chrome-extension://id/checkout.html?h=${handle}&c=same`);
 const shown=await a.bg.onMessage({type:'checkout_snapshot',handle,choice:'same'},page);
 assert.deepEqual(shown.snapshot,{title:quote().item.title,link:quote().item.link,currency:'USD',totalCost:32,payNow:{total:30},dutyOnDelivery:{estimate:2}});
 assert.equal(shown.seller,'Munteok');assert.doesNotMatch(JSON.stringify(shown),/quoteToken|quoteExpiresAt/);
 for(const intruder of [sender,{...page,tab:{id:999}},{...page,url:'chrome-extension://id/popup.html'}]) {
  assert.deepEqual(await a.bg.onMessage({...buy,handle},intruder),{error:'changed'});
  assert.deepEqual(await a.bg.onMessage({type:'checkout_snapshot',handle,choice:'same'},intruder),{error:'changed'});
 }
 assert.deepEqual(await a.bg.onMessage({...buy,handle},page),{ok:true});
 assert.deepEqual(a.updates,[{id:101,url:'https://checkout.stripe.com/c/pay/exact-tab'}]);
 assert.doesNotMatch(JSON.stringify([a.storage.data,a.session.data]),/buyer@example|Buyer Identity|quoteToken/);
});
test('changed checkout notifies only its originating document and handle',async()=>{
 const a=env(undefined,[{kind:'same',quote:quote({quoteExpiresAt:'2026-10-03T09:00:30Z'})},{kind:'same',quote:quote({totalCost:99})}]);
 const {handle}=await a.bg.onMessage(match,sender);
 assert.deepEqual(await buyFrom(a.bg,a,handle),{error:'changed'});
 assert.deepEqual(a.notifications,[[sender.tab.id,{type:'quote_changed',handle},{documentId:sender.documentId}]]);
});

test('an already opened checkout survives worker restart without persisting buyer details',async()=>{
 const a=env(),{handle}=await a.bg.onMessage(match,sender),page=await openCheckout(a.bg,a,handle),calls=[];
 const resumed=createBackground({chrome:a.chrome,fetchImpl:async(url,init)=>{
  const rpc=JSON.parse(init.body);calls.push(rpc);return response(rpc.params.name==='match_korea_product'?{kind:'same',quote:quote()}:{checkoutUrl:'https://checkout.stripe.com/c/pay/restarted-page'});
 }});
 assert.ok((await resumed.onMessage({type:'checkout_snapshot',handle,choice:'same'},page)).snapshot);
 assert.deepEqual(await resumed.onMessage({...buy,handle},page),{ok:true});
 assert.equal(calls[0].params.arguments.fresh,true);
 assert.deepEqual(a.updates,[{id:page.tab.id,url:'https://checkout.stripe.com/c/pay/restarted-page'}]);
 assert.doesNotMatch(JSON.stringify([a.storage.data,a.session.data]),/buyer@example|Buyer Identity|quoteToken|quoteExpiresAt/);
});
test('cache reads recheck deleted or revised consent and current settings before returning',async()=>{
 for(const revoke of [s=>deleteAllData(s),s=>acceptConsent(s,{autoCheck:true}),s=>s.set({autoCheck:false}),s=>s.set({disabledShops:['amazon.com']}),s=>s.set({destination:'JP'})]) {
  const a=env();await a.bg.onMessage(match,sender);
  const before=structuredClone(a.session.data),get=a.storage.get.bind(a.storage);let intercepted=false;
  a.storage.get=async keys=>{const value=await get(keys);if(keys==='resultCache' && !intercepted){intercepted=true;await revoke(a.storage);}return value;};
  assert.equal((await a.bg.onMessage(match,sender)).kind,'unavailable');
  assert.equal(a.calls.length,1);assert.deepEqual(a.session.data,before);
 }
});
