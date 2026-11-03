# Amazon Rating Verifier

Web app: search Amazon listings, filter to 4.3+ stars with
200+ reviews, cross-check the rating on Best Buy and Google Shopping
(SerpAPI), and flag products where Amazon's rating is more than 0.6
stars higher than the other sources.

## SerpAPI edition (2026-11-03)

This app no longer uses Amazon's official Product Advertising API,
which Amazon retired in May 2026 and which required an approved
Amazon Associates account. Amazon listings are now searched through
SerpAPI, the same approach as amazon-five-finder. No Amazon Access
Key, Secret Key, or Partner Tag is used or needed.

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

## Environment variables

- `SERPAPI_KEY` — **required** before a search will work; powers both
  the Amazon listing search and the Google Shopping cross-check
- `BESTBUY_API_KEY` — optional; without it, Best Buy is skipped

Without a SerpAPI key the app loads but a search returns a
configuration error explaining exactly what is missing. It does not
fall back to scraping Amazon, and it never prints or stores a key.

On Render (free tier, same pattern as amazon-five-finder):

- Build: `pip install -r requirements.txt`
- Start: `gunicorn --timeout 180 app:app`
- Health check: `/api/status`
- Set `SERPAPI_KEY` in the Render dashboard for this service.
  Keys do not carry over from amazon-five-finder; each Render
  service has its own environment variables.

Note: SerpAPI Amazon results do not always include a rating or a
review count, and items missing either are skipped, so results can
be thinner than the official API would have returned.
