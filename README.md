# LuggageDealsDaily

Static luggage and travel-accessory deals site owned by Amin Peracha. Built the same way as [ScentDealsDaily](https://github.com/Aministan/scentdealsdaily): one catalog, a Python build, and GitHub Pages.

Live site: https://luggagedealsdaily.com/

## What is in the catalog

`data/catalog.json` is the only place outbound product URLs live. Each product is keyed by id. Prices and measurements were copied from the maker's public product page on 2026-11-15. A missing price stays missing. The page says "Check today's price" and does not invent a number.

Pending Commission Junction merchants:

| Merchant | CJ advertiser | Stated rate | `cj_click_url` |
| --- | --- | --- | --- |
| Travelpro US | 5227635 | 5% | empty until approved |
| LEVEL8 | 6087891 | 10% | empty until approved |
| Horizn Studios | 5354360 | 6% | empty until approved |
| Stuart & Lau | 7777913 | not recorded | empty until approved |

Away, Monos, Samsonite, Tumi, Briggs & Riley, Béis, and Calpak are comparison pages. They are not affiliate links. Samsonite Freeform and Tumi have no verified product URL in this build, so those pages have no outbound button.

When a program is approved, set that merchant's `cj_click_url` to the CJ `https://…/click-…` URL. The build appends `sid` in the form `{pagetype}-{slug}-{placement}` and does not request the click host. A CJ product feed can fill `products[].feed.price`, `feed.currency`, `feed.sku`, and a plain `feed.url` on the merchant's own host.

## Build

```bash
python3 scripts/test_links.py
python3 scripts/build.py
```

Defaults match the custom domain:

- `SITE_URL=https://luggagedealsdaily.com`
- `PATH_PREFIX` empty

The custom domain is configured in GitHub Pages settings. The build does not write a CNAME file.

Output is `site/` (pages, `sitemap.xml`, `robots.txt`, `llms.txt`, `feed.xml`).

## Deploy

`.github/workflows/pages.yml` runs on every push to `main`. It calls `actions/configure-pages` with `enablement: true`, builds `site/`, and deploys with GitHub Pages.
