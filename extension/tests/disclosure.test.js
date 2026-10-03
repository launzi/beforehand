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
