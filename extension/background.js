import {shopFor,defaultDestination} from './core/shops.js';
import {matchRequest,checkoutRequest,MatchError,parseMatchRPC} from './core/match.js';
import {sendRequest} from './core/sink.js';
import {getSettings,requireConsent,hasConsent,appendTrace,RESULT_CACHE_MS,DAILY_AUTO_LIMIT,withStorageLock} from './core/storage.js';
const selected=(r,c)=>c==='same'?(r?.kind==='same'?r.quote:null):([0,1].includes(c)&&r?.kind==='alternatives'?r.items[c]?.quote:null);
const stripTokens=result=>JSON.parse(JSON.stringify(result,(key,value)=>['quoteToken','quoteExpiresAt'].includes(key)?undefined:value));
const quoteSnapshot=q=>q && ({title:q.item.title,link:q.item.link,currency:q.currency,totalCost:q.totalCost,payNow:{total:q.payNow.total},dutyOnDelivery:{estimate:q.dutyOnDelivery.estimate}});
const sameQuote=(a,b)=>a && b && a.title===b.item.title && a.link===b.item.link && a.currency===b.currency && a.totalCost===b.totalCost && a.payNow.total===b.payNow.total && a.dutyOnDelivery.estimate===b.dutyOnDelivery.estimate;
export function createBackground({chrome,fetchImpl,now=()=>Date.now()}) {
 const storage=chrome.storage.local,session=chrome.storage.session,memory=new Map(); let queue=Promise.resolve();
 const ready=session.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});
 chrome.storage.onChanged?.addListener((changes,area)=>{if(area==='local' && (changes.consent || changes.destination)) memory.clear();});
 const send=req=>sendRequest(req,{storage,fetchImpl});
 async function status(sender) {
  let host=''; try {const u=new URL(sender.url ?? sender.tab?.url);if(u.protocol==='https:') host=u.hostname;} catch { /* Untrusted or absent sender. */ }
  const settings=await getSettings(storage),shop=shopFor(host);
  return {...settings,shop,shopEnabled:!!shop && !settings.disabledShops.includes(shop.host),destination:settings.destination ?? defaultDestination(host)};
 }
 async function cacheRead(key) {
  const {resultCache=[]}=await storage.get('resultCache');
  const entries=Array.isArray(resultCache)?resultCache.filter(e=>e && now()-e.at<RESULT_CACHE_MS && e.at<=now()).slice(-200):[];
  const entry=entries.find(e=>e.key===key);
  if(!entry) return null;
  try {return parseMatchRPC({result:{structuredContent:entry.result}});} catch {return null;}
 }
 async function run(msg,sender) {
  await ready;
  const state=await status(sender);
  if(msg?.type==='status') return {onboarded:state.onboarded,autoCheck:state.autoCheck,shopEnabled:state.shopEnabled,destination:state.destination};
  if(!state.onboarded || !state.shopEnabled || (sender.frameId!=null && sender.frameId!==0)) throw new MatchError('unavailable');
  if(!['match','buy'].includes(msg?.type)) throw new MatchError('malformed');
  let record;
  if(msg.type==='buy') {
   const {snapshots={}}=await session.get('snapshots');
   record=typeof msg.handle==='string' && Object.hasOwn(snapshots,msg.handle)?snapshots[msg.handle]:null;
   if(!record || record.tabId!==sender.tab?.id || (record.documentId && record.documentId!==sender.documentId)) return {error:'changed'};
  }
  const input=record?record.snapshot:{name:msg.product?.name,brand:msg.product?.brand,destination:state.destination};
  const req=matchRequest(input),args=JSON.parse(req.body).params.arguments;
  const key=JSON.stringify([args.name,args.brand ?? '',args.destination]);
  const consent=await requireConsent(storage);
  if(record && (record.revision!==consent.revision || record.snapshot.destination!==state.destination)) throw new MatchError('unavailable');
  async function stillAllowed() {
   const current=await requireConsent(storage),s=await status(sender);
   if(current.revision!==consent.revision || !s.shopEnabled || s.destination!==state.destination || (msg.type==='match' && msg.manual!==true && !s.autoCheck)) throw new MatchError('unavailable');
  }
  async function lookup(fresh=false) {
   if(!fresh) {
    const cached=await cacheRead(key); if(cached) return cached;
    if(msg.manual!==true) {
     const allowed=await withStorageLock(storage,async()=>{
      await stillAllowed(); const d=new Date(now()),day=[d.getFullYear(),d.getMonth()+1,d.getDate()].join('-');
      const {autoCount}=await storage.get('autoCount'); const count=autoCount?.day===day && Number.isFinite(autoCount.count)?autoCount.count:0;
      if(count>=DAILY_AUTO_LIMIT) return false; await storage.set({autoCount:{day,count:count+1}});return true;
     }); if(!allowed) return {kind:'paused'};
    }
   }
   const epoch=(await storage.get('traceEpoch')).traceEpoch ?? null;
   await appendTrace(storage,{kind:'match_sent',shop:state.shop.host,name:args.name,brand:args.brand,destination:args.destination},now(),epoch);
   await stillAllowed();
   const result=await send(fresh?matchRequest({...args,fresh:true}):req);
   await stillAllowed();
   await withStorageLock(storage,async()=>{
    await stillAllowed(); const {resultCache=[]}=await storage.get('resultCache');
    const entries=(Array.isArray(resultCache)?resultCache:[]).filter(e=>e.key!==key && now()-e.at<RESULT_CACHE_MS);
    entries.push({key,at:now(),result:stripTokens(result)}); await storage.set({resultCache:entries.slice(-200)});
   });
   // A deleted log stays deleted even when an earlier request completes.
   await appendTrace(storage,{kind:'match_result',shop:state.shop.host,result:result.kind},now(),epoch);
   return result;
  }
  if(msg.type==='match') {
   if(msg.manual!==true && !state.autoCheck) throw new MatchError('unavailable');
   const result=await lookup(),publicResult=stripTokens(result);
   if(!['same','alternatives'].includes(result.kind)) return publicResult;
   if(!Number.isInteger(sender.tab?.id)) throw new MatchError('unavailable');
   const handle=crypto.randomUUID(),choices={};
   for(const choice of ['same',0,1]) {const q=selected(result,choice);if(q)choices[choice]=quoteSnapshot(q);}
   const {snapshots={}}=await session.get('snapshots');
   snapshots[handle]={tabId:sender.tab.id,documentId:sender.documentId ?? null,shop:state.shop.host,revision:consent.revision,
    snapshot:{name:args.name,brand:args.brand ?? '',destination:args.destination,choices}};
   const handles=Object.keys(snapshots);
   for(const old of handles.slice(0,Math.max(0,handles.length-200))) {delete snapshots[old];memory.delete(old);}
   await session.set({snapshots});
   memory.set(handle,result);
   return {...publicResult,handle};
  }
  // Validate identity before spending a refresh; never persist it.
  checkoutRequest({quoteToken:'VALIDATION_ONLY_TOKEN',email:msg.email,name:msg.name});
  const prior=record.snapshot.choices[msg.choice];
  if(!['same',0,1].includes(msg.choice) || !prior) return {error:'changed'};
  let q=selected(memory.get(msg.handle),msg.choice);
  if(!q?.quoteToken || !(Date.parse(q.quoteExpiresAt)-60000>now())) {
   const fresh=await lookup(true),next=selected(fresh,msg.choice);
   if(!sameQuote(prior,next)) return {error:'changed'};
   memory.set(msg.handle,fresh);q=next;
  }
  if(!sameQuote(prior,q)) return {error:'changed'};
  if(!q.quoteToken || !(Date.parse(q.quoteExpiresAt)-60000>now())) throw new MatchError('unavailable');
  await stillAllowed();
  const {checkoutUrl}=await send(checkoutRequest({quoteToken:q.quoteToken,email:msg.email,name:msg.name}));
  await stillAllowed(); await chrome.tabs.create({url:checkoutUrl});
  await appendTrace(storage,{kind:'checkout_opened',shop:state.shop.host},now()); return {ok:true};
 }
 async function onMessage(msg,sender={}) {
  const task=queue.then(()=>run(msg,sender));queue=task.catch(()=>{});
  try {return await task;} catch(e) {return {kind:e instanceof MatchError?e.code:'unavailable'};}
 }
 async function onInstalled({reason}) {
  // Clear retired provider credentials and old logs on the v4 migration.
  const value=await storage.get('consent');
  if(reason==='update' && !hasConsent(value)) await storage.clear();
  if(reason==='install' || (reason==='update' && !hasConsent(value))) await chrome.tabs.create({url:chrome.runtime.getURL('welcome.html')});
 }
 return {onMessage,onInstalled};
}
if(globalThis.chrome?.runtime?.onMessage) {
 const bg=createBackground({chrome:globalThis.chrome});
 chrome.runtime.onMessage.addListener((m,s,send)=>{bg.onMessage(m,s).then(send);return true;});
 chrome.runtime.onInstalled.addListener(details=>{void bg.onInstalled(details);});
 // Content scripts receive no direct access to consent, settings, cache or log.
 chrome.storage.local.setAccessLevel?.({accessLevel:'TRUSTED_CONTEXTS'});
}
