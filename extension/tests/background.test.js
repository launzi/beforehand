import test from 'node:test'; import assert from 'node:assert/strict';
import {createBackground} from '../background.js';
import {acceptConsent,deleteAllData,appendTrace,readTrace,DAILY_AUTO_LIMIT} from '../core/storage.js';
import {Store,consent,quote,response} from './helpers.js';
const sender={url:'https://www.amazon.com/dp/item',tab:{id:1,url:'https://www.amazon.com/dp/item'},frameId:0};
const product={name:'Anua Toner 250ml',brand:'Anua'};
const match={type:'match',product,manual:false};
const buy={type:'buy',choice:'same',email:'buyer@example.com',name:'Buyer Identity',product};
function env(data={...consent(),autoCheck:true},replies=[{kind:'same',quote:quote()}],clock=()=>Date.parse('2026-10-03T09:00:00Z')) {
 const storage=new Store(data),calls=[],tabs=[];
 const chrome={storage:{local:storage},tabs:{create:async x=>tabs.push(x)},runtime:{getURL:x=>'chrome-extension://id/'+x}};
 const fetchImpl=async(url,init)=>{calls.push(JSON.parse(init.body));return response(replies.shift());};
 return {storage,calls,tabs,chrome,bg:createBackground({chrome,fetchImpl,now:clock})};
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
 const resumed=createBackground({chrome:a.chrome,fetchImpl:async()=>{throw Error('cache miss');}});
 assert.equal((await resumed.onMessage(match,sender)).kind,'same');
});
test('Buy with expired token refreshes then opens Stripe',async()=>{
 const a=env(undefined,[{kind:'same',quote:quote({quoteExpiresAt:'2026-10-03T09:00:30Z'})},{kind:'same',quote:quote({quoteToken:'FAKE_NEW_TOKEN_12345'})},{checkoutUrl:'https://checkout.stripe.com/c/pay/cs_x'}]);
 await a.bg.onMessage(match,sender); assert.deepEqual(await a.bg.onMessage(buy,sender),{ok:true});
 assert.equal(a.calls[1].params.arguments.fresh,true); assert.equal(a.calls[2].params.name,'start_bestseller_checkout');
 assert.equal(a.calls[2].params.arguments.quoteToken,'FAKE_NEW_TOKEN_12345'); assert.deepEqual(a.tabs,[{url:'https://checkout.stripe.com/c/pay/cs_x'}]);
 assert.doesNotMatch(JSON.stringify(a.storage.data),/Buyer Identity|buyer@example|quoteToken/);
});
test('Buy refresh after worker restart and changed alternatives cannot buy another item',async()=>{
 const items=[{title:'Toner',why:'Toner',quote:quote()}];
 const a=env(undefined,[{kind:'alternatives',items},{kind:'alternatives',items:[{...items[0],quote:quote({item:{title:'Different item',priceKrw:1,link:null}})}]}]);
 await a.bg.onMessage(match,sender);
 const resumed=createBackground({chrome:a.chrome,fetchImpl:async(url,init)=>{a.calls.push(JSON.parse(init.body));return response({kind:'alternatives',items:[{...items[0],quote:quote({item:{title:'Different item',priceKrw:1,link:null}})}]});}});
 assert.deepEqual(await resumed.onMessage({...buy,choice:0},sender),{error:'changed'}); assert.equal(a.tabs.length,0);
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
