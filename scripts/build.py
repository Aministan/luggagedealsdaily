#!/usr/bin/env python3
"""Render data/catalog.json into site/.

SITE_URL and PATH_PREFIX set the public origin. The live site is
https://luggagedealsdaily.com/ (SITE_URL=https://luggagedealsdaily.com,
PATH_PREFIX empty). No CNAME file is written; the custom domain stays in
GitHub Pages settings.
"""
import datetime
import html
import json
import os
import re
import shutil
import urllib.parse

import links

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site")
CATALOG = json.load(open(os.path.join(ROOT, "data", "catalog.json"), encoding="utf-8"))
NAME = CATALOG["site_name"]
OWNER = CATALOG["owner"]
CHECKED = CATALOG["updated"]
MERCHANTS = CATALOG["merchants"]
PRODUCTS = CATALOG["products"]
BY_ID = {p["id"]: p for p in PRODUCTS}
OUTBOUND = CATALOG["outbound"]

BASE = os.environ.get("SITE_URL", "https://luggagedealsdaily.com").strip()
_parts = urllib.parse.urlsplit(BASE)
BASE = urllib.parse.urlunsplit((_parts.scheme, _parts.netloc.lower(), _parts.path.rstrip("/"), "", "")).rstrip("/")
PREFIX = os.environ.get("PATH_PREFIX", "").strip()
if PREFIX in ("", "/"):
    PREFIX = ""
else:
    PREFIX = "/" + PREFIX.strip("/")

e = html.escape
CTX = {"type": "site", "slug": ""}
PAGES = []  # (path, title, desc) indexable
FEED = []


def use_sid(typ, slug=""):
    CTX["type"] = links.sid_part(typ) or "site"
    CTX["slug"] = links.sid_part(slug)


def sid(placement, product=""):
    return links.make_sid(CTX["type"], CTX["slug"], placement, product=product)


def abs_url(path):
    path = path.strip("/")
    if not path:
        return f"{BASE}{PREFIX}/"
    return f"{BASE}{PREFIX}/{path}/"


def site_href(path):
    path = path.strip("/")
    if not path:
        return f"{PREFIX}/" if PREFIX else "/"
    return f"{PREFIX}/{path}/"


def money(product):
    price = resolved_price(product)
    if price is None:
        return None
    currency = resolved_currency(product)
    if currency == "USD":
        return f"${price:,.2f}"
    if currency == "EUR":
        return f"€{price:,.2f}"
    raise SystemExit(f"{product['id']}: currency {currency}")


def resolved_price(product):
    feed = product.get("feed") or {}
    if isinstance(feed.get("price"), (int, float)) and not isinstance(feed.get("price"), bool):
        if feed.get("currency") in ("USD", "EUR") and feed["price"] > 0:
            return round(float(feed["price"]), 2)
    price = product.get("price")
    if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
        return round(float(price), 2)
    return None


def resolved_currency(product):
    feed = product.get("feed") or {}
    if isinstance(feed.get("price"), (int, float)) and not isinstance(feed.get("price"), bool) and feed.get("currency"):
        return feed["currency"]
    return product.get("currency")


def compare_at(product):
    """Only a compare-at that is higher than the price we are showing."""
    price = resolved_price(product)
    raw = product.get("compare_at")
    if price is None or not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None
    if float(raw) <= price:
        return None
    return round(float(raw), 2)


def compare_text(product):
    raw = compare_at(product)
    if raw is None:
        return None
    currency = resolved_currency(product)
    if currency == "USD":
        return f"${raw:,.2f}"
    if currency == "EUR":
        return f"€{raw:,.2f}"
    return None


def pct_off(product):
    raw = compare_at(product)
    price = resolved_price(product)
    if raw is None or price is None:
        return None
    return round((1 - price / raw) * 100)


def display_name(product):
    brand = product["brand"].strip()
    line = (product.get("line") or "").strip()
    name = product["name"].strip()
    bits = [brand]
    blob = brand.lower()
    if line and line.lower() not in blob and line.lower() not in name.lower():
        bits.append(line)
        blob = f"{blob} {line.lower()}"
    if name.lower() not in blob:
        bits.append(name)
    return " ".join(bits)


def merchant_name(product):
    return MERCHANTS[product["merchant"]]["name"]


def plain_product_url(product):
    """Merchant product URL after an optional CJ-feed replacement. Never a tracking URL."""
    feed = product.get("feed") or {}
    candidate = feed.get("url") or product.get("url")
    if not candidate:
        return None
    if links.is_tracking_url(candidate) or links.is_banned_url(candidate):
        if feed.get("url") and not links.is_tracking_url(product.get("url") or "") and product.get("url"):
            return product["url"]
        return None
    merchant = MERCHANTS[product["merchant"]]
    home = merchant.get("homepage")
    if home:
        home_host = links.host_of(home)
        if home_host and not links.host_is(links.host_of(candidate), home_host):
            raise SystemExit(f"{product['id']}: product URL host is not {home_host}")
    return candidate


def outbound(product, placement):
    url = plain_product_url(product)
    if not url:
        return None, sid(placement, "" if CTX["type"] == "deal" else product["id"])
    merchant = MERCHANTS[product["merchant"]]
    placement_sid = sid(placement, "" if CTX["type"] == "deal" else product["id"])
    affiliate = product.get("role") == "affiliate"
    href = links.outbound_href(url, placement_sid, merchant.get("cj_click_url"), affiliate=affiliate)
    return href, placement_sid


def ext_a(product, placement, label, cls="btn"):
    href, placement_sid = outbound(product, placement)
    if not href:
        return ""
    rel = links.rel_for(href)
    klass = f' class="{cls}"' if cls else ""
    return (
        f'<a{klass} rel="{rel}" target="_blank" data-sid="{e(placement_sid)}" '
        f'href="{e(href)}">{label}</a>'
    )


def button_label(product):
    if resolved_price(product) is None:
        return "Check today's price"
    if product.get("role") == "affiliate":
        return f"Buy at {e(merchant_name(product))}"
    return f"See it on {e(merchant_name(product))}"


def checked_label(product):
    raw = product.get("checked") or CHECKED
    year, month, day = raw.split("-")
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    return f"{months[int(month) - 1]} {int(day)}, {year}"


def price_valid_until(product):
    raw = product.get("checked") or CHECKED
    day = datetime.date.fromisoformat(raw) + datetime.timedelta(days=1)
    return day.isoformat()


CSS = """
*{box-sizing:border-box}
html{font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
body{margin:0;font-family:inherit;font-size:16px;line-height:1.5;color:#1c2430;background:#f6f3ee}
button,input,table,th,td{font-family:inherit}
a{color:#1f4e79}
header{background:#14324a;color:#fff;padding:14px 16px;display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px}
header a{color:#fff;text-decoration:none}
.logo{font-weight:800;font-size:20px;letter-spacing:-.4px;margin-right:auto}.logo span{color:#e2c48a}
.nav-toggle{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.nav-burger{display:none}
nav{display:flex;gap:14px;flex-wrap:wrap;font-size:14px}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:28px;line-height:1.2;margin:8px 0}
h2{font-size:22px;line-height:1.25}
.sub{color:#5c6772;margin:0 0 14px}
.lead-offer{background:#fff;border:1px solid #e4ddd2;border-radius:14px;padding:14px 16px;margin:0 0 14px;position:sticky;top:0;z-index:20;box-shadow:0 2px 10px rgba(20,50,74,.08)}
.lead-offer .btn{margin-top:8px;max-width:360px}
.price{font-size:28px;font-weight:800}
.was{color:#7b736a;text-decoration:line-through;margin-left:8px;font-size:16px}
.badge{display:inline-block;background:#14324a;color:#fff;border-radius:6px;padding:1px 7px;font-size:13px;font-weight:700;margin-left:6px}
.meta{font-size:13px;color:#6c655d}
.btn{display:inline-block;text-align:center;background:#14324a;color:#fff;border-radius:10px;padding:12px 16px;text-decoration:none;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}
.card{background:#fff;border:1px solid #e4ddd2;border-radius:14px;padding:12px;display:flex;flex-direction:column;min-width:0}
.card img{display:block;width:100%;height:auto;aspect-ratio:1/1;object-fit:contain;object-position:center;background:#fff;border-radius:10px;margin:0 0 10px}
.brand{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#7a7480}
.nm{font-weight:650;margin:2px 0 6px}
.nm a{color:inherit;text-decoration:none}
.card .btn{margin-top:auto}
img.thumb{display:block;width:72px;height:72px;aspect-ratio:1/1;object-fit:contain;object-position:center;background:#fff;border-radius:8px}
td.thumb,th.thumb{width:88px;padding:8px;vertical-align:middle;background:#fff}
.box{background:#fff;border:1px solid #e4ddd2;border-radius:14px;padding:16px;margin:18px 0}
.hero-photo{background:#fff;border:1px solid #e4ddd2;border-radius:14px;padding:12px;margin:0 0 16px}
.hero-photo img{display:block;width:min(100%,420px);height:auto;aspect-ratio:1/1;object-fit:contain;object-position:center;background:#fff;border-radius:10px}
table{width:100%;border-collapse:collapse;background:#fff}
th,td{text-align:left;padding:10px;border-bottom:1px solid #eee;vertical-align:top}
.chips a{display:inline-block;margin:4px;padding:4px 10px;border-radius:99px;background:#fff;border:1px solid #e3ddd6;text-decoration:none;font-size:14px}
.bf-banner{background:#14324a;color:#fff;border-radius:14px;padding:14px 16px;margin:0 0 16px}
.bf-banner a{color:#fff}
.bf-banner .btn{background:#e2c48a;color:#14324a;margin-top:8px}
header a.nav-bf{background:#e2c48a;color:#14324a;border-radius:999px;padding:2px 10px;font-weight:800}
footer{max-width:1100px;margin:20px auto;padding:16px;font-size:13px;color:#5c564e}
.crumbs{font-size:13px;color:#6c655d;margin:0 0 8px}
.crumbs a{text-decoration:none}
@media(max-width:640px){
  header{padding:8px 12px}
  .nav-burger{display:inline-flex;flex-direction:column;justify-content:center;gap:5px;width:44px;height:44px;cursor:pointer}
  .nav-burger span{display:block;width:20px;height:2px;background:#fff;border-radius:1px}
  nav{display:none;flex-basis:100%;flex-direction:column;gap:12px;padding:4px 0 8px}
  .nav-toggle:checked ~ nav{display:flex}
  nav a{padding:4px 0}
  main{padding:10px 12px}
  h1{font-size:22px}
  .price{font-size:24px}
  .grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .card{padding:10px}
  .card .btn{padding:10px 8px;font-size:14px}
  table.stack,table.stack thead,table.stack tbody,table.stack tr,table.stack th,table.stack td{display:block;width:100%}
  table.stack thead{display:none}
  table.stack tr{border-bottom:1px solid #eee;padding:8px 0}
  table.stack th,table.stack td{border:0;text-align:left;padding:2px 10px}
  table.stack th{color:#6c655d;font-size:13px;padding-top:8px}
  table.stack td[data-label]:not([data-label=""])::before{content:attr(data-label);display:block;margin-top:6px;font-weight:700;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:#6c655d}
  td.thumb,th.thumb{width:auto;padding:8px 10px 2px}
  img.thumb{width:72px;height:72px}
}
"""


