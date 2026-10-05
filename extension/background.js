import {shopFor,defaultDestination} from './core/shops.js';
import {matchRequest,checkoutRequest,MatchError,parseMatchResponse} from './core/match.js';
import {sendRequest} from './core/sink.js';
import {getSettings,requireConsent,hasConsent,appendTrace,RESULT_CACHE_MS,RESULT_CACHE_SCHEMA,DAILY_AUTO_LIMIT,withStorageLock} from './core/storage.js';
const selected=(r,c)=>c==='same'?(r?.kind==='same'?r.quote:null):([0,1].includes(c)&&r?.kind==='alternatives'?r.items[c]?.quote:null);
const stripTokens=result=>JSON.parse(JSON.stringify(result,(key,value)=>['quoteToken','quoteExpiresAt'].includes(key)?undefined:value));
const BREAKDOWN=['itemKrw','shippingKrw','serviceFeeKrw','paymentFeeKrw','fxRate'];
const quoteSnapshot=q=>q && ({title:q.item.title,link:q.item.link,currency:q.currency,totalCost:q.totalCost,payNow:{total:q.payNow.total,...Object.fromEntries(BREAKDOWN.map(k=>[k,q.payNow[k]]))},dutyOnDelivery:{estimate:q.dutyOnDelivery.estimate}});
// Search-priced quotes carry a shopping-results link that can change between lookups, so the link is not compared.
const sameQuote=(a,b)=>a && b && a.title===b.item.title && a.currency===b.currency && a.totalCost===b.totalCost && a.payNow.total===b.payNow.total && a.dutyOnDelivery.estimate===b.dutyOnDelivery.estimate;
const allQuotes=r=>r?.kind==='same'?[r.quote]:r?.kind==='alternatives'?r.items.map(i=>i.quote):[];
const tokenOf=q=>q?.quoteToken && q.quoteExpiresAt?{quoteToken:q.quoteToken,quoteExpiresAt:q.quoteExpiresAt}:null;
export function createBackground({chrome,fetchImpl,now=()=>Date.now()}) {
 const storage=chrome.storage.local,session=chrome.storage.session; let queue=Promise.resolve();
 const ready=session.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});
 chrome.storage.onChanged?.addListener((changes,area)=>{if(area==='local' && (changes.consent || changes.destination)) void session.remove?.('quoteTokens');});
 const send=req=>sendRequest(req,{storage,fetchImpl});
 async function status(sender) {
  let host=''; try {const u=new URL(sender.url ?? sender.tab?.url);if(u.protocol==='https:') host=u.hostname;} catch { /* Untrusted or absent sender. */ }
  const settings=await getSettings(storage),shop=shopFor(host);
  return {...settings,shop,shopEnabled:!!shop && !settings.disabledShops.includes(shop.host),destination:settings.destination ?? defaultDestination(host)};
 }
 async function cacheRead(key) {
  const {resultCache=[]}=await storage.get('resultCache');
  const entries=Array.isArray(resultCache)?resultCache.filter(e=>e && e.v===RESULT_CACHE_SCHEMA && now()-e.at<RESULT_CACHE_MS && e.at<=now()).slice(-200):[];
  const entry=entries.find(e=>e.key===key);
  if(!entry) return null;
  try {return parseMatchResponse(entry.result);} catch {return null;}
 }
 async function run(msg,sender) {
  await ready;
  if(msg?.type==='status') {
   const state=await status(sender);
   return {onboarded:state.onboarded,autoCheck:state.autoCheck,shopEnabled:state.shopEnabled,destination:state.destination};
  }
  if(!['match','open_checkout','checkout_snapshot','buy','open_options'].includes(msg?.type)) throw new MatchError('malformed');
  const checkoutPage=['checkout_snapshot','buy'].includes(msg.type);
  const checkoutURL=()=>chrome.runtime.getURL(`checkout.html?h=${encodeURIComponent(msg.handle)}&c=${encodeURIComponent(msg.choice)}`);
  let record;
  if(msg?.type==='open_options') {await chrome.runtime.openOptionsPage?.();return {ok:true};}
  if(msg.type!=='match') {
   const {snapshots={}}=await session.get('snapshots');
   record=typeof msg.handle==='string' && Object.hasOwn(snapshots,msg.handle)?snapshots[msg.handle]:null;
   if(!record || !['same',0,1].includes(msg.choice) || !record.snapshot.choices[msg.choice]) return {error:'changed'};
   if(checkoutPage) {
    if(sender.url!==checkoutURL() || !record.checkouts?.some(c=>c.tabId===sender.tab?.id && c.choice===msg.choice)) return {error:'changed'};
   } else if(record.tabId!==sender.tab?.id || (record.documentId && record.documentId!==sender.documentId)) return {error:'changed'};
  }
  const context=checkoutPage?{url:`https://${record.shop}/`}:sender;
  const state=await status(context);
  if(!state.onboarded || !state.shopEnabled || (sender.frameId!=null && sender.frameId!==0)) throw new MatchError('unavailable');
  const input=record?record.snapshot:{name:msg.product?.name,brand:msg.product?.brand,destination:state.destination};
  const req=matchRequest(input),args=JSON.parse(req.body);
  const key=JSON.stringify([args.name,args.brand ?? '',args.destination]);
  const consent=await requireConsent(storage);
  if(record && (record.revision!==consent.revision || record.snapshot.destination!==state.destination)) throw new MatchError('unavailable');
  async function stillAllowed() {
   const current=await requireConsent(storage),s=await status(context);
   if(current.revision!==consent.revision || !s.shopEnabled || s.destination!==state.destination || (msg.type==='match' && msg.manual!==true && !s.autoCheck)) throw new MatchError('unavailable');
  }
  async function changed() {
   try {await chrome.tabs.sendMessage(record.tabId,{type:'quote_changed',handle:msg.handle},record.documentId?{documentId:record.documentId}:{frameId:0});} catch { /* The source document may have closed. */ }
   return {error:'changed'};
  }
  const live=t=>t?.quoteToken && Date.parse(t.quoteExpiresAt)-60000>now();
  async function saveToken(token) {
   const {quoteTokens={}}=await session.get('quoteTokens');
   if(Object.hasOwn(quoteTokens,msg.handle)) {quoteTokens[msg.handle]={...quoteTokens[msg.handle],[msg.choice]:token};await session.set({quoteTokens});}
  }
  // Resolves the displayed choice to {token}, {repriced} when the same item now costs a different amount,
  // or {gone} when the offer no longer exists. A repriced choice is rebound and must be confirmed before paying.
  async function ensureToken() {
   const prior=record.snapshot.choices[msg.choice];
   const token=((await session.get('quoteTokens')).quoteTokens ?? {})[msg.handle]?.[msg.choice];
   if(live(token)) return {token};
   // The refreshed result may list the same offer under a different kind or position.
   const quotes=allQuotes(await lookup(true)),next=quotes.find(c=>sameQuote(prior,c));
   if(next) {
    const fresh=tokenOf(next);if(!live(fresh)) throw new MatchError('unavailable');
    await saveToken(fresh);return {token:fresh};
   }
   const moved=quotes.find(c=>c.item.title===prior.title && c.currency===prior.currency),fresh=tokenOf(moved);
   if(!moved || !live(fresh)) return {gone:true};
   const {snapshots={}}=await session.get('snapshots');
   if(!Object.hasOwn(snapshots,msg.handle)) return {gone:true};
   snapshots[msg.handle].snapshot.choices[msg.choice]={...quoteSnapshot(moved),titleEn:prior.titleEn ?? null,matchPercent:prior.matchPercent ?? null};await session.set({snapshots});
   record=snapshots[msg.handle];await saveToken(fresh);
   return {repriced:{previous:prior,snapshot:record.snapshot.choices[msg.choice],expiresAt:fresh.quoteExpiresAt}};
  }
  if(msg.type==='open_checkout') {
   await stillAllowed();
   const tab=await chrome.tabs.create({url:checkoutURL()});
   record.checkouts=[...(record.checkouts ?? []),{tabId:tab.id,choice:msg.choice}].slice(-20);
   const {snapshots={}}=await session.get('snapshots');
   snapshots[msg.handle]=record;await session.set({snapshots});
   return {ok:true};
  }
  if(msg.type==='checkout_snapshot') {
   await stillAllowed();
   // Refresh a cached (token-free) quote while the page loads, so a changed price shows before the buyer types.
   const r=await ensureToken();
   if(r.gone) return changed();
   if(r.repriced) {await changed();return {...r.repriced,seller:'Munteok',destination:record.snapshot.destination};}
   return {snapshot:record.snapshot.choices[msg.choice],expiresAt:r.token.quoteExpiresAt,seller:'Munteok',destination:record.snapshot.destination};
  }
  async function lookup(fresh=false) {
   if(!fresh) {
    const cached=await cacheRead(key);
    if(cached) {await stillAllowed();return cached;}
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
    const entries=(Array.isArray(resultCache)?resultCache:[]).filter(e=>e.key!==key && e.v===RESULT_CACHE_SCHEMA && now()-e.at<RESULT_CACHE_MS);
    entries.push({key,v:RESULT_CACHE_SCHEMA,at:now(),result:stripTokens(result)}); await storage.set({resultCache:entries.slice(-200)});
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
   const handle=crypto.randomUUID(),choices={},tokens={};
   const display=choice=>choice==='same'?{titleEn:result.titleEn ?? null,matchPercent:result.matchPercent ?? null}:{titleEn:result.items?.[choice]?.titleEn ?? null,matchPercent:null};
   for(const choice of ['same',0,1]) {const q=selected(result,choice);if(q){choices[choice]={...quoteSnapshot(q),...display(choice)};const t=tokenOf(q);if(t)tokens[choice]=t;}}
   const {snapshots={},quoteTokens={}}=await session.get(['snapshots','quoteTokens']);
   snapshots[handle]={tabId:sender.tab.id,documentId:sender.documentId ?? null,shop:state.shop.host,revision:consent.revision,
    snapshot:{name:args.name,brand:args.brand ?? '',destination:args.destination,choices}};
   const handles=Object.keys(snapshots);
   for(const old of handles.slice(0,Math.max(0,handles.length-200))) {delete snapshots[old];delete quoteTokens[old];}
   for(const old of Object.keys(quoteTokens)) if(!Object.hasOwn(snapshots,old)) delete quoteTokens[old];
   quoteTokens[handle]=tokens;
   // Tokens live in trusted, in-memory session storage so an idle worker restart does not force a re-check mid-checkout.
   await session.set({snapshots,quoteTokens});
   return {...publicResult,handle};
  }
  // Validate identity before spending a refresh; never persist it.
  checkoutRequest({quoteToken:'VALIDATION_ONLY_TOKEN',email:msg.email,name:msg.name,method:msg.method});
  const prior=record.snapshot.choices[msg.choice];
  if(!['same',0,1].includes(msg.choice) || !prior) return {error:'changed'};
  const r=await ensureToken();
  if(r.gone) return changed();
  if(r.repriced) {await changed();return {error:'changed',...r.repriced};}
  const {token}=r;
  await stillAllowed();
  const {url}=await send(checkoutRequest({quoteToken:token.quoteToken,email:msg.email,name:msg.name,method:msg.method}));
  await stillAllowed(); await chrome.tabs.update(sender.tab.id,{url});
  await appendTrace(storage,{kind:'checkout_opened',shop:state.shop.host},now()); return {ok:true};
 }
 async function onMessage(msg,sender={}) {
  const task=queue.then(()=>run(msg,sender));queue=task.catch(()=>{});
  try {return await task;} catch(e) {return {kind:e instanceof MatchError?e.code:'unavailable'};}
 }
 async function onInstalled({reason}) {
  // v3 and older held retired provider credentials, so updating from them clears local data.
  // From v4 on, settings and the log are kept and only fresh consent is asked for.
  const value=await storage.get('consent');
  if(reason==='update' && !hasConsent(value) && !(value?.consent?.version>=4)) await storage.clear();
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
