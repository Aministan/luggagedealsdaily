#!/usr/bin/env python3
"""Sid format and the rule that plain product URLs are not tracking links."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import links

def main():
    sid = links.make_sid("deal", "travelpro-platinum-elite-carry-on-spinner", "cta")
    if sid != "deal-travelpro-platinum-elite-carry-on-spinner-cta":
        raise SystemExit(f"deal sid changed: {sid}")
    if len(sid) > 64:
        raise SystemExit("sid over 64")
    hub = links.make_sid("best", "best-carry-on-luggage", "table", product="level8-voyageur-carry-on-20")
    if not hub.startswith("best-level8-voyageur-carry-on-20-"):
        raise SystemExit(f"product id was cut before the page slug: {hub}")
    if not hub.endswith("-table"):
        raise SystemExit(f"placement was cut: {hub}")
    long_sid = links.make_sid("best", "x" * 80, "cta", product="level8-voyageur-carry-on-20")
    if len(long_sid) > 64 or not long_sid.endswith("-cta"):
        raise SystemExit(f"long sid broke the placement rule: {long_sid}")
    plain = "https://travelpro.com/products/example"
    href = links.outbound_href(plain, sid, cj_click_url=None, affiliate=True)
    if href != plain or "sid=" in href:
        raise SystemExit(f"plain url was rewritten: {href}")
    click = "https://www.anrdoezrs.net/click-101905413-5227635"
    deep = links.outbound_href(plain, sid, cj_click_url=click, affiliate=True)
    if not deep.startswith(click + "?sid=" + sid + "&url="):
        raise SystemExit(f"deep link shape changed: {deep}")
    if links.is_tracking_url(plain):
        raise SystemExit("plain host looked like tracking")
    try:
        links.outbound_href("https://www.amazon.com/dp/test", sid, affiliate=False)
    except ValueError:
        pass
    else:
        raise SystemExit("amazon url was allowed")
    # The deep link is built as text. Nothing in this test requests it.
    print("links ok")

if __name__ == "__main__":
    main()
