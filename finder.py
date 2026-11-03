"""Core product-finding logic, adapted from the CLI script you supplied.

Faithful to the original rules:
- Amazon search via the official Product Advertising API (amazon_paapi)
- Ignore anything rated below MIN_RATING or with fewer than MIN_REVIEWS
- Cross-check the Amazon rating against Best Buy and Google Shopping
  (via SerpAPI) and flag it SUSPICIOUS if Amazon is more than
  MAX_RATING_GAP stars higher than the other sources' average
- UNVERIFIED if no other source has a matching rating

Differences from the CLI version, for the web app:
- No argparse / print statements in this module; search_products() is
  callable from Flask and from the CLI wrapper below.
- Missing Amazon credentials raise a clear ConfigError instead of
  failing deep inside the Amazon client, so the web UI can explain
  exactly what is missing.
- Best Buy / SerpAPI failures return None for that source instead of
  crashing the whole search.
"""

import os
from difflib import SequenceMatcher

import requests

AMAZON_KEY = os.getenv("AMAZON_ACCESS_KEY", "YOUR_KEY")
AMAZON_SECRET = os.getenv("AMAZON_SECRET_KEY", "YOUR_SECRET")
AMAZON_TAG = os.getenv("AMAZON_PARTNER_TAG", "YOUR_TAG")
AMAZON_COUNTRY = "US"

BESTBUY_KEY = os.getenv("BESTBUY_API_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

MIN_RATING = 4.3
MIN_REVIEWS = 200
MAX_RATING_GAP = 0.6


class ConfigError(Exception):
    """Raised when a required API credential is not configured."""


def amazon_configured():
    return all(
        v and not v.startswith("YOUR_")
        for v in (AMAZON_KEY, AMAZON_SECRET, AMAZON_TAG)
    )


def config_status():
    """Which keys are set, without ever returning a key value."""
    return {
        "amazon": amazon_configured(),
        "bestbuy": bool(BESTBUY_KEY),
        "serpapi": bool(SERPAPI_KEY),
    }


def search_amazon(keywords, max_price):
    """Search Amazon via the official API and return filtered products."""
    if not amazon_configured():
        raise ConfigError(
            "Amazon API credentials are not set. Set AMAZON_ACCESS_KEY, "
            "AMAZON_SECRET_KEY and AMAZON_PARTNER_TAG before searching."
        )
    from amazon_paapi import AmazonApi

    amazon = AmazonApi(AMAZON_KEY, AMAZON_SECRET, AMAZON_TAG, AMAZON_COUNTRY)
    results = amazon.search_items(
        keywords=keywords,
        max_price=int(max_price * 100),  # API wants cents
        item_count=10,
    )
    products = []
    for item in results.items:
        try:
            price = item.offers.listings[0].price.amount
            rating = item.customer_reviews.star_rating.value
            count = item.customer_reviews.count
        except (AttributeError, IndexError, TypeError):
            continue  # skip items missing price or review data
        if price > max_price or rating < MIN_RATING or count < MIN_REVIEWS:
            continue
        products.append({
            "title": item.item_info.title.display_value,
            "price": price,
            "amazon_rating": rating,
            "amazon_reviews": count,
            "url": item.detail_page_url,
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
        print(f"{i}. {p['title'][:80]}")
        print(f"   Price: ${p['price']:.2f}")
        print(f"   Amazon: {p['amazon_rating']} stars "
              f"({p['amazon_reviews']} reviews)")
        print(f"   Other sites: {p['other_ratings'] or 'none found'}")
        print(f"   Verdict: {p['verdict']}")
        print(f"   {p['url']}\n")
