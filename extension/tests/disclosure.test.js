import test from 'node:test';
import assert from 'node:assert/strict';
import {DISCLOSURE_V4} from '../core/disclosure.js';
test('approved disclosure describes product-only checks and buyer controls',()=>{
 assert.match(DISCLOSURE_V4,/product name and brand/); assert.match(DISCLOSURE_V4,/Serper/);
 assert.match(DISCLOSURE_V4,/Turn off and delete everything/);
});
