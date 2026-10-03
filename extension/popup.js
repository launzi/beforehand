import {renderQuoteCard} from './core/quote-card.js';
import {readHistory} from './core/history.js';
import {detectAll} from './core/signals.js';
import {getSettings,migrateSettings,secretValues,readTrace,appendTraces,acceptConsent,deleteAllData} from './core/storage.js';
import {PLANS} from './core/mandate.js';
import {Controller,decisionFor} from './core/controller.js';
import {scrubText} from './core/scrub.js';
const $ = id => document.getElementById(id);
const storage = chrome.storage.local;
const controller = new Controller(storage);
let busy = false;
function message(text='') { $('status').textContent=text; }
async function showError(error) {
  // Never echo network response bodies or arbitrary key-containing errors.
  let text=error instanceof Error ? error.message : 'The operation failed.';
  try {
    const settings=await getSettings(storage);
    for (const key of await secretValues(storage)) if (key) text=text.replaceAll(key,'[API key removed]');
  } catch { text='The operation failed and local storage could not be read.'; }
  $('error').textContent=scrubText(text,600);
}
function task(fn) {
  return async()=>{
    if (busy) return;
    busy=true; $('error').textContent='';
    for (const b of document.querySelectorAll('button')) if (b !== $('revoke')) b.disabled=true;
    try { await fn(); }
    catch(error) { await showError(error); }
    finally {
      busy=false;
      for (const b of document.querySelectorAll('button')) b.disabled=b.dataset.blocked === 'true';
      $('run').disabled=!controller.pending;
    }
  };
}
function preview() {
  const pending=controller.pending;
  $('preview').hidden=!pending;
  if (!pending) return;
  const labels={quote:'Quote: send only the product name and destination to Korea Concierge. Creates nothing and charges nothing.',models:'Step 1: discover available Nemotron models. No history data is sent.',triage:'Triage: ask Ultra whether this signal merits action.',search:'Research: send this scrubbed query to Tavily.',skill:'Suggestion: ask Nano for a useful next step.'};
  $('stage').textContent=labels[pending.stage];
  $('destination').textContent=`${pending.request.method} ${pending.request.url}`;
  $('body').textContent=pending.request.body ?? '(No request body)';
  $('previewDigest').textContent=`Mandate SHA-256: ${pending.mandate_digest}`;
  $('preview').scrollIntoView({block:'nearest'});
}
async function scan() {
  controller.cancel(); preview(); $('resultSection').hidden=true; $('signals').replaceChildren();
  const settings=await getSettings(storage);
  if (!settings.onboarded) throw new Error('Accept the history disclosure before scanning.');
  message('Reading local history…');
  const {data,options,coverage}=await readHistory(chrome.history,{storage,excludedHosts:settings.excludedHosts,
    onProgress:(done,total)=>message(`Reading local history: ${done} of ${total} URLs…`)});
  const signals=await detectAll(data,options);
  const decisions=await Promise.all(signals.map(signal=>decisionFor(signal,settings)));
  await appendTraces(storage,signals.map((signal,i)=>({kind:'mandate_decision',signal_key:signal.key,
    signal_kind:signal.kind,...decisions[i],planned_action:PLANS[signal.kind],triage:'not_run',executed:false,execution_status:'not_run'})));
  message(`${signals.length} signals from ${coverage.visits} visits. ${coverage.skipped} unsupported URLs skipped. Nothing sent.`);
  for (const [i,signal] of signals.entries()) {
    const decision=decisions[i];
    const card=document.createElement('article');
    const title=document.createElement('h2'); title.textContent=`${signal.kind.replaceAll('_',' ')} · ${signal.host ?? scrubText(signal.term)}`;
    const badge=document.createElement('span'); badge.className=`badge ${decision.verdict}`; badge.textContent=decision.verdict;
    const reason=document.createElement('p'); reason.textContent=decision.reason;
    const digest=document.createElement('p'); digest.className='digest'; digest.textContent=`Mandate SHA-256: ${decision.mandate_digest}`;
    const details=document.createElement('details');
    const summary=document.createElement('summary'); summary.textContent='Local evidence (not the outgoing request)';
    const evidence=document.createElement('pre'); evidence.textContent=JSON.stringify(signal.evidence,null,2);
    details.append(summary,evidence);
    const button=document.createElement('button'); button.textContent='Preview request';
    button.dataset.blocked=String(decision.verdict !== 'allow'); button.disabled=decision.verdict !== 'allow';
    button.addEventListener('click',task(async()=>{ await controller.prepare(signal,settings.excludedHosts); $('resultSection').hidden=true; $('quoteCard').replaceChildren(); $('result').textContent=''; preview(); }));
    card.append(title,badge,reason,digest,details,button); $('signals').append(card);
  }
  if (!signals.length) message('No signals found in this local window. Nothing was sent.');
}
$('accept').addEventListener('click',task(async()=>{
  await acceptConsent(storage); $('onboarding').hidden=true; $('mainControls').hidden=false;
  message('Local scans enabled. Add API keys in Settings when you want AI suggestions.');
}));
$('revoke').addEventListener('click',async()=>{
  try {
  await deleteAllData(storage); controller.discard(); preview(); $('signals').replaceChildren(); $('quoteCard').replaceChildren(); $('result').textContent='';
  $('resultSection').hidden=true; $('mainControls').hidden=true; $('onboarding').hidden=false;
  message('Consent withdrawn. All extension keys, settings and trace deleted.');
  } catch(error) { await showError(error); }
});
$('scan').addEventListener('click',task(scan));
$('settings').addEventListener('click',task(()=>chrome.runtime.openOptionsPage()));
$('workspace').addEventListener('click',()=>window.open(chrome.runtime.getURL('popup.html'),'_blank','noopener'));
$('cancel').addEventListener('click',task(async()=>{controller.cancel();preview();message('Cancelled. No further requests will be sent.');}));
$('run').addEventListener('click',task(async()=>{
  message('Running only the displayed request…');
  try {
    const result=await controller.run();
    message(result.status === 'SKIP' ? 'Triage chose SKIP. No skill was run.' : result.pending ? 'Request complete. Review the next request before running it.' : 'Suggestion complete.');
    if (result.quote) { renderQuoteCard($('quoteCard'),result.quote); $('resultSection').hidden=false; }
    if (result.text) { $('result').textContent=result.text; $('resultSection').hidden=false; }
  } finally { preview(); }
}));
$('export').addEventListener('click',task(async()=>{
  const records=await readTrace(storage);
  const blob=new Blob([JSON.stringify({format:'before-you-ask-trace-v1',records},null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=url; a.download=`before-you-ask-trace-${new Date().toISOString().replace(/[-:]/g,'').replace(/\.\d+Z$/,'Z')}.json`;
  document.body.append(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),30000);
  message('Trace exported locally. It contains the scrubbed requests you approved; share it carefully.');
}));
await task(async()=>{
  await storage.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});await migrateSettings(storage);
  const settings=await getSettings(storage); await readTrace(storage);
  $('onboarding').hidden=settings.onboarded; $('mainControls').hidden=!settings.onboarded;
})();
