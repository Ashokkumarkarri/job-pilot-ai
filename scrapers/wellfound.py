import asyncio, hashlib, random, yaml
from playwright.async_api import async_playwright
try:
    from playwright_stealth import stealth_async
    STEALTH = True
except ImportError:
    STEALTH = False


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


# Wellfound (AngelList Talent) uses role-slugs for filtering
ROLE_SLUGS = [
    "react-developer",
    "full-stack-developer",
    "node-js-developer",
    "frontend-developer",
    "react-native-developer",
]


async def _scrape_role(role_slug, max_jobs):
    url = f"https://wellfound.com/role/r/{role_slug}?years_experience_min=0&years_experience_max=1"
    jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )
        page = await context.new_page()
        if STEALTH:
            await stealth_async(page)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            try:
                await page.wait_for_selector(
                    "[class*='styles_jobListingCard'], [class*='JobCard'], div[data-test*='JobCard'], .job-card",
                    timeout=12000,
                )
            except Exception:
                pass
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(700 + random.randint(100, 300))

            cards = await page.query_selector_all(
                "[class*='styles_jobListingCard'], [class*='JobCard'], div[data-test*='JobCard']"
            )

            for card in cards[:max_jobs]:
                try:
                    title_el   = await card.query_selector("h2, h3, [class*='title'], a[href*='/jobs/']")
                    company_el = await card.query_selector("[class*='company'], [class*='startup']")
                    loc_el     = await card.query_selector("[class*='location'], [class*='remote']")
                    link_el    = await card.query_selector("a[href*='/jobs/']")

                    title   = (await title_el.inner_text()).strip()   if title_el   else ""
                    company = (await company_el.inner_text()).strip() if company_el else ""
                    loc     = (await loc_el.inner_text()).strip()     if loc_el     else "Remote"
                    href    = await link_el.get_attribute("href")     if link_el    else ""

                    if not title or not href:
                        continue
                    job_url = href if href.startswith("http") else f"https://wellfound.com{href}"
                    job_id  = hashlib.md5(job_url.encode()).hexdigest()
                    jobs.append({"job_id": job_id, "title": title, "company": company,
                                 "location": loc, "source": "wellfound", "job_url": job_url,
                                 "description": "", "date_posted": "", "company_website": ""})
                except Exception:
                    continue
        except Exception as e:
            print(f"    Wellfound error [{role_slug}]: {e}")
        finally:
            await browser.close()
    return jobs


async def _scrape_all():
    config   = load_config()
    max_jobs = config["scraping"].get("results_per_keyword", 25)
    delay    = config["scraping"].get("delay_between_requests", 3)
    results, seen = [], set()

    for slug in ROLE_SLUGS:
        print(f"  [Wellfound] {slug}")
        jobs = await _scrape_role(slug, max_jobs)
        new  = [j for j in jobs if j["job_id"] not in seen]
        for j in new:
            seen.add(j["job_id"])
            results.append(j)
        print(f"    +{len(new)} jobs")
        await asyncio.sleep(delay + random.random() * 2)
    return results


def scrape_wellfound():
    jobs = asyncio.run(_scrape_all())
    print(f"  Wellfound total: {len(jobs)}")
    return jobs