def crumbs(items):
    """items: list of (href or None, label). Last is current."""
    bits = []
    ld_items = []
    for i, (href, label) in enumerate(items, start=1):
        if href:
            bits.append(f'<a href="{href}">{e(label)}</a>')
            ld_items.append({"@type": "ListItem", "position": i, "name": label, "item": BASE + href if href.startswith("/") else href})
        else:
            bits.append(f'<span aria-current="page">{e(label)}</span>')
            ld_items.append({"@type": "ListItem", "position": i, "name": label})
        if i != len(items):
            bits.append('<span class="sep"> / </span>')
    html_bits = f'<nav class="crumbs" aria-label="Breadcrumb">{"".join(bits)}</nav>'
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": ld_items}
    return html_bits, ld


def page(path, title, desc, body, jsonld=None, index=True, crumbs_html=""):
    title = re.sub(r"\s+", " ", title).strip()
    desc = re.sub(r"\s+", " ", desc).strip()
    if len(title) > 60:
        raise SystemExit(f"title too long ({len(title)}) for {path}: {title}")
    if index and not (50 <= len(desc) <= 160):
        raise SystemExit(f"meta length {len(desc)} for {path}: {desc}")
    url = abs_url(path.replace("/index.html", "").replace("index.html", ""))
    if path == "index.html":
        url = abs_url("")
    ld = "".join(
        f'<script type="application/ld+json">{json.dumps(block, ensure_ascii=False)}</script>'
        for block in (jsonld or [])
    )
    robots = "" if index else '<meta name="robots" content="noindex">'
    nav = (
        f'<a class="nav-bf" href="{site_href("black-friday-luggage-deals")}">Black Friday</a>'
        f'<a href="{site_href("")}">Deals</a>'
        f'<a href="{site_href("carry-on")}">Carry-ons</a>'
        f'<a href="{site_href("checked")}">Checked</a>'
        f'<a href="{site_href("underseat")}">Underseat</a>'
        f'<a href="{site_href("best")}">Best of</a>'
        f'<a href="{site_href("gifts")}">Gifts</a>'
        f'<a href="{site_href("brands")}">Brands</a>'
    )
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{robots}<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="{e(NAME)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}"><meta name="twitter:card" content="summary">
<link rel="alternate" type="application/rss+xml" title="{e(NAME)}" href="{e(abs_url('feed.xml').rstrip('/') if False else BASE+PREFIX+'/feed.xml')}">
<style>{CSS}</style>{ld}</head><body>
<header><a class="logo" href="{site_href("")}">Luggage<span>Deals</span>Daily</a><input class="nav-toggle" id="nav-toggle" type="checkbox"><label class="nav-burger" for="nav-toggle" aria-label="Menu"><span></span><span></span><span></span></label><nav>{nav}</nav></header>
<main>{crumbs_html}{body}</main>
<footer>
<p>We may earn a commission if you buy through a link on this site. That does not change the price. <a href="{site_href("disclosure")}">Affiliate disclosure</a>.</p>
<p>Prices and measurements are copied from the maker's public product page on the date shown. We do not publish a price, rating, or measurement we did not read there.</p>
<p>© {CHECKED[:4]} {e(NAME)} · {e(OWNER)} · <a href="{site_href("about")}">About</a> · <a href="{site_href("privacy")}">Privacy</a> · <a href="{site_href("disclosure")}">Disclosure</a> · <a href="{PREFIX}/llms.txt">llms.txt</a> · <a href="{PREFIX}/sitemap.xml">sitemap</a></p>
</footer></body></html>"""
    rel = path if path.endswith(".html") else path.strip("/") + "/index.html"
    if rel == "/index.html":
        rel = "index.html"
    fp = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as handle:
        handle.write(doc)
    if index:
        PAGES.append(url if path != "index.html" else abs_url(""))
        return url
    return None


def spec_rows(product):
    rows = []
    if product.get("variant"):
        rows.append(("Size priced", product["variant"]))
    if product.get("shell"):
        rows.append(("Shell", product["shell"]))
    if product.get("overall"):
        label = "Overall size"
        if product.get("overall_includes"):
            label += f" ({product['overall_includes']})"
        rows.append((label, product["overall"]))
    if product.get("case_size"):
        rows.append(("Case size", product["case_size"]))
    if product.get("weight"):
        rows.append(("Weight", product["weight"]))
    if product.get("volume"):
        rows.append(("Volume", product["volume"]))
    if product.get("expansion"):
        rows.append(("Expansion listed", product["expansion"]))
    if product.get("material"):
        rows.append(("Material listed", product["material"]))
    if not rows:
        return ""
    body = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in rows)
    return (
        "<div class='box'><h2 style='margin-top:0'>Manufacturer specifications</h2>"
        "<p class='meta'>Copied from that model's public product page. Empty rows are measurements the page did not list.</p>"
        f"<table><tbody>{body}</tbody></table></div>"
    )


def product_description(product):
    name = display_name(product)
    bits = [f"{name} product page on {merchant_name(product)}."]
    shown = money(product)
    if shown:
        bits.append(f"Listed price {shown} on {checked_label(product)}.")
    if product.get("overall"):
        bits.append(f"Overall size listed as {product['overall']}.")
    if product.get("weight"):
        bits.append(f"Weight listed as {product['weight']}.")
    return " ".join(bits)


def product_ld(product):
    name = display_name(product)
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "description": product_description(product),
        "brand": {"@type": "Brand", "name": product["brand"]},
    }
    hosted = hosted_image(product)
    if hosted:
        src, _, _ = hosted
        data["image"] = src if src.startswith("http") else f"{BASE}{src}"
    price = resolved_price(product)
    url = plain_product_url(product)
    if price is not None and url:
        offer = {
            "@type": "Offer",
            "price": f"{price:.2f}",
            "priceCurrency": resolved_currency(product),
            "url": url,
            "priceValidUntil": price_valid_until(product),
            "seller": {"@type": "Organization", "name": merchant_name(product)},
        }
        if product.get("in_stock") is True:
            offer["availability"] = "https://schema.org/InStock"
        elif product.get("in_stock") is False:
            offer["availability"] = "https://schema.org/OutOfStock"
        data["offers"] = offer
    return data


def faq_ld(pairs):
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in pairs
        ],
    }


def faq_html(pairs):
    blocks = "".join(f"<h3>{e(q)}</h3><p>{e(a)}</p>" for q, a in pairs)
    return f"<div class='box'><h2 style='margin-top:0'>Questions</h2>{blocks}</div>"


def lead(product):
    shown = money(product)
    when = checked_label(product)
    seller = merchant_name(product)
    if shown:
        was = compare_text(product)
        was_html = f"<span class='was'>{e(was)}</span>" if was else ""
        pct = pct_off(product)
        badge = f"<span class='badge'>{pct}% under compare-at</span>" if pct else ""
        price_html = f"<p class='lead-price'><span class='price'>{e(shown)}</span>{was_html}{badge}</p>"
        source = f"Prices checked {when} on the {seller} product page"
        if was:
            source += ". The crossed-out figure is the compare-at price on that same page."
        if resolved_currency(product) == "EUR":
            source += " Horizn Studios' public cart currency is euros. This is not a dollar price."
    else:
        price_html = "<p class='lead-price'><span class='price'>Check today's price</span></p>"
        source = f"No verified price on file · last look {when}"
    variant = f"<p class='meta'>Price is for the {e(product['variant'])} option.</p>" if product.get("variant") and shown else ""
    btn = ext_a(product, "cta", button_label(product))
    if not btn and not shown:
        btn = "<p class='meta'>This page has no outbound button because we do not have a verified product URL.</p>"
    return (
        f"<div class='lead-offer'><p class='meta'>{e(source)}</p>"
        f"<p class='lead-name'><b>{e(display_name(product))}</b></p>"
        f"{price_html}{variant}{btn}</div>"
    )


def jpeg_size(path):
    """Width and height from a JPEG SOF marker. The site build does not import Pillow."""
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise SystemExit(f"{path} is not a jpeg")
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            if marker == 0xD9:
                break
            i += 2
            continue
        if i + 4 > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            if width > 0 and height > 0:
                return width, height
            break
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2:
            break
        i += 2 + length
    raise SystemExit(f"{path}: no jpeg size")


def hosted_image(product):
    """Photo saved from the merchant product page. A remote URL is never emitted."""
    filename = product["id"] + ".jpg"
    disk = os.path.join(ROOT, "media", "products", filename)
    if not os.path.isfile(disk):
        return None
    width, height = jpeg_size(disk)
    href = f"{PREFIX}/media/products/{filename}" if PREFIX else f"/media/products/{filename}"
    return href, width, height


def product_img(product, eager=False):
    hosted = hosted_image(product)
    if not hosted:
        return ""
    src, width, height = hosted
    alt = display_name(product)
    extra = "fetchpriority='high'" if eager else "loading='lazy'"
    return (
        f"<img {extra} decoding='async' src='{e(src)}' alt='{e(alt)}' width='{width}' height='{height}'>"
    )


def thumb_img(product):
    """Small copy of the hosted product photo for a table cell."""
    hosted = hosted_image(product)
    if not hosted:
        return ""
    src, _, _ = hosted
    return (
        f"<img class='thumb' loading='lazy' decoding='async' src='{e(src)}' alt='{e(display_name(product))}' "
        f"width='72' height='72'>"
    )


def thumb_cell(product, label="Photo"):
    return f"<td class='thumb' data-label='{e(label)}'>{thumb_img(product)}</td>"


def listed(product):
    """A deal we can show: it has the merchant's own product page."""
    return plain_product_url(product) is not None


