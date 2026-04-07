"""
LeadFinder v0 — Streamlit app
------------------------------
Finds highly-rated local businesses without a website on Google.

Deploy to Streamlit Community Cloud (free):
  1. Push this file + requirements.txt to a GitHub repo
  2. Go to https://streamlit.io/cloud → "New app" → connect your repo
  3. In app Settings → Secrets, add:
        GOOGLE_PLACES_KEY = "your_key_here"
  4. Deploy.

Run locally:
  pip install streamlit requests pandas
  export GOOGLE_PLACES_KEY=your_key_here   # or use .streamlit/secrets.toml
  streamlit run app.py
"""

import time
import requests
import pandas as pd
import streamlit as st

# ====== CONFIG ======
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

DEFAULT_CATEGORIES = [
    "restaurants", "bakeries", "cafes", "hair salons", "barber shops",
    "auto repair", "plumbers", "electricians", "landscapers",
    "cleaning services", "tailors", "dry cleaners", "pet groomers",
    "tattoo parlors", "yoga studios", "florists", "bike shops",
]

# ====== API LAYER ======
def search_category(api_key: str, category: str, city: str, max_pages: int = 3) -> list[dict]:
    """Run a Text Search for one category in one city. Returns up to 60 places."""
    results = []
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.nationalPhoneNumber,places.rating,places.userRatingCount,"
            "places.websiteUri,places.googleMapsUri,nextPageToken"
        ),
    }
    body = {"textQuery": f"{category} in {city}", "pageSize": 20}

    for page in range(max_pages):
        resp = requests.post(TEXT_SEARCH_URL, headers=headers, json=body, timeout=30)
        if resp.status_code != 200:
            st.warning(f"API error on '{category}': {resp.status_code} — {resp.text[:150]}")
            break

        data = resp.json()
        for p in data.get("places", []):
            results.append({
                "name": p.get("displayName", {}).get("text", ""),
                "category": category,
                "address": p.get("formattedAddress", ""),
                "phone": p.get("nationalPhoneNumber", ""),
                "rating": p.get("rating", 0.0),
                "review_count": p.get("userRatingCount", 0),
                "website": p.get("websiteUri", ""),
                "maps_url": p.get("googleMapsUri", ""),
                "place_id": p.get("id", ""),
            })

        next_token = data.get("nextPageToken")
        if not next_token:
            break
        time.sleep(2)  # Google requires ~2s before pageToken is valid
        body = {"textQuery": f"{category} in {city}", "pageSize": 20, "pageToken": next_token}

    return results


def filter_and_dedupe(rows: list[dict], min_rating: float, min_reviews: int) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["place_id"])
    df = df[
        (df["website"].fillna("") == "")
        & (df["rating"] >= min_rating)
        & (df["review_count"] >= min_reviews)
    ]
    return df.sort_values(["rating", "review_count"], ascending=False).reset_index(drop=True)


# ====== UI ======
st.set_page_config(page_title="LeadFinder — No-Website Business Leads", page_icon="🎯", layout="wide")

st.title("🎯 LeadFinder")
st.caption("Find highly-rated local businesses that don't have a website. Perfect for web designers, SEO agencies, and freelancers.")

# Get API key from Streamlit secrets or env
try:
    api_key = st.secrets["GOOGLE_PLACES_KEY"]
except (KeyError, FileNotFoundError):
    import os
    api_key = os.environ.get("GOOGLE_PLACES_KEY", "")

if not api_key:
    st.error("No Google Places API key found. Set `GOOGLE_PLACES_KEY` in Streamlit secrets or environment.")
    st.stop()

with st.sidebar:
    st.header("Search settings")
    city = st.text_input("City", value="Vaughan, Ontario, Canada", help="Be specific: include state/province and country.")
    categories = st.multiselect(
        "Business categories",
        options=DEFAULT_CATEGORIES,
        default=["bakeries", "hair salons", "auto repair"],
        help="Each category uses ~1 API search ($0.03 cost to operator).",
    )
    custom = st.text_input("Add custom category", placeholder="e.g. 'wedding photographers'")
    if custom:
        categories = list(set(categories + [custom]))

    st.divider()
    min_rating = st.slider("Minimum rating", 3.0, 5.0, 4.3, 0.1)
    min_reviews = st.number_input("Minimum review count", 0, 1000, 20)

    run = st.button("🔍 Find leads", type="primary", use_container_width=True)

if not run:
    st.info("👈 Pick a city and categories in the sidebar, then click **Find leads**.")
    st.markdown("""
    ### How it works
    1. We search Google Maps for businesses in each category you pick
    2. We filter for highly-rated ones (good reviews = real businesses worth pitching)
    3. We keep only those with **no website listed** on Google
    4. You get a downloadable CSV with name, phone, address, rating, and Maps link

    ### Tips
    - **Smaller categories convert better.** "Tailors" and "pet groomers" have fewer chains.
    - **Always verify before cold-outreach.** Some businesses have sites Google doesn't know about.
    - **Combine with phone outreach.** No-website businesses rarely respond to email.
    """)
    st.stop()

if not categories:
    st.error("Pick at least one category.")
    st.stop()

# Run search
all_rows = []
progress = st.progress(0.0, text="Searching...")
for i, cat in enumerate(categories):
    progress.progress((i) / len(categories), text=f"Searching: {cat}")
    try:
        rows = search_category(api_key, cat, city)
        all_rows.extend(rows)
    except Exception as e:
        st.warning(f"Failed on '{cat}': {e}")
progress.progress(1.0, text="Done")

st.success(f"Searched {len(categories)} categories — {len(all_rows)} raw results.")

leads = filter_and_dedupe(all_rows, min_rating, min_reviews)

col1, col2, col3 = st.columns(3)
col1.metric("Total found", len(all_rows))
col2.metric("After dedupe", all_rows and len(set(r["place_id"] for r in all_rows)) or 0)
col3.metric("Qualified leads", len(leads))

if leads.empty:
    st.warning("No qualifying leads. Try lowering the rating threshold or adding more categories.")
    st.stop()

st.subheader("Your leads")
st.dataframe(
    leads[["name", "category", "rating", "review_count", "phone", "address", "maps_url"]],
    use_container_width=True,
    column_config={
        "maps_url": st.column_config.LinkColumn("Maps", display_text="View"),
        "rating": st.column_config.NumberColumn("⭐", format="%.1f"),
    },
    hide_index=True,
)

csv = leads.to_csv(index=False).encode("utf-8")
st.download_button(
    "📥 Download CSV",
    data=csv,
    file_name=f"leads_{city.split(',')[0].strip().lower().replace(' ', '_')}.csv",
    mime="text/csv",
    type="primary",
)
