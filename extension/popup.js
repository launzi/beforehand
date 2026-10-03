import {renderQuoteCard} from './core/quote-card.js';
import {readHistory} from './core/history.js';
import {detectAll} from './core/signals.js';
import {getSettings,migrateSettings,secretValues,readTrace,appendTraces,acceptConsent,deleteAllData} from './core/storage.js';
import {PLANS} from './core/mandate.js';
import {Controller,decisionFor} from './core/controller.js';
import {scrubText} from './core/scrub.js';
import {describeRequest} from './core/preview.js';
const $ = id => document.getElementById(id);
const storage = chrome.storage.local;
const controller = new Controller(storage);
let busy = false;
function message(text='') { $('status').textContent=text; }
async function showError(error) {
  // Never echo network response bodies or arbitrary key-containing errors.
  let text=error instanceof Error ? error.message : 'The operation failed.';
  try {
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
  $('run').disabled=!pending;
  if (!pending) return;
  let description;
  try { description=describeRequest(pending.request); }
  catch (error) { controller.cancel();$('preview').hidden=true;$('run').disabled=true;throw error; }
  const {destination,sends,never}=description;
  $('flowDest').textContent={ai:'🤖',research:'🔎',quote:'🇰🇷'}[destination.kind];
  $('flowDest').title=destination.label;
  $('flowDest').setAttribute('aria-label',destination.label);
  $('stage').textContent=pending.stage==='models' ? 'Find available models'
    : destination.kind==='ai' ? `Ask ${destination.label}` : destination.kind==='research' ? 'Research via Korea Concierge' : 'Quote from Korea Concierge';
  $('sends').replaceChildren();$('never').replaceChildren();
  for (const {field,value} of sends.length ? sends : [{field:'body',value:'None (model list request)'}]) {
    const name=document.createElement('dt'), content=document.createElement('dd');
    name.textContent=field;content.textContent=value;$('sends').append(name,content);
  }
  for (const item of never) { const li=document.createElement('li');li.textContent=item;$('never').append(li); }
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
  message(`${signals.length} signals · nothing sent`);
  $('scanDetails').hidden=false;
  $('scanCoverage').textContent=`${coverage.visits} visits · ${coverage.skipped} unsupported URLs skipped`;
  for (const [i,signal] of signals.entries()) {
    const decision=decisions[i];
    const card=document.createElement('div');card.className='signal-row';
    const title=document.createElement('h2');title.className='signal-subject';
    const label={new_entry:'New',unresolved:'Unfinished',recurring:'Repeat',dropped:'Quiet',korea_product:'Korea'}[signal.kind];
    title.textContent=`${label} · ${signal.host ?? scrubText(signal.term)}`;
    const badge=document.createElement('span'); badge.className=`status-pill ${decision.verdict}`;
    badge.textContent=`${{allow:'✓',hold:'⏸',deny:'✕'}[decision.verdict]} ${decision.verdict}`;
    const reason=document.createElement('p'); reason.textContent=decision.reason;
    const digest=document.createElement('p'); digest.className='digest'; digest.textContent=`Mandate SHA-256: ${decision.mandate_digest}`;
    const details=document.createElement('details');
    const summary=document.createElement('summary'); summary.textContent='Local evidence (not the outgoing request)';
    const evidence=document.createElement('pre'); evidence.textContent=JSON.stringify(signal.evidence,null,2);
    details.append(summary,reason,digest,evidence);
    const button=document.createElement('button'); button.textContent='Preview request';
    button.dataset.blocked=String(decision.verdict !== 'allow'); button.disabled=decision.verdict !== 'allow';
    button.addEventListener('click',task(async()=>{ await controller.prepare(signal,settings.excludedHosts); $('resultSection').hidden=true; $('quoteCard').replaceChildren(); $('result').textContent=''; preview(); }));
    button.className='secondary-action signal-preview';
    card.append(signalIcon(signal.kind),title,badge,button,details); $('signals').append(card);
  }
}
function signalIcon(kind) {
  if (kind==='korea_product') { const flag=document.createElement('span');flag.className='signal-symbol';flag.textContent='🇰🇷';return flag; }
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('class','signal-symbol');svg.setAttribute('aria-hidden','true');
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');
  path.setAttribute('d',{new_entry:'M12 5v14M5 12h14',unresolved:'M17 11a6 6 0 1 1-12 0 6 6 0 0 1 12 0M16 16l5 5',recurring:'M4 12a8 8 0 0 1 14-5M20 12a8 8 0 0 1-14 5M18 3v4h-4M6 21v-4h4',dropped:'M7 6v12M17 6v12'}[kind]);
  svg.append(path);return svg;
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
