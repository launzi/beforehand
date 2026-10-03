(()=>{
 const CSS=`:host{all:initial;color-scheme:light dark;--bg:light-dark(#fbfaf6,#1c1b19);--ink:light-dark(#161512,#f2efe8);--mute:light-dark(#5b574f,#a8a296);--line:light-dark(#e1dccf,#33312c);--accent:light-dark(#2b3bff,#8c97ff);--on-accent:light-dark(#ffffff,#161512);position:fixed;bottom:16px;right:16px;z-index:2147483000;font:14px/1.5 system-ui,sans-serif;color:var(--ink)}
 *{box-sizing:border-box}.card{width:340px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);overflow:auto;background:var(--bg);border:1px solid var(--ink);border-radius:16px;padding:18px;box-shadow:0 8px 32px #0002}.header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.brand{display:flex;align-items:center;gap:8px;font-weight:700}svg{width:24px;height:24px}.mark{fill:var(--accent)}h2{font-size:17px;margin:8px 0}p{margin:8px 0;overflow-wrap:anywhere}.total{font-size:30px;font-weight:700;letter-spacing:-1px}.muted{color:var(--mute)}button,input{font:inherit}button{cursor:pointer;background:var(--bg);color:var(--ink);border:1px solid var(--ink);border-radius:8px;padding:8px 12px}button.buy{background:var(--accent);color:var(--on-accent);border-color:var(--accent);width:100%;font-weight:650}button:disabled{opacity:.5;cursor:wait}:focus-visible{outline:3px solid var(--ink);outline-offset:3px}a{color:var(--ink)}details{margin-top:12px}summary{cursor:pointer}label{display:block;margin:12px 0}input{display:block;width:100%;padding:8px;background:var(--bg);color:var(--ink);border:1px solid var(--ink);border-radius:6px}.row{padding:12px 0;border-top:1px solid var(--line)}.pill{display:flex;align-items:center;gap:8px;height:40px;border-radius:20px;background:var(--bg)}.compact{font-size:12px;padding:4px 8px}@supports not (color:light-dark(white,black)){:host{--bg:#fbfaf6;--ink:#161512;--mute:#5b574f;--line:#e1dccf;--soft:#f1ede2;--accent:#2b3bff;--on-accent:#ffffff;}@media(prefers-color-scheme:dark){:host{--bg:#1c1b19;--ink:#f2efe8;--mute:#a8a296;--line:#33312c;--soft:#26241f;--accent:#8c97ff;--on-accent:#161512;}}}`;
 const money=(n,currency)=>new Intl.NumberFormat('en',{style:'currency',currency,maximumFractionDigits:currency==='KRW'?0:2}).format(n);
 const savings=(quote,local)=>local && local.currency===quote.currency && Number.isFinite(local.price)?local.price-quote.totalCost:null;
 const safeLink=v=>{try {const u=new URL(v);return u.protocol==='https:' && !u.username && !u.password?v:null;}catch{return null;}};
 function mount(doc,{onBuy=()=>{},onCheck=()=>{},onClose=()=>{},setTimeout:later=globalThis.setTimeout,clearTimeout:cancel=globalThis.clearTimeout}={}) {
  const root=doc.createElement('div');root.id='beforehand-root';doc.body.append(root);
  const shadow=root.attachShadow({mode:'closed'}),style=doc.createElement('style');style.textContent=CSS;
  const body=doc.createElement('section');body.setAttribute('aria-label','beforehand Korea price');shadow.append(style,body);
  let current={view:'loading'},collapsed=false,timer=null,destroyed=false;
  const el=(tag,text,className)=>{const n=doc.createElement(tag);if(text!=null)n.textContent=text;if(className)n.className=className;return n;};
  const button=(label,fn,className)=>{const b=el('button',label,className);b.type='button';b.addEventListener('click',fn);return b;};
  function mark() {
   const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 56 56');svg.setAttribute('aria-hidden','true');
   const path=doc.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M14 4H42Q52 4 52 14V34Q52 44 42 44H26L14 54V44Q4 44 4 34V14Q4 4 14 4Z');path.setAttribute('class','mark');
   const b=doc.createElementNS('http://www.w3.org/2000/svg','path');b.setAttribute('d','M19 13V34H29Q38 34 38 27Q38 20 29 20H19');b.setAttribute('fill','none');b.setAttribute('stroke','var(--on-accent)');b.setAttribute('stroke-width','5');svg.append(path,b);return svg;
  }
  function pill(label,fn) {body.className='';const b=button(label,fn,'pill');b.append(mark());body.append(b);}
  function details(q,parent) {
   const d=el('details'),summary=el('summary','Details');d.append(summary);
   for(const [label,key] of [['Item','itemKrw'],['Shipping','shippingKrw'],['Service fee','serviceFeeKrw'],['Payment fee','paymentFeeKrw']]) d.append(el('p',`${label}: ${money(q.payNow[key],'KRW')}`));
   d.append(el('p',`Pay now: ${money(q.payNow.total,q.currency)}`),el('p',`Duty estimate: ${money(q.dutyOnDelivery.estimate,q.currency)}`),el('p',q.dutyOnDelivery.note),el('p',`Seller: ${q.seller}`));
   for(const line of q.dutyOnDelivery.lines) d.append(el('p',`${line.label} · ${line.rate} · ${money(line.amount,q.currency)} · ${line.source}`));
   for(const warning of q.warnings) d.append(el('p',warning,'muted'));
   const url=safeLink(q.item.link);if(url){const a=el('a','Korean listing');a.href=url;a.target='_blank';a.rel='noopener noreferrer';d.append(a);}parent.append(d);
  }
  function buyButton(parent,choice) {parent.append(button('Buy from Korea',()=>setState({view:'buy_form',choice}),'buy'));}
  function render() {
   if(destroyed)return;body.replaceChildren();
   if(collapsed) {pill('beforehand',()=>{collapsed=false;render();});return;}
   if(current.view==='manual') {pill('Check Korea price',onCheck);return;}
   if(current.view==='none') {pill('No Korea match',()=>{collapsed=true;render();});timer=later(()=>{collapsed=true;render();},4000);return;}
   body.className='card';const header=el('div',null,'header'),brand=el('span','beforehand','brand');brand.append(mark());
   header.append(brand,button('Collapse',()=>{collapsed=true;render();onClose();},'compact'));body.append(header);
   if(current.view==='same') {
    const q=current.quote;const local=current.local?.currency===q.currency && Number.isFinite(current.local.price) && current.local.price>0?current.local:q.localPrice?{price:q.localPrice.price,currency:q.currency}:null;
    const saved=savings(q,local),cheaper=q.verdict==='buy_local' || (saved!==null && saved<=0);
    body.append(el('h2','Same item from Korea'),el('p',q.item.title),el('p',money(q.totalCost,q.currency),'total'));
    if(local) body.append(el('p',`Local price: ${money(local.price,q.currency)}`,'muted'));
    if(cheaper) body.append(el('p','Cheaper here'));
    else {if(saved>0)body.append(el('p',`You save ${money(saved,q.currency)}`));buyButton(body,'same');}
    if(q.dutyOnDelivery.estimate>0)body.append(el('p','+ est. duty on delivery','muted'));
    details(q,body);
   } else if(current.view==='alternatives') {
    body.append(el('h2','Korean alternatives'));
    current.items.slice(0,2).forEach((item,index)=>{const row=el('div',null,'row');row.append(el('h2',item.title),el('p',item.why),el('p',money(item.quote.totalCost,item.quote.currency),'total'));buyButton(row,index);details(item.quote,row);body.append(row);});
   } else if(current.view==='buy_form') {
    body.append(el('h2','Buy from Korea'));const form=el('form');const email=el('input'),name=el('input');
    email.type='email';email.required=true;email.maxLength=200;email.autocomplete='email';name.type='text';name.required=true;name.maxLength=120;name.autocomplete='name';
    for(const [text,input] of [['Email',email],['Name',name]]) {const label=el('label',text);label.append(input);form.append(label);}
    const submit=el('button','Continue to payment','buy');submit.type='submit';form.append(submit);
    form.addEventListener('submit',async e=>{e.preventDefault();if(submit.disabled)return;submit.disabled=true;const choice=current.choice,mail=email.value.trim(),buyer=name.value.trim();email.value='';name.value='';setState({view:'opening'});try{await onBuy(choice,mail,buyer);}catch{setState({view:'busy'});}});
    body.append(form,el('p','Sent to Korea Concierge to create your order. Not stored by beforehand.','muted'));email.focus();
   } else {
    const messages={loading:'Checking Korea…',cant_ship:`Can't ship to ${current.destination ?? 'this country'}`,busy:'Busy — try again',paused:'Auto-check paused for today',opening:'Opening payment…',changed:'The quote changed. Check Korea price again.',opened:'Payment opened in a new tab.'};
    body.append(el('p',messages[current.view] ?? messages.busy));if(['busy','changed'].includes(current.view))body.append(button('Check Korea price',onCheck));
   }
  }
  function setState(state) {if(timer)cancel(timer);current=state;collapsed=false;render();}
  function destroy() {destroyed=true;if(timer)cancel(timer);current={};root.remove();}
  setState(current);return {root,setState,destroy};
 }
 globalThis.BeforehandCard={mount,savings};
})();
