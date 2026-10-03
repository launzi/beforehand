import {getSettings,updateSettings} from './storage.js';
import {SHOPS,shopFor} from './shops.js';
import {DESTINATIONS} from './match.js';
export const COUNTRY_NAMES={US:'United States',GB:'United Kingdom',JP:'Japan',CN:'China',TW:'Taiwan',HK:'Hong Kong'};
export async function renderSettings({doc,chrome,root,shopRoot}) {
 const storage=chrome.storage.local,settings=await getSettings(storage);root.replaceChildren();
 const el=(tag,text)=>{const node=doc.createElement(tag);if(text!=null)node.textContent=text;return node;};
 const error=el('p');error.setAttribute('role','status');
 async function save(patch,input) {input.disabled=true;try {await updateSettings(storage,patch);error.textContent='Saved.';}catch {error.textContent='Could not save. Reopen this page and try again.';}finally {input.disabled=!settings.onboarded;}}
 function toggle(parent,label,checked,id,change) {
  const row=el('label',label);row.className='switch-row';const input=el('input');input.type='checkbox';input.id=id;input.checked=checked;input.disabled=!settings.onboarded;
  input.addEventListener('change',()=>change(input));row.append(input);parent.append(row);return input;
 }
 async function setShop(shop,input) {
  const current=await getSettings(storage),disabled=new Set(current.disabledShops);if(input.checked)disabled.delete(shop.host);else disabled.add(shop.host);await save({disabledShops:[...disabled]},input);
 }
 let shop=null;
 try {const [tab]=await chrome.tabs.query({active:true,currentWindow:true});if(tab?.url){const url=new URL(tab.url);if(url.protocol==='https:')shop=shopFor(url.hostname);}}catch { /* Chrome may withhold the URL without host access. */ }
 if(shop) toggle(root,`Auto-check on ${shop.host}`,!settings.disabledShops.includes(shop.host),'autoShop',input=>setShop(shop,input));
 else root.append(el('p','Open a supported shop'));
 toggle(root,'Auto-check everywhere',settings.autoCheck,'autoEverywhere',input=>save({autoCheck:input.checked},input));
 const label=el('label','Ship to'),select=el('select');select.id='destination';select.disabled=!settings.onboarded;
 for(const [value,text] of [['','Auto (shop country)'],...DESTINATIONS.map(c=>[c,COUNTRY_NAMES[c]])]){const option=el('option',text);option.value=value;select.append(option);}
 select.value=settings.destination ?? '';select.addEventListener('change',()=>save({destination:select.value || null},select));label.append(select);root.append(label,error);
 if(!settings.onboarded) {const link=el('a','Set up beforehand');link.href=chrome.runtime.getURL('welcome.html');link.target='_blank';link.rel='noopener noreferrer';root.append(link);}
 if(shopRoot) {shopRoot.replaceChildren();for(const s of SHOPS)toggle(shopRoot,s.host,!settings.disabledShops.includes(s.host),'shop-'+s.host,input=>setShop(s,input));}
 return settings;
}
