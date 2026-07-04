"""
Hirist.tech scraper — requests + BeautifulSoup (no browser needed).
Hirist specialises in Indian tech jobs, good for React/Node/Full-stack.
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
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.hirist.tech/",
}

KEYWORD_MAP = {
    "MERN Stack Developer Fresher":      "mern stack developer",
    "React Developer 0-1 Years":         "react developer",
    "Junior React Developer":            "react developer",
    "Entry Level Full Stack Developer":  "full stack developer",
    "Junior MERN Developer":             "mern developer",
    "React Node Fresher":                "react node developer",
    "Junior Frontend Developer React":   "react frontend developer",
    "Junior Node.js Developer":          "nodejs developer",
}


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _fetch(keyword):
    kw  = KEYWORD_MAP.get(keyword, keyword.lower())
    url = f"https://www.hirist.tech/jobs/?query={requests.utils.quote(kw)}&experience=0-1"
    jobs = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"    Hirist error [{keyword}]: {e}")
        return jobs

    cards = (
        soup.select(".job-card")
        or soup.select("li.job")
        or soup.select("[class*='job-item']")
        or soup.select("article.job")
        or soup.select(".jobCard")
    )

    for card in cards[:30]:
        try:
            title_el   = (card.select_one("h2 a") or card.select_one("h3 a")
                          or card.select_one(".job-title a") or card.select_one("a[href*='/job/']"))
            company_el = (card.select_one(".company-name") or card.select_one(".company")
                          or card.select_one("[class*='company']"))
            loc_el     = (card.select_one(".location") or card.select_one("[class*='location']"))
            exp_el     = card.select_one(".experience, [class*='exp']")

            title   = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            loc_txt = loc_el.get_text(strip=True) if loc_el else "India"
            exp_txt = exp_el.get_text(strip=True) if exp_el else ""
            href    = title_el.get("href", "") if title_el else ""

            if not title or not href:
                continue
            job_url = href if href.startswith("http") else f"https://www.hirist.tech{href}"
            job_id  = hashlib.md5(job_url.encode()).hexdigest()

            jobs.append({
                "job_id": job_id, "title": title, "company": company,
                "location": loc_txt, "source": "hirist", "job_url": job_url,
                "description": f"{title} at {company}. Experience: {exp_txt}".strip(". "),
                "date_posted": "", "company_website": "",
            })
        except Exception:
            continue

    return jobs


def scrape_hirist():
    config   = load_config()
    keywords = config["search"]["keywords"]
    delay    = config["scraping"].get("delay_between_requests", 3)

    results   = []
    seen_ids  = set()
    seen_kws  = set()

    for keyword in keywords:
        kw = KEYWORD_MAP.get(keyword, keyword.lower())
        if kw in seen_kws:
            continue
        seen_kws.add(kw)

        jobs = _fetch(keyword)
        new  = [j for j in jobs if j["job_id"] not in seen_ids]
        for j in new:
            seen_ids.add(j["job_id"])
            results.append(j)
        if new:
            print(f"  [Hirist] {keyword[:35]}: {len(new)} jobs")
        time.sleep(delay + random.random())

    print(f"  Hirist total: {len(results)} unique jobs")
    return results
