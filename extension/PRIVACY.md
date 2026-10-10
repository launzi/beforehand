# beforehand privacy policy

Publisher: **Munteok**. Sold by Munteok, operated by Youngji Kim (Seoul, Korea).
Contact: **privacy@munteok.com**.
Policy version 5 · Effective: 2026-10-12 · Changes since the 2026-10-05 text: publisher line, order record, operator alerts without personal information, and less detail about internal processing. What the extension reads or sends is unchanged.

## What it does

beforehand shows the Korea delivered price, or Korean alternatives, for the product on the supported shopping page you are viewing. Korea Concierge is operated by Munteok, the developer of this extension. Quotes are free; a service fee is included if you choose to buy. The seller is Munteok. Import duty and tax are estimated and paid on delivery.

## What is sent and when

Before any request, you choose whether to turn on auto-check or use manual checks. Only when auto-check is on, or you click **Check Korea price**, the product name, brand and delivery country go to Korea Concierge's partner API at **https://concierge.youngji.kim/api/commerce/v1**. The extension contacts no other server directly. A repeated check may use an on-device cached result. Automatic requests are limited to 200 per local day.

If you choose **Buy from Korea**, a new tab opens an extension page showing the selected quote and seller Munteok. Your email and name are entered on that extension page and sent to Korea Concierge to create an order when you click **Continue to payment**, together with the payment method you chose (card or PayPal). They are not stored by the extension or included in its log. Quote tokens are kept in Chrome's in-memory session storage, readable only by the extension itself, and are sent only to Korea Concierge to start checkout; they are never sent to the shop page or written to disk, and they disappear when the browser closes. If a quote has expired, buying re-checks the same product name, brand and delivery country with Korea Concierge. If the item now costs a different amount, the checkout page shows the old and new price and continues only after you confirm; if the item is gone, check again from the shop. To pay, the checkout tab opens **https://checkout.stripe.com** (card) or **https://www.paypal.com** (PayPal). beforehand never sees your card details. If the item is out of stock in Korea, Munteok refunds your full payment through the same provider. Buying is optional.

## What never leaves your device

Your browsing history, the shopping page address, the price on the page and other tabs are never sent. Your identity is not sent during a product check; email and name are sent only when you choose to buy. beforehand does not have permission to read browsing history. The card's local price comes from the shop page; savings are computed on your device using that price and the Korea total, only when their currencies match. Korea amounts come from Korea Concierge. Page price and currency are never sent for this comparison. No advertising or analytics SDK is included, and no remote code runs.

## Korea Concierge processing and retention

Payment is processed by **Stripe** when you pay by card, which receives your email and name with the order, or by **PayPal** when you choose PayPal. Korea Concierge keeps an order record with your email, name, the quote and the payment reference, plus the shipping address and phone number that Stripe or PayPal returns after you pay. After the item is bought in Korea, the record also holds the Korean purchase details and the shipping tracking number. Order alerts to the operator contain only operational details, such as the order number, amount and product link, and no personal information. The extension does not contact Stripe or PayPal directly.

Korea Concierge keeps a demand record containing a normalized product name, category, delivery country, result type, channel label and browser family. It does not keep your IP address with that record. To limit abuse, requests are counted per 10 minutes under a keyed hash of the IP address; these counters are deleted within 24 hours. Demand records support product demand analysis by the operator. This policy does not promise a deletion period for those records or for order records. Contact Munteok about data already received. Other processors apply their own retention policies.

## What is stored on your device

Chrome local and session extension storage are used, not Chrome sync. Content scripts cannot access either storage area:

- Consent version, auto-check settings, disabled shops and delivery country: until you delete them or uninstall.
- Product result cache: valid for 24 hours, at most 200 entries, without quote tokens or expiry fields. Expired entries are ignored and pruned when writing the cache.
- Displayed quotes in session storage: at most 200, with product name, brand, country and each choice's title, link, currency, total, pay-now total with its KRW cost lines and exchange rate, and estimated duty, plus their quote tokens. They last for the browser session or until removed; removing consent invalidates access.
- A daily automatic-check counter and date.
- Local log: up to 500 records, kept for 30 days and pruned when read or updated. Records contain product name and brand, shop host, delivery country, time, result type or checkout-opened status. They contain no page address, quote token, buyer email or buyer name.

Exported JSON logs remain wherever you save them until you delete the file.

## Your controls

The toolbar popup lets you turn auto-check off for the current shop or everywhere and choose a delivery country. When auto-check is off globally, you can still request a manual check. A disabled shop is not checked, including manually. Settings lets you change individual shops, export or delete the local log, or **Turn off and delete my data**. The last action removes consent, settings, cache, counters and log, and opens the welcome page again. Uninstalling removes extension storage. These actions cannot recall a request already sent or remove records a processor already holds.

Supported shop origins (HTTPS, including subdomains):

- United States: amazon.com, walmart.com, ebay.com, target.com, sephora.com, ulta.com.
- United Kingdom: amazon.co.uk, ebay.co.uk, argos.co.uk, boots.com, lookfantastic.com, next.co.uk.
- Japan: amazon.co.jp, rakuten.co.jp, shopping.yahoo.co.jp, zozo.jp, cosme.com.
- Taiwan: momoshop.com.tw, pchome.com.tw.
- Hong Kong: hktvmall.com, watsons.com.hk, sasa.com.hk.

## Limited Use

**The use of information received from Google APIs will adhere to the Chrome Web Store User Data Policy, including the Limited Use requirements.**

## Contact and changes

For questions or deletion requests, contact **privacy@munteok.com**. For order questions, contact **support@munteok.com**. If what the extension reads or sends changes, we update this policy and the disclosure version and ask for consent again. Updating from version 4 keeps your settings and local log and asks for version 5 consent; no check runs until you agree. Updating from older versions removes retired credentials and local logs first.
