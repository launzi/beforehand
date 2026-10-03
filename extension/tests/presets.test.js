// extension/tests/presets.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import {PRESETS,activeProviders,presetFor} from '../core/presets.js';
import {BUILD} from '../core/build-config.js';
test('store build exposes only openai and anthropic by default',()=>{
  assert.equal(BUILD.target,'store');
  assert.deepEqual(activeProviders(),['openai','anthropic']);
  assert.equal(BUILD.defaultProvider,'openai');
});
test('presets have fixed https endpoints and role patterns',()=>{
  for (const id of ['openai','anthropic','nebius']) {
    const p=PRESETS[id];
    assert.match(p.chat.url,/^https:\/\//); assert.match(p.models.url,/^https:\/\//);
    assert.ok(p.roles.triage.length && p.roles.skill.length);
  }
  assert.equal(PRESETS.openai.chat.url,'https://api.openai.com/v1/chat/completions');
  assert.equal(PRESETS.anthropic.chat.url,'https://api.anthropic.com/v1/messages');
  assert.equal(PRESETS.nebius.chat.url,'https://api.tokenfactory.nebius.com/v1/chat/completions');
});
test('presetFor rejects providers outside the build',()=>{
  assert.throws(()=>presetFor('nebius'),/not available/);
  assert.equal(presetFor('nebius',{providers:['nebius']}).id,'nebius');
});
