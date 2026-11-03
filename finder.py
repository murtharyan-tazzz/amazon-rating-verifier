"""Core product-finding logic, SerpAPI edition.

Rebuilt 2026-11-03 at the user's request so the app works like
amazon-five-finder, without Amazon Product Advertising API keys:
- Amazon listings are searched via SerpAPI's Amazon engine, not the
  official Product Advertising API (which Amazon retired in May 2026)
- Ignore anything rated below MIN_RATING or with fewer than MIN_REVIEWS
- Cross-check the Amazon rating against Best Buy and Google Shopping
  (via SerpAPI) and flag it SUSPICIOUS if Amazon is more than
  MAX_RATING_GAP stars higher than the other sources' average
- UNVERIFIED if no other source has a matching rating

Differences from the original CLI version:
- No argparse / print statements in this module; search_products() is
  callable from Flask and from the CLI wrapper below.
- Missing SerpAPI credentials raise a clear ConfigError instead of
  failing deep inside a client, so the web UI can explain exactly
  what is missing.
- Best Buy / SerpAPI failures return None for that source instead of
  crashing the whole search.
- SerpAPI Amazon results do not always carry a rating or a review
  count; items missing either are skipped, exactly as the original
  code skipped items missing price or review data, so results can
  be thinner than the official API would have returned.
"""

import os
import re
from difflib import SequenceMatcher

import requests

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
BESTBUY_KEY = os.getenv("BESTBUY_API_KEY", "")

MIN_RATING = 4.3
MIN_REVIEWS = 200
MAX_RATING_GAP = 0.6


class ConfigError(Exception):
    """Raised when a required API credential is not configured."""


def serpapi_configured():
    return bool(SERPAPI_KEY)


def config_status():
    """Which keys are set, without ever returning a key value.

    "amazon" here means Amazon listings searched via SerpAPI, not
    the retired official Amazon API.
    """
    return {
        "amazon": serpapi_configured(),
        "bestbuy": bool(BESTBUY_KEY),
        "serpapi": serpapi_configured(),
    }


