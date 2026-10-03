// Deterministic port of browsing/signals.py. All *_us fields are decimal strings.
import {DAY, HALF_HOUR, dateFromUs, isoToUs, sha256, codepointCompare} from './util.js';
import {koreaProductTitle} from './korea-quote.js';
export const ONBOARDING = ['/signup', '/sign-up', '/register', '/login', '/auth', '/onboarding', '/welcome', '/users/register'];
export async function detectAll(data, {since_us, until_us, now_us, profile = null, include_restricted = false}) {
  const since = BigInt(since_us), until = BigInt(until_us), now = BigInt(now_us);
  const urls = new Map(data.urls.map(u => [u.url_key, u]));
  const domains = new Map(data.domains.map(d => [d.host, d]));
  const joined = data.visits.flatMap(v => {
    const u = urls.get(v.url_key);
    return u && u.host && (include_restricted || domains.get(u.host)?.sensitivity !== 'restricted')
      ? [{...v, host: u.host, path: u.path, product:koreaProductTitle(u.host,u.path,u.product ?? u.title), us: BigInt(v.visit_time_us)}] : [];
  });
  const scoped = joined.filter(v => profile === null || v.profile === profile);
  const window = scoped.filter(v => v.us >= since && v.us < until);
  const group = (rows, key) => {
    const result = new Map();
    for (const r of rows) { const k = key(r); if (!result.has(k)) result.set(k, []); result.get(k).push(r); }
    return result;
  };
  const signals = [];
  const add = async (kind, id, host, term, rows, evidence) => {
    const times = rows.map(v => v.us).sort((a,b) => a < b ? -1 : a > b ? 1 : 0);
    signals.push({kind, key: await sha256(`${kind}|${id}`), host, term, evidence,
      first_us: times[0].toString(), last_us: times.at(-1).toString()});
  };
  for (const [host, rows] of group(window, v => v.host)) {
    const paths = [...new Set(rows.map(v => v.path).filter(p => p && ONBOARDING.some(x => p.toLowerCase().includes(x))))].sort(codepointCompare);
    const times = rows.map(v => v.us).sort((a,b) => a < b ? -1 : a > b ? 1 : 0);
    if (paths.length) await add('new_entry', host, host, null, rows, {
      onboarding_paths: paths, first_visit_us: times[0].toString(), visit_count: rows.length});
    const days = [...new Set(rows.map(v => dateFromUs(v.us, true)))].sort();
    if (days.length >= 3) await add('recurring', host, host, null, rows, {
      distinct_days: days.length, total_visits: rows.length, first_day: days[0], last_day: days.at(-1)});
  }
  const searches = data.searches.map(s => ({...s, us: isoToUs(s.first_seen_utc)}))
    .filter(s => s.us !== null && s.us >= since && s.us < until && (profile === null || s.profile === profile));
  for (const [norm, rows] of group(searches, s => s.normalized_term)) {
    const counts = rows.map(s => joined.filter(v => v.profile === s.profile && v.us >= since && v.us < until + HALF_HOUR
      && v.us > s.us && v.us <= s.us + HALF_HOUR && v.host !== urls.get(s.url_key)?.host).length);
    const days = new Set(rows.map(s => dateFromUs(s.us, true)));
    const low = counts.some(n => n < 3), repeat = days.size >= 2;
    if (low || repeat) await add('unresolved', norm, null, norm, rows, {
      term: rows[0].term, search_count: rows.length, follow_through_counts: counts,
      distinct_days: days.size, low_follow_through: low, repeat_across_days: repeat});
  }
  for (const [host, rows] of group(scoped.filter(v => v.us < now), v => v.host)) {
    const days = new Set(rows.map(v => dateFromUs(v.us, true)));
    const last = rows.reduce((n,v) => v.us > n ? v.us : n, rows[0].us);
    if (days.size >= 3 && last < now - 7n * DAY) await add('dropped', host, host, null, rows, {
      active_days: days.size, last_visit_us: last.toString(), days_quiet: Number((now-last)/DAY)});
  }
  for (const [key,rows] of group(window.filter(v=>v.product),v=>v.url_key)) {
    const first=rows.reduce((n,v)=>v.us<n?v.us:n,rows[0].us), host=rows[0].host;
    const transaction=window.some(v=>v.host===host && v.us>=first && /\/(?:checkout|orders?|payment|purchase)(?:\/|$|[.?])/i.test(v.path || ''));
    if(rows.length>=2 && !transaction) await add('korea_product',key,host,rows[0].product,rows,
      {product:rows[0].product,visit_count:rows.length,purchase_page_observed:false});
  }
  return signals.sort((a,b) => codepointCompare(a.kind,b.kind) || codepointCompare(a.key,b.key));
}