def photo(product):
    img = product_img(product, eager=True)
    if not img:
        return "<p class='meta'>No manufacturer photo is stored for this page.</p>"
    return (
        f"<figure class='hero-photo'>{img}"
        f"<figcaption class='meta'>Photo from the {e(merchant_name(product))} product page.</figcaption></figure>"
    )


def card(product, placement="grid"):
    shown = money(product)
    price = f"<div class='price' style='font-size:22px'>{e(shown)}</div>" if shown else "<div class='meta'>Check today's price</div>"
    was = compare_text(product)
    was_html = f"<div class='meta'>Compare-at {e(was)}</div>" if was else ""
    img = product_img(product)
    internal = site_href(f"luggage/{product['id']}")
    return (
        f"<article class='card'>{img}"
        f"<div class='brand'>{e(product['brand'])}</div>"
        f"<div class='nm'><a href='{internal}'>{e(display_name(product))}</a></div>"
        f"{price}{was_html}"
        f"{ext_a(product, placement, button_label(product))}</article>"
    )


def related_sections(product):
    family = [p for p in PRODUCTS if p["family"] == product["family"] and p["id"] != product["id"] and p.get("url")]
    category = [
        p for p in PRODUCTS
        if p["category"] == product["category"] and p["family"] != product["family"] and p.get("url") and resolved_price(p) is not None
    ]
    category = category[:4]
    family = family[:4]
    html_bits = ""
    if family:
        html_bits += "<h2>Other sizes and models in this line</h2><div class='grid'>" + "".join(card(p, "also") for p in family) + "</div>"
    if category:
        html_bits += "<h2>More in this category</h2><div class='grid'>" + "".join(card(p, "also") for p in category) + "</div>"
    return html_bits


def product_faqs(product):
    name = display_name(product)
    seller = merchant_name(product)
    shown = money(product)
    when = checked_label(product)
    if shown:
        q1 = (
            f"What price is listed for the {name}?",
            f"On {when}, the {seller} product page listed {shown}"
            + (f" for the {product['variant']} option." if product.get("variant") else ".")
            + (" The compare-at price on that page was " + compare_text(product) + "." if compare_text(product) else ""),
        )
    else:
        q1 = (
            f"What does the {name} cost?",
            "We do not have a price copied from a current product page, so this page does not show a number.",
        )
    if plain_product_url(product):
        q_link = (
            "Where does the button go?",
            f"It opens the {seller} product page in a new tab.",
        )
    else:
        q_link = (
            "Where can I buy it?",
            "This page has no buy button because we do not have a verified product URL.",
        )
    specs = []
    if product.get("overall"):
        specs.append(f"overall {product['overall']}")
    if product.get("weight"):
        specs.append(f"weight {product['weight']}")
    if product.get("volume"):
        specs.append(f"volume {product['volume']}")
    if specs:
        q_spec = (
            f"What size does {seller} list?",
            "The product page lists " + ", ".join(specs) + ". Measurements that were not on that page are left blank here.",
        )
    else:
        q_spec = (
            f"What size does {seller} list?",
            "The product text we read did not include a measurement we could copy, so this page does not print one.",
        )
    return [q1, q_spec, q_link, (
        "How current is this page?",
        f"Prices checked {when}. They can change. Open the maker's page to see today's figure.",
    )]


def render_product(product):
    use_sid("deal", product["id"])
    name = display_name(product)
    shown = money(product)
    seller = merchant_name(product)
    when = checked_label(product)
    short_name = re.sub(r"\s*\([^)]*\)", "", product["name"]).strip()
    if shown:
        title = next(c for c in (
            f"{name}: {shown}",
            f"{product['brand']} {short_name}: {shown}",
            f"{short_name}: {shown}",
            f"{product['brand']} {shown}",
        ) if len(c) <= 60)
        desc = next(c for c in (
            f"{name} is {shown} at {seller}, checked {when}. Maker measurements are on the page when the product page listed them.",
            f"{product['brand']} {short_name} is {shown} at {seller}, checked {when}.",
            f"{short_name} is {shown} at {seller}, checked {when}.",
        ) if 50 <= len(c) <= 160)
    else:
        title = next(c for c in (
            f"{name}: check today's price",
            f"{product['brand']}: check today's price",
        ) if len(c) <= 60)
        desc = f"No verified price for {name}. Compare priced Travelpro and LEVEL8 bags on this site instead of a guessed number."
        if len(desc) > 160:
            desc = f"No verified price for {product['brand']} {short_name}. Compare priced Travelpro and LEVEL8 bags instead."
    path = f"luggage/{product['id']}"
    if product["category"] in ("carry-on", "checked", "underseat"):
        section_href = site_href(product["category"])
        section_label = {"carry-on": "Carry-ons", "checked": "Checked", "underseat": "Underseat"}[product["category"]]
    elif product["category"] in ("packing-cube", "backpack", "weekender", "duffel"):
        section_href = site_href("accessories")
        section_label = "Accessories"
    else:
        section_href = site_href("brands")
        section_label = "Brands"
    crumb_html, crumb_ld = crumbs([
        (site_href(""), "Deals"),
        (section_href, section_label),
        (None, name),
    ])
    faqs = product_faqs(product)
    body = (
        f"<h1>{e(name)}</h1>"
        f"<p class='sub'>{e(product['brand'])} · {e(product['category'].replace('-', ' '))}</p>"
        + lead(product)
        + photo(product)
        + spec_rows(product)
        + faq_html(faqs)
        + related_sections(product)
    )
    blocks = [crumb_ld, faq_ld(faqs)]
    if resolved_price(product) is not None and plain_product_url(product):
        blocks.append(product_ld(product))
    page(path, title, desc, body, blocks, index=listed(product), crumbs_html=crumb_html)
    if shown:
        FEED.append((name, abs_url(path), desc))


def category_page(slug, title, desc, intro, products):
    use_sid("cat", slug)
    crumb_html, crumb_ld = crumbs([(site_href(""), "Deals"), (None, title)])
    faqs = [(
        f"Where do these {title.lower()} prices come from?",
        f"Prices checked {checked_label({'checked': CHECKED})}. Each figure was copied from that maker's public product page. Models without a verified price are not given a number.",
    ), (
        "Where does the button go?",
        "It opens the maker's own product page.",
    )]
    body = (
        f"<h1>{e(title)}</h1><p class='sub'>{e(intro)}</p>"
        + "<div class='grid'>" + "".join(card(p) for p in products) + "</div>"
        + faq_html(faqs)
    )
    page(slug, title, desc, body, [crumb_ld, faq_ld(faqs)], crumbs_html=crumb_html)


