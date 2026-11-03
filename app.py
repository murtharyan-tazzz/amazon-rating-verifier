"""Flask web app for the Amazon rating cross-checker.

Same rules as finder.py, behind a simple form:
  query + max price -> ranked products with VERIFIED / SUSPICIOUS /
  UNVERIFIED verdicts, Amazon rating + review count, other-site ratings,
  and a link to the Amazon product page.

No search, purchase, or API call happens until the form is submitted.
If Amazon credentials are missing, /api/search returns a plain
configuration error instead of crashing, and /api/status shows which
sources are configured (never the key values).
"""

from flask import Flask, jsonify, render_template, request

from finder import ConfigError, config_status, search_products

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html", status=config_status())


@app.route("/api/status")
def status():
    return jsonify({"configured": config_status()})


@app.route("/api/search", methods=["POST"])
def search():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    try:
        max_price = float(data.get("max_price"))
    except (TypeError, ValueError):
        return jsonify({"error": "Enter a maximum price in dollars."}), 400
    if not query:
        return jsonify({"error": "Enter something to search for."}), 400
    if max_price <= 0:
        return jsonify({"error": "Maximum price must be above $0."}), 400
    try:
        products = search_products(query, max_price)
    except ConfigError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:  # Amazon / network errors surface as text
        return jsonify({"error": f"Search failed: {exc}"}), 502
    return jsonify({
        "query": query,
        "max_price": max_price,
        "filters": {"min_rating": 4.3, "min_reviews": 200,
                    "max_rating_gap": 0.6},
        "products": products,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
