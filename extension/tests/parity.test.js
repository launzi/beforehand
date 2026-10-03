import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import {detectAll} from '../core/signals.js';
import {scrubURL} from '../core/scrub.js';
import {evaluateMandate,canonicalMandate} from '../core/mandate.js';
import * as prompts from '../core/prompts.js';
import {formatEvidence} from '../core/agent.js';
const directory = new URL('./vectors/',import.meta.url);
const file = (await readdir(directory)).filter(x=>/^parity-.*\.json$/.test(x)).sort().at(-1);
if (!file) throw new Error('Generate vectors with extension/tests/export_vectors.py first');
const vector = JSON.parse(await readFile(new URL(file,directory),'utf8'));
for (const c of vector.cases) test(`Python detector parity: ${c.name}`,async()=>{
  assert.deepEqual(await detectAll(vector.data,c.options),c.expected);
});
for (const c of vector.edge.cases) test(`Python detector boundary parity: ${c.name}`,async()=>{
  assert.deepEqual(await detectAll(vector.edge.data,c.options),c.expected);
});
for (const [i,c] of vector.scrub.entries()) test(`Python scrub parity: ${i}`,()=>assert.deepEqual(scrubURL(c.input),c.expected));
for (const [i,c] of vector.mandate.entries()) test(`Python mandate + canonical bytes + SHA-256 parity: ${i}`,async()=>{
  assert.equal(canonicalMandate(c.mandate),c.canonical);
  assert.deepEqual(await evaluateMandate(c.mandate,c.signal,c.plan),c.expected);
});
test('Prompt and token budget literals match Python oracle',()=>{
  for (const [k,v] of Object.entries(vector.constants)) assert.deepEqual(prompts[k],v);
});
for (const [i,c] of vector.formatting.entries()) test(`Python triage/skill evidence formatting: ${i}`,()=>{
  assert.equal(formatEvidence(c.evidence),c.triage);
  assert.equal(formatEvidence(c.evidence,true),c.skill);
});
