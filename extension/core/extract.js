(()=>{
 const onHost=(host,list)=>list.some(h=>host===h || host.endsWith('.'+h));
 const amazon=host=>onHost(host,['amazon.com','amazon.co.uk','amazon.co.jp']);
 // Shops whose product name is only in og:title (no og:type, no JSON-LD) — measured 2026-10-03.
 const OG_TITLE_SHOPS=['momoshop.com.tw'];
 // Store names that appear as title suffixes/prefixes or as a fake brand. Matching is anchored, so
 // ordinary hyphens inside product names are left alone.
 const STORE_SUFFIX=/\s*[|｜\-–—]\s*(?:walmart\.com|amazon\.(?:com|co\.uk|co\.jp)|ebay|target|ulta(?: beauty)?|sephora|argos|boots|lookfantastic|next(?: uk)?|hktvmall[^|｜]*|pchome[^|｜]*|香港莎莎網店|香港屈臣氏|watsons)\s*$/i;
 const ZOZO_SUFFIX=/\s*｜[^｜]*通販\s*-\s*ZOZO(?:TOWN)?\s*$/;
 const STORE_PREFIX=/^\s*【(?:楽天市場|楽天)】\s*/;
 const RAKUTEN_SHOP_SUFFIX=/\s*[：:][^：:]*楽天市場店\s*$/;
 const STORE_BRANDS=/^(?:walmart(?:\.com)?|amazon(?:\.com)?|ebay|target|香港莎莎網店|莎莎|sasa|香港屈臣氏|屈臣氏|watsons|hktvmall)$/i;
 const ENTITIES={amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:' '};
 // Decodes HTML entities without a DOM: content scripts must not parse page strings as HTML.
 const decode=s=>s.replace(/&(?:#(\d{1,7})|#x([0-9a-f]{1,6})|([a-z]{2,6}));/gi,(m,d,h,n)=>{
  if(n) return ENTITIES[n.toLowerCase()] ?? m;
  const cp=d?Number(d):parseInt(h,16);
  return cp>0 && cp<=0x10ffff && !(cp>=0xd800 && cp<=0xdfff) ? String.fromCodePoint(cp) : m;
 });
 const clean=(v,max)=>typeof v==='string'?decode(v).replace(/\s+/g,' ').trim().slice(0,max):'';
 const tidyName=v=>clean(v,400).replace(STORE_PREFIX,'').replace(ZOZO_SUFFIX,'').replace(RAKUTEN_SHOP_SUFFIX,'').replace(STORE_SUFFIX,'').trim();
 function number(v) {
  if(typeof v!=='string' && typeof v!=='number') return null;
  const n=Number(String(v).replace(/[,\s$£¥￥]/g,''));
  return Number.isFinite(n)&&n>0?n:null;
 }
 function* nodes(value) {
  if(Array.isArray(value)) {for(const node of value) yield* nodes(node);}
  else if(value && typeof value==='object') {yield value; if(value['@graph']) yield* nodes(value['@graph']);}
 }
 const isProduct=node=>[].concat(node['@type'] ?? []).some(t=>t==='Product' || t==='ProductGroup');
 function offerOf(node) {
  const variants=[].concat(node.hasVariant ?? []).flatMap(v=>[].concat(v?.offers ?? []));
  return [...[].concat(node.offers ?? []),...variants].find(o=>o && (o.price!=null || o.lowPrice!=null)) ?? {};
 }
 function extractFromParts(parts={},shopHost='') {
  let raw=null;
  for(const source of parts.jsonLd ?? []) {
   let data; try {data=JSON.parse(source);} catch {continue;}
   for(const node of nodes(data)) {
    if(isProduct(node)) {
     const offer=offerOf(node);
     raw={name:node.name,brand:typeof node.brand==='string'?node.brand:node.brand?.name,price:offer.price ?? offer.lowPrice,currency:offer.priceCurrency}; break;
    }
   }
   if(raw) break;
  }
  const meta=parts.meta ?? {}, selectors=parts.selectors ?? {}, micro=parts.micro ?? {};
  if(!raw && /product/i.test(meta['og:type'] ?? '')) raw={name:meta['og:title'],brand:meta['product:brand'],price:meta['product:price:amount'],currency:meta['product:price:currency']};
  if(!raw && micro.name) raw={name:micro.name,brand:micro.brand,price:micro.price,currency:micro.currency};
  if(!raw && onHost(shopHost,OG_TITLE_SHOPS) && meta['og:title']) raw={name:meta['og:title']};
  if(!raw && amazon(shopHost) && selectors.title) raw={name:selectors.title,
   brand:clean(selectors.brand,200).replace(/^Visit the\s+/i,'').replace(/^Brand:\s*/i,'').replace(/\s+Store$/i,''),
   price:selectors.price,currency:/£/.test(selectors.price)?'GBP':/[¥￥]/.test(selectors.price)?'JPY':/\$/.test(selectors.price)?'USD':null};
  if(!raw || /http|www\./i.test(String(raw.name ?? ''))) return null;
  const name=tidyName(raw.name).slice(0,200); if(name.length<2) return null;
  const brand=clean(raw.brand,80);
  return {name,brand:brand && !STORE_BRANDS.test(brand) ? brand : null,price:number(raw.price),currency:/^[A-Z]{3}$/.test(raw.currency ?? '')?raw.currency:null};
 }
 const text=el=>el ? (el.getAttribute('content') ?? el.textContent ?? '').trim() : '';
 // The itemscope an element's itemprop belongs to: for a nested item (itemscope on the element
 // itself) that is the enclosing scope. Breadcrumb ListItems inside a Product page are skipped.
 const owner=el=>(el.hasAttribute('itemscope') ? el.parentElement : el)?.closest('[itemscope]') ?? null;
 // Empty placeholders (seen on Boots) are skipped; nested items count as present (brand, offers).
 const prop=(scope,name)=>scope ? Array.from(scope.querySelectorAll(`[itemprop="${name}"]`)).find(el=>owner(el)===scope && (el.hasAttribute('itemscope') || text(el))) ?? null : null;
 function readMicrodata(doc) {
  const root=doc.querySelector('[itemscope][itemtype*="schema.org/Product"]');
  if(!root) return {};
  const brandEl=prop(root,'brand'), offer=prop(root,'offers');
  const brand=brandEl ? (text(prop(brandEl,'name')) || text(brandEl)) : '';
  return {name:text(prop(root,'name')),brand,price:text(prop(root,'price') ?? prop(offer,'price')),currency:text(prop(root,'priceCurrency') ?? prop(offer,'priceCurrency'))};
 }
 function readPageParts(doc,shopHost) {
  const jsonLd=Array.from(doc.querySelectorAll('script[type="application/ld+json"]'),s=>s.textContent);
  const meta={};
  for(const el of doc.querySelectorAll('meta[property], meta[name]')) {
   const key=el.getAttribute('property') || el.getAttribute('name'); if(key) meta[key]=el.getAttribute('content') ?? '';
  }
  const selectors={};
  if(amazon(shopHost)) for(const [key,selector] of Object.entries({title:'#productTitle',brand:'#bylineInfo',price:'.a-price .a-offscreen'})) selectors[key]=doc.querySelector(selector)?.textContent ?? '';
  return {jsonLd,meta,selectors,micro:readMicrodata(doc)};
 }
 globalThis.BeforehandExtract={extractFromParts,readPageParts};
})();
