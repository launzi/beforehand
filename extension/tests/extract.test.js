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
 const doc={querySelectorAll:s=>s.startsWith('script')?[{textContent:'{}'}]:[{getAttribute:k=>({property:'og:type',content:'product'})[k]}],querySelector:s=>({textContent:({'#productTitle':'Toner','#bylineInfo':'Brand: Anua','.a-price .a-offscreen':'£1,000'})[s]})};
 assert.deepEqual(readPageParts(doc,'www.amazon.co.uk'),{jsonLd:['{}'],meta:{'og:type':'product'},selectors:{title:'Toner',brand:'Brand: Anua',price:'£1,000'}});
});