def best_page(slug, title, desc, intro, products, extra=""):
    use_sid("best", slug)
    crumb_html, crumb_ld = crumbs([(site_href(""), "Deals"), (site_href("best"), "Best of"), (None, title)])
    rows = []
    for p in products:
        shown = money(p) or "Check today's price"
        size = p.get("overall") or "—"
        rows.append(
            f"<tr>{thumb_cell(p)}<td data-label='Model'><a href='{site_href('luggage/'+p['id'])}'>{e(display_name(p))}</a>"
            f"<div class='meta'>{e(merchant_name(p))}</div></td>"
            f"<td data-label='Size'>{e(size)}</td><td data-label='Listed'><b>{e(shown)}</b></td>"
            f"<td>{ext_a(p, 'table', button_label(p), cls='')}</td></tr>"
        )
    priced = [p for p in products if resolved_price(p) is not None]
    faqs = [(
        "How is this list ordered?",
        "Dollar prices are listed before euro prices. Within one currency the lower listed price is first. This is a price sort of pages we checked, not a lab test.",
    ), (
        "Why are some famous suitcases missing a price?",
        "Away, Monos, Béis, Calpak, and Briggs & Riley appear when a price was on the brand's own site. Samsonite Freeform and Tumi are left off because this site has no verified product page for them.",
    )]
    if priced:
        low = min(priced, key=lambda p: (0 if resolved_currency(p) == "USD" else 1, resolved_price(p)))
        faqs.insert(0, (
            "Which checked price is the lowest on this page?",
            f"{display_name(low)} at {money(low)} on the {merchant_name(low)} page. Prices checked {checked_label(low)}.",
        ))
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": title,
        "itemListElement": [],
    }
    for i, p in enumerate(priced, start=1):
        node = product_ld(p)
        node.pop("@context", None)
        item_list["itemListElement"].append({"@type": "ListItem", "position": i, "item": node})
    body = (
        f"<h1>{e(title)}</h1><p>{e(intro)}</p>{extra}"
        + "<table class='stack'><thead><tr><th class='thumb'>Photo</th><th>Model</th><th>Listed size</th><th>Listed price</th><th></th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
        + "<h2>Pages</h2><div class='grid'>" + "".join(card(p) for p in products) + "</div>"
        + faq_html(faqs)
    )
    blocks = [crumb_ld, faq_ld(faqs)]
    if item_list["itemListElement"]:
        blocks.append(item_list)
    page(f"best/{slug}", f"{title}", desc, body, blocks, crumbs_html=crumb_html)


def vs_page(slug, title, left_id, right_id, intro):
    use_sid("vs", slug)
    a = BY_ID[left_id]
    b = BY_ID[right_id]
    crumb_html, crumb_ld = crumbs([(site_href(""), "Deals"), (site_href("best"), "Best of"), (None, title)])
    def cell(p, field):
        if field == "price":
            return money(p) or "No verified price"
        if field == "seller":
            return merchant_name(p)
        return p.get(field) or "Not listed on the page we read"
    rows = ""
    for label, field in (
        ("Listed price", "price"),
        ("Seller", "seller"),
        ("Overall size", "overall"),
        ("Weight", "weight"),
        ("Volume", "volume"),
        ("Shell", "shell"),
    ):
        rows += (
            f"<tr><th>{e(label)}</th>"
            f"<td data-label='{e(display_name(a))}'>{e(cell(a, field))}</td>"
            f"<td data-label='{e(display_name(b))}'>{e(cell(b, field))}</td></tr>"
        )
    rows = (
        f"<tr><th>Photo</th><td class='thumb' data-label='{e(display_name(a))}'>{thumb_img(a)}</td>"
        f"<td class='thumb' data-label='{e(display_name(b))}'>{thumb_img(b)}</td></tr>"
        + rows
    )
    rows += (
        f"<tr><th></th><td data-label='{e(display_name(a))}'>{ext_a(a, 'table', button_label(a))}</td>"
        f"<td data-label='{e(display_name(b))}'>{ext_a(b, 'table', button_label(b))}</td></tr>"
    )
    faqs = [(
        f"Which listed price is lower, {display_name(a)} or {display_name(b)}?",
        price_compare_sentence(a, b),
    ), (
        "Where do the buttons go?",
        "Each button opens that brand's own product page.",
    ), (
        "Did you test these bags?",
        "No. The table repeats the price and the measurements printed on each product page. It is not a wear test.",
    )]
    body = (
        f"<h1>{e(title)}</h1><p>{e(intro)}</p>"
        + "<div class='box'><table class='stack'><thead><tr><th></th><th>"
        + f"<a href='{site_href('luggage/'+a['id'])}'>{e(display_name(a))}</a></th><th>"
        + f"<a href='{site_href('luggage/'+b['id'])}'>{e(display_name(b))}</a></th></tr></thead><tbody>{rows}</tbody></table></div>"
        + faq_html(faqs)
        + "<div class='grid'>" + card(a) + card(b) + "</div>"
    )
    blocks = [crumb_ld, faq_ld(faqs)]
    if resolved_price(a):
        blocks.append(product_ld(a))
    if resolved_price(b):
        blocks.append(product_ld(b))
    meta = intro
    if not (50 <= len(meta) <= 160):
        meta = f"{display_name(a)} vs {display_name(b)}: listed prices and the measurements each product page published, checked {checked_label(a)}."
    if len(meta) > 160:
        meta = f"{display_name(a)} vs {display_name(b)}, with listed prices checked {checked_label(a)}."
    page(f"vs/{slug}", title, meta, body, blocks, crumbs_html=crumb_html)


def price_compare_sentence(a, b):
    pa, pb = resolved_price(a), resolved_price(b)
    if pa is None or pb is None:
        return "One of these pages has no verified price, so this page does not call a winner on price."
    if resolved_currency(a) != resolved_currency(b):
        return f"{display_name(a)} is listed at {money(a)} and {display_name(b)} at {money(b)}. The currencies differ, so they are not ranked against each other."
    if pa == pb:
        return f"Both pages listed {money(a)} on {checked_label(a)}."
    low, high = (a, b) if pa < pb else (b, a)
    return f"{display_name(low)} is the lower listed price at {money(low)}. {display_name(high)} is listed at {money(high)}. Prices checked {checked_label(a)}."


def gift_page(slug, title, desc, intro, ids):
    use_sid("gifts", slug)
    picks = [BY_ID[i] for i in ids]
    crumb_html, crumb_ld = crumbs([(site_href(""), "Deals"), (site_href("gifts"), "Gifts"), (None, title)])
    faqs = [(
        "Are these ranked as the best gifts?",
        "No. They are products with a price copied from the maker, grouped for this occasion. Each card shows that product's own listed price.",
    ), (
        "Can I buy them from this site?",
        "The button opens the maker's own product page.",
    )]
    body = (
        f"<h1>{e(title)}</h1><p>{e(intro)}</p>"
        + lead(picks[0])
        + "<div class='grid'>" + "".join(card(p) for p in picks) + "</div>"
        + faq_html(faqs)
    )
    nodes = []
    for i, p in enumerate(picks, start=1):
        if resolved_price(p) is None:
            continue
        node = product_ld(p)
        node.pop("@context", None)
        nodes.append({"@type": "ListItem", "position": i, "item": node})
    page(f"gifts/{slug}", title, desc, body, [
        crumb_ld,
        faq_ld(faqs),
        {"@context": "https://schema.org", "@type": "ItemList", "name": title, "itemListElement": nodes},
    ], crumbs_html=crumb_html)


def airline_page():
    use_sid("guide", "carry-on-size-rules")
    delta = OUTBOUND["delta-carry-on-policy"]
    southwest = OUTBOUND["southwest-carry-on-policy"]
    crumb_html, crumb_ld = crumbs([(site_href(""), "Deals"), (site_href("best"), "Best of"), (None, "Carry-on size rules")])
    # Links are plain informational URLs stored in the catalog, not product affiliate links.
    use_sid("guide", "carry-on-size-rules")
    delta_sid = sid("policy")
    sw_sid = sid("policy2")
    faqs = [(
        "What carry-on size does Delta publish?",
        delta["quote"] + f" That sentence is from Delta's carry-on baggage page as read on {checked_label({'checked': delta['checked']})}.",
    ), (
        "What about American, United, JetBlue, Alaska, Spirit, and Frontier?",
        "This build does not print a number for those airlines. Their pages did not return a measurement we could copy. Check the airline's own site before you fly, and compare it with the overall size on the suitcase page, wheels and handles included, when the maker lists one.",
    ), (
        "Does Southwest publish a size on the page we opened?",
        "We opened Southwest's carry-on article and did not get the size text in the HTML, so this page does not quote one. The article link is below.",
    )]
    body = (
        "<h1>Carry-on size rules by airline</h1>"
        "<p>Airline limits change, and a suitcase's overall size includes wheels and handles when the maker says so. "
        "This page quotes only the measurement we could read on the airline's own page.</p>"
        f"<div class='box'><h2 style='margin-top:0'>Delta</h2><p>{e(delta['quote'])}</p>"
        f"<p><a rel='noopener noreferrer' target='_blank' data-sid='{e(delta_sid)}' href='{e(delta['url'])}'>{e(delta['label'])}</a></p></div>"
        f"<div class='box'><h2 style='margin-top:0'>Southwest</h2>"
        "<p>Southwest's carry-on article responded, and the HTML we read did not include a size figure. Use the airline's page for the current rule.</p>"
        f"<p><a rel='noopener noreferrer' target='_blank' data-sid='{e(sw_sid)}' href='{e(southwest['url'])}'>{e(southwest['label'])}</a></p></div>"
        "<div class='box'><h2 style='margin-top:0'>Other airlines</h2>"
        "<p>American, United, JetBlue, Alaska, Spirit, and Frontier are not given a number here. Open each airline's baggage page before a trip.</p></div>"
        + faq_html(faqs)
        + "<p class='chips'><a href='" + site_href("best/best-carry-on-luggage") + "'>Carry-on pages with a checked price</a>"
        + "<a href='" + site_href("luggage/travelpro-platinum-elite-carry-on-spinner") + "'>Travelpro Platinum Elite carry-on</a></p>"
    )
    desc = "Delta's carry-on page lists 22 x 14 x 9 inches, handles and wheels included, and a 45 linear inch total. Other airlines are not given a guessed size."
    page("guides/carry-on-size-rules", "Carry-on size rules by airline", desc, body, [crumb_ld, faq_ld(faqs)], crumbs_html=crumb_html)


