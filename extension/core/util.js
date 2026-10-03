// Apache-2.0 — Munteok. Chrome timestamps exceed Number.MAX_SAFE_INTEGER.
export const EPOCH = 11644473600000000n;
export const DAY = 86400000000n;
export const HALF_HOUR = 1800000000n;
export const usFromMs = ms => (BigInt(Math.round(ms * 1000)) + EPOCH).toString();
export const floorDiv = (a, b) => a / b - (a < 0n && a % b !== 0n ? 1n : 0n);
export const dateFromUs = (us, kst = false) => new Date(Number(floorDiv(BigInt(us) - EPOCH + (kst ? 9n * 3600000000n : 0n), 1000n))).toISOString().slice(0, 10);
export function isoToUs(value) {
  // Python fromisoformat accepts naive times as UTC and preserves microseconds.
  let s = value;
  if (!/(Z|[+-]\d\d:\d\d)$/i.test(s)) s += 'Z';
  const ms = Date.parse(s);
  if (!Number.isFinite(ms)) return null;
  const fraction = /\.(\d+)/.exec(s)?.[1] ?? '';
  const extra = BigInt((fraction.padEnd(6, '0').slice(3, 6)) || '0');
  return BigInt(usFromMs(ms)) + extra;
}
export async function sha256(value) {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(bytes)].map(x => x.toString(16).padStart(2, '0')).join('');
}
export const codepointCompare = (a, b) => {
  const aa = Array.from(a, c => c.codePointAt(0)), bb = Array.from(b, c => c.codePointAt(0));
  for (let i = 0; i < Math.min(aa.length, bb.length); i++) if (aa[i] !== bb[i]) return aa[i] - bb[i];
  return aa.length - bb.length;
};
// json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=True).
export function pythonJSON(value) {
  const sorted = x => Array.isArray(x) ? x.map(sorted) : x && typeof x === 'object'
    ? Object.fromEntries(Object.keys(x).sort(codepointCompare).map(k => [k, sorted(x[k])])) : x;
  return JSON.stringify(sorted(value)).replace(/[\u007f-\uffff]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
}
