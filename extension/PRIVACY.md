# beforehand privacy policy

Publisher: **Munteok**, an individual developer in the Republic of Korea.
Contact: **privacy@munteok.com**.
Policy version 4 · Effective: 2026-10-03.

## What it does

beforehand shows the Korea delivered price, or Korean alternatives, for the product on the supported shopping page you are viewing. Korea Concierge is operated by Munteok, the developer of this extension. Quotes are free; a service fee is included if you choose to buy. The seller is Munteok. Import duty and tax are estimated and paid on delivery.

## What is sent and when

Before any request, you choose whether to turn on auto-check or use manual checks. Only when auto-check is on, or you click **Check Korea price**, the product name, brand and delivery country go to **https://concierge.youngji.kim/api/mcp**. The extension contacts no other server directly. A repeated check may use an on-device cached result. Automatic requests are limited to 200 per local day.

If you choose **Buy from Korea**, the extension asks for your email and name and sends them with a quote token to Korea Concierge to create an order. It may first refresh an expired quote using the same product name, brand and delivery country. It then opens **https://checkout.stripe.com** in a new tab. beforehand does not store your email or name and never sees your card details. Buying is optional.

## What never leaves your device

Your browsing history, the shopping page address, the price on the page and other tabs are never sent. Your identity is not sent during a product check; email and name are sent only when you choose to buy. beforehand does not have permission to read browsing history. The page price and currency are used only for an on-device comparison. No advertising or analytics SDK is included, and no remote code runs.

## Korea Concierge processing and retention

Korea Concierge uses **NVIDIA Nemotron on Nebius** to interpret product names, **Serper (Google Shopping)** to find Korean listings, and the **Jikgugak quote engine** to estimate shipping, fees and duty. **Stripe** processes payment when you choose to buy. The extension does not contact Nebius or Serper directly and does not require an AI account or key.

Korea Concierge keeps a demand record containing a normalized product name, category, delivery country, result type, channel label and browser family. It does not keep your IP address with that record. To limit abuse, requests are counted per 10 minutes under a keyed hash of the IP address; these counters are deleted within 24 hours. Demand records support product demand analysis by the operator. This policy does not promise a deletion period for those records or for order records. Contact Munteok about data already received. Other processors apply their own retention policies.

## What is stored on your device

Only Chrome local extension storage is used, not Chrome sync:

- Consent version, auto-check settings, disabled shops and delivery country: until you delete them or uninstall.
- Product result cache: valid for 24 hours, at most 200 entries, without quote tokens or expiry fields. Expired entries are ignored and pruned when writing the cache.
- A daily automatic-check counter and date.
- Local log: up to 500 records, kept for 30 days and pruned when read or updated. Records contain product name and brand, shop host, delivery country, time, result type or checkout-opened status. They contain no page address, quote token, buyer email or buyer name.

Quote tokens are held only in service-worker memory for buying. The quote may be refreshed if that memory is lost or the token expires. Exported JSON logs remain wherever you save them until you delete the file.

## Your controls

The toolbar popup lets you turn auto-check off for the current shop or everywhere and choose a delivery country. When auto-check is off globally, you can still request a manual check. A disabled shop is not checked, including manually. Settings lets you change individual shops, export or delete the local log, or **Turn off and delete everything**. The last action removes consent, settings, cache, counters and log, and opens the welcome page again. A response from an earlier consent session is discarded. Uninstalling removes extension storage. These actions cannot recall a request already sent or remove records a processor already holds.

Supported shop origins (HTTPS, including subdomains):

- United States: amazon.com, walmart.com, ebay.com, target.com, bestbuy.com, sephora.com, ulta.com.
- United Kingdom: amazon.co.uk, ebay.co.uk, argos.co.uk, boots.com, lookfantastic.com, next.co.uk.
- Japan: amazon.co.jp, rakuten.co.jp, shopping.yahoo.co.jp, zozo.jp, cosme.com.
- Taiwan: shopee.tw, momoshop.com.tw, pchome.com.tw.
- Hong Kong: hktvmall.com, watsons.com.hk, sasa.com.hk.
- China: jd.com.

## Limited Use

**The use of information received from Google APIs will adhere to the Chrome Web Store User Data Policy, including the Limited Use requirements.**

## Contact and changes

For questions or deletion requests, contact **privacy@munteok.com**. If what the extension reads or sends changes, we update this policy and the disclosure version and ask for consent again. Updating from the previous product removes retired credentials and local logs before asking for version 4 consent.
