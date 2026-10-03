import {validRequest,parseMatchRPC,parseCheckoutRPC,MatchError} from './match.js';
import {requireConsent} from './storage.js';
async function readKC(response) {
 if(response.headers?.get('content-type')?.includes('text/event-stream')) {
  const source=await response.text();
  for(const event of source.replace(/\r\n/g,'\n').split('\n\n')) {
   const data=event.split('\n').filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');
   if(!data || data==='[DONE]') continue;
   const value=JSON.parse(data); if(value.id===1 && (value.result || value.error)) return value;
  }
  throw new MatchError('malformed');
 }
 return response.json();
}
export async function sendRequest(req,{storage,fetchImpl=globalThis.fetch,timeoutMs=45000}) {
 const consent=await requireConsent(storage);
 if(!validRequest(req)) throw new MatchError('malformed');
 // Snapshot the validated request before yielding to any asynchronous work.
 const {url,method,body,kind}=req;
 let response;
 try {
  const fetch=fetchImpl;
  response=await fetch(url,{method,body,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(timeoutMs),headers:{'Content-Type':'application/json',Accept:'application/json, text/event-stream'}});
 } catch {throw new MatchError('unavailable');}
 if(response.status===429) throw new MatchError('rate_limited');
 if(!response.ok) throw new MatchError('unavailable');
 let raw; try {raw=await readKC(response);} catch {throw new MatchError('malformed');}
 const current=await requireConsent(storage);
 if(current.revision!==consent.revision) throw new MatchError('unavailable');
 return kind==='match'?parseMatchRPC(raw):parseCheckoutRPC(raw);
}
