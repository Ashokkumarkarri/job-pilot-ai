"""
Internshala scraper — requests + BeautifulSoup (no browser needed).
Targets /jobs/ listings only (not internships — user wants full-time roles).
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.7,en;q=0.3",
    "Referer": "https://internshala.com/",
}

KEYWORD_SLUGS = {
    "MERN Stack Developer Fresher":      "mern-stack-development",
    "React Developer 0-1 Years":         "reactjs",
    "Junior React Developer":            "reactjs",
    "Entry Level Full Stack Developer":  "full-stack-development",
    "Junior MERN Developer":             "mern-stack-development",
    "React Node Fresher":                "nodejs",
    "Junior Frontend Developer React":   "frontend-development",
    "Junior Node.js Developer":          "nodejs",
}


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _fetch_jobs(slug):
    url  = f"https://internshala.com/jobs/{slug}-jobs/"
    jobs = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"    Internshala error [{slug}]: {e}")
        return jobs

    # Try multiple card selectors in order
    cards = (
        soup.select(".individual_internship")
        or soup.select(".job-listing-container")
        or soup.select("[id^='job_']")
    )

    for card in cards[:30]:
        try:
            # Title — Internshala uses a.job-title-href
            title_el = (card.select_one("a.job-title-href")
                        or card.select_one("h2.job-internship-name a")
                        or card.select_one(".profile a")
                        or card.select_one("h3.heading_4_5 a"))
            # Company
            company_el = (card.select_one("p.company-name")
                          or card.select_one(".company_name")
                          or card.select_one("a.company-name"))
            # Location — Internshala puts location as a link with empty href or .location_link
            loc_el = (card.select_one("p.locations a")
                      or card.select_one(".location_link")
                      or card.select_one(".locations"))
            # Use title element href as job URL
            link_el = title_el

            title   = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            loc_txt = loc_el.get_text(strip=True) if loc_el else "India"
            href    = link_el.get("href", "") if link_el else ""

            if not title or not href:
                continue

            job_url = href if href.startswith("http") else f"https://internshala.com{href}"
            job_id  = hashlib.md5(job_url.encode()).hexdigest()

            # Extract salary / stipend if present (nice to have)
            sal_el  = card.select_one(".stipend, .salary")
            salary  = sal_el.get_text(strip=True) if sal_el else ""

            # Date posted
            date_el = card.select_one(".status-inactive, .posted_by_container, .posted-date")
            date_posted = ""
            if date_el:
                txt = date_el.get_text(" ", strip=True)
                m   = re.search(r"\d{1,2}\s+\w+\s+\d{4}", txt)
                if m:
                    date_posted = m.group(0)

            jobs.append({
                "job_id":          job_id,
                "title":           title,
                "company":         company,
                "location":        loc_txt or "India",
                "source":          "internshala",
                "job_url":         job_url,
                "description":     f"{title} at {company}. Location: {loc_txt}. {salary}".strip(),
                "date_posted":     date_posted,
                "company_website": "",
            })
        except Exception:
            continue

    return jobs


def scrape_internshala():
    config  = load_config()
    keywords  = config["search"]["keywords"]
    delay     = config["scraping"].get("delay_between_requests", 3)

    results   = []
    seen_ids  = set()
    seen_slugs = set()

    for keyword in keywords:
        slug = KEYWORD_SLUGS.get(keyword, keyword.lower().replace(" ", "-"))
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        jobs = _fetch_jobs(slug)
        new  = [j for j in jobs if j["job_id"] not in seen_ids]
        for j in new:
            seen_ids.add(j["job_id"])
            results.append(j)
        if new:
            print(f"  [Internshala] {slug}: {len(new)} jobs")
        time.sleep(delay + random.random())

    print(f"  Internshala total: {len(results)} unique jobs")
    return results
