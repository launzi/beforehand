import {requireConsent} from './storage.js';
import {validQuoteRequest,parseQuoteRPC,QuoteError} from './korea-quote.js';
export const TOKEN_FACTORY = 'https://api.tokenfactory.nebius.com/v1/chat/completions';
export const MODEL_LIST = 'https://api.tokenfactory.nebius.com/v1/models';
export const TAVILY = 'https://api.tavily.com/search';
export class ProviderError extends Error {}
export const modelRequest = () => Object.freeze({provider:'nebius',url:MODEL_LIST,method:'GET',body:null});
export function resolveModel(models,tier) {
  if (!['nano','super','lightning','ultra'].includes(tier)) throw new ProviderError('Unknown model tier');
  const candidates = models.filter(x=>typeof x?.id === 'string' && x.id.toLowerCase().includes('nemotron') && x.id.toLowerCase().includes(tier));
  if (!candidates.length) throw new ProviderError(`No model found for tier '${tier}'`);
  return candidates.reduce((best,x)=>x.id.length < best.length ? x.id : best,candidates[0].id);
}
export function completionRequest({model,tier,prompt,system,max_tokens}) {
  if (typeof prompt !== 'string' || !prompt.trim()) throw new ProviderError('Prompt must not be blank');
  const messages = [];
  if (['nano','super','lightning'].includes(tier)) messages.push({role:'system',content:system ? `${system}\n\n/no_think` : '/no_think'});
  else if (system) messages.push({role:'system',content:system});
  messages.push({role:'user',content:prompt.trim()});
  return Object.freeze({provider:'nebius',url:TOKEN_FACTORY,method:'POST',body:JSON.stringify({model,messages,max_tokens,stream:false})});
}
export function searchRequest(query) {
  if (typeof query !== 'string' || !query.trim()) throw new ProviderError('Search query must not be blank');
  return Object.freeze({provider:'tavily',url:TAVILY,method:'POST',body:JSON.stringify({query:query.trim(),max_results:5})});
}
export function completionText(raw,tier,model) {
  const choice = raw?.choices?.[0];
  if (!choice || !choice.message || typeof choice.message !== 'object') throw new ProviderError('Malformed Nebius response');
  const content = choice.message.content ?? '';
  if (typeof content !== 'string') throw new ProviderError('Malformed Nebius response');
  if (choice.finish_reason === 'length' && !content.trim()) throw new ProviderError(`Nemotron finish_reason=length (tier=${tier}, model=${model})`);
  if (!content.trim()) throw new ProviderError(`Nemotron empty content (tier=${tier}, model=${model})`);
  // Python currently accepts nonempty content even when finish_reason=length.
  return content;
}
export function searchResults(raw) {
  const results = raw?.results ?? [];
  if (!Array.isArray(results)) throw new ProviderError('Malformed Tavily response');
  return results.slice(0,5).map(r=>{
    if (!r || typeof r !== 'object') throw new ProviderError('Malformed Tavily result');
    const fields = {title:r.title || '',url:r.url || '',snippet:r.content || ''};
    if (Object.values(fields).some(v=>typeof v !== 'string')) throw new ProviderError('Malformed Tavily result');
    return fields;
  });
}
export async function sendRequest(request,key,{storage, fetchImpl = globalThis.fetch, timeoutMs = 60000} = {}) {
  await requireConsent(storage);
  // The only network sink. No discovery, retries, telemetry, or calls on page load.
  const permitted = (request.provider === 'nebius' && ((request.url === MODEL_LIST && request.method === 'GET' && request.body === null)
    || (request.url === TOKEN_FACTORY && request.method === 'POST' && typeof request.body === 'string')))
    || (request.provider === 'tavily' && request.url === TAVILY && request.method === 'POST' && typeof request.body === 'string') || validQuoteRequest(request);
  if (!permitted) throw new ProviderError('Request destination is not permitted');
  if (request.provider !== 'kc' && (typeof key !== 'string' || !key.trim())) throw new ProviderError('Missing provider API key');
  const abort = new AbortController(), timer = setTimeout(()=>abort.abort(),timeoutMs);
  try {
    let response;
    try {
      response = await fetchImpl(request.url,{method:request.method,
        headers:{...(request.provider === 'kc' ? {Accept:'application/json, text/event-stream'} : {Authorization:`Bearer ${key}`,Accept:'application/json'}),...(request.body === null ? {} : {'Content-Type':'application/json'})},
        ...(request.body === null ? {} : {body:request.body}),signal:abort.signal,
        credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});
    } catch { throw new ProviderError(abort.signal.aborted ? 'Provider request timed out' : 'Provider network request failed'); }
    await requireConsent(storage);
    if (request.provider === 'kc' && response.status === 429) throw new QuoteError('Rate limit exceeded');
    if (!response.ok) throw new ProviderError(`${request.provider} HTTP ${response.status}`);
    let raw;
    try {
      if (request.provider === 'kc' && response.headers?.get('content-type')?.includes('text/event-stream')) {
        const events=(await response.text()).replaceAll('\r\n','\n').split('\n\n').filter(block=>block.split('\n').some(line=>line.startsWith('data:')))
          .map(block=>JSON.parse(block.split('\n').filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n')));
        const replies=events.filter(e=>e?.id===1);
        if(replies.length!==1) throw new Error('Malformed quote stream');
        raw=replies[0];
      } else raw=await response.json();
    } catch { throw new ProviderError('Provider returned invalid JSON'); }
    await requireConsent(storage);
    if (request.provider === 'kc') {
      const quote=parseQuoteRPC(raw);
      if(quote.destination!==JSON.parse(request.body).params.arguments.destination) throw new QuoteError('Quote destination mismatch');
      return quote;
    }
    return raw;
  } finally { clearTimeout(timer); }
}