def static_pages():
    use_sid("about", "")
    about_body = (
        f"<h1>About {e(NAME)}</h1>"
        f"<p>{e(NAME)} is a luggage and travel-accessory deal site run by {e(OWNER)}. "
        "Each deal shows a price and the measurements copied from the maker's own product page.</p>"
        "<p>A price appears only when it was on that page. If it was not, the deal says to check today's price and does not guess a number.</p>"
        f"<p>Buttons leave this site and open the maker's page. Some of those links may earn us a commission, at no extra cost to you. "
        f"<a href='{site_href('disclosure')}'>Affiliate disclosure</a>.</p>"
    )
    page("about", f"About {NAME}", f"{NAME} is owned by {OWNER}. Prices are copied from each maker's product page, and we do not guess a number.", about_body, crumbs_html=crumbs([(site_href(""), "Deals"), (None, "About")])[0])

    use_sid("privacy", "")
    privacy = (
        "<h1>Privacy</h1>"
        f"<p>{e(NAME)} is a static site. It does not ask you to create an account, and this version does not set analytics cookies or embed a tracker.</p>"
        "<p>Product buttons open another site. That site has its own privacy policy.</p>"
        "<p>Email the site owner through the contact published with the domain registration if you need a page changed. This page does not collect that message itself.</p>"
    )
    page("privacy", f"Privacy · {NAME}", f"{NAME} is a static site with no accounts and no analytics cookies. Buttons open merchant pages with no tracking parameter.", privacy, crumbs_html=crumbs([(site_href(""), "Deals"), (None, "Privacy")])[0])

    use_sid("disclosure", "")
    disclosure = (
        "<h1>Affiliate disclosure</h1>"
        f"<p>{e(NAME)} is owned by {e(OWNER)}. Some links on this site may be affiliate links. "
        "If you buy through one, we may earn a commission. That does not add anything to the price you pay.</p>"
        "<p>A button opens the maker's own product page. The price on that page is the one that matters.</p>"
    )
    page("disclosure", f"Affiliate disclosure · {NAME}", f"{NAME} may earn a commission if you buy through a link. That does not change the price on the maker's page.", disclosure, crumbs_html=crumbs([(site_href(""), "Deals"), (None, "Disclosure")])[0])


def home():
    use_sid("home", "")
    checked = checked_label({"checked": CHECKED})
    carry = [p for p in PRODUCTS if p["category"] == "carry-on" and p["role"] == "affiliate" and resolved_currency(p) == "USD" and resolved_price(p) and listed(p)]
    carry.sort(key=lambda p: resolved_price(p))
    groups = [
        ("Carry-ons with a dollar price", [p for p in carry]),
        ("Checked luggage with a dollar price", [p for p in PRODUCTS if p["category"] == "checked" and resolved_currency(p) == "USD" and resolved_price(p) and p["role"] == "affiliate" and listed(p)]),
        ("Horizn Studios, listed in euros", [p for p in PRODUCTS if p["merchant"] == "horizn" and listed(p)]),
        ("Underseat, backpacks, and packing cubes", [p for p in PRODUCTS if p["category"] in ("underseat", "backpack", "packing-cube", "weekender", "duffel") and p["role"] == "affiliate" and listed(p)]),
    ]
    sections = ""
    for heading, rows in groups:
        rows = sorted(rows, key=lambda p: resolved_price(p) or 10**9)
        sections += f"<h2>{e(heading)}</h2><div class='grid'>" + "".join(card(p) for p in rows) + "</div>"
    faqs = [(
        "Where do the prices come from?",
        f"Prices checked {checked}. Each figure was copied from the maker's public product page. A model without that reading shows Check today's price instead of a number.",
    ), (
        "Where does the button go?",
        "It opens the maker's own product page.",
    )]
    crumb_html = ""
    body = (
        "<h1>Luggage deals</h1>"
        f"<p class='sub'>Carry-ons, checked bags, and travel accessories from Travelpro, LEVEL8, Horizn Studios, Stuart &amp; Lau, and other makers. Prices checked {e(checked)}.</p>"
        f"<div class='bf-banner'><p style='margin:0 0 6px'><b>Black Friday 2026 is Friday, November 27.</b> Cyber Monday is November 30.</p>"
        f"<p style='margin:0'>The largest gaps versus each product's own compare-at are on one page. Horizn prices stay in euros.</p>"
        f"<a class='btn' href='{site_href('black-friday-luggage-deals')}'>Black Friday luggage deals</a></div>"
        + sections
        + "<p class='chips'>"
        + "".join(f"<a href='{site_href(path)}'>{e(label)}</a>" for path, label in (
            ("best/best-carry-on-luggage", "Best carry-on luggage"),
            ("best/best-checked-luggage", "Best checked luggage"),
            ("best/best-luggage-under-200", "Luggage under $200"),
            ("best/best-underseat-bags", "Underseat bags"),
            ("best/away-alternatives", "Away alternatives"),
            ("vs/travelpro-platinum-elite-vs-away", "Travelpro vs Away"),
            ("vs/level8-voyageur-vs-away", "LEVEL8 vs Away"),
            ("guides/carry-on-size-rules", "Carry-on size rules"),
            ("gifts/graduation-travel-gifts", "Graduation gifts"),
            ("gifts/holiday-travel-gifts", "Holiday travel gifts"),
        ))
        + "</p>"
        + faq_html(faqs)
    )
    desc = f"Luggage prices from Travelpro, LEVEL8, Horizn Studios, and Stuart & Lau, checked {checked_label({'checked': CHECKED})}. Each deal card opens with the product photo."
    page("index.html", f"{NAME}: checked luggage prices", desc, body, [faq_ld(faqs)], crumbs_html=crumb_html)


def sort_price(rows):
    return sorted(rows, key=lambda p: (0 if resolved_currency(p) == "USD" else 1, resolved_price(p) or 10**9, p["id"]))


def savings_amount(product):
    """Compare-at minus listed price, only when both numbers are already stored and the compare-at is higher."""
    price = resolved_price(product)
    was = compare_at(product)
    if price is None or was is None:
        return None
    return round(was - price, 2)


def money_amount(amount, currency):
    if currency == "USD":
        return f"${amount:,.2f}"
    if currency == "EUR":
        return f"€{amount:,.2f}"
    raise SystemExit(f"unknown currency {currency}")


def deals_with_savings():
    """Biggest stored gap first, dollars as a group, then euros. No currency conversion."""
    rows = [p for p in PRODUCTS if savings_amount(p) is not None and plain_product_url(p)]
    rows.sort(key=lambda p: (
        0 if resolved_currency(p) == "USD" else 1,
        -savings_amount(p),
        p["id"],
    ))
    return rows


