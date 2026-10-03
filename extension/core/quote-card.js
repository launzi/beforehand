import {DISCLOSURE,safeLink} from './korea-quote.js';
// No innerHTML: service titles, verdicts, warnings and source strings are untrusted.
export function renderQuoteCard(container,quote,doc=document) {
  container.replaceChildren();
  const element=(tag,text)=>{const node=doc.createElement(tag);node.textContent=text;return node;};
  const card=element('article','');card.className='card quote-card';
  card.append(element('h3',quote.item.title));
  const badge=element('strong',quote.verdict);badge.className='badge';card.append(badge);
  if(quote.verdict==='buy_local') card.append(element('p',"It's cheaper to buy locally"));
  else card.append(element('p','Service verdict shown verbatim; no recommendation inferred.'));
  const money=n=>`${quote.currency} ${n}`;
  const table=element('table','');
  for (const [label,value] of [
    ['Destination',quote.destination],['Item',`KRW ${quote.payNow.itemKrw}`],['Shipping',`KRW ${quote.payNow.shippingKrw}`],
    ['Service fee',`KRW ${quote.payNow.serviceFeeKrw}`],['Payment fee',`KRW ${quote.payNow.paymentFeeKrw}`],
    ['Pay now (quote only)',`${money(quote.payNow.total)} / KRW ${quote.payNow.totalKrw}`],['FX rate',`${quote.payNow.fxRate} KRW / ${quote.currency}`],
    ['Estimated duty on delivery',money(quote.dutyOnDelivery.estimate)],['Estimated total cost',money(quote.totalCost)],
    ['Local price',quote.localPrice ? money(quote.localPrice.price) : 'Not available']]) {
    const row=element('tr','');row.append(element('th',label),element('td',value));table.append(row);
  }
  card.append(table,element('h4','Duty on delivery'));
  for(const line of quote.dutyOnDelivery.lines) card.append(element('p',`${line.label}: ${line.rate} · ${money(line.amount)} — Source: ${line.source}`));
  card.append(element('p',quote.dutyOnDelivery.note));
  const warnings=element('details','');warnings.append(element('summary',`Warnings (${quote.warnings.length})`));
  for(const warning of quote.warnings) warnings.append(element('p',warning));
  card.append(warnings,element('p',DISCLOSURE),element('p','Quotes only. No orders or payments are created.'));
  for(const [label,url] of [['Korean item reference',quote.item.link],['Local price reference',quote.localPrice?.url]]) {
    if(!safeLink(url)) continue;
    const link=element('a',label);link.href=url;link.target='_blank';link.rel='noopener noreferrer';card.append(link,element('br',''));
  }
  container.append(card);
}
