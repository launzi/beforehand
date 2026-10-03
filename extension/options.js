import {getSettings,readTrace,deleteTrace,deleteAllData} from './core/storage.js';
import {searchPolicy,mandateDigest} from './core/mandate.js';
const $=id=>document.getElementById(id), storage=chrome.storage.local;
async function act(fn) {
  $('error').textContent=''; $('status').textContent='';
  try { await fn(); } catch { $('error').textContent='The local settings operation failed. Check the hostname list and local storage access; no API request was sent.'; }
}
async function load() {
  const settings=await getSettings(storage); await readTrace(storage);
  $('nebius').value=settings.nebiusKey; $('tavily').value=settings.tavilyKey;
  $('policy').value=!settings.mandate.allow_search ? 'deny' : settings.mandate.require_confirmation.includes('research_briefing') ? 'hold' : 'allow';
  $('excluded').value=settings.excludedHosts.join('\n');
  $('digest').textContent=`Mandate SHA-256: ${await mandateDigest(settings.mandate)}`;
  if (settings.mandate.error) $('error').textContent='Stored mandate is invalid and denies all actions. Save valid settings to replace it.';
}
$('form').addEventListener('submit',event=>{
  event.preventDefault();
  act(async()=>{
    const excludedHosts=[...new Set($('excluded').value.split('\n').map(s=>s.trim().toLowerCase()).filter(Boolean))];
    if (excludedHosts.some(s=>! /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(s))) throw new Error('Invalid hostname');
    const mandate=searchPolicy($('policy').value);
    await storage.set({nebiusKey:$('nebius').value.trim(),tavilyKey:$('tavily').value.trim(),mandate,excludedHosts});
    $('digest').textContent=`Mandate SHA-256: ${await mandateDigest(mandate)}`;
    $('status').textContent='Saved locally. Scan again to use the new settings. No provider was contacted.';
  });
});
$('clearTrace').addEventListener('click',()=>act(async()=>{await deleteTrace(storage);$('status').textContent='Local trace deleted.';}));
$('clearAll').addEventListener('click',()=>act(async()=>{
  if (!window.confirm('Delete all extension keys, settings, onboarding consent and local trace?')) return;
  await deleteAllData(storage); await load(); $('status').textContent='All extension data deleted. Local scans require the disclosure again.';
}));
await act(async()=>{await storage.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});await load();});
