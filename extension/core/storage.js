import {DEFAULT_MANDATE,normalizeMandate} from './mandate.js';
export async function getSettings(storage) {
  const value = await storage.get(['nebiusKey','tavilyKey','mandate','onboarded','excludedHosts']);
  return {nebiusKey:typeof value.nebiusKey === 'string' ? value.nebiusKey : '',
    tavilyKey:typeof value.tavilyKey === 'string' ? value.tavilyKey : '',
    mandate:normalizeMandate(value.mandate === undefined ? DEFAULT_MANDATE : value.mandate),
    onboarded:value.onboarded === true, excludedHosts:Array.isArray(value.excludedHosts) ? value.excludedHosts.filter(x=>typeof x === 'string') : []};
}
export const TRACE_LIMIT = 500;
export const TRACE_DAYS = 30;
async function loadTrace(storage,now) {
  const {trace=[]} = await storage.get('trace');
  if (!Array.isArray(trace)) throw new Error('Local audit log is invalid. Clear local data before continuing.');
  const kept = trace.filter(x=>Date.parse(x.ts) >= now-TRACE_DAYS*86400000).slice(-TRACE_LIMIT);
  if (kept.length !== trace.length) await storage.set({trace:kept});
  return kept;
}
const locked = fn => globalThis.navigator?.locks?.request
  ? navigator.locks.request('before-you-ask-local-trace',fn) : fn();
export const readTrace = (storage,now=Date.now()) => locked(()=>loadTrace(storage,now));
export async function appendTrace(storage,event,now=Date.now(),requireRequestId=null) {
  return appendTraces(storage,[event],now,requireRequestId);
}
export async function appendTraces(storage,events,now=Date.now(),requireRequestId=null) {
  // No keys, headers, raw history or provider response bodies belong in event.
  return locked(async()=>{
    const trace = await loadTrace(storage,now);
    // Deleting a trace during a request must not resurrect it when the response arrives.
    if (requireRequestId !== null && !trace.some(event=>event.kind === 'request_prepared' && event.request_id === requireRequestId)) return false;
    const keys=await storage.get(['nebiusKey','tavilyKey']);
    const secrets=Object.values(keys).filter(v=>typeof v === 'string' && v.length);
    const redact=value=>typeof value === 'string' ? secrets.reduce((s,key)=>s.replaceAll(key,'[API key removed]'),value)
      : Array.isArray(value) ? value.map(redact) : value && typeof value === 'object'
        ? Object.fromEntries(Object.entries(value).map(([k,v])=>[k,redact(v)])) : value;
    trace.push(...events.slice(-TRACE_LIMIT).map(event=>({...redact(event),ts:new Date(now).toISOString()})));
    await storage.set({trace:trace.slice(-TRACE_LIMIT)}); // A write failure propagates and blocks sending.
    return true;
  });
}
export const deleteTrace = storage => locked(()=>storage.remove('trace'));
export const deleteAllData = storage => locked(()=>storage.clear());
