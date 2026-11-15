#!/usr/bin/env python3
"""Outbound link rules for LuggageDealsDaily.

Shopper ids use {pagetype}-{slug}-{placement}. A sid is appended only to a
Commission Junction click URL. Plain merchant pages stay plain: no sid query
and no tracking host.

Scripts may check a URL as text. They must not request a tracking URL.
"""
import re
import urllib.parse

TRACKING_DOMAINS = (
    "anrdoezrs.net",
    "jdoqocy.com",
    "tkqlhce.com",
    "dpbolvw.net",
    "kqzyfj.com",
    "emjcd.com",
    "awin1.com",
    "linksynergy.com",
    "click.linksynergy.com",
)
BANNED_HOSTS = (
    "amazon.com",
    "amazon.co.uk",
    "ebay.com",
    "walmart.com",
    "nordstromrack.com",
    "sephora.com",
)
_CJ_CLICK = re.compile(r"/click-\d+-\d+")
_SID = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,63}$")


def host_of(url):
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return ""


def host_is(host, domain):
    host = (host or "").lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def is_tracking_host(host):
    return any(host_is(host, domain) for domain in TRACKING_DOMAINS)


def is_tracking_url(url):
    if not isinstance(url, str) or not url:
        return False
    if is_tracking_host(host_of(url)):
        return True
    low = url.lower()
    return any(domain in low for domain in TRACKING_DOMAINS)


def is_banned_url(url):
    host = host_of(url)
    if any(host_is(host, domain) for domain in BANNED_HOSTS):
        return True
    low = (url or "").lower()
    return any(domain in low for domain in BANNED_HOSTS)


def sid_part(value):
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-_]+", "-", (value or "").lower())).strip("-")


def make_sid(pagetype, slug, placement, product=""):
    """{pagetype}-{slug}-{placement}, charset [a-z0-9-_], at most 64 characters.

    A hub link can pass the product id. It is placed in front of the page slug
    so a sid that does not fit keeps the product and cuts the page slug.
    Deal pages already use the product id as the page slug.
    The placement is never the part that is cut.
    """
    typ = sid_part(pagetype) or "site"
    page = sid_part(slug)
    place = sid_part(placement) or "link"
    extra = "" if typ == "deal" else sid_part(product)
    slug_bit = "-".join(part for part in (extra, page) if part)
    sid = "-".join(part for part in (typ, slug_bit, place) if part)
    if len(sid) <= 64 and _SID.match(sid):
        return sid
    budget = 64 - len(typ) - len(place) - 2
    cut = ""
    if slug_bit and budget >= 1:
        cut = slug_bit[:budget].rstrip("-")
        if len(slug_bit) > budget and "-" in cut:
            cut = cut.rsplit("-", 1)[0]
        cut = cut.strip("-")
    sid = "-".join(part for part in (typ, cut, place) if part)
    sid = sid[:64].strip("-")
    if not _SID.match(sid):
        raise ValueError(f"sid is not usable: {sid!r}")
    return sid


def add_sid(url, sid):
    """Put sid on a CJ click URL. Leave every other query parameter byte-for-byte."""
    if not _SID.match(sid or ""):
        raise ValueError(f"refusing sid {sid!r}")
    sid_q = urllib.parse.quote(sid, safe="-_")
    frag = ""
    if "#" in url:
        url, frag = url.split("#", 1)
        frag = "#" + frag
    if "?" not in url:
        return url + "?sid=" + sid_q + frag
    base, query = url.split("?", 1)
    parts = [part for part in query.split("&") if part and not part.startswith("sid=")]
    extra = ("&" + "&".join(parts)) if parts else ""
    return base + "?sid=" + sid_q + extra + frag


def cj_deep_link(click_url, merchant_url, sid):
    """Text-only CJ deep link. Does not request the click host."""
    if not click_url:
        return None
    if not is_tracking_url(click_url):
        raise ValueError("cj_click_url is not a CJ click host")
    parsed = urllib.parse.urlparse(click_url)
    if parsed.scheme != "https" or not _CJ_CLICK.search(parsed.path or ""):
        raise ValueError("cj_click_url is not a https CJ /click-id path")
    if is_tracking_url(merchant_url) or is_banned_url(merchant_url):
        raise ValueError("merchant url is not a plain product page")
    base = click_url.split("#", 1)[0]
    linked = add_sid(base, sid)
    path = urllib.parse.urlparse(merchant_url)
    if (path.path or "") in ("", "/") and not path.query:
        return linked
    joiner = "&" if "?" in linked else "?"
    return linked + joiner + "url=" + urllib.parse.quote(merchant_url, safe="")


def outbound_href(product_url, placement_sid, cj_click_url=None, affiliate=False):
    """Href for a button. Plain product URL until a CJ click URL is configured."""
    if not isinstance(product_url, str) or not product_url.startswith("https://"):
        return None
    if is_tracking_url(product_url) or is_banned_url(product_url):
        raise ValueError(f"refusing product url {product_url}")
    if affiliate and cj_click_url:
        return cj_deep_link(cj_click_url, product_url, placement_sid)
    return product_url


def rel_for(href):
    if is_tracking_url(href):
        return "nofollow sponsored noopener"
    return "noopener noreferrer"