def _parse_price(value):
    """Extract a float price from SerpAPI's varied price shapes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        if value.get("extracted") is not None:
            try:
                return float(value["extracted"])
            except (TypeError, ValueError):
                pass
        value = value.get("raw") or value.get("value")
        if value is None:
            return None
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _parse_count(value):
    """Extract an int review count from SerpAPI's varied shapes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        value = value.get("count") or value.get("total") or value.get("value")
        if value is None:
            return None
        return _parse_count(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        match = re.search(r"\d+", cleaned)
        if match:
            try:
                return int(match.group(0))
            except ValueError:
                return None
    return None


def search_amazon(keywords, max_price):
    """Search Amazon listings via SerpAPI and return filtered products."""
    if not serpapi_configured():
        raise ConfigError(
            "SerpAPI key is not set. Set SERPAPI_KEY in Render's "
            "environment variables before searching."
        )
    # The Amazon engine uses `k` for the keyword, not `q` — using `q`
    # makes SerpAPI return HTTP 400 for a missing query parameter.
    params = {
        "engine": "amazon",
        "k": keywords,
        "amazon_domain": "amazon.com",
        "api_key": SERPAPI_KEY,
    }
    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        # Never include the request URL in the error: it carries the
        # api_key as a query parameter and would leak it into the UI.
        # Do include SerpAPI's own error string from the response body,
        # which names the actual problem (e.g. invalid key, missing
        # parameter) without containing the key.
        status = exc.response.status_code if exc.response is not None else "unknown"
        detail = ""
        try:
            detail = exc.response.json().get("error", "") if exc.response is not None else ""
        except Exception:
            detail = ""
        raise RuntimeError(
            f"SerpAPI request failed with HTTP {status}"
            + (f": {detail}" if detail else ".")
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("SerpAPI request failed (network error).") from exc
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"SerpAPI error: {data['error']}")
    products = []
    for item in data.get("organic_results", []) or []:
        if len(products) >= 10:
            break
        price = _parse_price(item.get("price"))
        try:
            rating = float(item["rating"]) if item.get("rating") else None
        except (TypeError, ValueError):
            rating = None
        count = _parse_count(
            item.get("ratings") if item.get("ratings") is not None
            else item.get("reviews") if item.get("reviews") is not None
            else item.get("review_count")
        )
        if price is None or rating is None or count is None:
            continue  # skip items missing price or review data
        if price > max_price or rating < MIN_RATING or count < MIN_REVIEWS:
            continue
        products.append({
            "title": item.get("title", ""),
            "price": price,
            "amazon_rating": rating,
            "amazon_reviews": count,
            "url": item.get("link", ""),
        })
    return products


def similar(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def other_rating_bestbuy(title):
    """Look up a matching product on Best Buy and return its rating."""
    if not BESTBUY_KEY:
        return None
    try:
        short = " ".join(title.split()[:5])
        url = f"https://api.bestbuy.com/v1/products((search={short}))"
        params = {"apiKey": BESTBUY_KEY, "format": "json",
                  "show": "name,customerReviewAverage,customerReviewCount",
                  "pageSize": 3}
        data = requests.get(url, params=params, timeout=15).json()
        for p in data.get("products", []):
            if similar(title, p["name"]) > 0.5 and p.get("customerReviewAverage"):
                return float(p["customerReviewAverage"])
    except Exception:
        return None
    return None


def other_rating_google(title):
    """Look up a matching product on Google Shopping via SerpApi."""
    if not SERPAPI_KEY:
        return None
    try:
        params = {"engine": "google_shopping", "q": title, "api_key": SERPAPI_KEY}
        data = requests.get("https://serpapi.com/search", params=params,
                            timeout=20).json()
        for p in data.get("shopping_results", [])[:5]:
            if p.get("rating") and similar(title, p.get("title", "")) > 0.5:
                return float(p["rating"])
    except Exception:
        return None
    return None


def cross_check(product):
    """Compare Amazon's rating with other sources and flag big gaps."""
    others = [r for r in (other_rating_bestbuy(product["title"]),
                          other_rating_google(product["title"])) if r]
    product["other_ratings"] = others
    if not others:
        product["verdict"] = "UNVERIFIED (no match on other sites)"
        product["score"] = product["amazon_rating"] * 0.8
        return product
    avg_other = sum(others) / len(others)
    gap = product["amazon_rating"] - avg_other
    if gap > MAX_RATING_GAP:
        product["verdict"] = f"SUSPICIOUS (Amazon {gap:.1f} stars higher)"
        product["score"] = avg_other * 0.7
    else:
        product["verdict"] = "VERIFIED (ratings agree)"
        product["score"] = (product["amazon_rating"] + avg_other) / 2
    return product


def search_products(query, max_price):
    """Full pipeline: Amazon search -> cross-check -> ranked by score."""
    products = search_amazon(query, max_price)
    checked = [cross_check(p) for p in products]
    checked.sort(key=lambda p: p["score"], reverse=True)
    return checked


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Find the best products.")
    parser.add_argument("query", help="product category, e.g. 'wireless earbuds'")
    parser.add_argument("--max-price", type=float, required=True,
                        help="maximum price in dollars")
    args = parser.parse_args()

    print(f"Searching Amazon for '{args.query}' under ${args.max_price:.2f}...")
    try:
        products = search_products(args.query, args.max_price)
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        raise SystemExit(1)
    if not products:
        print("No products matched your filters. Try raising the max price.")
        raise SystemExit(0)

    print(f"Cross-checking {len(products)} products on other sites...\n")
    for i, p in enumerate(products, 1):
        print(f"   {i}. {p['title'][:80]}")
        print(f"   Price: ${p['price']:.2f}")
        print(f"   Amazon: {p['amazon_rating']} stars "
              f"({p['amazon_reviews']} reviews)")
        print(f"   Other sites: {p['other_ratings'] or 'none found'}")
        print(f"   Verdict: {p['verdict']}")
        print(f"   {p['url']}\n")
