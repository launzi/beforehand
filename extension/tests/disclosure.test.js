// extension/tests/disclosure.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {build,manifestFor,TARGETS} from '../scripts/build.mjs';
import {renderMarkdown} from '../scripts/md.mjs';
import {DISCLOSURE_VERSION} from '../core/storage.js';
const privacy=await readFile(new URL('../PRIVACY.md',import.meta.url),'utf8');
const hostsIn=text=>new Set([...text.matchAll(/\b(api\.openai\.com|api\.anthropic\.com|api\.tokenfactory\.nebius\.com|concierge\.youngji\.kim|api\.tavily\.com)\b/g)].map(m=>m[1]));
test('disclosure version is 3 everywhere',async()=>{
  assert.equal(DISCLOSURE_VERSION,3);
  assert.match(privacy,/Policy version 3/);
  assert.match(await readFile(new URL('../popup.html',import.meta.url),'utf8'),/Disclosure version 3/);
});
test('every destination a build can contact is named in PRIVACY.md, and no retired one is',()=>{
  const named=hostsIn(privacy);
  for (const t of ['store','hackathon']) for (const h of manifestFor(t).host_permissions.map(x=>new URL(x.replace('/*','')).host)) assert.ok(named.has(h),`${t}: ${h} missing from PRIVACY.md`);
  assert.ok(!named.has('api.tavily.com'),'PRIVACY.md must not say the extension calls Tavily directly');
});
test('markdown renderer escapes HTML and keeps tables, lists, links, bold and code',()=>{
  const html=renderMarkdown('# T\n\nA **b** `c` [d](https://e.example) <script>\n\n- x\n- y\n\n| h1 | h2 |\n|---|---|\n| a | b |\n');
  assert.ok(html.includes('<h1>T</h1>') && html.includes('<strong>b</strong>') && html.includes('<code>c</code>'));
  assert.ok(html.includes('<a href="https://e.example" rel="noopener noreferrer">d</a>') && html.includes('&lt;script&gt;'));
  assert.ok(html.includes('<ul><li>x</li><li>y</li></ul>') && html.includes('<table>') && html.includes('<td>b</td>'));
  assert.ok(!renderMarkdown('[x](javascript:alert(1))').includes('javascript:'));
});
test('no unreplaced template markers ship',()=>{ assert.ok(!renderMarkdown(privacy.replace('{{EFFECTIVE_DATE}}','2026-10-15')).includes('{{')); });

test('applied disclosures preserve the approved drafts verbatim',async()=>{
  const read=path=>readFile(new URL(path,import.meta.url),'utf8');
  assert.equal(privacy,await read('../drafts/PRIVACY.v3.md'));
  assert.equal(await read('../STORE_LISTING.md'),await read('../drafts/STORE_LISTING.v3.md'));
  const popup=await read('../popup.html');
  assert.equal(popup.match(/<details id="consentDetails">[\s\S]*?<\/details>/)[0],
    (await read('../drafts/consent.v3.html')).trimEnd());
});

test('both builds generate privacy HTML from the policy and replace every effective date',async()=>{
  for (const target of ['store','hackathon']) {
    await build(target);
    const html=await readFile(new URL(`../dist/${target}/privacy.html`,import.meta.url),'utf8');
    const body=renderMarkdown(privacy.replaceAll('{{EFFECTIVE_DATE}}',TARGETS[target].effectiveDate));
    assert.equal(html,`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Beforehand — Privacy</title><link rel="stylesheet" href="style.css"></head><body><main class="doc">${body}</main></body></html>\n`);
    assert.ok(!html.includes('{{EFFECTIVE_DATE}}'));
    assert.ok(!html.includes('Before You Ask'));
    if (target==='store') assert.equal(await readFile(new URL('../privacy.html',import.meta.url),'utf8'),html);
  }
});
