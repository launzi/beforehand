(()=>{
 const CSS=`:host{all:initial;color-scheme:light dark;--bg:light-dark(#fbfaf6,#1c1b19);--ink:light-dark(#161512,#f2efe8);--mute:light-dark(#5b574f,#a8a296);--line:light-dark(#e1dccf,#33312c);--soft:light-dark(#f1ede2,#26241f);--accent:light-dark(#2b3bff,#8c97ff);--on-accent:light-dark(#ffffff,#161512);position:fixed;bottom:16px;right:16px;z-index:2147483000;font:14px/1.5 system-ui,sans-serif;color:var(--ink)}
 *{box-sizing:border-box}.card{width:340px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);overflow:auto;background:var(--bg);border:1px solid var(--ink);border-radius:14px;padding:16px 18px 18px;box-shadow:0 10px 30px #0000002a;font-variant-numeric:tabular-nums}.card.state{width:300px;padding:14px 16px}
 .header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.brand{display:flex;align-items:center;gap:7px;font-weight:700}svg{width:20px;height:20px}.mark{fill:var(--accent)}
 .eyebrow{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);margin:0}.title{font-weight:600;line-height:1.35;margin:4px 0 10px;overflow-wrap:anywhere}
 p{margin:6px 0;overflow-wrap:anywhere}.total{font-size:32px;font-weight:700;letter-spacing:-1px;line-height:1.1;margin:0}.muted{color:var(--mute)}.sm{font-size:12.5px}.xs{font-size:11.5px}
 .line{display:flex;justify-content:space-between;gap:12px;padding:2px 0;font-size:12.5px}.compare{border-top:1px solid var(--line);margin-top:10px;padding-top:8px}
 button,input{font:inherit}button{cursor:pointer;background:transparent;color:var(--ink);border:1px solid var(--ink);border-radius:8px;padding:7px 12px;font-size:13px}
 button.buy{display:block;width:100%;margin-top:14px;padding:12px;border:0;border-radius:10px;background:var(--accent);color:var(--on-accent);font-weight:650;font-size:14px}button.buy.small{display:inline-block;width:auto;margin:0;padding:8px 12px;font-size:13px}
 button.link{border:0;padding:0;background:none;text-decoration:underline;text-underline-offset:3px;font-size:12.5px}button.x{border:0;padding:2px 6px;color:var(--mute);font-size:13px}
 button:disabled{opacity:.5;cursor:wait}:focus-visible{outline:3px solid var(--ink);outline-offset:3px}a{color:var(--ink)}
 details{margin-top:10px}summary{cursor:pointer;text-align:center;font-size:12.5px;text-decoration:underline;text-underline-offset:3px;list-style:none}summary::-webkit-details-marker{display:none}
 .timeline{position:relative;margin:10px 0 0;padding-left:18px}.timeline:before{content:"";position:absolute;left:4px;top:8px;bottom:8px;border-left:1.5px solid var(--line)}
 .timeline .line{position:relative}.timeline .line:before{content:"";position:absolute;left:-18px;top:8px;width:9px;height:9px;border-radius:50%;background:var(--bg);border:1.5px solid var(--mute)}
 .timeline .strong{font-weight:700}.timeline .strong:before{background:var(--ink);border-color:var(--ink)}.timeline .later{color:var(--mute)}.timeline .later:before{border-style:dashed}
 .alt{display:grid;grid-template-columns:1fr auto;gap:2px 14px;padding:12px 0;border-top:1px solid var(--line)}.alt:first-of-type{margin-top:6px}.alt .name{font-weight:600;line-height:1.35;margin:0;overflow-wrap:anywhere}.alt .price{text-align:right;font-weight:700;font-size:18px;margin:0}
 .alt .act{grid-column:1/3;display:flex;justify-content:flex-end;align-items:center;margin-top:8px}.alt details{grid-column:1/3;margin-top:0}.alt summary{text-align:left;width:max-content;margin-top:-27px}
 .skeleton{height:10px;border-radius:5px;background:var(--soft);margin:8px 0}.pill{display:flex;align-items:center;gap:8px;height:40px;border-radius:20px;background:var(--bg);border:1px solid var(--ink);padding:0 14px;font-weight:600}
 @supports not (color:light-dark(white,black)){:host{--bg:#fbfaf6;--ink:#161512;--mute:#5b574f;--line:#e1dccf;--soft:#f1ede2;--accent:#2b3bff;--on-accent:#ffffff;}@media(prefers-color-scheme:dark){:host{--bg:#1c1b19;--ink:#f2efe8;--mute:#a8a296;--line:#33312c;--soft:#26241f;--accent:#8c97ff;--on-accent:#161512;}}}`;
 const COUNTRY={US:'United States',GB:'United Kingdom',JP:'Japan',CN:'China',TW:'Taiwan',HK:'Hong Kong'};
 const money=(n,currency)=>new Intl.NumberFormat('en',{style:'currency',currency,maximumFractionDigits:currency==='KRW'?0:2}).format(n);
 const savings=(quote,local)=>local && local.currency===quote.currency && Number.isFinite(local.price)?local.price-quote.totalCost:null;
 const safeLink=v=>{try {const u=new URL(v);return u.protocol==='https:' && !u.username && !u.password?v:null;}catch{return null;}};
 function mount(doc,{onBuy=()=>{},onCheck=()=>{},onClose=()=>{},onSettings=()=>{},setTimeout:later=globalThis.setTimeout,clearTimeout:cancel=globalThis.clearTimeout}={}) {
  const root=doc.createElement('div');root.id='beforehand-root';doc.body.append(root);
  const shadow=root.attachShadow({mode:'closed'}),style=doc.createElement('style');style.textContent=CSS;
  const body=doc.createElement('section');body.setAttribute('aria-label','beforehand Korea price');shadow.append(style,body);
  let current={view:'loading'},collapsed=false,timer=null,destroyed=false;
  const el=(tag,text,className)=>{const n=doc.createElement(tag);if(text!=null)n.textContent=text;if(className)n.className=className;return n;};
  const button=(label,fn,className)=>{const b=el('button',label,className);b.type='button';b.addEventListener('click',fn);return b;};
  const line=(label,value,className)=>{const r=el('div',null,'line'+(className?' '+className:''));r.append(el('span',label),el('span',value));return r;};
  function mark() {
   const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 56 56');svg.setAttribute('aria-hidden','true');
   const path=doc.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M14 4H42Q52 4 52 14V34Q52 44 42 44H26L14 54V44Q4 44 4 34V14Q4 4 14 4Z');path.setAttribute('class','mark');
   const b=doc.createElementNS('http://www.w3.org/2000/svg','path');b.setAttribute('d','M19 13V34H29Q38 34 38 27Q38 20 29 20H19');b.setAttribute('fill','none');b.setAttribute('stroke','var(--on-accent)');b.setAttribute('stroke-width','5');svg.append(path,b);return svg;
  }
  function pill(label,fn) {body.className='';const b=button(label,fn,'pill');b.prepend?.(mark());if(!b.prepend)b.append(mark());body.append(b);}
  function details(q,parent) {
   const d=el('details'),summary=el('summary','Details');d.append(summary);
   const tl=el('div',null,'timeline');
   for(const [label,key] of [['Item','itemKrw'],['International shipping','shippingKrw'],['Service fee','serviceFeeKrw'],['Payment fee','paymentFeeKrw']]) tl.append(line(label,money(q.payNow[key],'KRW')));
   tl.append(line('Pay now',money(q.payNow.total,q.currency),'strong'));
   if(q.dutyOnDelivery.estimate>0) tl.append(line('Estimated duty · pay on delivery',money(q.dutyOnDelivery.estimate,q.currency),'later'));
   d.append(tl);
   for(const l of q.dutyOnDelivery.lines) d.append(el('p',`${l.label} · ${l.rate} · ${money(l.amount,q.currency)} · ${l.source}`,'muted xs'));
   d.append(el('p','Duty is an estimate, not part of Pay now. You pay it to the carrier or customs on delivery.','muted xs'));
   if(q.dutyOnDelivery.note) d.append(el('p',q.dutyOnDelivery.note,'muted xs'));
   for(const warning of q.warnings) d.append(el('p',warning,'muted xs'));
   const seller=el('p',`Sold by ${q.seller}`,'muted xs'),url=safeLink(q.item.link);
   if(url){const a=el('a','View Korean listing ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';seller.append(' · ',a);}
   d.append(seller);parent.append(d);
  }
  function buyButton(parent,choice,className='buy') {parent.append(button('Buy from Korea',async()=>{setState({view:'opening'});try{await onBuy(choice);}catch{setState({view:'busy'});}},className));}
  function header() {
   const h=el('div',null,'header'),brand=el('span','beforehand','brand');brand.prepend?.(mark());if(!brand.prepend)brand.append(mark());
   h.append(brand,button('Collapse',()=>{collapsed=true;render();onClose();},'x'));body.append(h);
  }
  function state(eyebrow,text,action) {
   body.className='card state';body.append(el('p',eyebrow,'eyebrow'));if(text)body.append(el('p',text,'sm'));if(action)body.append(action);
  }
  function render() {
   if(destroyed)return;body.replaceChildren();if(timer){cancel(timer);timer=null;}
   if(collapsed) {pill('beforehand',()=>{collapsed=false;render();});return;}
   if(current.view==='manual') {pill('Check Korea price',onCheck);return;}
   if(current.view==='same') {
    body.className='card';header();
    const q=current.quote;const local=current.local?.currency===q.currency && Number.isFinite(current.local.price) && current.local.price>0?current.local:null;
    const saved=savings(q,local),cheaper=q.verdict==='buy_local' || (saved!==null && saved<=0);
    body.append(el('p','Same item from Korea','eyebrow'),el('p',q.item.title,'title'),el('p',money(q.totalCost,q.currency),'total'));
    const split=q.dutyOnDelivery.estimate>0?`Estimated total · ${money(q.payNow.total,q.currency)} now + ${money(q.dutyOnDelivery.estimate,q.currency)} duty on delivery`:'Estimated total';
    body.append(el('p',split,'muted sm'));
    if(local) {const c=el('div',null,'compare');c.append(line('This shop',money(local.price,q.currency)));if(saved>0)c.append(line('Estimated savings',money(saved,q.currency)));body.append(c);}
    if(cheaper) body.append(el('p','Cheaper at this shop','sm'));else buyButton(body,'same');
    details(q,body);
   } else if(current.view==='alternatives') {
    body.className='card';header();body.append(el('p','Alternatives from Korea','eyebrow'));
    current.items.slice(0,2).forEach((item,index)=>{
     const q=item.quote,row=el('div',null,'alt');
     row.append(el('p',item.title,'name'),el('p',money(q.totalCost,q.currency),'price'));
     row.append(typeof item.why==='string' && item.why && !/[\p{N}$£€¥￥₩%]/u.test(item.why)?el('p',item.why,'muted sm'):el('span'),el('p','est. total','muted xs'));
     const act=el('div',null,'act');row.append(act);buyButton(act,index,'buy small');details(q,row);
     body.append(row);
    });
   } else if(current.view==='loading') {
    body.className='card state';const b=el('span','Checking Korea…','brand');b.prepend?.(mark());if(!b.prepend)b.append(mark());body.append(b);
    for(const w of [70,40,85]){const s=el('div',null,'skeleton');s.setAttribute('style',`width:${w}%`);body.append(s);}
   } else if(current.view==='none') {
    state('No match in Korea',null,button('Hide for this item',()=>{collapsed=true;render();},'link'));timer=later(()=>{collapsed=true;render();},4000);
   } else if(current.view==='cant_ship') {
    state(`Can't ship to ${COUNTRY[current.destination] ?? current.destination ?? 'this country'}`,typeof current.message==='string'?current.message:null,button('Change delivery country',onSettings,'link'));
   } else if(current.view==='paused') {
    state('Auto-check paused for today',"You've hit today's 200 automatic checks.",button('Check this item',onCheck));
   } else if(current.view==='changed') {
    state('Price changed','Check again to see the current price.',button('Check again',onCheck));
   } else if(current.view==='opening') {
    state('Opening checkout…');
   } else if(current.view==='opened') {
    state('Checkout opened in a new tab.');
   } else {
    state("Couldn't get a quote",null,button('Try again',onCheck));
   }
  }
  function setState(next) {current=next;collapsed=false;render();}
  function destroy() {destroyed=true;if(timer)cancel(timer);current={};root.remove();}
  setState(current);return {root,setState,destroy};
 }
 globalThis.BeforehandCard={mount,savings};
})();
