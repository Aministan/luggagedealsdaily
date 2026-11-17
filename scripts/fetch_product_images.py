#!/usr/bin/env python3
"""Save each product's official photo as media/products/{id}.jpg.

Product page URLs come from data/catalog.json. This script requests that
merchant page and the og:image (or the Product JSON-LD image) on it.
It does not request affiliate click hosts, and it does not open /go/, /out/,
/redirect/, or /r/ paths. Prices are left untouched.

Pillow is imported inside the resize function. The site build does not run
this script and does not import Pillow.
"""
import html as html_lib
import io
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import links

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_PATH = os.path.join(ROOT, "data", "catalog.json")
MEDIA_DIR = os.path.join(ROOT, "media", "products")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BLOCKED_SEGMENTS = {"go", "out", "redirect", "r"}
SKIP_NAME = ("logo", "icon", "favicon", "sprite", "badge", "payment", "placeholder", "pixel")
CTX = ssl.create_default_context()


def blocked(url):
    if not isinstance(url, str) or not url:
        return True
    if links.is_tracking_url(url) or links.is_banned_url(url):
        return True
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return True
    segments = [segment.lower() for segment in parts.path.split("/") if segment]
    return any(segment in BLOCKED_SEGMENTS for segment in segments)


class GuardRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if blocked(newurl):
            raise RuntimeError(f"refusing redirect to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(GuardRedirect, urllib.request.HTTPSHandler(context=CTX))


def request_url(url):
    parts = urllib.parse.urlsplit(url.strip())
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def fetch(url, accept):
    if blocked(url):
        raise RuntimeError(f"refusing {url}")
    req = urllib.request.Request(request_url(url), headers={"User-Agent": UA, "Accept": accept})
    with OPENER.open(req, timeout=30) as resp:
        final = resp.geturl()
        if blocked(final):
            raise RuntimeError(f"refusing final {final}")
        data = resp.read(2_500_000)
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        return final, ctype, data


def path_key(url):
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).rstrip("/").lower()
    return path


def attr(tag, name):
    match = re.search(rf"""\b{name}\s*=\s*(['"])(.*?)\1""", tag, flags=re.I | re.S)
    if not match:
        return ""
    return html_lib.unescape(match.group(2)).strip()


def meta_images(page):
    found = []
    for tag in re.findall(r"<meta\b[^>]*>", page, flags=re.I):
        prop = (attr(tag, "property") or attr(tag, "name")).lower()
        if prop in ("og:image", "og:image:secure_url", "twitter:image"):
            content = attr(tag, "content")
            if content:
                found.append((prop, content))
    return found


def jsonld_images(page):
    images = []
    for raw in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        flags=re.I | re.S,
    ):
        try:
            data = json.loads(html_lib.unescape(raw.strip()))
        except json.JSONDecodeError:
            continue
        images.extend(product_images(data))
    return images


def product_images(node):
    found = []
    if isinstance(node, list):
        for item in node:
            found.extend(product_images(item))
        return found
    if not isinstance(node, dict):
        return found
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    if "Product" in kinds and node.get("image"):
        found.extend(flatten_image(node["image"]))
    for value in node.values():
        if isinstance(value, (dict, list)):
            found.extend(product_images(value))
    return found


