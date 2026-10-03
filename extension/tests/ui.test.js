import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
test('brand assets are present',async()=>{
 for(const file of ['mark.svg','lockup.svg']) assert.match(await readFile(new URL('../icons/'+file,import.meta.url),'utf8'),/<svg/);
});
