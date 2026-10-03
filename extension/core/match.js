export const KC_ENDPOINT='https://concierge.youngji.kim/api/mcp';
export const DESTINATIONS=Object.freeze(['US','GB','JP','CN','TW','HK']);
export class MatchError extends Error {
 constructor(code='malformed') {super(({rate_limited:'Too many checks. Try again in a few minutes.',unavailable:'Korea check is unavailable right now.',malformed:'Korea check returned an invalid response.'})[code]);this.code=code;}
}
const malformed=()=>{throw new MatchError('malformed');};
const text=(v,min=0,max=10000)=>typeof v==='string' && v.length>=min && v.length<=max?v:malformed();
const amount=v=>typeof v==='number' && Number.isFinite(v) && v>=0?v:malformed();
const keys=(v,expected)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join(',')===[...expected].sort().join(',');
function matchArgs({name,brand,destination,fresh=false}) {
 name=text(name,2,200).trim(); if(name.length<2 || /http|www\./i.test(name) || !DESTINATIONS.includes(destination) || typeof fresh!=='boolean') malformed();
 const args={name};
 if(brand!=null) {brand=text(brand,0,80).trim(); if(brand) args.brand=brand;}
 args.destination=destination; if(fresh) args.fresh=true;
 return args;
}
function checkoutArgs({quoteToken,email,name}) {
 text(quoteToken,10,8000); email=text(email,1,200).trim(); name=text(name,1,120).trim();
 if(!name || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) malformed();
 return {quoteToken,email,name};
}
const request=(kind,name,args)=>Object.freeze({kind,url:KC_ENDPOINT,method:'POST',body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{name,arguments:args}})});
export const matchRequest=input=>request('match','match_korea_product',matchArgs(input));
export const checkoutRequest=input=>request('checkout','start_bestseller_checkout',checkoutArgs(input));
export function validRequest(req) {
 try {
  if(!keys(req,['kind','url','method','body']) || req.url!==KC_ENDPOINT || req.method!=='POST' || typeof req.body!=='string') return false;
  const rpc=JSON.parse(req.body);
  if(!keys(rpc,['jsonrpc','id','method','params']) || rpc.jsonrpc!=='2.0' || rpc.id!==1 || rpc.method!=='tools/call' || !keys(rpc.params,['name','arguments'])) return false;
  const match=req.kind==='match'; if(!match && req.kind!=='checkout') return false;
  if(rpc.params.name!==(match?'match_korea_product':'start_bestseller_checkout')) return false;
  const args=rpc.params.arguments, canonical=match?matchArgs(args):checkoutArgs(args);
  return keys(args,Object.keys(canonical)) && Object.keys(canonical).every(k=>args[k]===canonical[k]);
 } catch {return false;}
}
export function safeLink(v) {
 try {const u=new URL(v);return u.protocol==='https:' && !u.username && !u.password?v:null;} catch {return null;}
}
export function sanitizeQuote(raw) {
 try {
  const p=raw.payNow,d=raw.dutyOnDelivery,i=raw.item,l=raw.localPrice;
  const quote={seller:text(raw.seller,1,120),item:{title:text(i.title,2,300),priceKrw:amount(i.priceKrw),link:safeLink(i.link)},destination:text(raw.destination),currency:text(raw.currency),
   payNow:Object.fromEntries(['total','totalKrw','itemKrw','shippingKrw','serviceFeeKrw','paymentFeeKrw','fxRate'].map(k=>[k,amount(p[k])])),
   dutyOnDelivery:{estimate:amount(d.estimate),note:text(d.note),lines:d.lines.map(line=>({label:text(line.label),rate:text(line.rate),amount:amount(line.amount),source:text(line.source)}))},
   totalCost:amount(raw.totalCost),localPrice:l?.price==null?null:{price:amount(l.price),url:safeLink(l.url)},verdict:raw.verdict==null?null:text(raw.verdict),warnings:raw.warnings.map(v=>text(v))};
  if(!DESTINATIONS.includes(quote.destination) || !/^[A-Z]{3}$/.test(quote.currency)) malformed();
  if(raw.quoteToken!=null) quote.quoteToken=text(raw.quoteToken,10,8000);
  if(raw.quoteExpiresAt!=null) {quote.quoteExpiresAt=text(raw.quoteExpiresAt,1,80);if(!Number.isFinite(Date.parse(quote.quoteExpiresAt))) malformed();}
  return quote;
 } catch(e) {if(e instanceof MatchError) throw e; malformed();}
}
function dataFromRPC(raw) {
 if(!raw || typeof raw!=='object') malformed();
 if(raw.error) throw new MatchError(raw.error.code===-32000 && /rate limit/i.test(String(raw.error.message))?'rate_limited':'unavailable');
 const result=raw.result; if(!result || typeof result!=='object') malformed();
 if(result.isError) throw new MatchError('unavailable');
 if(result.structuredContent!=null) return result.structuredContent;
 const texts=(result.content ?? []).filter(v=>v?.type==='text'); if(texts.length!==1) malformed();
 try {return JSON.parse(texts[0].text);} catch {malformed();}
}
export function parseMatchRPC(raw) {
 try {
  const data=dataFromRPC(raw);
  if(data.kind==='rate_limited' || data.kind==='unavailable') throw new MatchError(data.kind);
  if(data.kind==='same') return {kind:'same',quote:sanitizeQuote(data.quote)};
  if(data.kind==='alternatives') {
   if(!Array.isArray(data.items) || !data.items.length) malformed();
   return {kind:'alternatives',items:data.items.slice(0,2).map(i=>({title:text(i.title,2,300),why:text(i.why,0,120),quote:sanitizeQuote(i.quote)}))};
  }
  if(data.kind==='none' || data.kind==='cant_ship') return {kind:data.kind,message:text(data.message,1,500)};
  malformed();
 } catch(e) {if(e instanceof MatchError) throw e; malformed();}
}
export function parseCheckoutRPC(raw) {
 const data=dataFromRPC(raw),url=safeLink(data?.checkoutUrl);
 if(!url || new URL(url).host!=='checkout.stripe.com') malformed(); return {checkoutUrl:url};
}
