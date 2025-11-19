import os
from typing import List, Dict, Any
import re
import urllib.parse

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup

app = FastAPI(title="Game Finder (Legal Sources)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

@app.get("/")
def read_root():
    return {"message": "Game Finder API running"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Used",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    return response

# -------------------------
# Helpers
# -------------------------

def normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", q).strip()


def limited(items: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    return items[:limit]


# -------------------------
# Source scrapers (legal sources only)
# -------------------------

def search_epic_free_games(query: str) -> Dict[str, Any]:
    url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        elements = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
        hits: List[Dict[str, str]] = []
        for el in elements:
            title = el.get("title", "").strip()
            # Only include items currently free (promotions available)
            promotions = el.get("promotions") or {}
            is_free_now = False
            if promotions:
                upcomings = promotions.get("promotionalOffers") or []
                if upcomings and upcomings[0].get("promotionalOffers"):
                    is_free_now = True
            if title and query.lower() in title.lower() and is_free_now:
                # Build product slug link
                product_slug = None
                key_images = el.get("keyImages") or []
                # Prefer productSlug from offer if available
                product_slug = el.get("productSlug")
                if not product_slug:
                    offer_mappings = el.get("urlSlug")
                    product_slug = offer_mappings
                if product_slug:
                    link = f"https://store.epicgames.com/en-US/p/{product_slug.strip('/')}"
                else:
                    link = "https://store.epicgames.com/free-games"
                hits.append({"title": title, "url": link})
        more_url = "https://store.epicgames.com/en-US/free-games"
        return {"source": "Epic Games Store (Free Now)", "more_url": more_url, "hits": hits, "total_hits": len(hits)}
    except Exception:
        return {"source": "Epic Games Store (Free Now)", "more_url": "https://store.epicgames.com/en-US/free-games", "hits": [], "total_hits": 0}


def search_itch_free(query: str) -> Dict[str, Any]:
    search_url = f"https://itch.io/games/free?q={urllib.parse.quote(query)}"
    hits: List[Dict[str, str]] = []
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".game_cell, .game_list .game_row"):
            title_el = item.select_one(".title, .game_title")
            link_el = item.select_one("a.title, a.game_link, a.thumb_link")
            if not title_el or not link_el:
                continue
            title = title_el.get_text(strip=True)
            href = link_el.get("href")
            if title and href and query.lower() in title.lower():
                hits.append({"title": title, "url": href})
        return {"source": "itch.io (Free)", "more_url": search_url, "hits": hits, "total_hits": len(hits)}
    except Exception:
        return {"source": "itch.io (Free)", "more_url": search_url, "hits": [], "total_hits": 0}


def search_steam_free(query: str) -> Dict[str, Any]:
    # Filter to free-to-play and demos where possible
    search_url = f"https://store.steampowered.com/search/?term={urllib.parse.quote(query)}&price=free"
    hits: List[Dict[str, str]] = []
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.search_result_row"):
            title_el = a.select_one("span.title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = a.get("href")
            if title and href and query.lower() in title.lower():
                hits.append({"title": title, "url": href})
        return {"source": "Steam (Free to Play)", "more_url": search_url, "hits": hits, "total_hits": len(hits)}
    except Exception:
        return {"source": "Steam (Free to Play)", "more_url": search_url, "hits": [], "total_hits": 0}


def search_internet_archive(query: str) -> Dict[str, Any]:
    # Search for legally free/shareware games
    base = "https://archive.org/advancedsearch.php"
    params = {
        "q": f"{query} AND mediatype:(software)",
        "fl[]": ["identifier", "title"],
        "rows": 50,
        "output": "json",
    }
    try:
        r = requests.get(base, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        docs = data.get("response", {}).get("docs", [])
        hits = [{"title": d.get("title", "Untitled"), "url": f"https://archive.org/details/{d.get('identifier')}"} for d in docs if d.get("title") and query.lower() in d.get("title", "").lower()]
        more_url = f"https://archive.org/search.php?query={urllib.parse.quote(query)}&and[]=mediatype%3A%22software%22"
        return {"source": "Internet Archive (Software)", "more_url": more_url, "hits": hits, "total_hits": len(hits)}
    except Exception:
        return {"source": "Internet Archive (Software)", "more_url": f"https://archive.org/search.php?query={urllib.parse.quote(query)}", "hits": [], "total_hits": 0}


@app.get("/api/search")
def search_games(q: str = Query(..., description="Game title to search for")):
    """
    Search legal, safe sources for free versions: Epic weekly free, itch.io freebies, Steam free-to-play,
    and Internet Archive software. Returns grouped hits per source with a few top links and a 'more' URL.
    """
    query = normalize_query(q)
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    sources = [
        search_epic_free_games(query),
        search_itch_free(query),
        search_steam_free(query),
        search_internet_archive(query),
    ]

    # Order: prioritize current giveaways (Epic), then itch, Steam F2P, Archive
    # Filter out empty sources at the end for clarity
    ordered = []
    for src in sources:
        # Trim to a preview subset for UI; full list available via more_url
        src["preview"] = limited(src.get("hits", []), 3)
        ordered.append(src)

    return {"query": query, "sources": ordered}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
