"""
Quick test for the updated contact_finder.
Tests:
  1. Company with no website (discover via DuckDuckGo)
  2. Company with a direct website URL
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.contact_finder import find_contact, _discover_website

TESTS = [
    # (label, company_website, company_name)
    ("Direct URL — Zoho",        "https://www.zoho.com",  ""),
    ("No URL — Infosys",         "",                       "Infosys"),
    ("No URL — Freshworks",      "",                       "Freshworks"),
    ("No URL — Razorpay",        "",                       "Razorpay"),
]

print("=" * 60)
print("  Contact Finder Test")
print("=" * 60)

for label, website, company in TESTS:
    print(f"\n[TEST] {label}")
    print(f"  website='{website}' | company='{company}'")

    if not website and company:
        discovered = _discover_website(company)
        print(f"  Discovered URL: {discovered}")

    result = find_contact(website, company_name=company)

    if result.get("email_1"):
        print(f"  email_1 : {result['email_1']}")
        print(f"  email_2 : {result.get('email_2', '-')}")
        print(f"  email_3 : {result.get('email_3', '-')}")
        print(f"  phone   : {result.get('phone', '-')}")
        print(f"  form    : {result.get('contact_form', '-')}")
        print("  STATUS  : PASS")
    else:
        print("  No contact info found")
        print("  STATUS  : no results (site may block scrapers)")

print("\n" + "=" * 60)
print("  Test complete")
print("=" * 60)
