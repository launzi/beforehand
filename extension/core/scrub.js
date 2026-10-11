// URL compatibility scrubber: same query ordering/whitelist as browsing/scrub.py.
const WHITE = new Set(['q','query','search_query','keyword','s','wd','page','tab']);
const BLACK = ['code','state','token','access_token','id_token','refresh_token','auth','session','secret','password','passwd','pwd','key','apikey','api_key','sig','signature','credential','assertion','nonce','_hsenc','_hsmi'];
const quote = s => encodeURIComponent(s).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
const pyString = x => x === null ? 'None' : x === true ? 'True' : x === false ? 'False' : String(x);
export function scrubURL(input) {
  const original = pyString(input);
  const value = original.replace(/^[\x00-\x20]+/, '').replace(/[\t\r\n]/g, '');
  const netloc = /^(?:[a-z][a-z0-9+.-]*:)?\/\/([^/?#]*)/i.exec(value)?.[1];
  let invalid = false;
  if (netloc) {
    const simplified=netloc.replace(/[@:#?]/g,'');
    const normalized=simplified.normalize('NFKC');
    if (normalized !== simplified && /[/?#@:]/.test(normalized)) invalid=true;
  }
  if (netloc?.includes('[') || netloc?.includes(']')) {
    try {
      // Python validates bracketed IPs but not numeric ports in urlparse.
      const bracket = /\[([^\]]+)\]/.exec(netloc);
      if (!bracket) invalid = true;
      else if (!/^v[0-9a-f]+\..+$/i.test(bracket[1])) new URL(`http://[${bracket[1]}]/`);
    } catch { invalid = true; } // Explicit parse failure, never a successful scrub.
  }
  if (invalid) {
    const q = original.indexOf('?'), hash = original.indexOf('#',q);
    return [q < 0 ? original : original.slice(0,q) + (hash < 0 ? '' : original.slice(hash)), 'failed'];
  }
  const hash = value.indexOf('#'), beforeHash = hash < 0 ? value : value.slice(0,hash);
  const q = beforeHash.indexOf('?');
  if (q < 0 || q === beforeHash.length - 1) return [original,'ok'];
  const params = [...new URLSearchParams(beforeHash.slice(q+1))].map(([name,raw]) => {
    let val = raw;
    if (!WHITE.has(name) && !name.startsWith('utm_') && (BLACK.some(x => name.toLowerCase().includes(x)) || (Array.from(raw).length >= 40 && /^[A-Za-z0-9+/=_-]+$/.test(raw))))
      val = `<redacted:${Array.from(raw).length}>`;
    return quote(name) + '=' + (val.startsWith('<redacted:') && val.endsWith('>') ? val : quote(val));
  }).join('&');
  const prefix = beforeHash.slice(0,q).replace(/^([a-z][a-z0-9+.-]*):/i, (_,s) => s.toLowerCase() + ':');
  return [prefix + (params ? '?' + params : '') + (hash < 0 || hash === value.length-1 ? '' : value.slice(hash)), 'ok'];
}
// Extra outbound minimization. Kept separate so URL parity never implies PII safety.
export function scrubText(value, max = 240) {
  return String(value ?? '').normalize('NFKC')
    .replace(/https?:\/\/[^\s<>]+/gi, '[URL removed]')
    .replace(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/gi, '[email removed]')
    .replace(/\b(?:bearer\s+)?(?:sk-|tvly-|eyJ)[A-Za-z0-9._-]{8,}/gi, '[credential removed]')
    .replace(/\b(?:password|passwd|pwd|token|api[_ -]?key|secret|authorization)\s*[:=]\s*\S+/gi, '[credential removed]')
    .replace(/[A-Za-z0-9+/_=-]{40,}/g, '[long identifier removed]')
    .replace(/\+?\d[\d ().-]{7,}\d/g, '[number removed]')
    .replace(/[\x00-\x1f\x7f]/g, ' ').slice(0,max);
}
