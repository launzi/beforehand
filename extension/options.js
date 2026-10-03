import {getSettings,migrateSettings,readTrace,deleteTrace,deleteAllData} from './core/storage.js';
import {searchPolicy,mandateDigest} from './core/mandate.js';
import {activeProviders,PRESETS} from './core/presets.js';
const $=id=>document.getElementById(id), storage=chrome.storage.local;
const radios=name=>Array.from(document.getElementsByName(name));
const selected=name=>radios(name).find(input=>input.checked)?.value;
async function act(fn) {
  $('error').textContent=''; $('status').textContent='';
  try { await fn(); } catch { $('error').textContent='The local settings operation failed. Check the hostname list and local storage access; no API request was sent.'; }
}
function updateKeyHelp() {
  $('keyHelp').textContent=PRESETS[selected('provider')]?.keyHelp ?? '';
}
function providers() {
  $('providers').replaceChildren();
  for (const id of activeProviders()) {
    const label=document.createElement('label'), input=document.createElement('input'), text=document.createElement('span');
    input.type='radio';input.name='provider';input.value=id;text.textContent=PRESETS[id].label;
    input.addEventListener('change',()=>{
      if (!input.checked) return;
      $('providerKey').value='';$('providerKey').type='password';$('toggleKey').setAttribute('aria-label','Show key');
      updateKeyHelp();
    });
    label.append(input,text);$('providers').append(label);
  }
}
async function load() {
  const settings=await getSettings(storage); await readTrace(storage);
  $('country').value=settings.destination;
  for (const input of radios('provider')) input.checked=input.value===settings.provider;
  $('providerKey').value=settings.providerKey;$('providerKey').type='password';$('toggleKey').setAttribute('aria-label','Show key');
  updateKeyHelp();
  const policy=!settings.mandate.allow_search ? 'deny' : settings.mandate.require_confirmation.includes('research_briefing') ? 'hold' : 'allow';
  for (const input of radios('policy')) input.checked=input.value===policy;
  $('excluded').value=settings.excludedHosts.join('\n');
  $('digest').textContent=`Mandate SHA-256: ${await mandateDigest(settings.mandate)}`;
  if (settings.mandate.error) $('error').textContent='Stored mandate is invalid and denies all actions. Save valid settings to replace it.';
}
$('toggleKey').addEventListener('click',()=>{
  const show=$('providerKey').type==='password';$('providerKey').type=show ? 'text' : 'password';
  $('toggleKey').setAttribute('aria-label',show ? 'Hide key' : 'Show key');
});
$('form').addEventListener('submit',event=>{
  event.preventDefault();
  return act(async()=>{
    const provider=selected('provider'),policy=selected('policy');
    if (!activeProviders().includes(provider) || !['allow','hold','deny'].includes(policy)) throw new Error('Invalid settings');
    const excludedHosts=[...new Set($('excluded').value.split('\n').map(s=>s.trim().toLowerCase()).filter(Boolean))];
    if (excludedHosts.some(s=>! /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(s))) throw new Error('Invalid hostname');
    const mandate=searchPolicy(policy);
    await storage.set({provider,providerKey:$('providerKey').value.trim(),mandate,excludedHosts,destination:$('country').value});
    $('digest').textContent=`Mandate SHA-256: ${await mandateDigest(mandate)}`;
    $('status').textContent='Saved locally. Scan again to use the new settings. No provider was contacted.';
  });
});
$('clearTrace').addEventListener('click',()=>act(async()=>{
  if (!window.confirm('Delete the local log? This cannot be undone.')) return;
  await deleteTrace(storage);$('status').textContent='Local trace deleted.';
}));
$('clearAll').addEventListener('click',()=>act(async()=>{
  if (!window.confirm('Delete all extension keys, settings, consent and local log? This cannot be undone.')) return;
  await deleteAllData(storage);await load();$('status').textContent='All extension data deleted. Local scans require the disclosure again.';
}));
await act(async()=>{await storage.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});await migrateSettings(storage);providers();await load();});
