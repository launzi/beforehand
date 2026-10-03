import test from 'node:test';
import assert from 'node:assert/strict';
import {manifestFor} from '../scripts/build.mjs';
import {SHOPS,shopFor,defaultDestination} from '../core/shops.js';
test('manifest asks only for storage, the shops and KC',()=>{
 const m=manifestFor('store'); assert.deepEqual(m.permissions,['storage']);
 assert.equal(SHOPS.length,25); assert.equal(m.host_permissions.length,26);
 assert.ok(m.host_permissions.includes('https://concierge.youngji.kim/*'));
 assert.doesNotMatch(JSON.stringify(m),/history|tabs|<all_urls>|scripting|web_accessible|openai|anthropic|nebius/);
 assert.match(m.content_security_policy.extension_pages,/connect-src https:\/\/concierge\.youngji\.kim$/);
 assert.ok(m.description.length<=132); assert.equal(m.name,'beforehand');
 assert.deepEqual(m.content_scripts[0].js,['core/extract.js','core/card.js','content.js']);
 assert.throws(()=>manifestFor('hackathon'));
});
test('shopFor matches subdomains and prefers the longest host',()=>{
 assert.equal(shopFor('item.jd.com').host,'jd.com');
 assert.equal(shopFor('store.shopping.yahoo.co.jp').host,'shopping.yahoo.co.jp');
 assert.equal(shopFor('www.amazon.co.jp').country,'JP');
 assert.equal(shopFor('evilamazon.com'),null); assert.equal(shopFor('amazon.com.evil.test'),null);
 assert.equal(defaultDestination('www.boots.com'),'GB');
});
