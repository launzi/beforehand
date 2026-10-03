// extension/core/quote-card.js
import {icon} from './icons.js';
import {DISCLOSURE,safeLink} from './korea-quote.js';
const money=(v,c)=>new Intl.NumberFormat('en-US',{style:'currency',currency:c}).format(v);
const krw=v=>'₩'+new Intl.NumberFormat('en-US').format(v);
export function renderQuoteCard(root,q,doc=document) {
  const el=(tag,cls,text)=>{const e=doc.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
  const card=el('div','quote-card');
  const head=el('div','quote-heading'),item=el('span');item.append(icon('globe',doc),el('span','',` Korea · ${q.item.title}`));head.append(item,el('span','status-pill','Quote only'));
  const rail=el('ol','cost-rail');
  for (const [op,label,value] of [['·','Item',krw(q.payNow.itemKrw)],['+','Shipping',krw(q.payNow.shippingKrw)],['+','Service fee',krw(q.payNow.serviceFeeKrw)],
    ['+','Payment fee',krw(q.payNow.paymentFeeKrw)],['+','Duty on delivery (est.)',money(q.dutyOnDelivery.estimate,q.currency)]]) {
    const li=el('li');li.dataset.op=op;li.append(el('span','',label),el('span','cost-value',value));rail.append(li);
  }
  const total=el('div','quote-total'),destination=el('span');destination.append(icon('globe',doc),el('span','',` ${q.destination} · Total`));total.append(destination,el('strong','total-amount',money(q.totalCost,q.currency)));
  card.append(head,rail,total);
  if (q.verdict==='buy_local') card.append(el('p','quote-verdict',"It's cheaper to buy locally"));
  if (q.localPrice) {
    const max=Math.max(q.totalCost,q.localPrice.price);
    const bars=el('div','price-comparison');
    for (const [cls,label,v] of [['kr','Korea',q.totalCost],['local','Local',q.localPrice.price]]) {
      const row=el('div','comparison-row'), track=el('div','comparison-track');
      const bar=el('div','comparison-fill '+cls);bar.style.setProperty('--fraction',`${max>0 ? Math.round(v/max*100) : 0}%`);
      track.append(bar);row.append(track,el('span','comparison-label',`${label} ${money(v,q.currency)}`));bars.append(row);
    }
    card.append(bars);
  }
  const details=el('details');details.append(el('summary','','Details'),el('p','',`Pay now ${money(q.payNow.total,q.currency)} (₩${q.payNow.totalKrw}) · FX ${q.payNow.fxRate} KRW/${q.currency}`));
  details.append(el('p','',`Service verdict: ${q.verdict}`));
  for (const line of q.dutyOnDelivery.lines) details.append(el('p','',`${line.label}: ${line.rate} · ${q.currency} ${line.amount} — ${line.source}`));
  details.append(el('p','',q.dutyOnDelivery.note));
  for (const w of q.warnings) details.append(el('p','',w));
  for (const [label,url] of [['Korean item',q.item.link],['Local price',q.localPrice?.url]]) {
    const href=safeLink(url); if (!href) continue;
    const a=el('a','',label);a.href=href;a.target='_blank';a.rel='noopener noreferrer';details.append(a);
  }
  const disclosure=el('p','disclosure');disclosure.append(icon('info',doc),el('span','',DISCLOSURE));
  card.append(details,disclosure);
  root.replaceChildren(card);
}
