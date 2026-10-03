import {shopFor,defaultDestination} from './core/shops.js';
import {matchRequest,checkoutRequest,MatchError,parseMatchRPC} from './core/match.js';
import {sendRequest} from './core/sink.js';
import {getSettings,requireConsent,hasConsent,appendTrace,RESULT_CACHE_MS,DAILY_AUTO_LIMIT,withStorageLock} from './core/storage.js';
const selected=(r,c)=>c==='same'?(r?.kind==='same'?r.quote:null):([0,1].includes(c)&&r?.kind==='alternatives'?r.items[c]?.quote:null);
const stripTokens=result=>JSON.parse(JSON.stringify(result,(key,value)=>['quoteToken','quoteExpiresAt'].includes(key)?undefined:value));
const sameQuote=(a,b)=>a && b && a.item.title===b.item.title && a.item.link===b.item.link && a.currency===b.currency && a.totalCost===b.totalCost;
export function createBackground({chrome,fetchImpl,now=()=>Date.now()}) {
 const storage=chrome.storage.local,memory=new Map(); let queue=Promise.resolve();
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
  const state=await status(sender);
  if(msg?.type==='status') return {onboarded:state.onboarded,autoCheck:state.autoCheck,shopEnabled:state.shopEnabled,destination:state.destination};
  if(!state.onboarded || !state.shopEnabled || (sender.frameId!=null && sender.frameId!==0)) throw new MatchError('unavailable');
  if(!['match','buy'].includes(msg?.type)) throw new MatchError('malformed');
  const input={name:msg.product?.name,brand:msg.product?.brand,destination:state.destination};
  const req=matchRequest(input),args=JSON.parse(req.body).params.arguments;
  const key=JSON.stringify([args.name,args.brand ?? '',args.destination]);
  const consent=await requireConsent(storage);
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
   await appendTrace(storage,{kind:'match_sent',shop:state.shop.host,name:args.name,brand:args.brand,destination:args.destination},now());
   const result=await send(fresh?matchRequest({...args,fresh:true}):req);
   await stillAllowed();
   await withStorageLock(storage,async()=>{
    await stillAllowed(); const {resultCache=[]}=await storage.get('resultCache');
    const entries=(Array.isArray(resultCache)?resultCache:[]).filter(e=>e.key!==key && now()-e.at<RESULT_CACHE_MS);
    entries.push({key,at:now(),result:stripTokens(result)}); await storage.set({resultCache:entries.slice(-200)});
   });
   memory.set(key,{at:now(),result}); if(memory.size>200) memory.delete(memory.keys().next().value);
   // A deleted log stays deleted even when an earlier request completes.
   if(((await storage.get('traceEpoch')).traceEpoch ?? null)===epoch) await appendTrace(storage,{kind:'match_result',shop:state.shop.host,result:result.kind},now());
   return result;
  }
  if(msg.type==='match') {
   if(msg.manual!==true && !state.autoCheck) throw new MatchError('unavailable');
   return lookup();
  }
  // Validate identity before spending a refresh; never persist it.
  checkoutRequest({quoteToken:'VALIDATION_ONLY_TOKEN',email:msg.email,name:msg.name});
  const mem=memory.get(key),prior=mem && now()-mem.at<RESULT_CACHE_MS?mem.result:await cacheRead(key);
  let q=selected(prior,msg.choice); if(!q) return {error:'changed'};
  if(!q.quoteToken || Date.parse(q.quoteExpiresAt)-60000<=now() || !Number.isFinite(Date.parse(q.quoteExpiresAt))) {
   const fresh=await lookup(true),next=selected(fresh,msg.choice);
   if(!sameQuote(q,next)) return {error:'changed'}; q=next;
  }
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
