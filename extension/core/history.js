import {sha256, usFromMs} from './util.js';
import {scrubURL} from './scrub.js';
const CAP = 1000;
export function classifyHost(rules, host) {
  if (!host) return ['unknown','none'];
  const labels = host.trim().toLowerCase().split(':')[0].split('.');
  for (let i = 0; i < labels.length; i++) {
    const match = rules[labels.slice(i).join('.')];
    if (match) return match;
  }
  return ['unknown','none'];
}
export function searchTerm(url) {
  const host = url.hostname.toLowerCase(), path = url.pathname;
  if ((['google.com','www.google.com','google.co.kr','www.google.co.kr'].includes(host) && path === '/search')
    || (['bing.com','www.bing.com'].includes(host) && path === '/search')
    || ['duckduckgo.com','www.duckduckgo.com'].includes(host)) return url.searchParams.get('q');
  if (['search.naver.com','m.search.naver.com'].includes(host)) return url.searchParams.get('query');
  if (['youtube.com','www.youtube.com'].includes(host) && path === '/results') return url.searchParams.get('search_query');
  return null;
}
export async function readHistory(history, {now = Date.now(), lookbackDays = 90, excludedHosts = [], onProgress = () => {}} = {}) {
  const start = now - lookbackDays * 86400000;
  const byURL = new Map();
  let calls = 0;
  async function collect(lo, hi) {
    if (++calls > 4096) throw new Error('History is too large to scan completely. No partial signals were used.');
    const page = await history.search({text:'', startTime:lo, endTime:hi, maxResults:CAP});
    if (page.length >= CAP) {
      if (hi-lo <= 1) throw new Error('History result limit reached at one timestamp. No partial signals were used.');
      const mid = Math.floor((lo+hi)/2);
      await collect(lo,mid); await collect(mid,hi); // Boundary duplicates are deduplicated by URL.
    } else for (const item of page) if (item.url) byURL.set(item.url,item);
    if (byURL.size > 20000) throw new Error('More than 20,000 URLs in this window. No partial signals were used.');
  }
  await collect(start, now);
  const data = {urls:[],visits:[],searches:[],domains:[]};
  const domains = new Map(), knownVisits = new Set(), urls = new Map(), searches = new Map();
  let skipped = 0, processed = 0;
  // Sequential reads keep memory and Chrome API pressure bounded.
  for (const raw of byURL.keys()) {
    let url;
    try { url = new URL(raw); }
    catch { skipped++; continue; }
    if (!['http:','https:'].includes(url.protocol)) { skipped++; continue; }
    const [scrubbed,status] = scrubURL(raw);
    if (status !== 'ok') { skipped++; continue; }
    const host = url.hostname.toLowerCase();
    const restricted = excludedHosts.some(h => host === h || host.endsWith('.'+h));
    domains.set(host,{host,sensitivity:restricted ? 'restricted' : 'none'});
    const visits = (await history.getVisits({url:raw})).filter(v => Number.isFinite(v.visitTime) && v.visitTime >= start && v.visitTime < now);
    if (!visits.length) continue;
    const url_key = await sha256(scrubbed);
    urls.set(url_key,{url_key,host,path:url.pathname || '/'}); // No full URL or page title retained.
    for (const v of visits) {
      // Python ingestion deduplicates by profile + scrubbed URL key + time.
      const visit_time_us=usFromMs(v.visitTime), id = `${url_key}|${visit_time_us}`;
      if (knownVisits.has(id)) continue;
      knownVisits.add(id);
      data.visits.push({profile:'current', url_key, visit_time_us});
    }
    const term = searchTerm(url);
    // Python keyword_search_terms supplies one record per URL/term, earliest visit.
    if (term && !restricted) {
      const first = visits.reduce((min,v)=>Math.min(min,v.visitTime),Infinity);
      const first_seen_utc=new Date(first).toISOString().replace(/\.\d{3}Z$/, 'Z');
      const key=`${url_key}|${term}`, old=searches.get(key);
      if (!old || first_seen_utc < old.first_seen_utc) searches.set(key,{profile:'current',url_key,term,
        normalized_term:term.trim().toLowerCase(),first_seen_utc});
    }
    onProgress(++processed, byURL.size);
  }
  data.domains = [...domains.values()];
  data.urls = [...urls.values()]; data.searches = [...searches.values()];
  return {data, coverage:{lookbackDays, urls:processed, visits:data.visits.length, skipped, complete:true},
    options:{since_us:usFromMs(now-30*86400000),until_us:usFromMs(now),now_us:usFromMs(now)}};
}
