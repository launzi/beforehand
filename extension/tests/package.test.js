import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir,stat} from 'node:fs/promises';
const root=new URL('../',import.meta.url);
const read=path=>readFile(new URL(path,root),'utf8');
test('MV3 manifest has only requested permissions and explicit provider hosts',async()=>{
  const m=JSON.parse(await read('manifest.json'));
  assert.equal(m.manifest_version,3);assert.equal(m.name,'Before You Ask');assert.equal(m.version,'0.1.0');
  assert.deepEqual(m.permissions,['history','storage']);
  assert.deepEqual(m.host_permissions,['https://api.tokenfactory.nebius.com/*','https://api.tavily.com/*']);
  assert.equal(m.background,undefined);assert.equal(m.content_scripts,undefined);
  for (const file of [m.action.default_popup,m.options_page]) assert.ok((await stat(new URL(file,root))).isFile());
  assert.ok(m.content_security_policy.extension_pages.includes("script-src 'self'"));
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
  assert.ok(privacy.includes('Munteok'));assert.ok(privacy.includes('TODO'));
  const short=listing.split('## Short description\n\n')[1].split('\n')[0];assert.ok(short.length<=132,short.length);
  assert.ok((await read('LICENSE')).includes('Apache License'));
  const p=JSON.parse(await read('package.json'));assert.equal(p.dependencies,undefined);assert.equal(p.devDependencies,undefined);
});
