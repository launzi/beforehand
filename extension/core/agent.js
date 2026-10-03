import * as P from './prompts.js';
import {ONBOARDING} from './signals.js';
import {dateFromUs, EPOCH, DAY, floorDiv} from './util.js';
import {scrubText} from './scrub.js';
import {completionRequest,resolveModel,searchRequest} from './providers.js';
const py = x => x === true ? 'True' : x === false ? 'False' : x === null ? 'None' : String(x);
const substitute = (template,fields) => template.replace(/\{(\w+)\}/g,(_,k)=>fields[k]);
export const triageVerdict = reply => /^ACT(?:\s*:[^\r\n]+)?$/.test((reply || '').trim().toUpperCase());
export function formatEvidence(evidence, skill = false) {
  if (!Object.keys(evidence).length) return '(empty)';
  return Object.entries(evidence).map(([k,v])=>{
    const label = skill ? (P._SKILL_EVIDENCE_LABELS[k] ?? k.replace(/_us$/,'').replaceAll('_',' ')) : k;
    const values = Array.isArray(v) ? v : [v];
    const rendered = values.map(x=>skill && k.endsWith('_us') ? dateFromUs(x) : skill && typeof x === 'boolean' ? x ? 'yes' : 'no' : py(x));
    return `  ${label}: ${rendered.join(', ')}`;
  }).join('\n');
}
// A deliberately smaller outbound contract than the local detector result.
// Never send URL, title, path IDs, profile, visit IDs, or stable signal hashes.
export function minimizeSignal(signal) {
  const allowed = {
    unresolved:['search_count','follow_through_counts','distinct_days','low_follow_through','repeat_across_days'],
    new_entry:['visit_count'], recurring:['distinct_days','total_visits','first_day','last_day'],
    dropped:['active_days','days_quiet'],
  }[signal.kind];
  if (!allowed) throw new Error('Unknown signal kind');
  const evidence = {};
  for (const k of allowed) if (Object.hasOwn(signal.evidence,k)) evidence[k] = structuredClone(signal.evidence[k]);
  if (signal.kind === 'new_entry') evidence.onboarding_paths = [...new Set((signal.evidence.onboarding_paths ?? []).flatMap(p=>ONBOARDING.filter(x=>p.toLowerCase().includes(x))))];
  const coarse = us => (floorDiv(BigInt(us)-EPOCH,DAY)*DAY+EPOCH).toString();
  if (signal.kind === 'new_entry') evidence.first_visit_us = coarse(signal.first_us);
  if (signal.kind === 'dropped') evidence.last_visit_us = coarse(signal.last_us);
  const term = signal.term === null ? null : scrubText(signal.term);
  if (signal.kind === 'unresolved') evidence.term = term;
  let host = signal.host;
  if (host && (host.length > 150 || !host.includes('.') || /(?:localhost|\.local$|\.internal$)|(?:^\d+\.\d+\.\d+\.\d+$)|[\[\]:]|[a-z0-9_-]{40}/i.test(host))) host = '[private host removed]';
  return {kind:signal.kind, key:'(local identifier withheld)', host, term, evidence,
    first_us:coarse(signal.first_us),last_us:coarse(signal.last_us)};
}
export function triageRequest(signal,models) {
  const prompt = substitute(P.TRIAGE_TEMPLATE,{...signal,host:signal.host ?? '(none)',term:signal.term ?? '(none)',
    evidence:formatEvidence(signal.evidence),rubric:P.TRIAGE_RUBRICS[signal.kind]});
  return completionRequest({model:resolveModel(models,P.TRIAGE_TIER),tier:P.TRIAGE_TIER,prompt,system:P.TRIAGE_SYSTEM,max_tokens:P.TRIAGE_MAX_TOKENS});
}
export function skillRequest(signal,models,hits=[]) {
  const templates = {unresolved:P.UNRESOLVED_PROMPT,new_entry:P.NEW_ENTRY_PROMPT,recurring:P.RECURRING_PROMPT,dropped:P.DROPPED_PROMPT};
  const safeHits = hits.map(h=>({title:scrubText(h.title),url:safeHitURL(h.url),snippet:scrubText(h.snippet,700)}));
  const hitsText = safeHits.length ? safeHits.map((h,i)=>`${i+1}. ${h.title}\n   ${h.url}\n   ${h.snippet}`).join('\n') : '(no hits)';
  const prompt = substitute(templates[signal.kind],{...signal,evidence:formatEvidence(signal.evidence,true),hits:hitsText});
  return completionRequest({model:resolveModel(models,'nano'),tier:'nano',prompt,system:P.SKILL_SYSTEM,max_tokens:P.SKILL_MAX_TOKENS[signal.kind]});
}
function safeHitURL(value) {
  try { const u = new URL(value); return ['http:','https:'].includes(u.protocol) ? u.origin + scrubText(u.pathname,200) : '[URL removed]'; }
  catch { return '[invalid URL removed]'; }
}
export const researchRequest = signal => searchRequest(signal.term);
export function redactKnownKeys(request,settings) {
  let body = request.body;
  if (body !== null) {
    // Work on strings recursively, not serialized JSON, so quotes/backslashes in a key cannot break JSON.
    const clean = value => typeof value === 'string' ? [settings.nebiusKey,settings.tavilyKey].filter(Boolean).reduce((s,k)=>s.replaceAll(k,'[API key removed]'),value)
      : Array.isArray(value) ? value.map(clean) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([k,v])=>[k,clean(v)])) : value;
    body = JSON.stringify(clean(JSON.parse(body)));
  }
  return Object.freeze({...request,body});
}
