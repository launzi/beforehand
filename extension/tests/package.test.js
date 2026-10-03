import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir,stat} from 'node:fs/promises';
const root=new URL('../',import.meta.url);
const read=path=>readFile(new URL(path,root),'utf8');
import {manifestFor,build} from '../scripts/build.mjs';
test('manifest per build lists only that build\'s destinations',()=>{
  const s=manifestFor('store'), h=manifestFor('hackathon');
  assert.deepEqual(s.permissions,['history','storage']);
  assert.deepEqual(s.host_permissions,['https://api.openai.com/*','https://api.anthropic.com/*','https://concierge.youngji.kim/*']);
  assert.deepEqual(h.host_permissions,['https://api.tokenfactory.nebius.com/*','https://concierge.youngji.kim/*']);
  for (const m of [s,h]) {
    assert.equal(m.manifest_version,3);assert.equal(m.name,'Beforehand');assert.equal(m.version,'0.2.0');
    assert.equal(m.background,undefined);assert.equal(m.content_scripts,undefined);
    assert.ok(!JSON.stringify(m).includes('tavily'));
    assert.match(m.content_security_policy.extension_pages,/script-src 'self'; object-src 'none'; connect-src /);
  }
  assert.ok(!s.content_security_policy.extension_pages.includes('tokenfactory'));
  assert.ok(!h.content_security_policy.extension_pages.includes('openai'));
});
test('checked-in manifest.json equals the store build',async()=>{
  assert.deepEqual(JSON.parse(await read('manifest.json')),manifestFor('store'));
});

test('UI assets and module imports resolve locally, with no inline or remote scripts',async()=>{
  for (const file of ['popup.html','options.html','privacy.html']) {
    const html=await read(file);assert.match(html,/<html lang="en">/);
    for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
      assert.equal(match[2],'');const source=/src="([^"]+)"/.exec(match[1])?.[1];assert.ok(source);assert.ok(!source.includes('://'));await read(source);
    }
    for (const match of html.matchAll(/(?:src|href)="([^"]+)"/g)) if (!match[1].includes('://')) await read(match[1]);
  }
  const files=['popup.js','options.js',...(await readdir(new URL('core/',root))).filter(x=>x.endsWith('.js')).map(x=>'core/'+x)];
  for (const file of files) {
    const js=await read(file);assert.doesNotMatch(js,/\beval\s*\(|\bnew\s+Function\b|\.innerHTML\s*=/);
    for (const match of js.matchAll(/from\s+['"]([^'"]+)['"]/g)) {
      assert.ok(match[1].startsWith('.'));await readFile(new URL(match[1],new URL(file,root)));
    }
  }
});
test('Popup controls referenced in JavaScript exist in shipped HTML',async()=>{
  for (const stem of ['popup','options']) {
    const js=await read(stem+'.js'),html=await read(stem+'.html');
    for (const match of js.matchAll(/\$\('([^']+)'\)/g)) assert.ok(html.includes(`id="${match[1]}"`),`${stem}: missing ${match[1]}`);
  }
});
test('Required privacy language and publisher are present; listing description meets 132-character ceiling',async()=>{
  const privacy=await read('PRIVACY.md'), listing=await read('STORE_LISTING.md');
  assert.ok(privacy.includes('The use of information received from Google APIs will adhere to the Chrome Web Store User Data Policy, including the Limited Use requirements.'));
  assert.ok(privacy.includes('Munteok'));assert.ok(privacy.includes('privacy@munteok.com'));assert.ok(!privacy.includes('TODO'));
  const short=listing.split('## Short description\n\n')[1].split('\n')[0];assert.ok(short.length<=132,short.length);
  assert.ok((await read('LICENSE')).includes('Apache License'));
  const p=JSON.parse(await read('package.json'));assert.equal(p.dependencies,undefined);assert.equal(p.devDependencies,undefined);
});

test('built manifests and UI titles use Beforehand for both targets',async()=>{
  for (const target of ['store','hackathon']) {
    await build(target);
    const manifest=JSON.parse(await read(`dist/${target}/manifest.json`));
    assert.deepEqual(manifest,manifestFor(target));
    assert.equal(manifest.name,'Beforehand');
    assert.equal(manifest.action.default_title,manifest.name);
    for (const file of ['popup.html','options.html']) {
      assert.ok((await read(`dist/${target}/${file}`)).includes(`<title>${manifest.name}`));
    }
  }
});
