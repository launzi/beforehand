// extension/core/llm.js
import {PRESETS} from './presets.js';
export class LLMError extends Error {}
const preset = id => { const p=PRESETS[id]; if (!p) throw new LLMError('Unknown provider'); return p; };
export const modelsRequest = id => Object.freeze({provider:id,url:preset(id).models.url,method:'GET',body:null});
export function parseModels(id,raw) {
  const list = Array.isArray(raw) ? raw : raw?.data;
  if (!Array.isArray(list)) throw new LLMError('Malformed model list');
  return list.map(m=>m?.id).filter(x=>typeof x==='string');
}
export function resolveRole(id,ids,role) {
  for (const pattern of preset(id).roles[role] ?? []) {
    const hit = ids.filter(x=>pattern.test(x.toLowerCase()));
    if (hit.length) return id==='nebius' ? hit.reduce((a,b)=>b.length<a.length?b:a) : hit[0];
  }
  throw new LLMError(`No model for role ${role}`);
}
export function chatRequest(id,{model,role,prompt,system,maxTokens}) {
  if (typeof prompt!=='string' || !prompt.trim()) throw new LLMError('Prompt must not be blank');
  const p=preset(id), user={role:'user',content:prompt.trim()};
  let body;
  if (id==='anthropic') body={model,max_tokens:maxTokens,...(system?{system}:{}),messages:[user]};
  else if (id==='openai') body={model,messages:[...(system?[{role:'system',content:system}]:[]),user],max_completion_tokens:maxTokens,stream:false};
  else {
    const sys = role==='skill' ? (system ? `${system}\n\n/no_think` : '/no_think') : system;
    body={model,messages:[...(sys?[{role:'system',content:sys}]:[]),user],max_tokens:maxTokens,stream:false};
  }
  return Object.freeze({provider:id,url:p.chat.url,method:'POST',body:JSON.stringify(body)});
}
export function chatText(id,raw) {
  let text, truncated;
  if (id==='anthropic') {
    if (!Array.isArray(raw?.content)) throw new LLMError('Malformed provider response');
    text=raw.content.filter(c=>c?.type==='text' && typeof c.text==='string').map(c=>c.text).join('');
    truncated=raw.stop_reason==='max_tokens';
  } else {
    const c=raw?.choices?.[0];
    if (!c || !c.message || typeof c.message!=='object') throw new LLMError('Malformed provider response');
    text=c.message.content ?? ''; truncated=c.finish_reason==='length';
    if (typeof text!=='string') throw new LLMError('Malformed provider response');
  }
  if (!text.trim()) throw new LLMError(truncated ? `${id}: answer truncated before any text` : `${id}: empty answer`);
  return text;
}
export function authHeaders(id,key) {
  if (id==='anthropic') return {'x-api-key':key,'anthropic-version':'2023-06-01','anthropic-dangerous-direct-browser-access':'true'};
  return {Authorization:`Bearer ${key}`};
}
