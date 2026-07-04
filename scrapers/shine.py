"""
Shine.com scraper — requests + BeautifulSoup (no Playwright needed).
Shine serves static HTML with __NEXT_DATA__ and embeds job cards in the DOM.
Gets ~20 unique jobs per keyword from the first page.
"""
import hashlib
import re
import time
import random
import yaml
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.7,en;q=0.3",
    "Referer": "https://www.shine.com/",
}

# Patterns to exclude from location field (experience, salary, skills)
_EXP_PAT   = re.compile(r"\d+\s*(to|-)\s*\d+\s*(yr|year|Yr|Year)", re.IGNORECASE)
_SALARY_PAT = re.compile(r"LPA|Lacs|Lac|INR|\$", re.IGNORECASE)


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _extract_location(center_div) -> str:
    if not center_div:
        return "India"
    for part in center_div.stripped_strings:
        part = part.strip()
        if not part or len(part) < 3:
            continue
        if _EXP_PAT.search(part) or _SALARY_PAT.search(part):
            continue
        if re.match(r"^[A-Z][a-zA-Z ,/]+$", part) and len(part) >= 4:
            return part
    return "India"


def _parse_page(html) -> list:
    soup = BeautifulSoup(html, "html.parser")
    seen_hrefs = set()
    jobs = []

    for a in soup.select("a[href*='/jobs/']"):
        href = a.get("href", "")
        if not href or href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        if not href.startswith("http"):
            href = "https://www.shine.com" + href

        # Navigate up: a → h3 → bigCardTopTitle div → bigCardTop div → bigCard div
        h3 = a.find_parent()
        if not h3:
            continue
        title_div = h3.find_parent()
        if not title_div:
            continue

        company_el = title_div.select_one("[class*='TitleName'], [class*='CompName']")
        company    = company_el.get_text(strip=True) if company_el else ""

        card = title_div.find_parent().find_parent()
        center_el = card.select_one("[class*='bigCardCenter']") if card else None
        location  = _extract_location(center_el)

        job_id = hashlib.md5(href.encode()).hexdigest()
        jobs.append({
            "job_id":          job_id,
            "title":           title,
            "company":         company,
            "location":        location,
            "source":          "shine",
            "job_url":         href,
            "description":     "",
            "date_posted":     "",
            "company_website": "",
        })

    return jobs


def _fetch_keyword(keyword: str, delay: float = 3.0) -> list:
    kw_slug = keyword.lower().replace(" ", "-")
    kw_enc  = keyword.replace(" ", "+")
    url = f"https://www.shine.com/job-search/{kw_slug}-jobs/?q={kw_enc}&freshness=7"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return _parse_page(resp.text)
    except Exception as e:
        print(f"    Shine error [{keyword[:30]}]: {e}")
        return []


def scrape_shine():
    config   = load_config()
    keywords = config["search"]["keywords"]
    delay    = config["scraping"].get("delay_between_requests", 3)

    results  = []
    seen_ids = set()

    for kw in keywords:
        jobs = _fetch_keyword(kw, delay)
        new  = [j for j in jobs if j["job_id"] not in seen_ids]
        for j in new:
            seen_ids.add(j["job_id"])
            results.append(j)
        if new:
            print(f"  [Shine] {kw[:35]}: {len(new)} jobs")
        time.sleep(delay + random.random() * 2)

    print(f"  Shine total: {len(results)} unique jobs")
    return results