def black_friday_page():
    use_sid("bf", "black-friday-luggage-deals")
    ranked = deals_with_savings()
    if not ranked:
        raise SystemExit("black friday page has no stored savings")
    usd = [p for p in ranked if resolved_currency(p) == "USD"]
    eur = [p for p in ranked if resolved_currency(p) == "EUR"]
    top_usd = max(usd, key=savings_amount) if usd else None
    top_eur = max(eur, key=savings_amount) if eur else None
    crumb_html, crumb_ld = crumbs([
        (site_href(""), "Deals"),
        (None, "Black Friday"),
    ])
    rank_rows = []
    for p in ranked:
        gap = savings_amount(p)
        rank_rows.append(
            "<tr>"
            f"{thumb_cell(p)}"
            f"<td data-label='Model'><a href='{site_href('luggage/'+p['id'])}'>{e(display_name(p))}</a>"
            f"<div class='meta'>{e(merchant_name(p))}</div></td>"
            f"<td data-label='Listed'><b>{e(money(p))}</b></td>"
            f"<td data-label='Compare-at'>{e(compare_text(p))}</td>"
            f"<td data-label='Savings'>{e(money_amount(gap, resolved_currency(p)))}</td>"
            f"<td>{ext_a(p, 'table', button_label(p), cls='')}</td>"
            "</tr>"
        )
    groups = [
        ("Carry-on", [p for p in PRODUCTS if p["category"] == "carry-on" and listed(p)]),
        ("Checked", [p for p in PRODUCTS if p["category"] == "checked" and listed(p)]),
        ("Sets", []),
        ("Bags", [p for p in PRODUCTS if p["category"] in ("underseat", "backpack", "weekender", "duffel", "packing-cube") and listed(p)]),
    ]
    sections = ""
    linked = 0
    for heading, rows in groups:
        rows = sorted(rows, key=lambda p: (
            0 if savings_amount(p) is not None else 1,
            0 if resolved_currency(p) == "USD" else 1,
            -(savings_amount(p) or 0),
            resolved_price(p) or 10**9,
            p["id"],
        ))
        if heading == "Sets" and not rows:
            sections += (
                "<h2>Sets</h2>"
                "<p>This site has no luggage set with a checked price, so this section does not list one. "
                "Packing-cube sets are with bags.</p>"
            )
            continue
        bits = []
        for p in rows:
            shown = money(p)
            gap = savings_amount(p)
            extra = ""
            if shown and gap is not None:
                extra = f" · {e(shown)} · {e(money_amount(gap, resolved_currency(p)))} under compare-at"
            elif shown:
                extra = f" · {e(shown)}"
            else:
                extra = " · no verified price"
            bits.append(f"<li><a href='{site_href('luggage/'+p['id'])}'>{e(display_name(p))}</a>{extra}</li>")
            linked += 1
        sections += f"<h2>{e(heading)}</h2><ul>{''.join(bits)}</ul>"
    faqs = [
        (
            "When is Black Friday 2026?",
            "Black Friday 2026 is Friday, November 27. Cyber Monday is Monday, November 30.",
        ),
        (
            "Are these Black Friday sale prices?",
            f"No. They are the listed price and the compare-at already stored from each merchant page on {checked_label({'checked': CHECKED})}. The order is the size of that gap. It is not a forecast of the November 27 price.",
        ),
        (
            "Which stored gap is the largest?",
            (
                (f"In dollars, {display_name(top_usd)} is listed at {money(top_usd)} against a {compare_text(top_usd)} compare-at, a gap of {money_amount(savings_amount(top_usd), 'USD')}. " if top_usd else "")
                + (f"In euros, {display_name(top_eur)} is listed at {money(top_eur)} against a {compare_text(top_eur)} compare-at, a gap of {money_amount(savings_amount(top_eur), 'EUR')}. " if top_eur else "")
                + "The two currencies are not converted or ranked against each other."
            ),
        ),
        (
            "Why are some Horizn prices in euros?",
            "Horizn Studios' public cart currency is euros. This page shows that currency as stored and does not convert it to dollars.",
        ),
        (
            "Where are the luggage sets?",
            "This site has no luggage set with a checked price. Packing-cube sets are listed under bags.",
        ),
    ]
    body = (
        "<h1>Black Friday luggage deals 2026</h1>"
        "<p>Black Friday 2026 is Friday, November 27. Cyber Monday is Monday, November 30. "
        f"The table keeps every model that already has both a listed price and a higher compare-at. Prices checked {e(checked_label({'checked': CHECKED}))}. "
        "Dollar gaps are listed before euro gaps. Nothing here is a predicted holiday percent off.</p>"
        "<table class='stack'><thead><tr><th class='thumb'>Photo</th><th>Model</th><th>Listed price</th><th>Compare-at</th><th>Gap</th><th></th></tr></thead><tbody>"
        + "".join(rank_rows) + "</tbody></table>"
        + "<h2>Deal cards</h2>"
        + "<p class='sub'>The same models as the table. Each photo is the image from that merchant's product page.</p>"
        + "<div class='grid' id='deal-cards'>" + "".join(card(p, "card") for p in ranked) + "</div>"
        + sections
        + "<h2>What to expect on Black Friday</h2>"
        "<p>Luggage prices often move from Black Friday through Cyber Monday, sometimes more than once. "
        "Open the merchant page that day and use the price printed there. "
        "A compare-at on a product page is the merchant's own reference price, not a holiday rate this site promises. "
        "Check the size, the model name, and the return window before you buy. "
        "This page does not estimate a weekend percent off.</p>"
        + faq_html(faqs)
    )
    title = "Black Friday Luggage Deals 2026"
    desc = "Black Friday 2026 is November 27. Luggage deals ranked by the compare-at gap already stored, with Horizn prices kept in euros."
    page(
        "black-friday-luggage-deals",
        title,
        desc,
        body,
        [crumb_ld, faq_ld(faqs)],
        crumbs_html=crumb_html,
    )
    print(f"black friday: {len(ranked)} priced gaps, {linked} model links")


def hubs():
    best_index_links = []
    def remember(slug, title):
        best_index_links.append((slug, title))

    carry_ids = [
        "travelpro-maxlite-5-carry-on-rollaboard",
        "travelpro-maxlite-5-compact-carry-on-spinner",
        "travelpro-maxlite-5-carry-on-spinner",
        "travelpro-maxlite-5-international-carry-on-spinner",
        "level8-luminous-carry-on-20",
        "level8-road-runner-carry-on-20",
        "travelpro-crew-classic-carry-on-rollaboard",
        "level8-hegent-carry-on-20",
        "travelpro-crew-classic-carry-on-spinner",
        "level8-voyageur-carry-on-20",
        "travelpro-platinum-elite-compact-hardside-spinner",
        "travelpro-platinum-elite-carry-on-hardside-spinner",
        "travelpro-platinum-elite-carry-on-spinner",
        "horizn-h5-essential",
        "horizn-h5-pro",
        "horizn-m5-pro",
    ]
    remember("best-carry-on-luggage", "Best carry-on luggage")
    best_page(
        "best-carry-on-luggage",
        "Best carry-on luggage",
        "Carry-on luggage with a price copied from Travelpro, LEVEL8, or Horizn Studios. Dollar prices are sorted before Horizn's euro prices. Not a lab ranking.",
        "These are carry-on models whose price we could read on the maker's page. The order is the listed price, low to high inside each currency. It is not a score from a test.",
        sort_price([BY_ID[i] for i in carry_ids]),
    )
    checked_ids = [
        "travelpro-maxlite-5-medium-check-in-spinner",
        "level8-luminous-checked-24",
        "travelpro-maxlite-5-large-check-in-spinner",
        "travelpro-crew-classic-medium-check-in-spinner",
        "travelpro-crew-classic-large-check-in-spinner",
        "level8-voyageur-checked-28",
        "travelpro-platinum-elite-medium-hardside-spinner",
        "travelpro-platinum-elite-large-hardside-spinner",
        "travelpro-platinum-elite-medium-check-in-spinner",
        "travelpro-platinum-elite-large-check-in-spinner",
        "horizn-h6-essential",
        "horizn-h7-pro",
    ]
    remember("best-checked-luggage", "Best checked luggage")
    best_page(
        "best-checked-luggage",
        "Best checked luggage",
        "Checked luggage with a price copied from Travelpro, LEVEL8, or Horizn Studios. Sorted by the listed price inside each currency, not by a test score.",
        "Checked suitcases we could price from the maker's page. Dollar listings come first. Horizn Studios prices stay in euros.",
        sort_price([BY_ID[i] for i in checked_ids]),
    )
    under = [
        p for p in PRODUCTS
        if p["role"] == "affiliate" and p["category"] in ("carry-on", "checked", "underseat")
        and resolved_currency(p) == "USD" and resolved_price(p) is not None and resolved_price(p) < 200
    ]
    remember("best-luggage-under-200", "Best luggage under $200")
    best_page(
        "best-luggage-under-200",
        "Best luggage under $200",
        "Suitcases and underseat bags whose dollar price on the maker's page was under $200. Packing cubes are on their own page. Euro prices are not converted.",
        "Included when the price we read was in US dollars and under 200. Horizn Studios prices are in euros and are not converted into this list. Packing cubes are listed with accessories instead.",
        sort_price(under),
    )
    underseat = [p for p in PRODUCTS if p["category"] == "underseat" and p.get("url")]
    remember("best-underseat-bags", "Best underseat bags")
    best_page(
        "best-underseat-bags",
        "Best underseat bags",
        "Underseat totes and rolling underseat bags from Travelpro, with the price and size copied from each product page.",
        "Travelpro underseat bags we could price. Airline personal-item limits differ, so compare the listed overall size with the airline's current rule.",
        sort_price(underseat),
    )
    cubes = [p for p in PRODUCTS if p["category"] == "packing-cube"]
    remember("packing-cubes", "Packing cubes")
    best_page(
        "packing-cubes",
        "Packing cubes",
        "Packing cube sets sold by Travelpro and LEVEL8, with the price copied from each product page. Dimensions appear only when that page listed them.",
        "Travelpro Essentials and LEVEL8 packing-cube sets. The price is the one on the product page. A set without published measurements does not get a guessed size.",
        sort_price(cubes),
    )
    packs = [p for p in PRODUCTS if p["category"] == "backpack" and p.get("url")]
    remember("travel-backpacks", "Travel backpacks")
    best_page(
        "travel-backpacks",
        "Travel backpacks",
        "Travel and laptop backpacks from Travelpro and Stuart & Lau, with listed prices and the measurements each product page published.",
        "Backpacks those merchants sell, priced from their own pages. This is not a comfort ranking.",
        sort_price(packs),
    )
    alt_ids = [
        "travelpro-maxlite-5-carry-on-spinner",
        "level8-luminous-carry-on-20",
        "level8-voyageur-carry-on-20",
        "travelpro-platinum-elite-carry-on-spinner",
        "away-the-carry-on",
        "away-the-bigger-carry-on",
        "monos-carry-on-pro",
        "beis-carry-on-roller",
        "calpak-hue-carry-on",
        "briggs-riley-baseline-essential-22",
    ]
    remember("away-alternatives", "Away alternatives")
    best_page(
        "away-alternatives",
        "Away alternatives",
        "Away The Carry-On in Jet Black was $275. This page lines it up with priced Travelpro and LEVEL8 carry-ons, plus Monos, Béis, Calpak, and Briggs & Riley.",
        "Away The Carry-On in Jet Black was listed at $275, and The Bigger Carry-On in Jet Black at $295, on Away's own pages. Samsonite Freeform and Tumi are not listed because we do not have a verified product page or price for them.",
        [BY_ID[i] for i in alt_ids],
    )

    use_sid("best", "index")
    links_html = "".join(f"<a href='{site_href('best/'+slug)}'>{e(title)}</a>" for slug, title in best_index_links)
    links_html += f"<a href='{site_href('vs/travelpro-platinum-elite-vs-away')}'>Travelpro vs Away</a>"
    links_html += f"<a href='{site_href('vs/level8-voyageur-vs-away')}'>LEVEL8 vs Away</a>"
    links_html += f"<a href='{site_href('guides/carry-on-size-rules')}'>Carry-on size rules by airline</a>"
    crumb_html, crumb_ld = crumbs([(site_href(""), "Deals"), (None, "Best of")])
    page(
        "best",
        "Best of luggage guides",
        "Carry-on, checked, under-$200, underseat, packing cube, backpack, and Away-alternative guides built from prices we read on merchant pages.",
        f"<h1>Best of</h1><p>Guides sort checked prices. They do not award test scores.</p><div class='chips'>{links_html}</div>",
        [crumb_ld],
        crumbs_html=crumb_html,
    )

    vs_page(
        "travelpro-platinum-elite-vs-away",
        "Travelpro Platinum Elite vs Away The Carry-On",
        "travelpro-platinum-elite-carry-on-spinner",
        "away-the-carry-on",
        "Travelpro lists the Platinum Elite carry-on spinner at $390 with overall size 23.5 x 14.5 x 9 in. Away lists The Carry-On in Jet Black at $275. Away's description we read did not include exterior inches, so that cell stays blank.",
    )
    vs_page(
        "level8-voyageur-vs-away",
        "LEVEL8 Voyageur vs Away The Carry-On",
        "level8-voyageur-carry-on-20",
        "away-the-carry-on",
        "LEVEL8 lists the Voyageur Carry-On 20 inch at $259.99, overall 15.1 x 9.8 x 21.3 in including handle and wheels. Away lists The Carry-On in Jet Black at $275 without exterior inches on the description we read.",
    )

    gift_page(
        "graduation-travel-gifts",
        "Graduation travel gifts",
        "Graduation travel gifts with a price from Travelpro, LEVEL8, or Stuart & Lau: a carry-on, an underseat tote, backpacks, and packing cubes.",
        "A short list for a graduate who is about to travel. Each price is the one on the merchant page. This is not a ranking of what graduates prefer.",
        [
            "level8-luminous-carry-on-20",
            "travelpro-maxlite-5-carry-on-spinner",
            "travelpro-crew-classic-underseat-tote",
            "travelpro-essentials-sparepack-backpack",
            "stuart-crosby-backpack",
            "travelpro-essentials-packing-cubes-sml",
        ],
    )
    gift_page(
        "holiday-travel-gifts",
        "Holiday travel gifts",
        "Holiday travel gifts with checked prices: a Platinum Elite carry-on, a Voyageur carry-on, a weekender, a duffel, packing cubes, and an H5 cabin case in euros.",
        "Holiday shopping list of travel bags we could price. Horizn Studios is shown in euros because that is the shop currency. Nothing here is marked as a tested best gift.",
        [
            "travelpro-platinum-elite-carry-on-spinner",
            "level8-voyageur-carry-on-20",
            "stuart-monaco-weekender",
            "stuart-tabitomo-duffel",
            "level8-packing-cubes-4",
            "horizn-h5-essential",
        ],
    )
    use_sid("gifts", "index")
    gift_html, gift_ld = crumbs([(site_href(""), "Deals"), (None, "Gifts")])
    page(
        "gifts",
        "Travel gift guides",
        "Graduation and holiday travel gift pages. Each pick has a price copied from the merchant product page, and the button opens that page.",
        "<h1>Travel gift guides</h1><div class='chips'>"
        f"<a href='{site_href('gifts/graduation-travel-gifts')}'>Graduation travel gifts</a>"
        f"<a href='{site_href('gifts/holiday-travel-gifts')}'>Holiday travel gifts</a></div>",
        [gift_ld],
        crumbs_html=gift_html,
    )


