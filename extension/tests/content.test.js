import test from 'node:test'; import assert from 'node:assert/strict'; import {documentFake} from './dom.js';
await import('../content.js'); const {createContent}=globalThis.BeforehandContent;
function setup(sendMessage) {
 const doc=documentFake(),location={href:'https://walmart.com/item/1',hostname:'walmart.com'},cards=[],messages=[],listeners=new Set();
 let product={name:'Toner',brand:'Anua',price:20,currency:'USD'},reads=0;
 const app=createContent({doc,location,onMessage:{addListener:fn=>listeners.add(fn),removeListener:fn=>listeners.delete(fn)},sendMessage:async m=>{messages.push(m);return sendMessage(m);},extract:{readPageParts:()=>({}),extractFromParts:()=>{reads++;return product;}},card:{mount:(_,opts)=>{const c={opts,states:[],setState(s){this.states.push(s);},destroy(){this.destroyed=true;}};cards.push(c);return c;}},setInterval:()=>1,clearInterval:()=>{}});
 return {app,doc,location,cards,messages,setProduct:value=>{product=value;},readCount:()=>reads,notify:m=>{for(const listener of listeners)listener(m);},listeners};
}
const status={onboarded:true,shopEnabled:true,autoCheck:true,destination:'US'};
test('SPA URL changes destroy old card, check once and never send local price or URL',async()=>{
 const a=setup(async m=>m.type==='status'?status:{kind:'none'});await a.app.tick();await a.app.tick();
 assert.equal(a.messages.filter(m=>m.type==='match').length,1);a.location.href='https://walmart.com/item/2';await a.app.tick();assert.equal(a.cards[0].destroyed,true);assert.equal(a.messages.filter(m=>m.type==='match').length,2);
 assert.doesNotMatch(JSON.stringify(a.messages),/walmart|currency|price|href/);a.app.destroy();
});
test('manual mode sends nothing until clicked and hidden pages do not check',async()=>{
 const a=setup(async m=>m.type==='status'?{...status,autoCheck:false}:{kind:'none'});a.doc.visibilityState='hidden';await a.app.tick();assert.equal(a.messages.length,0);
 a.doc.visibilityState='visible';await a.app.tick();assert.equal(a.cards[0].states[0].view,'manual');assert.equal(a.messages.length,1);
 await a.cards[0].opts.onCheck();assert.equal(a.messages[1].manual,true);a.app.destroy();
});
test('stale async results cannot render on a new SPA page',async()=>{
 let resolve;let first=true;
 const a=setup(async m=>{if(m.type==='status')return status;if(first){first=false;return new Promise(r=>resolve=r);}return {kind:'cant_ship'};});
 const pending=a.app.tick();await new Promise(r=>setImmediate(r));a.location.href='https://walmart.com/item/2';await a.app.tick();resolve({kind:'none'});await pending;
 assert.equal(a.cards[1].states.at(-1).view,'cant_ship');assert.equal(a.cards[0].states.length,1);a.app.destroy();
});
test('no card without consent and transport errors become retryable busy',async()=>{
 const a=setup(async()=>({...status,onboarded:false}));await a.app.tick();assert.equal(a.cards.length,0);a.app.destroy();
 const b=setup(async m=>{if(m.type==='status')return status;throw Error('gone');});await b.app.tick();assert.equal(b.cards[0].states.at(-1).view,'busy');b.app.destroy();
});

test('Buy sends the displayed handle and choice without reselecting by product',async()=>{
 const a=setup(async m=>m.type==='status'?status:m.type==='match'?{kind:'same',handle:'display-a'}:{error:'changed'});
 await a.app.tick();await a.cards[0].opts.onBuy('same');
 assert.deepEqual(a.messages.at(-1),{type:'open_checkout',handle:'display-a',choice:'same'});
 assert.equal(a.cards[0].states.at(-1).view,'changed');a.app.destroy();
});

test('checkout change notifications affect only the matching displayed handle',async()=>{
 const a=setup(async m=>m.type==='status'?status:{kind:'same',handle:'display-a'});await a.app.tick();
 a.notify({type:'quote_changed',handle:'display-b'});assert.equal(a.cards[0].states.at(-1).view,'same');
 a.notify({type:'quote_changed',handle:'display-a'});assert.equal(a.cards[0].states.at(-1).view,'changed');
 a.app.destroy();assert.equal(a.listeners.size,0);
});

test('URL-first navigation checks the hydrated product on a later visible tick',async()=>{
 const a=setup(async m=>m.type==='status'?status:{kind:'none'});await a.app.tick();
 a.location.href='https://walmart.com/item/new';await a.app.tick();
 a.setProduct({name:'New product',brand:'New brand'});await a.app.tick();await a.app.tick();
 assert.deepEqual(a.messages.filter(m=>m.type==='match').map(m=>m.product.name),['Toner','Toner','New product']);
 assert.equal(a.cards[1].destroyed,true);assert.equal(a.readCount(),4);a.app.destroy();
});
test('empty extraction retries later and identical ticks send only one check',async()=>{
 const a=setup(async m=>m.type==='status'?status:{kind:'none'});a.setProduct(null);
 await a.app.tick();await a.app.tick();assert.equal(a.messages.length,0);
 a.setProduct({name:'Hydrated toner',brand:'Anua'});await a.app.tick();await a.app.tick();await a.app.tick();
 assert.equal(a.messages.filter(m=>m.type==='match').length,1);assert.equal(a.readCount(),5);
 a.doc.visibilityState='hidden';await a.app.tick();assert.equal(a.readCount(),5);a.app.destroy();
});
test('a variant or brand change on the same URL triggers exactly one new check',async()=>{
 const a=setup(async m=>m.type==='status'?status:{kind:'none'});await a.app.tick();
 a.setProduct({name:'Toner 50ml',brand:'Anua'});await a.app.tick();await a.app.tick();
 assert.equal(a.cards[0].destroyed,true);assert.equal(a.messages.filter(m=>m.type==='match').length,2);
 a.setProduct({name:'Toner 50ml',brand:'Another brand'});await a.app.tick();await a.app.tick();
 assert.equal(a.cards[1].destroyed,true);assert.equal(a.messages.filter(m=>m.type==='match').length,3);a.app.destroy();
});
test('late response for a previous identity on the same URL cannot replace the new card',async()=>{
 let resolve,first=true;const a=setup(async m=>{if(m.type==='status')return status;if(first){first=false;return new Promise(r=>resolve=r);}return {kind:'cant_ship'};});
 const pending=a.app.tick();await new Promise(r=>setImmediate(r));a.setProduct({name:'New variant',brand:'Anua'});await a.app.tick();
 resolve({kind:'same',handle:'stale'});await pending;assert.equal(a.cards[0].destroyed,true);assert.equal(a.cards[1].states.at(-1).view,'cant_ship');a.app.destroy();
});
