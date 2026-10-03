import {BUILD} from './build-config.js';
import {DEFAULT_MANDATE,normalizeMandate} from './mandate.js';
export const DISCLOSURE_VERSION = 3;
export const hasConsent = value => value?.consent?.accepted === true && value.consent.version === DISCLOSURE_VERSION;
export async function requireConsent(storage) {
  if (!storage || !hasConsent(await storage.get('consent'))) throw new Error('Read and agree to the current disclosure first.');
}
export const acceptConsent = storage => locked(()=>storage.set({consent:{accepted:true,version:DISCLOSURE_VERSION}}));
export async function getSettings(storage) {
  const value = await storage.get(['provider','providerKey','mandate','consent','excludedHosts','destination']);
  return {provider:typeof value.provider==='string' ? value.provider : BUILD.defaultProvider,
    providerKey:typeof value.providerKey==='string' ? value.providerKey : '',
    mandate:normalizeMandate(value.mandate === undefined ? DEFAULT_MANDATE : value.mandate),
    onboarded:hasConsent(value), destination:value.destination === undefined ? 'US' : value.destination,
    excludedHosts:Array.isArray(value.excludedHosts) ? value.excludedHosts.filter(x=>typeof x === 'string') : []};
}
export async function migrateSettings(storage,build=BUILD) {
  return locked(async()=>{
  const v=await storage.get(['nebiusKey','tavilyKey','provider','providerKey']);
  const updates={};
  if (typeof v.nebiusKey==='string' && v.nebiusKey && build.providers.includes('nebius') && !v.providerKey) Object.assign(updates,{provider:'nebius',providerKey:v.nebiusKey});
  const provider=updates.provider ?? v.provider;
  if (!provider || !build.providers.includes(provider)) Object.assign(updates,{provider:build.defaultProvider,providerKey:''});
  const secrets=await secretValues(storage), {trace}=await storage.get('trace');
  if (Array.isArray(trace) && secrets.length) {
    const clean=value=>typeof value==='string' ? secrets.reduce((text,key)=>text.replaceAll(key,'[API key removed]'),value)
      : Array.isArray(value) ? value.map(clean) : value && typeof value==='object' ? Object.fromEntries(Object.entries(value).map(([key,v])=>[key,clean(v)])) : value;
    updates.trace=clean(trace);
  }
  if (Object.keys(updates).length) await storage.set(updates);
  if ('nebiusKey' in v) await storage.remove('nebiusKey');
  if ('tavilyKey' in v) await storage.remove('tavilyKey');
  });
}
export async function secretValues(storage) {
  const keys=await storage.get(['providerKey','nebiusKey','tavilyKey']);
  return Object.values(keys).filter(v=>typeof v==='string' && v.length);
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
    await requireConsent(storage);
    const trace = await loadTrace(storage,now);
    // Deleting a trace during a request must not resurrect it when the response arrives.
    if (requireRequestId !== null && !trace.some(event=>event.kind === 'request_prepared' && event.request_id === requireRequestId)) return false;
    const secrets=await secretValues(storage);
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
