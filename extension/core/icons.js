// Small monochrome UI symbols; labels carry the meaning independently of color.
export function icon(name,doc=document) {
  const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('class','ui-icon');
  svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
  const path=doc.createElementNS('http://www.w3.org/2000/svg','path');
  path.setAttribute('d',{hold:'M8 5v14M16 5v14'}[name]);
  svg.append(path);return svg;
}
