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


async def _scrape_keyword(keyword, max_jobs):
    kw_enc = keyword.replace(" ", "%20")
    url = f"https://cutshort.io/jobs?q={kw_enc}&experienceMin=0&experienceMax=1"
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
                await page.wait_for_selector("[class*='job-card'], [class*='JobCard'], .job-item, article", timeout=12000)
            except Exception:
                pass
            # Scroll a couple of times to load lazy content
            for _ in range(2):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800 + random.randint(100, 400))

            cards = await page.query_selector_all("[class*='job-card'], [class*='JobCard'], .job-item")

            for card in cards[:max_jobs]:
                try:
                    title_el   = await card.query_selector("h2, h3, [class*='title'], a[href*='/jobs/']")
                    company_el = await card.query_selector("[class*='company'], [class*='Company']")
                    loc_el     = await card.query_selector("[class*='location'], [class*='Location']")
                    link_el    = await card.query_selector("a[href*='/jobs/']")

                    title   = (await title_el.inner_text()).strip()   if title_el   else ""
                    company = (await company_el.inner_text()).strip() if company_el else ""
                    loc     = (await loc_el.inner_text()).strip()     if loc_el     else "India"
                    href    = await link_el.get_attribute("href")     if link_el    else ""

                    if not title or not href:
                        continue
                    job_url = href if href.startswith("http") else f"https://cutshort.io{href}"
                    job_id  = hashlib.md5(job_url.encode()).hexdigest()
                    jobs.append({"job_id": job_id, "title": title, "company": company,
                                 "location": loc, "source": "cutshort", "job_url": job_url,
                                 "description": "", "date_posted": "", "company_website": ""})
                except Exception:
                    continue
        except Exception as e:
            print(f"    Cutshort error [{keyword}]: {e}")
        finally:
            await browser.close()
    return jobs


async def _scrape_all():
    config   = load_config()
    keywords = config["search"]["keywords"]
    max_jobs = config["scraping"].get("results_per_keyword", 25)
    delay    = config["scraping"].get("delay_between_requests", 3)
    results, seen = [], set()

    for kw in keywords:
        print(f"  [Cutshort] {kw}")
        jobs = await _scrape_keyword(kw, max_jobs)
        new  = [j for j in jobs if j["job_id"] not in seen]
        for j in new:
            seen.add(j["job_id"])
            results.append(j)
        print(f"    +{len(new)} jobs")
        await asyncio.sleep(delay + random.random() * 2)
    return results


def scrape_cutshort():
    jobs = asyncio.run(_scrape_all())
    print(f"  Cutshort total: {len(jobs)}")
    return jobs
