// extension/core/research.js
import {KC_ENDPOINT} from './korea-quote.js';
import {scrubText} from './scrub.js';
export class ResearchError extends Error {}
const URLISH=/(?:https?:\/\/|www\.)/i;
function cleanQuery(q) {
  if (typeof q!=='string') throw new ResearchError('Research query must be text');
  if (q.trim().length>200 || URLISH.test(q.normalize('NFKC'))) throw new ResearchError('Research query must be 2-200 characters without links');
  const s=scrubText(q,200).replace(/\s+/g,' ').trim();
  if (s.length<2 || s.length>200 || URLISH.test(s)) throw new ResearchError('Research query must be 2-200 characters without links');
  return s;
}
export function researchRequest(term) {
  return Object.freeze({provider:'kc',url:KC_ENDPOINT,method:'POST',body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',
    params:{name:'research_briefing',arguments:{query:cleanQuery(term)}}})});
}
export function validResearchRequest(r) {
  if (r?.provider!=='kc' || r.url!==KC_ENDPOINT || r.method!=='POST') return false;
  try {
    const rpc=JSON.parse(r.body), a=rpc.params.arguments;
    return Object.keys(rpc).sort().join(',')==='id,jsonrpc,method,params' && rpc.jsonrpc==='2.0' && rpc.id===1 && rpc.method==='tools/call'
      && Object.keys(rpc.params).sort().join(',')==='arguments,name' && rpc.params.name==='research_briefing'
      && Object.keys(a).join(',')==='query' && a.query===cleanQuery(a.query);
  } catch { return false; }
}
const httpsOnly=v=>{try{const u=new URL(v);return u.protocol==='https:'&&!u.username&&!u.password?u.href:'';}catch{return '';}};
export function parseResearchRPC(raw) {
  if (raw?.error) throw new ResearchError(/rate limit/i.test(String(raw.error.message||'')) ? 'Rate limit exceeded' : 'Research unavailable');
  const result=raw?.result;
  if (!result || typeof result!=='object' || result.isError) throw new ResearchError('Research unavailable');
  let data=result.structuredContent;
  if (data==null) {
    const texts=(result.content||[]).filter(c=>c?.type==='text').map(c=>c.text);
    if (texts.length!==1) throw new ResearchError('Research unavailable');
    try { data=JSON.parse(texts[0]); } catch { throw new ResearchError('Research unavailable'); }
  }
  if (!Array.isArray(data?.results)) throw new ResearchError('Research unavailable');
  return data.results.slice(0,5).map(r=>({title:typeof r?.title==='string'?r.title:'',url:httpsOnly(r?.url),snippet:typeof r?.snippet==='string'?r.snippet:''}));
}
