# Amazon Rating Verifier

Web version of the CLI script: search Amazon, filter to 4.3+ stars with
200+ reviews, cross-check the rating on Best Buy and Google Shopping
(SerpAPI), and flag products where Amazon's rating is more than 0.6
stars higher than the other sources.

## Run locally

```bash
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

The CLI still works too:

```bash
python finder.py "wireless earbuds" --max-price 50
```

## Environment variables (required before a search will work)

- `AMAZON_ACCESS_KEY` — Amazon Product Advertising API access key
- `AMAZON_SECRET_KEY` — Amazon Product Advertising API secret key
- `AMAZON_PARTNER_TAG` — Amazon Associates partner tag
- `BESTBUY_API_KEY` — optional; without it, Best Buy is skipped
- `SERPAPI_KEY` — optional; without it, Google Shopping is skipped

Without Amazon credentials the app loads but a search returns a
configuration error explaining exactly what is missing. It does not
fall back to scraping Amazon, and it never prints or stores a key.

On Render (free tier, same pattern as amazon-five-finder):

- Build: `pip install -r requirements.txt`
- Start: `gunicorn --timeout 180 app:app`
- Health check: `/api/status`
- Set the env vars above in the Render dashboard. Amazon PAAPI access
  requires an approved Amazon Associates account; a SerpAPI key alone
  does not unlock the Amazon search in this app.
