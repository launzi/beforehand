import {scrubText} from './scrub.js';
export const KC_API='https://concierge.youngji.kim/api/commerce/v1';
export const DESTINATIONS=Object.freeze(['US','GB','JP','CN','TW','HK']);
export class MatchError extends Error {
 constructor(code='malformed') {super(({rate_limited:'Too many checks. Try again in a few minutes.',unavailable:'Korea check is unavailable right now.',malformed:'Korea check returned an invalid response.'})[code]);this.code=code;}
}
const malformed=()=>{throw new MatchError('malformed');};
const text=(v,min=0,max=10000)=>typeof v==='string' && v.length>=min && v.length<=max?v:malformed();
const amount=v=>typeof v==='number' && Number.isFinite(v) && v>=0?v:malformed();
const keys=(v,expected)=>v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join(',')===[...expected].sort().join(',');
function matchArgs({name,brand,destination,fresh=false}) {
 name=text(name,2,200).trim(); if(/\[(?:URL|email|credential|long identifier|number) removed\]/.test(scrubText(name,10000))) malformed();
 if(name.length<2 || /http|www\./i.test(name) || !DESTINATIONS.includes(destination) || typeof fresh!=='boolean') malformed();
 const args={name};
 if(brand!=null) {brand=text(brand,0,80).trim(); if(/\[(?:URL|email|credential|long identifier|number) removed\]/.test(scrubText(brand,10000))) malformed(); if(brand) args.brand=brand;}
 args.destination=destination; if(fresh) args.fresh=true;
 return args;
}
function checkoutArgs({quoteToken,email,name,method}) {
 text(quoteToken,10,8000); email=text(email,1,200).trim(); name=text(name,1,120).trim();
 if(!name || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !['card','paypal'].includes(method)) malformed();
 return {quoteToken,email,name,method};
}
const request=(kind,path,args)=>Object.freeze({kind,url:KC_API+path,method:'POST',body:JSON.stringify(args)});
export const matchRequest=input=>request('match','/matches',matchArgs(input));
export const checkoutRequest=input=>request('checkout','/checkout',checkoutArgs(input));
export function validRequest(req) {
 try {
  if(!keys(req,['kind','url','method','body']) || req.method!=='POST' || typeof req.body!=='string') return false;
  const match=req.kind==='match'; if(!match && req.kind!=='checkout') return false;
  if(req.url!==KC_API+(match?'/matches':'/checkout')) return false;
  const args=JSON.parse(req.body),canonical=match?matchArgs(args):checkoutArgs(args);
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
// Display fields are optional and lenient: a bad value is dropped, never fatal, so older KC results still parse.
const optText=(v,max)=>typeof v==='string' && v.trim() && v.length<=max && !/[\u0000-\u001f]/.test(v)?v.trim():null;
const optBool=v=>typeof v==='boolean'?v:null;
const optSize=v=>v && typeof v==='object' && ['ml','g','count'].includes(v.unit) && typeof v.value==='number' && Number.isFinite(v.value) && v.value>0?{value:v.value,unit:v.unit}:null;
const optPercent=v=>typeof v==='number' && Number.isFinite(v) && v>=0 && v<=100?Math.round(v):null;
const optSource=v=>v && typeof v==='object'?{brand:optText(v.brand,60),typeEn:optText(v.typeEn,40),size:optSize(v.size)}:{brand:null,typeEn:null,size:null};
export function parseMatchResponse(data) {
 try {
  if(!data || typeof data!=='object' || Array.isArray(data)) malformed();
  if(data.kind==='rate_limited' || data.kind==='unavailable') throw new MatchError(data.kind);
  if(data.kind==='same') return {kind:'same',quote:sanitizeQuote(data.quote),titleEn:optText(data.titleEn,200),matchPercent:optPercent(data.matchPercent),size:optSize(data.size),source:optSource(data.source)};
  if(data.kind==='alternatives') {
   if(!Array.isArray(data.items) || !data.items.length) malformed();
   return {kind:'alternatives',source:optSource(data.source),items:data.items.slice(0,2).map(i=>({title:text(i.title,2,300),why:text(i.why,0,120),quote:sanitizeQuote(i.quote),
    titleEn:optText(i.titleEn,200),sameBrand:optBool(i.sameBrand),sameType:optBool(i.sameType),size:optSize(i.size)}))};
  }
  if(data.kind==='none' || data.kind==='cant_ship') return {kind:data.kind,message:text(data.message,1,500)};
  malformed();
 } catch(e) {if(e instanceof MatchError) throw e; malformed();}
}
export function parseCheckoutResponse(data) {
 const url=safeLink(text(data?.url,1,10000));
 if(!url || !['card','paypal'].includes(data.method) || !['https://checkout.stripe.com','https://www.paypal.com','https://www.sandbox.paypal.com'].includes(new URL(url).origin)) malformed();
 const result={method:data.method,url};
 if(data.orderId!==undefined) result.orderId=text(data.orderId,1,200);
 return result;
}
