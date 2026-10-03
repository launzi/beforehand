import test from 'node:test'; import assert from 'node:assert/strict'; import {documentFake} from './dom.js';
await import('../content.js'); const {createContent}=globalThis.BeforehandContent;
function setup(sendMessage) {
 const doc=documentFake(),location={href:'https://walmart.com/item/1',hostname:'walmart.com'},cards=[],messages=[];
 const app=createContent({doc,location,sendMessage:async m=>{messages.push(m);return sendMessage(m);},extract:{readPageParts:()=>({}),extractFromParts:()=>({name:'Toner',brand:'Anua',price:20,currency:'USD'})},card:{mount:(_,opts)=>{const c={opts,states:[],setState(s){this.states.push(s);},destroy(){this.destroyed=true;}};cards.push(c);return c;}},setInterval:()=>1,clearInterval:()=>{}});
 return {app,doc,location,cards,messages};
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
 await a.app.tick();await a.cards[0].opts.onBuy('same','buyer@example.com','Buyer');
 assert.deepEqual(a.messages.at(-1),{type:'buy',handle:'display-a',choice:'same',email:'buyer@example.com',name:'Buyer'});
 assert.equal(a.cards[0].states.at(-1).view,'changed');a.app.destroy();
});