def flatten_image(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(flatten_image(item))
        return out
    if isinstance(value, dict):
        url = value.get("url") or value.get("contentUrl") or value.get("@id")
        return [url] if isinstance(url, str) else []
    return []


def host_ok(image_url, page_url):
    image_host = links.host_of(image_url)
    page_host = links.host_of(page_url)
    if not image_host or not page_host:
        return False
    if links.host_is(image_host, page_host) or links.host_is(page_host, image_host):
        return True
    return image_host in ("cdn.shopify.com", "cdn.shopifycdn.net")


def https_image(url, page_url):
    url = urllib.parse.urljoin(page_url, url.strip())
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "http":
        url = urllib.parse.urlunsplit(("https",) + parts[1:])
    if blocked(url) or not host_ok(url, page_url):
        return None
    name = urllib.parse.unquote(parts.path).lower()
    if any(token in name for token in SKIP_NAME):
        return None
    if not re.search(r"\.(jpe?g|png|webp)(?:$|\?)", url, flags=re.I):
        return None
    return url


def choose_image(page, page_url):
    metas = meta_images(page)
    ordered = []
    secure = [url for prop, url in metas if prop == "og:image:secure_url"]
    og = [url for prop, url in metas if prop == "og:image"]
    twitter = [url for prop, url in metas if prop == "twitter:image"]
    for candidate in secure + og + twitter + jsonld_images(page):
        image = https_image(candidate, page_url)
        if image and image not in ordered:
            ordered.append(image)
    return ordered


def save_jpeg(data, dest):
    # Lazy import: a top-level Pillow import has broken a deploy before.
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    image.load()
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        plate = Image.new("RGB", rgba.size, (255, 255, 255))
        plate.paste(rgba, mask=rgba.split()[-1])
        image = plate
    else:
        image = image.convert("RGB")
    width, height = image.size
    if width < 200 or height < 200:
        raise RuntimeError(f"image is only {width}x{height}")
    ratio = width / height
    if ratio > 2.6 or ratio < 0.35:
        raise RuntimeError(f"image ratio {width}x{height} does not look like a product photo")
    if width > 600:
        height = max(1, round(height * 600 / width))
        width = 600
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    image.save(dest, "JPEG", quality=78, optimize=True, progressive=True)
    return width, height


def plain_product_url(product, merchants):
    feed = product.get("feed") or {}
    candidate = feed.get("url") or product.get("url")
    if not candidate:
        return None
    if links.is_tracking_url(candidate) or links.is_banned_url(candidate) or blocked(candidate):
        fallback = product.get("url")
        if feed.get("url") and fallback and not links.is_tracking_url(fallback) and not blocked(fallback):
            candidate = fallback
        else:
            return None
    home = (merchants.get(product["merchant"]) or {}).get("homepage")
    if home:
        home_host = links.host_of(home)
        if home_host and not links.host_is(links.host_of(candidate), home_host):
            return None
    return candidate


def one(product, merchants):
    url = plain_product_url(product, merchants)
    if not url:
        return product["id"], None, "no merchant product URL"
    try:
        final, ctype, body = fetch(url, "text/html,application/xhtml+xml")
    except Exception as exc:
        return product["id"], None, f"page: {exc}"
    if "html" not in ctype and "xml" not in ctype:
        return product["id"], None, f"page content-type {ctype}"
    if path_key(final) != path_key(url):
        return product["id"], None, f"left the product page for {final}"
    page = body.decode("utf-8", "replace")
    errors = []
    for image_url in choose_image(page, final):
        try:
            image_final, image_type, image_bytes = fetch(image_url, "image/avif,image/webp,image/apng,image/*,*/*;q=0.8")
        except Exception as exc:
            errors.append(f"{image_url} ({exc})")
            continue
        if blocked(image_final) or not host_ok(image_final, final):
            errors.append(f"rejected host {image_final}")
            continue
        if image_type and not image_type.startswith("image/"):
            errors.append(f"content-type {image_type}")
            continue
        dest = os.path.join(MEDIA_DIR, product["id"] + ".jpg")
        try:
            width, height = save_jpeg(image_bytes, dest)
        except Exception as exc:
            errors.append(str(exc))
            if os.path.exists(dest):
                os.remove(dest)
            continue
        return product["id"], {
            "image": f"/media/products/{product['id']}.jpg",
            "image_width": width,
            "image_height": height,
            "source": image_final,
        }, None
    detail = "; ".join(errors) if errors else "no og:image or product image"
    return product["id"], None, detail


def main():
    catalog = json.load(open(CATALOG_PATH, encoding="utf-8"))
    merchants = catalog["merchants"]
    products = catalog["products"]
    before = [(p.get("price"), p.get("compare_at"), p.get("url"), p.get("currency")) for p in products]
    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one, product, merchants) for product in products]
        for future in as_completed(futures):
            product_id, saved, error = future.result()
            results[product_id] = (saved, error)
            if saved:
                print(f"ok   {product_id} {saved['image_width']}x{saved['image_height']} {saved['source']}")
            else:
                print(f"skip {product_id}: {error}")
    saved_count = 0
    skipped = []
    for product in products:
        saved, error = results[product["id"]]
        if saved:
            product["image"] = saved["image"]
            product["image_width"] = saved["image_width"]
            product["image_height"] = saved["image_height"]
            saved_count += 1
        else:
            product["image"] = None
            product.pop("image_width", None)
            product.pop("image_height", None)
            skipped.append((product["id"], error))
    after = [(p.get("price"), p.get("compare_at"), p.get("url"), p.get("currency")) for p in products]
    if before != after:
        raise SystemExit("refusing to write catalog: a price or URL changed")
    if saved_count < 40:
        raise SystemExit(f"only saved {saved_count} images; catalog left unchanged")
    with open(CATALOG_PATH, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(catalog, indent=2, ensure_ascii=False))
    print(f"saved {saved_count} images, skipped {len(skipped)}")


if __name__ == "__main__":
    main()
