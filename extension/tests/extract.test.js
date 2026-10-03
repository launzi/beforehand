import test from 'node:test'; import assert from 'node:assert/strict'; import {readFile} from 'node:fs/promises';
await import('../core/extract.js'); const {extractFromParts,readPageParts}=globalThis.BeforehandExtract;
const fx=async n=>JSON.parse(await readFile(new URL(`./fixtures/pages/${n}.json`,import.meta.url),'utf8'));
test('JSON-LD Product inside @graph',async()=>assert.deepEqual(extractFromParts(await fx('sephora'),'sephora.com'),{name:'Heartleaf 77% Soothing Toner',brand:'Anua',price:29,currency:'USD'}));
test('JSON-LD array with AggregateOffer',async()=>assert.equal(extractFromParts(await fx('walmart'),'walmart.com').price,12.97));
test('Amazon selectors with byline cleanup',async()=>assert.deepEqual(extractFromParts(await fx('amazon'),'amazon.com'),{name:'COSRX Snail Mucin 96% Power Repairing Essence 3.38 fl.oz',brand:'COSRX',price:17.7,currency:'USD'}));
test('OpenGraph product fallback',async()=>assert.equal(extractFromParts(await fx('og-only'),'zozo.jp').price,1234));
test('non-product page returns null',async()=>assert.equal(extractFromParts(await fx('no-product'),'target.com'),null));
test('malformed JSON-LD does not throw',()=>assert.equal(extractFromParts({jsonLd:['{bad'],meta:{},selectors:{}},'ulta.com'),null));
test('names containing links and very short titles are rejected',()=>{
 for(const name of ['see https://x.y','www.example.com','x']) assert.equal(extractFromParts({jsonLd:[JSON.stringify({'@type':'Product',name})]},'ulta.com'),null);
});
test('offer arrays, whitespace, maximum lengths and invalid prices',()=>{
 const parts={jsonLd:[JSON.stringify({'@type':'Product',name:'  Nice \n toner '+ 'x'.repeat(210),brand:'b'.repeat(90),offers:[{}, {price:'-1',priceCurrency:'USD'}]})]};
 const p=extractFromParts(parts,'ulta.com'); assert.equal(p.name.length,200); assert.equal(p.brand.length,80); assert.equal(p.price,null);
});
test('selectors are Amazon-only and cannot match lookalike hosts',async()=>assert.equal(extractFromParts(await fx('amazon'),'evilamazon.com'),null));
test('DOM adapter reads JSON-LD, metadata, and Amazon selectors',()=>{
 const doc={querySelectorAll:s=>s.startsWith('script')?[{textContent:'{}'}]:[{getAttribute:k=>({property:'og:type',content:'product'})[k]}],querySelector:s=>{const t=({'#productTitle':'Toner','#bylineInfo':'Brand: Anua','.a-price .a-offscreen':'£1,000'})[s];return t===undefined?null:{textContent:t};}};
 assert.deepEqual(readPageParts(doc,'www.amazon.co.uk'),{jsonLd:['{}'],meta:{'og:type':'product'},selectors:{title:'Toner',brand:'Brand: Anua',price:'£1,000'},micro:{}});
});
// Cases measured on live pages, 2026-10-03 (research/events/beforehand-shop-extraction-e2e-20261003-195118.md).
const ld=o=>({jsonLd:[JSON.stringify(o)],meta:{},selectors:{}});
test('JSON-LD ProductGroup with variant offers (Sephora, Next)',()=>{
 assert.deepEqual(extractFromParts(ld({'@type':'ProductGroup',name:'Lip Sleeping Mask',brand:{name:'LANEIGE'},hasVariant:[{'@type':'Product',offers:{price:'24.00',priceCurrency:'USD'}}]}),'www.sephora.com'),
  {name:'Lip Sleeping Mask',brand:'LANEIGE',price:24,currency:'USD'});
 assert.equal(extractFromParts(ld({'@type':'ProductGroup',name:'FatFace Sling Bag',brand:'Fat Face'}),'www.next.co.uk').name,'FatFace Sling Bag');
});
test('microdata fallback (Boots, @cosme)',()=>{
 const p=extractFromParts({jsonLd:[],meta:{'og:type':'website'},selectors:{},micro:{name:'COSRX ADVANCED SNAIL 96 Mucin Power Essence Gel 100ml',brand:'COSRX',price:'23.00',currency:'GBP'}},'www.boots.com');
 assert.deepEqual(p,{name:'COSRX ADVANCED SNAIL 96 Mucin Power Essence Gel 100ml',brand:'COSRX',price:23,currency:'GBP'});
});
test('momo uses og:title only on momoshop',()=>{
 const parts={jsonLd:[],meta:{'og:title':'【COSRX】96% 蝸牛賦活黏液精華 Advanced Snail 96 Mucin Power Essence'},selectors:{}};
 assert.equal(extractFromParts(parts,'www.momoshop.com.tw').name,'【COSRX】96% 蝸牛賦活黏液精華 Advanced Snail 96 Mucin Power Essence');
 assert.equal(extractFromParts(parts,'www.ulta.com'),null);
});
test('HTML entities are decoded (eBay, Sasa)',()=>{
 assert.equal(extractFromParts(ld({'@type':'Product',name:'Serum for Soothing &amp; Hydrating'}),'www.ebay.com').name,'Serum for Soothing & Hydrating');
 assert.equal(extractFromParts(ld({'@type':'Product',name:'I&#39;MINT Espresso &#x27;mint&#x27;'}),'www.sasa.com.hk').name,"I'MINT Espresso 'mint'");
});
test('store-name noise is removed from titles, ordinary hyphens are kept',()=>{
 const og=t=>({jsonLd:[],meta:{'og:type':'product','og:title':t},selectors:{}});
 assert.equal(extractFromParts(og('COSRX Advanced Snail 96 Mucin Power Essence (3.38 fl.oz) - Walmart.com'),'www.walmart.com').name,'COSRX Advanced Snail 96 Mucin Power Essence (3.38 fl.oz)');
 assert.equal(extractFromParts(og('【楽天市場】[COSRX 公式] 「アドバンスド スネイル96 ムチン パワー エッセンス (100ml)」'),'item.rakuten.co.jp').name,'[COSRX 公式] 「アドバンスド スネイル96 ムチン パワー エッセンス (100ml)」');
 assert.equal(extractFromParts(og('【楽天市場】[COSRX 公式] エッセンス (100ml) 韓国コスメ：COSRX楽天市場店'),'item.rakuten.co.jp').name,'[COSRX 公式] エッセンス (100ml) 韓国コスメ');
 assert.equal(extractFromParts(og('サマーグロウリチュアルキット（スキンケアキット/ギフトセット）｜FEMMUE（ファミュ）のファッション通販 - ZOZO'),'zozo.jp').name,'サマーグロウリチュアルキット（スキンケアキット/ギフトセット）');
 assert.equal(extractFromParts(og('Anti-Aging Night Cream - Rich'),'www.target.com').name,'Anti-Aging Night Cream - Rich');
});
test('a brand that is just the store name is dropped',()=>{
 assert.equal(extractFromParts(ld({'@type':'Product',name:'Mint candy',brand:'香港莎莎網店'}),'www.sasa.com.hk').brand,null);
 assert.equal(extractFromParts(ld({'@type':'Product',name:'Mint candy',brand:'Walmart.com'}),'www.walmart.com').brand,null);
});
test('DOM adapter reads only the Product\'s own microdata, skipping breadcrumb items',()=>{
 // Minimal element tree: root(Product) > [breadcrumb ListItem > name "TOP"], name, brand(Brand) > name, offers(Offer) > price, priceCurrency
 const mk=(attrs,text='',children=[])=>{const e={attrs,textContent:text,children,parentElement:null,
  hasAttribute:k=>k in attrs,getAttribute:k=>attrs[k]??null,
  closest(sel){let n=this;while(n){if(sel==='[itemscope]'&&'itemscope' in n.attrs) return n;n=n.parentElement;}return null;},
  querySelectorAll(sel){const m=/^\[itemprop="(.+)"\]$/.exec(sel);const out=[];const walk=x=>{for(const c of x.children){if(m&&c.attrs.itemprop===m[1]) out.push(c);walk(c);}};walk(this);return out;}};
  for(const c of children) c.parentElement=e; return e;};
 const crumb=mk({itemscope:'',itemtype:'http://schema.org/ListItem'},'',[mk({itemprop:'name'},'TOP')]);
 const brand=mk({itemprop:'brand',itemscope:'',itemtype:'http://schema.org/Brand'},'',[mk({itemprop:'name'},' COSRX ')]);
 const offer=mk({itemprop:'offers',itemscope:'',itemtype:'http://schema.org/Offer'},'',[mk({itemprop:'price',content:'2530'}),mk({itemprop:'priceCurrency',content:'JPY'})]);
 const root=mk({itemscope:'',itemtype:'http://schema.org/Product'},'',[crumb,mk({itemprop:'name'},'  '),mk({itemprop:'name'},' The Ceramide Moisturizer / 80mL '),brand,offer]);
 const doc={querySelectorAll:()=>[],querySelector:s=>s==='[itemscope][itemtype*="schema.org/Product"]'?root:null};
 assert.deepEqual(readPageParts(doc,'www.cosme.com').micro,{name:'The Ceramide Moisturizer / 80mL',brand:'COSRX',price:'2530',currency:'JPY'});
});
