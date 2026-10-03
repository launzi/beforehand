export async function initCheckout({doc,chrome,location}) {
 const params=new URLSearchParams(location.search),handle=params.get('h'),raw=params.get('c');
 const choice=raw==='same'?'same':raw==='0'?0:raw==='1'?1:null;
 const form=doc.getElementById('checkoutForm'),submit=doc.getElementById('continue'),notice=doc.getElementById('notice');
 const email=doc.getElementById('email'),name=doc.getElementById('name');
 const changed=()=>{notice.textContent='Price changed — check again. Return to the shop and click Check Korea price.';submit.disabled=true;};
 submit.disabled=true;
 if(!handle || choice===null) {changed();return;}
 try {
  const reply=await chrome.runtime.sendMessage({type:'checkout_snapshot',handle,choice});
  if(!reply?.snapshot) {changed();return;}
  const q=reply.snapshot,summary=doc.getElementById('summary');
  const money=value=>new Intl.NumberFormat('en',{style:'currency',currency:q.currency}).format(value);
  for(const [tag,text] of [['h2',q.title],['p',`Total ${money(q.totalCost)}`],['p',`Pay now ${money(q.payNow.total)}`],['p',`+ est. duty on delivery ${money(q.dutyOnDelivery.estimate)}`],['p','Seller: Munteok']]) {
   const node=doc.createElement(tag);node.textContent=text;summary.append(node);
  }
  form.hidden=false;submit.disabled=false;notice.textContent='';
 } catch {notice.textContent='Could not load checkout. Return to the shop and try again.';return;}
 let submitting=false;
 form.addEventListener('submit',async event=>{
  event.preventDefault();if(submitting || submit.disabled)return;
  submitting=true;submit.disabled=true;
  const buyer={email:email.value.trim(),name:name.value.trim()};email.value='';name.value='';
  notice.textContent='Opening payment…';
  try {
   const reply=await chrome.runtime.sendMessage({type:'buy',handle,choice,...buyer});
   if(reply?.error==='changed') {changed();return;}
   if(reply?.ok)return;
   notice.textContent='Could not start payment. Enter your details and try again.';
  } catch {notice.textContent='Could not start payment. Enter your details and try again.';}
  finally {buyer.email='';buyer.name='';}
  submitting=false;submit.disabled=false;
 });
}
if(globalThis.document && globalThis.chrome?.runtime) void initCheckout({doc:document,chrome,location:globalThis.location});
