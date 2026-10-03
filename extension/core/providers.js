// extension/core/providers.js
import {requireConsent} from './storage.js';
import {validQuoteRequest,parseQuoteRPC,QuoteError} from './korea-quote.js';
import {validResearchRequest,parseResearchRPC,ResearchError} from './research.js';
import {PRESETS} from './presets.js';
import {authHeaders} from './llm.js';
import {BUILD} from './build-config.js';
export class ProviderError extends Error {}
export function isPermitted(request,build=BUILD) {
  if (!request || typeof request!=='object') return false;
  if (request.provider==='kc') return validQuoteRequest(request) || validResearchRequest(request);
  if (!build.providers.includes(request.provider)) return false;
  const p=PRESETS[request.provider];
  return (request.url===p.models.url && request.method==='GET' && request.body===null)
    || (request.url===p.chat.url && request.method==='POST' && typeof request.body==='string');
}
async function readKC(response) {
  if (response.headers?.get('content-type')?.includes('text/event-stream')) {
    const events=(await response.text()).replaceAll('\r\n','\n').split('\n\n').filter(b=>b.split('\n').some(l=>l.startsWith('data:')))
      .map(b=>JSON.parse(b.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trimStart()).join('\n')));
    const replies=events.filter(e=>e?.id===1);
    if (replies.length!==1) throw new Error('Malformed stream');
    return replies[0];
  }
  return response.json();
}
export async function sendRequest(request,key,{storage,fetchImpl=globalThis.fetch,timeoutMs=60000,build=BUILD}={}) {
  await requireConsent(storage);
  // The only network sink. No discovery, retries, telemetry, or calls on page load.
  if (!isPermitted(request,build)) throw new ProviderError('Request destination is not permitted');
  const kc=request.provider==='kc';
  if (!kc && (typeof key!=='string' || !key.trim())) throw new ProviderError('Missing provider API key');
  const abort=new AbortController(), timer=setTimeout(()=>abort.abort(),timeoutMs);
  try {
    let response;
    try {
      response=await fetchImpl(request.url,{method:request.method,
        headers:{...(kc?{Accept:'application/json, text/event-stream'}:{...authHeaders(request.provider,key),Accept:'application/json'}),...(request.body===null?{}:{'Content-Type':'application/json'})},
        ...(request.body===null?{}:{body:request.body}),signal:abort.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});
    } catch { throw new ProviderError(abort.signal.aborted ? 'Provider request timed out' : 'Provider network request failed'); }
    await requireConsent(storage);
    const research=kc && validResearchRequest(request);
    if (kc && response.status===429) throw research ? new ResearchError('Rate limit exceeded') : new QuoteError('Rate limit exceeded');
    if (!response.ok) throw new ProviderError(`${request.provider} HTTP ${response.status}`);
    let raw;
    try { raw=kc ? await readKC(response) : await response.json(); }
    catch { throw new ProviderError('Provider returned invalid JSON'); }
    await requireConsent(storage);
    if (research) return parseResearchRPC(raw);
    if (kc) {
      const quote=parseQuoteRPC(raw);
      if (quote.destination!==JSON.parse(request.body).params.arguments.destination) throw new QuoteError('Quote destination mismatch');
      return quote;
    }
    return raw;
  } finally { clearTimeout(timer); }
}
