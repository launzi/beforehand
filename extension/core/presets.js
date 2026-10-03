// extension/core/presets.js
import {BUILD} from './build-config.js';
const re = list => Object.freeze(list.map(s=>new RegExp(s)));
// Model ids are never hardcoded: each role lists preference patterns, resolved against the provider's /v1/models.
export const PRESETS = Object.freeze({
  openai:Object.freeze({id:'openai',label:'ChatGPT',keyHelp:'An OpenAI API key from platform.openai.com (not a ChatGPT subscription).',
    chat:{url:'https://api.openai.com/v1/chat/completions'},models:{url:'https://api.openai.com/v1/models'},
    roles:{triage:re(['^gpt-5(\\.\\d+)?$','^gpt-4\\.1$']),skill:re(['^gpt-5(\\.\\d+)?-mini$','^gpt-4\\.1-mini$'])}}),
  anthropic:Object.freeze({id:'anthropic',label:'Claude',keyHelp:'An Anthropic API key from console.anthropic.com.',
    chat:{url:'https://api.anthropic.com/v1/messages'},models:{url:'https://api.anthropic.com/v1/models'},
    roles:{triage:re(['^claude-sonnet-']),skill:re(['^claude-haiku-'])}}),
  nebius:Object.freeze({id:'nebius',label:'Nemotron (Nebius)',keyHelp:'A Nebius Token Factory API key.',
    chat:{url:'https://api.tokenfactory.nebius.com/v1/chat/completions'},models:{url:'https://api.tokenfactory.nebius.com/v1/models'},
    roles:{triage:re(['nemotron.*ultra']),skill:re(['nemotron.*nano'])}}),
});
export const activeProviders = (build=BUILD) => [...build.providers];
export function presetFor(id,build=BUILD) {
  if (!build.providers.includes(id) || !PRESETS[id]) throw new Error('Provider not available in this build');
  return PRESETS[id];
}
