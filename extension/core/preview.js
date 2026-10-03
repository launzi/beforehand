// extension/core/preview.js
import {PRESETS} from './presets.js';
export const NEVER_BY_KIND=Object.freeze({
  ai:Object.freeze(['raw URLs','page titles','visit times','browsing history']),
  research:Object.freeze(['URLs','visit times','browsing history','your API key']),
  quote:Object.freeze(['product URL','visit times','browsing history','your API key']),
});
// Body-level detectors for the never items that can be checked mechanically.
// AI prompts may legitimately carry public search-result URLs (research → skill), so the URL check applies only to KC requests;
// for AI requests "raw URLs" is guaranteed upstream by minimizeSignal, and only visit timestamps are checked here.
const LEAKS=[['URLs',/https?:\/\//i],['product URL',/https?:\/\//i],['visit times',/\b20\d\d-\d\d-\d\dT\d\d:\d\d/]];
export function describeRequest(request) {
  const host=new URL(request.url).host;
  let kind,label,sends;
  if (request.provider==='kc') {
    const rpc=JSON.parse(request.body), a=rpc.params.arguments;
    kind=rpc.params.name==='research_briefing' ? 'research' : 'quote';
    label='Korea Concierge';
    sends=Object.entries(a).map(([field,value])=>({field,value:String(value)}));
  } else {
    kind='ai'; label=PRESETS[request.provider]?.label ?? request.provider;
    if (request.body===null) sends=[];
    else {
      const b=JSON.parse(request.body);
      const prompt=(b.messages ?? []).filter(m=>m.role==='user').map(m=>m.content).join('\n');
      sends=[{field:'prompt',value:prompt},...(b.system||b.messages?.some(m=>m.role==='system') ? [{field:'instructions',value:b.system || b.messages.filter(m=>m.role==='system').map(m=>m.content).join('\n')}] : [])];
    }
  }
  const never=[...NEVER_BY_KIND[kind]];
  // Inspect every JSON string, including instructions and additional fields.
  const strings=value=>typeof value==='string' ? [value] : value && typeof value==='object' ? Object.values(value).flatMap(strings) : [];
  const text=request.body===null ? '' : strings(JSON.parse(request.body)).join('\n');
  for (const [item,re] of LEAKS) if (never.includes(item) && re.test(text)) throw new Error(`Preview invariant violated: ${item}`);
  return {destination:{kind,label,host},sends,never};
}
