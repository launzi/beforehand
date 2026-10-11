import {KC_API,validRequest,parseMatchResponse,parseCheckoutResponse,MatchError} from './match.js';
import {requireConsent} from './storage.js';
// Reserved event endpoint: payload validation is required before any sender is enabled.
const allowedURLs=new Set(['/matches','/checkout','/curation/events'].map(path=>KC_API+path));
export async function sendRequest(req,{storage,fetchImpl=globalThis.fetch,timeoutMs=45000}) {
 const consent=await requireConsent(storage);
 if(!validRequest(req) || !allowedURLs.has(req.url)) throw new MatchError('malformed');
 // Snapshot the validated request before yielding to any asynchronous work.
 const {url,method,body,kind}=req;
 let response;
 try {
  const fetch=fetchImpl;
  response=await fetch(url,{method,body,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(timeoutMs),headers:{'Content-Type':'application/json',Accept:'application/json'}});
 } catch {throw new MatchError('unavailable');}
 if(response.status===429) throw new MatchError('rate_limited');
 if(!response.ok) throw new MatchError('unavailable');
 let raw; try {raw=await response.json();} catch {throw new MatchError('malformed');}
 const current=await requireConsent(storage);
 if(current.revision!==consent.revision) throw new MatchError('unavailable');
 return kind==='match'?parseMatchResponse(raw):parseCheckoutResponse(raw);
}
