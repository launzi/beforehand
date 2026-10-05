import test from 'node:test';
import assert from 'node:assert/strict';
import {DISCLOSURE_V4} from '../core/disclosure.js';
test('approved disclosure describes product-only checks and buyer controls',()=>{
 assert.match(DISCLOSURE_V4,/product name and brand/); assert.match(DISCLOSURE_V4,/Serper/);
 assert.match(DISCLOSURE_V4,/Turn off and delete everything/);
});

import {DISCLOSURE_VERSION,getSettings,acceptConsent,deleteAllData} from '../core/storage.js';
import {Store} from './helpers.js';
test('v4 consent defaults to manual and delete-all resets onboarding',async()=>{
 const s=new Store({consent:{accepted:true,version:3},autoCheck:true});
 assert.equal(DISCLOSURE_VERSION,4); assert.equal((await getSettings(s)).autoCheck,false);
 await acceptConsent(s,{autoCheck:false}); assert.equal((await getSettings(s)).onboarded,true);
 await deleteAllData(s); assert.equal((await getSettings(s)).onboarded,false);
});

import {readFile} from 'node:fs/promises';
import {manifestFor} from '../scripts/build.mjs';
test('privacy names every shop host, KC and all processors; Limited Use is preserved',async()=>{
 const text=await readFile(new URL('../PRIVACY.md',import.meta.url),'utf8');
 for(const pattern of manifestFor('store').host_permissions) assert.ok(text.includes(pattern.replace('https://','').replace('*.','').replace('/*','')),pattern);
 for(const name of ['Nebius','Serper','Stripe','Jikgugak']) assert.ok(text.includes(name));
 assert.ok(text.includes('The use of information received from Google APIs will adhere to the Chrome Web Store User Data Policy, including the Limited Use requirements.'));
 assert.doesNotMatch(text,/\{\{|provider key|no checkout/i);
});
test('store listing shares the manifest description and keeps detailed copy short',async()=>{
 const listing=await readFile(new URL('../STORE_LISTING.md',import.meta.url),'utf8');assert.ok(listing.includes(manifestFor('store').description));
 const detail=listing.split('## Detailed description\n')[1]?.split('\n## ')[0]?.trim();assert.ok(detail && detail.length<=1500);
});
test('approved consent draft and constant remain identical',async()=>{
 assert.equal((await readFile(new URL('../drafts/consent.v4.md',import.meta.url),'utf8')).trimEnd(),DISCLOSURE_V4);
});
test('privacy and listing describe the checkout boundary, quote refresh and amount sources',async()=>{
 for(const file of ['PRIVACY.md','STORE_LISTING.md']) {
  const text=await readFile(new URL('../'+file,import.meta.url),'utf8');
  assert.match(text,/extension page/);assert.match(text,/same product name, brand and delivery country/);
  assert.match(text,/tokens are kept in Chrome's in-memory session storage.*sent only to Korea Concierge to start checkout/);
  assert.match(text,/local price.*shop page/i);assert.match(text,/savings.*computed on your device/i);
  assert.match(text,/Korea amounts come from the quote engine/);
  assert.match(text,/email and name.*Korea Concierge to create (?:the|your|an) order/);
  assert.match(text,/not stored by the extension/);
 }
});
