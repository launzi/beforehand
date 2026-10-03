import {pythonJSON, sha256, codepointCompare} from './util.js';
export const PLANS = Object.freeze(Object.fromEntries([
  ['unresolved','research_briefing',true], ['new_entry','setup_check',false],
  ['korea_product','commerce.quote',false], ['recurring','theme_summary',false], ['dropped','followup_nudge',false],
].map(([kind,action_kind,uses_search]) => [kind, Object.freeze({skill:kind === 'korea_product' ? 'korea_quote' : kind, signal_kind:kind, action_kind, uses_search, uses_llm:true})])));
export const DEFAULT_MANDATE = Object.freeze({allowed_skills:Object.values(PLANS).map(p=>p.skill), allow_search:true, require_confirmation:[], error:null});
export function normalizeMandate(input) {
  const fail = error => ({allowed_skills:[], allow_search:false, require_confirmation:[], error});
  if (!input || typeof input !== 'object' || Array.isArray(input)) return fail('Invalid stored mandate');
  const fields = ['allowed_skills','allow_search','require_confirmation'];
  const unknown = Object.keys(input).filter(k => ![...fields,'error'].includes(k)).sort();
  if (unknown.length) return fail(`local: unknown fields: ${unknown.join(', ')}`);
  if (input.error != null) return fail(typeof input.error === 'string' ? input.error : 'Invalid stored mandate');
  if (fields.some(k => !(k in input))) return fail('Invalid stored mandate: missing fields');
  if (typeof input.allow_search !== 'boolean') return fail('local: allow_search must be a boolean');
  const result = {allow_search:input.allow_search,error:null};
  for (const field of ['allowed_skills','require_confirmation']) {
    if (!Array.isArray(input[field]) || input[field].some(v => typeof v !== 'string' || !v.trim()))
      return fail(`local: ${field} must be a list of non-empty strings`);
    result[field] = [...new Set(input[field].map(v => v.trim().toLowerCase()))].sort(codepointCompare);
  }
  return result;
}
export const canonicalMandate = m => pythonJSON({schema_version:1, allowed_skills:[...new Set(m.allowed_skills)].sort(codepointCompare),
  allow_search:m.allow_search, require_confirmation:[...new Set(m.require_confirmation)].sort(codepointCompare), error:m.error ?? null});
export const mandateDigest = m => sha256(canonicalMandate(m));
export async function evaluateMandate(m, signal, plan = PLANS[signal.kind] ?? null) {
  let verdict = 'allow', reason = 'Action is within the configured mandate';
  if (plan?.action_kind === 'commerce.checkout') [verdict,reason] = ['deny','Checkout is out of scope for this build'];
  else if (m.error != null) [verdict,reason] = ['deny',`Invalid mandate: ${m.error}`];
  else if (plan === null) [verdict,reason] = ['deny','No declared skill for signal kind'];
  else if (signal.kind !== plan.signal_kind) [verdict,reason] = ['deny','Signal kind does not match the skill declaration'];
  else if (!m.allowed_skills.includes(plan.skill)) [verdict,reason] = ['deny',`Skill '${plan.skill}' is not allowed`];
  else if (plan.action_kind === 'commerce.quote' && !m.allow_search) [verdict,reason] = ['deny','External commerce quotes are not allowed'];
  else if (plan.uses_search && !m.allow_search) [verdict,reason] = ['deny','External search provider calls are not allowed'];
  else if (m.require_confirmation.includes(plan.action_kind)) [verdict,reason] = ['hold',`Action '${plan.action_kind}' requires user confirmation`];
  return {verdict,reason,mandate_digest:await mandateDigest(m)};
}
export function searchPolicy(mode) {
  if (!['allow','hold','deny'].includes(mode)) throw new Error('Unknown search policy');
  return {...DEFAULT_MANDATE, allow_search:mode !== 'deny', require_confirmation:mode === 'hold' ? ['research_briefing','commerce.quote'] : []};
}
