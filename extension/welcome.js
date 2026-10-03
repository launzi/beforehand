import {DISCLOSURE_V4} from './core/disclosure.js';
import {acceptConsent} from './core/storage.js';
import {SHOPS} from './core/shops.js';
export const COUNTRIES={US:'United States',GB:'United Kingdom',JP:'Japan',CN:'China',TW:'Taiwan',HK:'Hong Kong'};
export function renderDisclosure(root,doc) {
 root.replaceChildren();
 DISCLOSURE_V4.split('\n\n').forEach((block,index)=>{
  if(index)root.append('\n\n');const section=doc.createElement('section');const lines=block.split('\n');let list=null;
  lines.forEach((line,i)=>{
   if(i && !(line.startsWith('• ') && list))section.append('\n');
   const tag=i===0?'h2':line.startsWith('• ')?'li':'p',node=doc.createElement(tag);node.textContent=line;
   if(tag==='li') {if(!list){list=doc.createElement('ul');list.className='disclosure-list';section.append(list);}else list.append('\n');list.append(node);}
   else {list=null;section.append(node);}
  });root.append(section);
 });
}
export async function initWelcome({doc,chrome}) {
 const id=name=>doc.getElementById(name);renderDisclosure(id('disclosure'),doc);
 async function accept(autoCheck) {
  id('enable').disabled=true;id('notNow').disabled=true;
  try {
   await acceptConsent(chrome.storage.local,{autoCheck});id('welcomeActions').hidden=true;id('disclosure').hidden=true;
   id('complete').hidden=false;id('complete').textContent="You're set. Visit a product page on a supported shop.";
   id('shops').replaceChildren();
   for(const [code,country] of Object.entries(COUNTRIES)) {
    const heading=doc.createElement('h3');heading.textContent=country;const p=doc.createElement('p');p.textContent=SHOPS.filter(s=>s.country===code).map(s=>s.host).join(' · ');id('shops').append(heading,p);
   }
  }catch {id('complete').hidden=false;id('complete').textContent='Could not save your choice. Please try again.';id('enable').disabled=false;id('notNow').disabled=false;}
 }
 id('enable').addEventListener('click',()=>accept(true));id('notNow').addEventListener('click',()=>accept(false));
}
if(globalThis.document && globalThis.chrome?.storage) void initWelcome({doc:document,chrome});
