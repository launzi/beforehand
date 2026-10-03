import {evaluateMandate,PLANS} from './mandate.js';
import {getSettings,appendTrace} from './storage.js';
import {modelRequest,sendRequest,completionText,searchResults,resolveModel} from './providers.js';
import {minimizeSignal,triageRequest,skillRequest,researchRequest,triageVerdict,redactKnownKeys} from './agent.js';
export async function decisionFor(signal,settings) {
  const decision = await evaluateMandate(settings.mandate,signal);
  if (decision.verdict !== 'deny' && PLANS[signal.kind]?.uses_search && !settings.tavilyKey)
    return {...decision,verdict:'deny',reason:'Research requires an optional Tavily API key'};
  return decision;
}
export class Controller {
  #storage; #fetch; #models = null; #pending = null; #context = null; #busy = false;
  constructor(storage,fetchImpl=globalThis.fetch) { this.#storage=storage; this.#fetch=fetchImpl; }
  get pending() { return this.#pending; }
  cancel() { if (this.#busy) throw new Error('Wait for the current request to finish.'); this.#pending=null; this.#context=null; }
  async prepare(signal, expectedExcludedHosts = null) {
    if (this.#busy) throw new Error('A request is already running.');
    this.cancel();
    const settings = await getSettings(this.#storage), decision = await decisionFor(signal,settings);
    if (expectedExcludedHosts !== null && JSON.stringify(settings.excludedHosts) !== JSON.stringify(expectedExcludedHosts))
      throw new Error('Excluded websites changed. Scan again before preparing a request.');
    if (!settings.onboarded) throw new Error('Read and accept the local-history disclosure first.');
    if (!settings.nebiusKey) throw new Error('Set your Nebius API key in Settings.');
    if (decision.verdict !== 'allow') throw new Error(`${decision.verdict}: ${decision.reason}`);
    this.#context={signal:minimizeSignal(signal),localKey:signal.key,settings,decision};
    return this.#set(this.#models ? 'triage' : 'models');
  }
  #set(stage,hits=[]) {
    const c = this.#context;
    const request = stage === 'models' ? modelRequest() : stage === 'triage' ? triageRequest(c.signal,this.#models)
      : stage === 'search' ? researchRequest(c.signal) : skillRequest(c.signal,this.#models,hits);
    this.#pending=Object.freeze({stage,request:redactKnownKeys(request,c.settings),mandate_digest:c.decision.mandate_digest});
    return this.#pending;
  }
  async run() {
    if (this.#busy || !this.#pending) throw new Error('Prepare a request before pressing Run.');
    this.#busy=true;
    const pending = this.#pending, c=this.#context;
    let auditStarted=false, meta=null;
    this.#pending=null; // A request is single-use, including on errors.
    try {
      const latest=await getSettings(this.#storage), decision=await decisionFor(c.signal,latest);
      if (!latest.onboarded || decision.verdict !== 'allow' || decision.mandate_digest !== pending.mandate_digest
        || latest.nebiusKey !== c.settings.nebiusKey || latest.tavilyKey !== c.settings.tavilyKey
        || JSON.stringify(latest.excludedHosts) !== JSON.stringify(c.settings.excludedHosts))
        throw new Error('Settings changed. Scan and prepare again before running.');
      meta={request_id:crypto.randomUUID(),signal_key:c.localKey,signal_kind:c.signal.kind,stage:pending.stage,mandate_digest:decision.mandate_digest,
        verdict:decision.verdict,reason:decision.reason,planned_action:PLANS[c.signal.kind]};
      await appendTrace(this.#storage,{kind:'request_prepared',...meta,request:pending.request,status:'sending'});
      auditStarted=true;
      const raw=await sendRequest(pending.request,pending.request.provider === 'tavily' ? latest.tavilyKey : latest.nebiusKey,{fetchImpl:this.#fetch});
      let result;
      if (pending.stage === 'models') {
        const models=Array.isArray(raw) ? raw : raw?.data;
        if (!Array.isArray(models)) throw new Error('Malformed model list');
        resolveModel(models,'ultra'); resolveModel(models,'nano');
        this.#models=models;
        result={status:'ready',next:'triage'};
      } else if (pending.stage === 'triage') {
        const body=JSON.parse(pending.request.body);
        const act=triageVerdict(completionText(raw,'ultra',body.model));
        result=act ? {status:'ACT',next:c.signal.kind === 'unresolved' ? 'search' : 'skill'} : {status:'SKIP',next:null};
      } else if (pending.stage === 'search') {
        result={status:'ready',next:'skill',hits:searchResults(raw)};
      } else {
        const body=JSON.parse(pending.request.body);
        result={status:'complete',next:null,text:completionText(raw,'nano',body.model)};
      }
      const recorded=await appendTrace(this.#storage,{kind:'request_completed',...meta,status:result.status},Date.now(),meta.request_id);
      if (!recorded) throw new Error('Local request audit record was cleared or expired. Response discarded. Prepare again.');
      if (result.next) this.#set(result.next,result.hits);
      return {status:result.status,text:result.text,pending:this.#pending};
    } catch (error) {
      this.#pending=null;
      if (auditStarted) await appendTrace(this.#storage,{kind:'request_failed',...meta,status:'error',
        error:'Request or response processing failed; see the popup for the error category.'},Date.now(),meta.request_id);
      // Errors are surfaced; no retry or false successful result.
      throw error;
    } finally { this.#busy=false; }
  }
}
