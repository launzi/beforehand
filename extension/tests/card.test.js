import test from 'node:test'; import assert from 'node:assert/strict'; import {quote} from './helpers.js'; import {documentFake,all,findText} from './dom.js';
await import('../core/card.js'); const {mount,savings}=globalThis.BeforehandCard;
test('currency mismatch never computes page savings; engine local comparison is allowed',()=>{
 const q=quote(),local={price:2980,currency:'JPY'}; assert.equal(savings(q,local),null);
 const c=mount(documentFake()); c.setState({view:'same',quote:q,local}); assert.doesNotMatch(c.root.testShadow.textContent,/you save/i);
 c.setState({view:'same',quote:quote({localPrice:{price:50,url:null}}),local}); assert.match(c.root.testShadow.textContent,/You save/); c.destroy();
});
test('Cheaper here hides Buy for either local savings or engine verdict',()=>{
 const c=mount(documentFake());
 for(const q of [quote(),quote({verdict:'buy_local'})]) {
  c.setState({view:'same',quote:q,local:{price:20,currency:'USD'}});assert.match(c.root.testShadow.textContent,/Cheaper here/); assert.equal(findText(c.root.testShadow,'Buy from Korea'),undefined);
 } c.destroy();
});
test('alternatives are capped and untrusted HTML stays text',()=>{
 const c=mount(documentFake()); const title='<img src=x onerror=alert(1)>';
 c.setState({view:'alternatives',items:Array.from({length:3},()=>({title,why:'Toner',quote:quote()}))});
 assert.equal(all(c.root.testShadow).filter(n=>n.tagName==='button'&&n.textContent==='Buy from Korea').length,2);
 assert.equal(all(c.root.testShadow).filter(n=>n.tagName==='img').length,0); assert.ok(c.root.testShadow.textContent.includes(title)); c.destroy();
});
test('Buy opens checkout with only a choice and the card never renders inputs',async()=>{
 const calls=[],c=mount(documentFake(),{onBuy:async(...args)=>calls.push(args)});
 for(const state of [{view:'same',quote:quote(),local:null},{view:'alternatives',items:[{title:'Toner',why:'Gentle',quote:quote()}]}]) {
  c.setState(state);await findText(c.root.testShadow,'Buy from Korea').fire();
  assert.equal(all(c.root.testShadow).filter(n=>['input','form'].includes(n.tagName)).length,0);
 }
 assert.deepEqual(calls,[['same'],[0]]);c.destroy();
});
test('closed shadow isolates card, details use safe links, collapse and destroy work',async()=>{
 const doc=documentFake(),c=mount(doc);assert.equal(c.root.shadowOptions.mode,'closed');
 c.setState({view:'same',quote:quote(),local:null}); const link=all(c.root.testShadow).find(n=>n.tagName==='a');assert.equal(link.rel,'noopener noreferrer');assert.equal(link.target,'_blank');
 await findText(c.root.testShadow,'Collapse').fire(); assert.ok(findText(c.root.testShadow,'beforehand'));c.destroy();assert.equal(doc.body.children.length,0);
});

test('changed quote asks for an explicit re-check',async()=>{
 let checks=0;const c=mount(documentFake(),{onCheck:()=>checks++});c.setState({view:'changed'});
 assert.match(c.root.testShadow.textContent,/Price changed — check again/);
 await findText(c.root.testShadow,'Check Korea price').fire();assert.equal(checks,1);c.destroy();
});
test('alternative why is omitted for every numeric or currency marker',()=>{
 const c=mount(documentFake());
 for(const why of ['Save 250','Save ２５０','Save ٢٥٠','Save Ⅻ','Save ²',...['$','£','€','¥','￥','₩','%'].map(symbol=>'Save '+symbol)]) {
  c.setState({view:'alternatives',items:[{title:'Toner',why,quote:quote()}]});
  assert.ok(!c.root.testShadow.textContent.includes(why),why);
 }
 const why='A gentle Korean toner';c.setState({view:'alternatives',items:[{title:'Toner',why,quote:quote()}]});
 assert.ok(c.root.testShadow.textContent.includes(why));c.destroy();
});
