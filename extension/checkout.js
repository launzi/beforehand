import {COUNTRY_NAMES} from './core/settings-ui.js';
const PROVIDERS={card:'Stripe',paypal:'PayPal'};
const LINES=[['Item','itemKrw'],['International shipping','shippingKrw'],['Service fee','serviceFeeKrw'],['Payment fee','paymentFeeKrw']];
export async function initCheckout({doc,chrome,location,now=()=>Date.now(),setInterval:every=globalThis.setInterval,clearInterval:cancel=globalThis.clearInterval}) {
 const params=new URLSearchParams(location.search),handle=params.get('h'),raw=params.get('c');
 const choice=raw==='same'?'same':raw==='0'?0:raw==='1'?1:null;
 const id=name=>doc.getElementById(name);
 const form=id('checkoutForm'),pay=id('pay'),notice=id('notice'),error=id('error'),summary=id('summary'),expiry=id('expiry');
 const email=id('email'),name=id('name'),card=id('methodCard'),paypal=id('methodPaypal'),switcher=id('switchMethod');
 const el=(tag,text,className)=>{const n=doc.createElement(tag);if(text!=null)n.textContent=text;if(className)n.className=className;return n;};
 let timer=null,expiresAt=null,submitting=false;
 const method=()=>paypal.checked?'paypal':'card';
 function showMethod() {
  switcher.textContent=method()==='card'?'Use PayPal instead':'Use card instead';
 }
 function gone() {
  if(timer)cancel(timer);expiry.hidden=true;form.hidden=true;summary.hidden=true;pay.disabled=true;
  notice.textContent='Price changed. Go back to the shop and check again to see the current price.';
 }
 function tick() {
  const left=Math.floor((Date.parse(expiresAt)-now())/1000);
  if(!Number.isFinite(left)) {expiry.hidden=true;return;}
  expiry.hidden=false;
  expiry.textContent=left>0?`Quote expires in ${Math.floor(left/60)}:${String(left%60).padStart(2,'0')}`:'Quote expired · we check again when you continue';
 }
 function startClock(at) {expiresAt=at;if(timer)cancel(timer);tick();timer=every(tick,1000);}
 function render(q,destination,previous) {
  const money=(value,currency=q.currency,digits)=>new Intl.NumberFormat('en',{style:'currency',currency,...(digits!=null?{maximumFractionDigits:digits,minimumFractionDigits:digits}:{})}).format(value);
  const krw=value=>money(value,'KRW',0);
  const row=(label,value,className)=>{const r=el('div',null,'line'+(className?' '+className:''));r.append(el('span',label),el('span',value));return r;};
  summary.replaceChildren();
  summary.append(el('p',`Korea → ${COUNTRY_NAMES[destination] ?? destination ?? ''}`,'eyebrow'),el('h1',q.title,'item'),el('p','Sold by Munteok','mute sm'));
  if(previous && previous.payNow.total!==q.payNow.total) {
   const banner=el('p',null,'changed');banner.append(el('b','Price changed'),el('span',' · Pay now '),el('s',money(previous.payNow.total)),el('span',' → '),el('b',money(q.payNow.total)));summary.append(banner);
  }
  summary.append(el('p','Pay now','mute sm label'),el('p',money(q.payNow.total),'big'));
  const tl=el('div',null,'timeline');
  for(const [label,key] of LINES) if(Number.isFinite(q.payNow[key])) tl.append(row(label,krw(q.payNow[key])));
  const strong=el('div',null,'line strong'),left=el('span');left.append(el('b','Pay now'));
  if(Number.isFinite(q.payNow.fxRate)) left.append(el('span',` · ${money(1,q.currency,0)} = ${krw(q.payNow.fxRate)}`,'mute'));
  strong.append(left,el('b',money(q.payNow.total)));tl.append(strong);
  if(q.dutyOnDelivery.estimate>0) tl.append(row('Estimated duty · pay on delivery',money(q.dutyOnDelivery.estimate),'later'));
  summary.append(tl,row('Estimated total',money(q.totalCost),'total'));
  summary.hidden=false;
 }
 function apply(reply) {render(reply.snapshot,reply.destination,reply.previous);if(reply.expiresAt)startClock(reply.expiresAt);}
 pay.disabled=true;
 if(!handle || choice===null) {gone();return;}
 try {
  const reply=await chrome.runtime.sendMessage({type:'checkout_snapshot',handle,choice});
  if(!reply?.snapshot) {gone();return;}
  apply(reply);form.hidden=false;pay.disabled=false;notice.textContent='';notice.hidden=true;
 } catch {notice.textContent="Couldn't load your quote. Go back to the shop and try again.";return;}
 for(const input of [card,paypal]) input.addEventListener('change',showMethod);
 switcher.addEventListener('click',()=>{(method()==='card'?paypal:card).checked=true;showMethod();});
 showMethod();
 form.addEventListener('submit',async event=>{
  event.preventDefault();if(submitting || pay.disabled)return;
  submitting=true;pay.disabled=true;error.hidden=true;switcher.hidden=true;
  const chosen=method();pay.textContent=`Opening ${PROVIDERS[chosen]}…`;pay.classList?.add('busy');
  let reply;
  try {reply=await chrome.runtime.sendMessage({type:'buy',handle,choice,email:email.value.trim(),name:name.value.trim(),method:chosen});}
  catch {reply=null;}
  pay.classList?.remove('busy');submitting=false;
  if(reply?.ok)return;
  if(reply?.error==='changed') {
   if(!reply.snapshot) {gone();return;}
   apply(reply);pay.textContent='Continue to payment';pay.disabled=false;return;
  }
  error.textContent=reply?.kind==='rate_limited'?'Too many checks. Try again in a few minutes.':"Couldn't open the payment page. You haven't been charged.";
  error.hidden=false;pay.textContent='Try again';pay.disabled=false;
  if(reply?.kind!=='rate_limited')switcher.hidden=false;
 });
}
if(globalThis.document && globalThis.chrome?.runtime) void initCheckout({doc:document,chrome,location:globalThis.location});
