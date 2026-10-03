import {DESTINATIONS} from './match.js';
import {shopFor} from './shops.js';
export const DISCLOSURE_VERSION=4;
export const RESULT_CACHE_MS=24*3600*1000, DAILY_AUTO_LIMIT=200, TRACE_LIMIT=500, TRACE_DAYS=30;
export const hasConsent=value=>value?.consent?.accepted===true && value.consent.version===DISCLOSURE_VERSION;
export async function requireConsent(storage) {
 const value=await storage?.get('consent');
 if(!hasConsent(value)) throw new Error('Read and agree to the current disclosure first.');
 return value.consent;
}
const queues=new WeakMap();
export function withStorageLock(storage,fn) {
 if(globalThis.navigator?.locks?.request) return navigator.locks.request('beforehand-storage-v4',fn);
 const work=(queues.get(storage) ?? Promise.resolve()).then(fn); queues.set(storage,work.catch(()=>{})); return work;
}
export const acceptConsent=(storage,{autoCheck})=>withStorageLock(storage,()=>storage.set({consent:{accepted:true,version:DISCLOSURE_VERSION,revision:crypto.randomUUID()},autoCheck:autoCheck===true}));
export async function getSettings(storage) {
 const v=await storage.get(['consent','autoCheck','disabledShops','destination']);
 return {onboarded:hasConsent(v),autoCheck:hasConsent(v) && v.autoCheck===true,
 disabledShops:Array.isArray(v.disabledShops)?[...new Set(v.disabledShops.filter(h=>shopFor(h)?.host===h))]:[],destination:DESTINATIONS.includes(v.destination)?v.destination:null};
}
export async function updateSettings(storage,changes) {
 return withStorageLock(storage,async()=>{
  await requireConsent(storage); const patch={};
  if(typeof changes.autoCheck==='boolean') patch.autoCheck=changes.autoCheck;
  if(Array.isArray(changes.disabledShops)) patch.disabledShops=[...new Set(changes.disabledShops.filter(h=>shopFor(h)?.host===h))];
  if(changes.destination===null || DESTINATIONS.includes(changes.destination)) patch.destination=changes.destination;
  await storage.set(patch);
 });
}
const traceFields={match_sent:['shop','name','brand','destination'],match_result:['shop','result'],checkout_opened:['shop']};
async function loadTrace(storage,now) {
 const {trace=[]}=await storage.get('trace');
 if(!Array.isArray(trace)) throw new Error('Delete the invalid local log before continuing.');
 const kept=trace.filter(x=>Number.isFinite(Date.parse(x.ts)) && Date.parse(x.ts)>=now-TRACE_DAYS*86400000).slice(-TRACE_LIMIT);
 if(kept.length!==trace.length) await storage.set({trace:kept}); return kept;
}
export const readTrace=(storage,now=Date.now())=>withStorageLock(storage,()=>loadTrace(storage,now));
export const appendTrace=(storage,event,now=Date.now(),epoch)=>withStorageLock(storage,async()=>{
 await requireConsent(storage);
 if(epoch!==undefined && (await storage.get('traceEpoch')).traceEpoch!==epoch) return;
 const fields=traceFields[event.kind]; if(!fields) throw new Error('Unknown local log event');
 const safe={kind:event.kind,ts:new Date(now).toISOString()};
 for(const field of fields) if(typeof event[field]==='string') safe[field]=event[field].slice(0,200);
 const trace=await loadTrace(storage,now); trace.push(safe); await storage.set({trace:trace.slice(-TRACE_LIMIT)});
});
export const deleteTrace=storage=>withStorageLock(storage,async()=>{await storage.remove('trace');await storage.set({traceEpoch:crypto.randomUUID()});});
export const deleteAllData=storage=>withStorageLock(storage,()=>storage.clear());