def brand_pages():
    groups = {}
    for p in PRODUCTS:
        groups.setdefault(p["merchant"], []).append(p)
    chips = []
    for key, rows in groups.items():
        merchant = MERCHANTS[key]
        use_sid("brand", key)
        rows = [p for p in rows if listed(p)]
        rows = sorted(rows, key=lambda p: (p["category"], resolved_price(p) or 10**9))
        crumb_html, crumb_ld = crumbs([(site_href(""), "Deals"), (site_href("brands"), "Brands"), (None, merchant["name"])])
        if rows:
            note = f"Prices checked {checked_label({'checked': CHECKED})}."
            body = f"<h1>{e(merchant['name'])}</h1><p>{e(note)}</p><div class='grid'>" + "".join(card(p) for p in rows) + "</div>"
            desc = f"{merchant['name']} luggage on {NAME}. Prices checked {checked_label({'checked': CHECKED})}, copied from the maker's product page."
        else:
            body = f"<h1>{e(merchant['name'])}</h1><p>We do not have a verified product page or a listed price for {e(merchant['name'])} yet.</p>"
            desc = f"{merchant['name']} on {NAME}. We do not have a verified product page or a listed price for this brand yet."
        page(f"brands/{key}", f"{merchant['name']} luggage", desc[:170], body, [crumb_ld], crumbs_html=crumb_html)
        chips.append((key, merchant["name"]))
    use_sid("brand", "index")
    crumb_html, crumb_ld = crumbs([(site_href(""), "Deals"), (None, "Brands")])
    links_html = "".join(f"<a href='{site_href('brands/'+key)}'>{e(label)}</a>" for key, label in chips)
    page("brands", "Luggage brands", "Brand pages for Travelpro, LEVEL8, Horizn Studios, and Stuart & Lau, plus Away, Monos, Béis, Calpak, Briggs & Riley, Samsonite, and Tumi.", f"<h1>Brands</h1><div class='chips'>{links_html}</div>", [crumb_ld], crumbs_html=crumb_html)


def category_indexes():
    labels = {
        "carry-on": ("Carry-on luggage", "Carry-on suitcases with a product page. Prices are shown only when we read them on that page."),
        "checked": ("Checked luggage", "Checked suitcases with a product page. Prices are shown only when we read them on that page."),
        "underseat": ("Underseat bags", "Underseat totes and rolling underseat bags with a listed price from Travelpro."),
    }
    for slug, (title, intro) in labels.items():
        rows = [p for p in PRODUCTS if p["category"] == slug and listed(p)]
        rows = sort_price(rows)
        category_page(slug, title, intro, intro, rows)
    accessories = [p for p in PRODUCTS if p["category"] in ("packing-cube", "backpack", "weekender", "duffel")]
    category_page(
        "accessories",
        "Travel accessories",
        "Packing cubes, travel backpacks, a weekender, and a duffel from Travelpro, LEVEL8, and Stuart & Lau, with prices from their product pages.",
        "Accessories those merchants sell. Suitcases stay on the carry-on and checked pages.",
        sort_price(accessories),
    )


