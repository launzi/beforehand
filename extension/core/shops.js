export const SHOPS = Object.freeze([
 ['amazon.com','US'],['walmart.com','US'],['ebay.com','US'],['target.com','US'],['bestbuy.com','US'],['sephora.com','US'],['ulta.com','US'],
 ['amazon.co.uk','GB'],['ebay.co.uk','GB'],['argos.co.uk','GB'],['boots.com','GB'],['lookfantastic.com','GB'],['next.co.uk','GB'],
 ['amazon.co.jp','JP'],['rakuten.co.jp','JP'],['shopping.yahoo.co.jp','JP'],['zozo.jp','JP'],['cosme.com','JP'],
 ['shopee.tw','TW'],['momoshop.com.tw','TW'],['pchome.com.tw','TW'],['hktvmall.com','HK'],['watsons.com.hk','HK'],['sasa.com.hk','HK'],['jd.com','CN'],
].map(([host,country])=>Object.freeze({host,country})));
export function shopFor(hostname) {
 if(typeof hostname!=='string') return null;
 const host=hostname.toLowerCase();
 return SHOPS.filter(s=>host===s.host || host.endsWith('.'+s.host)).sort((a,b)=>b.host.length-a.host.length)[0] ?? null;
}
export const matchPatterns=()=>SHOPS.map(s=>`https://*.${s.host}/*`);
export const defaultDestination=hostname=>shopFor(hostname)?.country ?? 'US';
