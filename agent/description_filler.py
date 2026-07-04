"""
Description filler — fetches missing job descriptions for matched jobs in DB.

Why: When linkedin_fetch_description was False (early runs), jobs were stored
with description=None. Without a description the LLM can't check experience
requirements, so many 2+yr jobs slipped in with high scores.

This script:
  1. Finds all matched (score >= 7) jobs with no description
  2. Fetches the description from the job_url using requests + BeautifulSoup
  3. Re-scores each job with Groq using the full description
  4. Updates the DB — if new score < threshold, marks it appropriately
  5. Rebuilds the fresher export at the end

Safe to run concurrently with the scheduler (reads/writes different columns).
"""
import os
import re
import sqlite3
import sys
import time
import random

import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from agent.exp_filter import has_experience_requirement

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DB_PATH = "jobs.db"


def _load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _fetch_description(job_url: str, source: str) -> str:
    """Fetch job description from the job listing page."""
    if not job_url or not job_url.startswith("http"):
        return ""

    # Foundit job detail pages are JS-rendered — use Playwright directly
    if "foundit.in" in job_url:
        return _fetch_description_playwright(job_url)

    try:
        resp = requests.get(job_url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style/nav noise
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        # Source-specific extraction
        if "linkedin.com" in job_url:
            el = (soup.select_one(".description__text")
                  or soup.select_one(".jobs-description__content")
                  or soup.select_one("[class*='description']"))
        elif "indeed.com" in job_url:
            el = soup.select_one("#jobDescriptionText") or soup.select_one(".jobsearch-jobDescriptionText")
        elif "naukri.com" in job_url:
            el = soup.select_one(".job-desc") or soup.select_one("[class*='jd-desc']")
        elif "internshala.com" in job_url:
            el = soup.select_one(".about_the_job") or soup.select_one("#about_company")
        else:
            # Generic: find the largest text block
            el = None
            best_len = 0
            for tag in soup.find_all(["div", "section", "article"]):
                txt = tag.get_text(" ", strip=True)
                if len(txt) > best_len and len(txt) < 8000:
                    best_len = len(txt)
                    el = tag

        if el:
            text = el.get_text(" ", strip=True)
            text = re.sub(r"\s{3,}", "\n", text)
            return text[:3000]

    except Exception:
        pass
    return ""


def _fetch_description_playwright(job_url: str) -> str:
    """Playwright-based fetch for JS-rendered pages (Foundit)."""
    try:
        import asyncio
        from playwright.async_api import async_playwright

        async def _run():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=HEADERS["User-Agent"])
                try:
                    await page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(3000)
                    # Try Foundit-specific selectors first
                    for sel in [".job-desc-container", ".jd-container", "[class*='jobDescription']",
                                 "[class*='job-description']", "[class*='desc-container']",
                                 ".description", "section.details"]:
                        el = await page.query_selector(sel)
                        if el:
                            text = await el.inner_text()
                            if len(text) > 100:
                                return re.sub(r"\s{3,}", "\n", text.strip())[:3000]
                    # Fallback: largest text block on page
                    blocks = await page.query_selector_all("div, section, article")
                    best_text = ""
                    for block in blocks:
                        try:
                            txt = await block.inner_text()
                            if 200 < len(txt) < 6000 and len(txt) > len(best_text):
                                best_text = txt
                        except Exception:
                            continue
                    return re.sub(r"\s{3,}", "\n", best_text.strip())[:3000] if best_text else ""
                finally:
                    await browser.close()

        return asyncio.run(_run())
    except Exception:
        return ""


def run_filler(limit: int = 50, rescore: bool = True, dry_run: bool = False):
    """
    Fetch descriptions and optionally re-score matched jobs with no description.

    Args:
        limit:    Max jobs to process per run (keep low to avoid rate limits)
        rescore:  If True, re-score with Groq after fetching description
        dry_run:  If True, print results but don't update DB
    """
    config    = _load_config()
    threshold = config["matching"]["relevance_threshold"]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT job_id, title, company, job_url, source, relevance_score
        FROM jobs
        WHERE relevance_score >= 7
          AND (description IS NULL OR description IN ('', 'nan', 'None'))
          AND job_url IS NOT NULL AND job_url != ''
        ORDER BY relevance_score DESC, date_scraped DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    if not rows:
        print("[DescFiller] No no-description matched jobs found.")
        return

    print(f"[DescFiller] Processing {len(rows)} no-description matched jobs...")

    downgraded = 0
    enriched   = 0

    if rescore:
        from agent.resume_matcher import score_job, load_resume
        load_resume(config["resume"]["path"])

    for i, row in enumerate(rows, 1):
        job_id = row["job_id"]
        title  = row["title"]
        company = row["company"]
        url    = row["job_url"]
        old_score = row["relevance_score"]

        print(f"  [{i:>3}/{len(rows)}] Fetching: {title[:40]} @ {company[:25]}")

        desc = _fetch_description(url, row["source"])

        if not desc:
            print(f"    -> Could not fetch description, skipping")
            time.sleep(1)
            continue

        # Quick pre-check: does description have exp requirement?
        if has_experience_requirement(desc):
            new_score = 2
            reason    = "Description requires 2+ years experience (fetched post-insert)"
            print(f"    -> EXP REQUIRED in desc — downgrading {old_score} -> {new_score}")
        elif rescore:
            try:
                job_dict = dict(row)
                job_dict["description"] = desc
                result    = score_job(job_dict)
                new_score = int(result.get("score", old_score))
                reason    = result.get("reason", "")
                print(f"    -> Re-scored: {old_score} -> {new_score}  {reason[:60]}")
            except Exception as e:
                print(f"    -> Score error: {e}")
                new_score = old_score
                reason    = ""
        else:
            new_score = old_score
            reason    = ""

        if not dry_run:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "UPDATE jobs SET description = ?, relevance_score = ?, match_reason = ? WHERE job_id = ?",
                (desc, new_score, reason, job_id)
            )
            conn.commit()
            conn.close()

        if new_score < threshold and old_score >= threshold:
            downgraded += 1
        enriched += 1

        delay = 2 + random.random() * 2
        time.sleep(delay)

    print(f"\n[DescFiller] Done — enriched: {enriched}, downgraded: {downgraded}")
    if downgraded > 0 and not dry_run:
        print("[DescFiller] Rebuilding fresher export...")
        from export_fresher_jobs import export
        export()


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")
    run_filler(limit=100, rescore=True)
