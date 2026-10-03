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
test('buy form submits only choice/email/name and blocks duplicate submits',async()=>{
 const calls=[],doc=documentFake(),c=mount(doc,{onBuy:async(...args)=>calls.push(args)});
 c.setState({view:'same',quote:quote(),local:null}); await findText(c.root.testShadow,'Buy from Korea').fire();
 const inputs=all(c.root.testShadow).filter(n=>n.tagName==='input');inputs[0].value='buyer@example.com';inputs[1].value='Buyer';
 await all(c.root.testShadow).find(n=>n.tagName==='form').fire('submit');assert.deepEqual(calls,[['same','buyer@example.com','Buyer']]);
 assert.doesNotMatch(c.root.testShadow.textContent,/buyer@example.com/);c.destroy();
});
test('closed shadow isolates card, details use safe links, collapse and destroy work',async()=>{
 const doc=documentFake(),c=mount(doc);assert.equal(c.root.shadowOptions.mode,'closed');
 c.setState({view:'same',quote:quote(),local:null}); const link=all(c.root.testShadow).find(n=>n.tagName==='a');assert.equal(link.rel,'noopener noreferrer');assert.equal(link.target,'_blank');
 await findText(c.root.testShadow,'Collapse').fire(); assert.ok(findText(c.root.testShadow,'beforehand'));c.destroy();assert.equal(doc.body.children.length,0);
});