def write_meta():
    today = CHECKED
    urls = []
    seen = set()
    for url in PAGES:
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    origin = f"{BASE}{PREFIX}"
    sm_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in urls:
        if not url.startswith("https://") or not url.startswith(origin):
            raise SystemExit(f"sitemap URL is not on the site origin: {url}")
        # XML escaping only. html.escape also rewrites quotes, which a <loc> must not contain.
        loc = (url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        sm_lines.append("  <url>")
        sm_lines.append(f"    <loc>{loc}</loc>")
        sm_lines.append(f"    <lastmod>{today}</lastmod>")
        sm_lines.append("  </url>")
    sm_lines.append("</urlset>")
    sm_lines.append("")
    with open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(sm_lines))
    sitemap_url = origin + "/sitemap.xml"
    robots = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {sitemap_url}\n"
    )
    with open(os.path.join(OUT, "robots.txt"), "w", encoding="utf-8") as handle:
        handle.write(robots)
    lines = [f"# {NAME}", f"# Owned by {OWNER}", f"# Prices checked {today}", ""]
    for url in urls:
        lines.append(url)
    with open(os.path.join(OUT, "llms.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    items = []
    for title, url, desc in FEED:
        items.append(
            f"<item><title>{e(title)}</title><link>{e(url)}</link><guid>{e(url)}</guid><description>{e(desc)}</description></item>"
        )
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rss version="2.0"><channel><title>{e(NAME)}</title><link>{e(abs_url(""))}</link>'
        f"<description>Checked luggage prices</description>{''.join(items)}</channel></rss>\n"
    )
    with open(os.path.join(OUT, "feed.xml"), "w", encoding="utf-8") as handle:
        handle.write(feed)
    with open(os.path.join(OUT, ".nojekyll"), "w", encoding="utf-8") as handle:
        handle.write("")
    use_sid("404", "")
    page(
        "404.html",
        "Page not found",
        "That page is not on LuggageDealsDaily.",
        f"<h1>Page not found</h1><p><a href='{site_href('')}'>Back to today's deals</a></p>",
        index=False,
    )


def audit():
    banned = ("anrdoezrs.net", "jdoqocy.com", "tkqlhce.com", "dpbolvw.net", "kqzyfj.com", "emjcd.com", "awin1.com", "linksynergy.com", "amazon.", "ebay.com", "walmart.com", "nordstromrack.com", "sephora.com")
    deal_pages = 0
    for dirpath, _, files in os.walk(OUT):
        for fn in files:
            if not fn.endswith(".html"):
                continue
            text = open(os.path.join(dirpath, fn), encoding="utf-8").read()
            low = text.lower()
            for host in banned:
                if host in low:
                    raise SystemExit(f"{fn} contains {host}")
            if "aggregaterating" in low or "reviewcount" in low:
                raise SystemExit(f"{fn} has a rating schema")
            if fn == "index.html" and "luggage" in dirpath:
                pass
            rel = os.path.relpath(os.path.join(dirpath, fn), OUT)
            if rel.startswith("luggage" + os.sep) and fn == "index.html":
                deal_pages += 1
                lead_at = text.find("lead-offer")
                img_at = text.find("<img")
                if lead_at < 0:
                    raise SystemExit(f"{rel}: missing lead offer")
                if img_at >= 0 and img_at < lead_at:
                    raise SystemExit(f"{rel}: photo is above the price")
                if "FAQPage" not in text:
                    raise SystemExit(f"{rel}: missing FAQPage")
                if "sid=" in text.split("data-sid", 1)[-1] and "cj_click" in text:
                    pass
                # Plain buttons must not carry a sid query.
                for href in re.findall(r'href="(https?://[^"]+)"', text):
                    if "sid=" in href:
                        raise SystemExit(f"{rel}: sid query on {href}")
                    if links.is_tracking_url(href) or links.is_banned_url(href):
                        raise SystemExit(f"{rel}: bad outbound {href}")
    if deal_pages < 30:
        raise SystemExit(f"only {deal_pages} deal pages")
    sitemap = open(os.path.join(OUT, "sitemap.xml"), encoding="utf-8").read()
    if f"{BASE}{PREFIX}/luggage/" not in sitemap:
        raise SystemExit("sitemap missing luggage URLs")
    if "404" in sitemap:
        raise SystemExit("404 is in the sitemap")
    bf_loc = f"{BASE}{PREFIX}/black-friday-luggage-deals/"
    if f"<loc>{bf_loc}</loc>" not in sitemap:
        raise SystemExit("sitemap missing the Black Friday page")
    import xml.etree.ElementTree as ET
    root = ET.fromstring(sitemap)
    if root.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":
        raise SystemExit(f"sitemap root is {root.tag}")
    locs = [node.text or "" for node in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    if any(not loc.startswith(f"{BASE}{PREFIX}/") and loc != f"{BASE}{PREFIX}/" for loc in locs):
        raise SystemExit("sitemap has a URL outside the site origin")
    robots_txt = open(os.path.join(OUT, "robots.txt"), encoding="utf-8").read()
    if f"Sitemap: {BASE}{PREFIX}/sitemap.xml\n" not in robots_txt:
        raise SystemExit("robots.txt does not point at the sitemap")
    if "Disallow" in robots_txt:
        raise SystemExit("robots.txt disallows a path")
    bf = open(os.path.join(OUT, "black-friday-luggage-deals", "index.html"), encoding="utf-8").read()
    if "FAQPage" not in bf:
        raise SystemExit("black friday page missing FAQPage")
    if "What to expect on Black Friday" not in bf:
        raise SystemExit("black friday page missing the expectations section")
    ranked = deals_with_savings()
    cards = re.findall(r"<article class='card'>(.*?)</article>", bf)
    if len(cards) != len(ranked):
        raise SystemExit(f"black friday cards {len(cards)} != deals {len(ranked)}")
    pictured = 0
    for chunk in cards:
        imgs = re.findall(r"<img\b[^>]*>", chunk)
        if not imgs:
            if chunk.startswith("<img"):
                raise SystemExit("black friday card photo is not the first element")
            continue
        pictured += 1
        if not chunk.startswith("<img "):
            raise SystemExit("black friday card does not start with the photo")
        tag = imgs[0]
        if "loading='lazy'" not in tag or " width='" not in tag or " height='" not in tag or " alt='" not in tag:
            raise SystemExit(f"black friday card image is missing alt, size, or lazy: {tag}")
    tbody = bf.find("<tbody>")
    first_row_end = bf.find("</tr>", tbody)
    first_img = bf.find("<img")
    if tbody < 0 or first_img < 0 or not (tbody < first_img < first_row_end):
        raise SystemExit("black friday first image is not inside the first table row")
    for html_path in (
        os.path.join(dirpath, fn)
        for dirpath, _, files in os.walk(OUT)
        for fn in files
        if fn.endswith(".html")
    ):
        page_html = open(html_path, encoding="utf-8").read()
        for chunk in re.findall(r"<article class='card'>(.*?)</article>", page_html):
            if "<img" in chunk and not chunk.startswith("<img "):
                raise SystemExit(f"card photo is not first in {os.path.relpath(html_path, OUT)}")
    expected = sum(1 for product in ranked if hosted_image(product))
    if pictured != expected:
        raise SystemExit(f"black friday photos {pictured} != hosted images {expected}")
    for src in re.findall(r"<img\b[^>]*\bsrc='([^']+)'", bf):
        if links.is_tracking_url(src):
            raise SystemExit(f"black friday image is a tracking URL: {src}")
        rel = src
        if PREFIX and rel.startswith(PREFIX + "/"):
            rel = rel[len(PREFIX):]
        rel = rel.lstrip("/")
        if not rel.startswith("media/products/") or not os.path.isfile(os.path.join(OUT, rel)):
            raise SystemExit(f"black friday image is not a hosted file: {src}")
    home_html = open(os.path.join(OUT, "index.html"), encoding="utf-8").read()
    if site_href("black-friday-luggage-deals") not in home_html or "nav-bf" not in home_html:
        raise SystemExit("home or nav is missing the Black Friday link")
    if "Lowest checked carry-on" in home_html:
        raise SystemExit("home still duplicates the carry-on grid")
    if "Prices checked" not in home_html:
        raise SystemExit("home is missing the prices-checked date")
    if "nav-burger" not in home_html or "system-ui" not in home_html:
        raise SystemExit("home is missing the menu or the sans font stack")
    about_html = open(os.path.join(OUT, "about", "index.html"), encoding="utf-8").read()
    for needle in ("catalog.json", "feed.price", "5227635", "advertiser", "commission rate"):
        if needle.lower() in about_html.lower():
            raise SystemExit(f"about page still mentions {needle}")
    banned_copy = ("Affiliate application for", "not an affiliate merchant", "Comparison page.")
    for dirpath, _, files in os.walk(OUT):
        for fn in files:
            if not fn.endswith(".html"):
                continue
            text = open(os.path.join(dirpath, fn), encoding="utf-8").read()
            for phrase in banned_copy:
                if phrase in text:
                    raise SystemExit(f"{os.path.relpath(os.path.join(dirpath, fn), OUT)} still says {phrase}")
    for slug in ("samsonite-freeform", "tumi-carry-on"):
        dead = open(os.path.join(OUT, "luggage", slug, "index.html"), encoding="utf-8").read()
        if 'name="robots" content="noindex"' not in dead:
            raise SystemExit(f"{slug} is missing noindex")
        if f"/luggage/{slug}/" in sitemap:
            raise SystemExit(f"{slug} is still in the sitemap")
        for dirpath, _, files in os.walk(OUT):
            for fn in files:
                if not fn.endswith(".html"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), OUT)
                if rel == os.path.join("luggage", slug, "index.html"):
                    continue
                text = open(os.path.join(dirpath, fn), encoding="utf-8").read()
                if f"/luggage/{slug}/" in text and "<article class='card'>" in text and f"luggage/{slug}" in text.split("<article class='card'>", 1)[-1]:
                    pass
                if f"href='{site_href('luggage/'+slug)}'" in text or f'href="{site_href("luggage/"+slug)}"' in text:
                    raise SystemExit(f"{rel} still links to {slug}")
    if "data-label='Listed'" not in bf or "data-label='Compare-at'" not in bf or "data-label='Savings'" not in bf:
        raise SystemExit("black friday table is missing price labels")
    print(f"built {deal_pages} luggage pages, {len(PAGES)} indexable URLs, origin {BASE}{PREFIX}/")


def copy_product_images():
    src = os.path.join(ROOT, "media", "products")
    dst = os.path.join(OUT, "media", "products")
    if not os.path.isdir(src):
        return
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        if name.endswith(".jpg"):
            shutil.copyfile(os.path.join(src, name), os.path.join(dst, name))


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    copy_product_images()
    for product in PRODUCTS:
        render_product(product)
    category_indexes()
    hubs()
    airline_page()
    brand_pages()
    static_pages()
    home()
    black_friday_page()
    write_meta()
    audit()


if __name__ == "__main__":
    main()
