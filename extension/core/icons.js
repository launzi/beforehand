// Small monochrome UI symbols; labels carry the meaning independently of color.
export function icon(name,doc=document) {
  const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('class','ui-icon');
  svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
  const path=doc.createElementNS('http://www.w3.org/2000/svg','path');
  path.setAttribute('d',{
    hold:'M8 5v14M16 5v14',
    allow:'m5 12 4 4L19 6',
    deny:'m6 6 12 12M18 6 6 18',
    device:'M4 4h16v12H4zM2 20h20M9 16v4M15 16v4',
    eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    play:'m7 4 13 8-13 8z',
    settings:'M9 3h6l1 4 4 1v8l-4 1-1 4H9l-1-4-4-1V8l4-1zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    expand:'M9 3H3v6M15 21h6v-6M3 3l7 7M21 21l-7-7',
    research:'M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0m-2 5 6 6',
    ai:'M12 3v3M7 3h10M4 7h16v13H4zM8 11v2M16 11v2M8 16h8',
    globe:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M3 12h18M12 3c-5 5-5 13 0 18 5-5 5-13 0-18',
    info:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M12 11v6M12 7v1',
  }[name]);
  svg.append(path);return svg;
}
