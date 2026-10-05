import test from 'node:test'; import assert from 'node:assert/strict'; import {quote} from './helpers.js'; import {documentFake,all,findText} from './dom.js';
await import('../core/card.js'); const {mount,savings,compareAlternatives}=globalThis.BeforehandCard;
test('local price and savings use only same-currency shop-page prices',()=>{
 const q=quote(),local={price:2980,currency:'JPY'}; assert.equal(savings(q,local),null);
 const c=mount(documentFake()); c.setState({view:'same',quote:q,local}); assert.doesNotMatch(c.root.testShadow.textContent,/you save/i);
 c.setState({view:'same',quote:quote({localPrice:{price:50,url:null}}),local}); assert.doesNotMatch(c.root.testShadow.textContent,/Estimated savings|This shop/);
 c.setState({view:'same',quote:quote({localPrice:{price:99,url:null}}),local:{price:40,currency:'USD'}});
 assert.match(c.root.testShadow.textContent,/This shop\$40\.00/);assert.match(c.root.testShadow.textContent,/Estimated savings\$8\.00/);c.destroy();
});
test('Cheaper at this shop hides Buy for either local savings or engine verdict',()=>{
 const c=mount(documentFake());
 for(const q of [quote(),quote({verdict:'buy_local'})]) {
  c.setState({view:'same',quote:q,local:{price:20,currency:'USD'}});assert.match(c.root.testShadow.textContent,/Cheaper at this shop/); assert.equal(findText(c.root.testShadow,'Buy from Korea'),undefined);
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
 assert.match(c.root.testShadow.textContent,/Price changed/);assert.match(c.root.testShadow.textContent,/Check again to see the current price\./);
 await findText(c.root.testShadow,'Check again').fire();assert.equal(checks,1);c.destroy();
});
test('the engine note is never shown: tiles replace free text',()=>{
 const c=mount(documentFake());
 for(const why of ['Save 250','A gentle Korean toner']) {c.setState({view:'alternatives',items:[{title:'Toner',why,quote:quote()}]});assert.ok(!c.root.testShadow.textContent.includes(why),why);}
 c.destroy();
});
test('same-item card shows the estimated total split and the reviewed wording only',()=>{
 const c=mount(documentFake());c.setState({view:'same',quote:quote(),local:null});const text=c.root.testShadow.textContent;
 for(const t of ['Same item from Korea','$32.00','Estimated total · $30.00 now + $2.00 duty on delivery','International shipping','Estimated duty · pay on delivery','Sold by Munteok','View Korean listing ↗']) assert.ok(text.includes(t),t);
 assert.doesNotMatch(text,/Delivered|EMS|Seller:/);c.destroy();
});
test('every card state has one line and one next step with reviewed copy',async()=>{
 let checks=0,settings=0;const c=mount(documentFake(),{onCheck:()=>checks++,onSettings:()=>settings++,setTimeout:()=>1,clearTimeout:()=>{}});
 c.setState({view:'cant_ship',destination:'GB',message:'Batteries cannot be posted abroad.'});
 assert.match(c.root.testShadow.textContent,/Can't ship to United Kingdom/);assert.match(c.root.testShadow.textContent,/Batteries cannot be posted abroad\./);
 await findText(c.root.testShadow,'Change delivery country').fire();assert.equal(settings,1);
 c.setState({view:'paused'});assert.match(c.root.testShadow.textContent,/Auto-check paused for today/);await findText(c.root.testShadow,'Check this item').fire();
 c.setState({view:'busy'});assert.match(c.root.testShadow.textContent,/Couldn't get a quote/);await findText(c.root.testShadow,'Try again').fire();assert.equal(checks,2);
 c.setState({view:'none'});assert.match(c.root.testShadow.textContent,/No match in Korea/);assert.ok(findText(c.root.testShadow,'Hide for this item'));
 assert.doesNotMatch(c.root.testShadow.textContent,/—/);c.destroy();
});

const ml=value=>({value,unit:'ml'});
const altItem=(o={})=>({title:'라네즈 워터 슬리핑 마스크 EX 100ml',why:'x',quote:quote({totalCost:58.8}),titleEn:'LANEIGE Water Sleeping Mask EX 100ml',sameBrand:true,sameType:true,size:ml(100),...o});
const source={brand:'LANEIGE',typeEn:'Sleeping mask',size:ml(70)},local={price:78,currency:'USD'};
test('alternatives compare brand, type, size and price with the page product',()=>{
 const [ex,cica]=compareAlternatives([altItem(),altItem({title:'시카',titleEn:'LANEIGE Cica Sleeping Mask 60ml',quote:quote({totalCost:60.02}),size:ml(60)})],source,local);
 assert.deepEqual(ex.tiles.map(t=>[t.key,t.state,t.value]),[['Brand','same','Same'],['Type','same','Same'],['Size','better','100 ml'],['Price','better','▼ $19.20']]);
 assert.deepEqual(cica.tiles.map(t=>[t.key,t.state]),[['Brand','same'],['Type','same'],['Size','same'],['Price','better']]);
 assert.deepEqual(ex.badges,['Lowest price','Most for the money']);assert.deepEqual(cica.badges,['Closest']);
});
test('badges need their inputs: no page price, mixed units or a single option hide them',()=>{
 const [only]=compareAlternatives([altItem()],source,null);
 assert.deepEqual(only.badges,[]);assert.deepEqual(only.tiles.map(t=>t.key),['Brand','Type','Size']);
 const mixed=compareAlternatives([altItem(),altItem({size:{value:50,unit:'g'},quote:quote({totalCost:40})})],source,local);
 assert.deepEqual(mixed.map(r=>r.badges.includes('Most for the money')),[false,false]);
 const pricier=compareAlternatives([altItem({quote:quote({totalCost:90})})],source,local);
 // $90 for 100 ml costs less per ml than the page's $78 for 70 ml: more for the money, not the lowest price.
 assert.deepEqual(pricier[0].badges,['Most for the money']);assert.equal(pricier[0].tiles.at(-1).value,'▲ $12.00');
 const unknown=compareAlternatives([altItem({sameBrand:null,sameType:false,size:null})],{brand:null,typeEn:null,size:null},null);
 assert.deepEqual(unknown[0].tiles.map(t=>[t.key,t.state]),[['Type','other']]);
});
test('size at exactly -15% counts as the same size and can win Closest',()=>{
 const [a,b]=compareAlternatives([altItem({sameBrand:null,sameType:null,size:ml(85),quote:quote({totalCost:20})}),altItem({sameBrand:null,sameType:null,size:ml(80),quote:quote({totalCost:21})})],{...source,size:ml(100)},null);
 assert.equal(a.tiles.find(t=>t.key==='Size').state,'same');assert.ok(a.badges.includes('Closest'));assert.ok(!b.badges.includes('Closest'));
});
test('prices in different currencies are never compared or ranked',()=>{
 const rows=compareAlternatives([altItem({quote:quote({totalCost:30})}),altItem({quote:quote({totalCost:20,currency:'GBP'})})],{...source,size:ml(100)},{price:25,currency:'USD'});
 assert.deepEqual(rows.map(r=>r.badges),[[],[]]);
 assert.equal(rows[1].tiles.some(t=>t.key==='Price'),false);
});
test('price state uses the exact difference, not the rounded one',()=>{
 const [r]=compareAlternatives([altItem({quote:quote({totalCost:20})})],source,{price:20.004,currency:'USD'});
 assert.equal(r.tiles.at(-1).state,'better');
});
test('alternatives card shows the reference row, title pair, tiles and badges; Korean title stands alone without English',()=>{
 const c=mount(documentFake());
 c.setState({view:'alternatives',source,local,items:[altItem(),altItem({titleEn:null,title:'라네즈 시카 슬리핑 마스크 60ml',quote:quote({totalCost:60.02}),size:ml(60)})]});
 const text=c.root.testShadow.textContent;
 for(const t of ['vs this page · LANEIGE · Sleeping mask · 70 ml','$78.00','LANEIGE Water Sleeping Mask EX 100ml','라네즈 워터 슬리핑 마스크 EX 100ml','Lowest price','✓ Same','100 ml','▼ $19.20','라네즈 시카 슬리핑 마스크 60ml']) assert.ok(text.includes(t),t);
 c.destroy();
});
test('same item shows the match ring and English title over the Korean original',()=>{
 const c=mount(documentFake());
 c.setState({view:'same',quote:quote(),local:null,titleEn:'Anua Toner 250ml',matchPercent:96});
 const text=c.root.testShadow.textContent;assert.ok(text.includes('96%'));assert.ok(text.includes('MATCH'));assert.ok(text.includes('Anua Toner 250ml'));assert.ok(text.includes('Anua Toner 250ml'+quote().item.title) || text.includes(quote().item.title));
 c.setState({view:'same',quote:quote(),local:null,titleEn:null,matchPercent:null});assert.ok(!c.root.testShadow.textContent.includes('MATCH'));
 c.destroy();
});
