import {quoteRequest,validateSummary} from './korea-quote.js';
import {evaluateMandate,PLANS} from './mandate.js';
import {getSettings,appendTrace} from './storage.js';
import {sendRequest} from './providers.js';
import {modelsRequest,parseModels,resolveRole,chatText} from './llm.js';
import {BUILD} from './build-config.js';
import {minimizeSignal,triageRequest,skillRequest,researchRequestFor,triageVerdict,redactKnownKeys,koreaQuoteSummaryRequest} from './agent.js';
export async function decisionFor(signal,settings) { return evaluateMandate(settings.mandate,signal); }
export class Controller {
  #storage; #fetch; #build; #modelIdentity=null; #models = null; #pending = null; #context = null; #busy = false;
  constructor(storage,fetchImpl=globalThis.fetch,build=BUILD) { this.#storage=storage; this.#fetch=fetchImpl; this.#build=build; }
  get pending() { return this.#pending; }
  discard() { this.#pending=null; this.#context=null; this.#models=null; }
  cancel() { if (this.#busy) throw new Error('Wait for the current request to finish.'); this.#pending=null; this.#context=null; }
  async prepare(signal, expectedExcludedHosts = null) {
    if (this.#busy) throw new Error('A request is already running.');
    this.cancel();
    const settings = await getSettings(this.#storage), decision = await decisionFor(signal,settings);
    if (expectedExcludedHosts !== null && JSON.stringify(settings.excludedHosts) !== JSON.stringify(expectedExcludedHosts))
      throw new Error('Excluded websites changed. Scan again before preparing a request.');
    if (!settings.onboarded) throw new Error('Read and accept the local-history disclosure first.');
    if (!this.#build.providers.includes(settings.provider)) throw new Error('Choose an AI provider in Settings.');
    if (!settings.providerKey) throw new Error('Add your AI provider API key in Settings.');
    if (this.#modelIdentity !== JSON.stringify([settings.provider,settings.providerKey])) this.#models=null;
    if (decision.verdict !== 'allow') throw new Error(`${decision.verdict}: ${decision.reason}`);
    this.#context={signal:minimizeSignal(signal),localKey:signal.key,settings,decision};
    return this.#set(this.#models ? 'triage' : 'models');
  }
  #set(stage,hits=[]) {
    const c = this.#context;
    const request = stage === 'models' ? modelsRequest(c.settings.provider) : stage === 'triage' ? triageRequest(c.settings.provider,c.signal,this.#models)
      : stage === 'quote' ? quoteRequest(c.signal.term,c.settings.destination)
      : stage === 'search' ? researchRequestFor(c.signal) : c.signal.kind === 'korea_product' ? koreaQuoteSummaryRequest(c.settings.provider,c.quote,this.#models) : skillRequest(c.settings.provider,c.signal,this.#models,hits);
    this.#pending=Object.freeze({stage,request:redactKnownKeys(request,[c.settings.providerKey]),mandate_digest:c.decision.mandate_digest});
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
        || latest.destination !== c.settings.destination
        || latest.provider !== c.settings.provider || latest.providerKey !== c.settings.providerKey
        || JSON.stringify(latest.excludedHosts) !== JSON.stringify(c.settings.excludedHosts))
        throw new Error('Settings changed. Scan and prepare again before running.');
      meta={request_id:crypto.randomUUID(),signal_key:c.localKey,signal_kind:c.signal.kind,stage:pending.stage,mandate_digest:decision.mandate_digest,
        verdict:decision.verdict,reason:decision.reason,planned_action:PLANS[c.signal.kind]};
      await appendTrace(this.#storage,{kind:'request_prepared',...meta,request:pending.request,status:'sending'});
      auditStarted=true;
      const raw=await sendRequest(pending.request,pending.request.provider === 'kc' ? '' : latest.providerKey,{storage:this.#storage,fetchImpl:this.#fetch,build:this.#build});
      let result;
      if (pending.stage === 'models') {
        const ids=parseModels(c.settings.provider,raw);
        resolveRole(c.settings.provider,ids,'triage'); resolveRole(c.settings.provider,ids,'skill');
        this.#models=ids; this.#modelIdentity=JSON.stringify([c.settings.provider,c.settings.providerKey]);
        result={status:'ready',next:'triage'};
      } else if (pending.stage === 'triage') {
        const act=triageVerdict(chatText(c.settings.provider,raw));
        result=act ? {status:'ACT',next:c.signal.kind === 'korea_product' ? 'quote' : c.signal.kind === 'unresolved' ? 'search' : 'skill'} : {status:'SKIP',next:null};
      } else if (pending.stage === 'quote') {
        c.quote=raw;
        result={status:'quoted',next:'skill',quote:c.quote};
      } else if (pending.stage === 'search') {
        result={status:'ready',next:'skill',hits:raw};
      } else {
        const text=chatText(c.settings.provider,raw);
        result={status:'complete',next:null,text:c.quote ? validateSummary(text,c.quote) : text,quote:c.quote};
      }
      const recorded=await appendTrace(this.#storage,{kind:'request_completed',...meta,status:result.status},Date.now(),meta.request_id);
      if (!recorded) throw new Error('Local request audit record was cleared or expired. Response discarded. Prepare again.');
      if (result.next) this.#set(result.next,result.hits);
      return {status:result.status,text:result.text,quote:result.quote,pending:this.#pending};
    } catch (error) {
      this.#pending=null;
      if (auditStarted) await appendTrace(this.#storage,{kind:'request_failed',...meta,status:'error',
        error:'Request or response processing failed; see the popup for the error category.'},Date.now(),meta.request_id);
      // Errors are surfaced; no retry or false successful result.
      throw error;
    } finally { this.#busy=false; }
  }
}
