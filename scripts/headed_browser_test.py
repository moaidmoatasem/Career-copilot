"""Comprehensive headed browser test script for Career Copilot.

Runs the local web console with rich seed data and drives a real headed browser
(Google Chrome / Chromium) via Playwright, displaying prominent visual progress
banners, smoothly scrolling each view, and keeping the browser open for user inspection.
"""

from __future__ import annotations

import io
import os
import sys
import time
import zipfile
import threading
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import uvicorn
from playwright.sync_api import sync_playwright

from career_copilot import console
from career_copilot.service import Copilot

TEST_HOME = Path(__file__).resolve().parent.parent / "tests" / "test_headed_env"
SCREENSHOT_DIR = Path(r"C:\Users\moaid\.gemini\antigravity\brain\caf806cb-9892-423b-af82-b6f1b49ff351\screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_CONTENT = """[candidate]
name = "Alex Mercer"
linkedin_url = "https://www.linkedin.com/in/alex-mercer-tech"
seniority = "lead"
acceptable_seniority = ["senior", "lead", "principal"]

[targets]
titles = ["Senior Python Engineer", "Staff Backend Engineer", "Lead Platform Engineer", "Backend Architect"]
locations = ["London, United Kingdom", "Remote", "Dubai, United Arab Emirates"]
remote_ok = true
exclude_title_keywords = ["intern", "junior", "graduate"]

[skills]
have = ["python", "fastapi", "postgresql", "docker", "aws", "distributed systems", "redis", "ci/cd", "microservices", "banking"]
learning = ["kubernetes", "go", "terraform"]

[privacy]
retention_days = 90

[news]
interests = ["python", "distributed systems", "cloud architecture"]

[[news.feeds]]
name = "Tech Engineering News"
url = "https://example.com/feed.xml"
"""

MONZO_JOB_DESC = """About the Role:
We are looking for a Staff Backend Engineer to help scale our core banking transaction platform.
You will architect mission-critical microservices, design event-driven systems, and mentor engineers.

Requirements:
- 7+ years of backend engineering experience
- Expert Python and FastAPI or asynchronous frameworks
- Deep knowledge of PostgreSQL, query optimization, and schema design
- Production experience with Docker, CI/CD, and AWS infrastructure
- Experience with Distributed Systems, Redis caching, and high-throughput messaging
- Banking domain knowledge and microservices architecture
- Strong communication and architectural leadership

Nice to have:
- Familiarity with Kubernetes orchestration and Terraform
- Experience in regulated fintech environments
"""

REVOLUT_JOB_DESC = """About the Role:
Revolut is seeking a Senior Python Platform Engineer to build high-performance developer tooling and infrastructure platforms.

Requirements:
- Strong Python expertise
- Hands-on Go (Golang) for infrastructure tooling
- Kubernetes cluster management and container orchestration
- Infrastructure as Code using Terraform
- CI/CD automation and observability
- Experience building resilient cloud services on AWS or GCP
"""

DELIVEROO_JOB_DESC = """About the Role:
Join Deliveroo's logistics dispatch team as a Lead Infrastructure Engineer.

Requirements:
- Extensive experience in cloud networking and Linux systems
- Terraform and Kubernetes
- Python or Go scripting
- Incident management and reliability engineering
"""

SPONSOR_REGISTER_CSV = """Organisation Name,Town/City,County,Type & Rating,Route
Monzo Bank Limited,London,,Worker (A rating),Skilled Worker
Revolut Ltd,London,,Worker (A rating),Skilled Worker
Deliveroo Operations Ltd,London,,Worker (A rating),Skilled Worker
"""

CONNECTIONS_CSV = """First Name,Last Name,URL,Company,Position,Connected On
David,Chen,https://www.linkedin.com/in/david-chen-staff,Monzo Bank Limited,Staff Infrastructure Engineer,12 Jan 2023
Elena,Rostova,https://www.linkedin.com/in/elena-rostova,Monzo Bank Limited,Engineering Director,05 Mar 2022
Marcus,Vance,https://www.linkedin.com/in/marcus-vance,Revolut Ltd,Technical Talent Partner,18 Nov 2023
"""


def setup_test_environment() -> Copilot:
    """Prepare test environment with profile, jobs, drafts, inbox, and sponsors."""
    if TEST_HOME.exists():
        import shutil
        shutil.rmtree(TEST_HOME, ignore_errors=True)
    TEST_HOME.mkdir(parents=True, exist_ok=True)

    os.environ["CAREER_COPILOT_HOME"] = str(TEST_HOME)
    (TEST_HOME / "profile.toml").write_text(PROFILE_CONTENT, encoding="utf-8")

    cp = Copilot(TEST_HOME)

    # 1. Sponsor register
    cp.imports_dir.mkdir(parents=True, exist_ok=True)
    (cp.imports_dir / "register.csv").write_text(SPONSOR_REGISTER_CSV, encoding="utf-8")
    cp.import_sponsor_register("register.csv")

    # 2. LinkedIn export mock (Connections.csv)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Connections.csv", CONNECTIONS_CSV)
        zf.writestr("Profile.csv", "First Name,Last Name\nAlex,Mercer\n")
    (cp.imports_dir / "linkedin_export.zip").write_bytes(zip_buffer.getvalue())
    cp.import_linkedin_export("linkedin_export.zip")

    # 3. Jobs across tiers
    j1 = cp.add_job("Staff Backend Engineer", "Monzo Bank Limited", "London, United Kingdom",
                    "https://monzo.com/careers/staff-backend", MONZO_JOB_DESC)
    j2 = cp.add_job("Senior Python Platform Engineer", "Revolut Ltd", "London, United Kingdom",
                    "https://revolut.com/careers/platform-eng", REVOLUT_JOB_DESC)
    j3 = cp.add_job("Lead Infrastructure Engineer", "Deliveroo Operations Ltd", "London, United Kingdom",
                    "https://deliveroo.co.uk/careers/infra", DELIVEROO_JOB_DESC)
    j4 = cp.add_job("Senior Python Developer", "Bayt Technology Partners", "Dubai, United Arab Emirates",
                    "https://www.bayt.com/en/job-445566/")
    j5 = cp.add_job("Backend Architect", "Global FinTech", "London, United Kingdom",
                    "https://www.linkedin.com/jobs/view/9988776655/")

    # 4. Inbox items with proper LinkedIn email structure
    msg_monzo = """Sara Ahmed
Talent Acquisition Partner at Monzo Bank
Hi Alex, I saw your impressive background in Python, distributed systems, and AWS. We are currently scaling our Core Banking platform at Monzo and think you would be a great fit for our Staff Backend Engineer role. Would you be free for a brief intro call next week?
View message: https://www.linkedin.com/comm/messaging/thread/2-monzo-chat/?trk=eml
"""
    cp.ingest_email(
        '"Sara Ahmed via LinkedIn" <messages-noreply@linkedin.com>',
        "Sara Ahmed sent you a new message",
        msg_monzo,
        "Mon, 18 Sep 2026 10:30:00 +0000"
    )

    msg_scam = """Suspicious Recruiter
Recruitment Office
Immediate Job Offer: Please send a $250 verification fee via Western Union or provide your banking OTP code immediately to secure this position.
View message: https://www.linkedin.com/comm/messaging/thread/2-scam-chat/?trk=eml
"""
    cp.ingest_email(
        '"Global Career Services via LinkedIn" <messages-noreply@linkedin.com>',
        "Global Career Services sent you a new message",
        msg_scam,
        "Tue, 19 Sep 2026 09:15:00 +0000"
    )

    inbox_items = cp.list_inbox()["items"]
    monzo_item = next((item for item in inbox_items if "Sara" in item["sender"]), None)

    # 5. Pending Drafts
    if monzo_item:
        cp.draft_message_reply(
            monzo_item["id"],
            "Hi Sara, thank you for reaching out! The Core Banking platform scale sounds fascinating. "
            "I'd love to chat—I am available Tuesday at 2:00 PM or Thursday at 11:00 AM GMT. Looking forward to speaking.",
            "Recruiter response"
        )

    cp.draft_post(
        "Over the last 6 months, migrating our microservices to FastAPI cut median latency by 35% "
        "and reduced monthly AWS compute spend by $12,000. Here are 3 non-obvious trade-offs we encountered: "
        "https://blog.example.com/fastapi-scale\n\nWhat has your experience been with async Python in production?",
        "Engineering learnings post"
    )

    # 6. Courses in Career Path
    cp.add_course("kubernetes", "Kubernetes for Production Engineers", "Coursera", "https://coursera.org/k8s", "2026-11-30")
    cp.add_course("go", "Mastering Go & Concurrency", "Udemy", "https://udemy.com/go-concurrency", "2026-12-15")

    return cp


def start_server(cp: Copilot, port: int) -> tuple[uvicorn.Server, threading.Thread, str]:
    """Start the Starlette application in a background thread."""
    app = console.create_app(cp, port)
    token = app.state.launch_token
    login_url = f"http://127.0.0.1:{port}/login?token={token}"

    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    time.sleep(1.0)
    return server, thread, login_url


def show_banner(page, text: str, duration: float = 3.5):
    """Display a floating progress banner on the page and pause for observation."""
    try:
        page.evaluate("""(msg) => {
            let b = document.getElementById('demo-banner');
            if (!b) {
                b = document.createElement('div');
                b.id = 'demo-banner';
                b.style.position = 'fixed';
                b.style.top = '18px';
                b.style.left = '50%';
                b.style.transform = 'translateX(-50%)';
                b.style.backgroundColor = '#6d28d9';
                b.style.color = '#ffffff';
                b.style.padding = '12px 28px';
                b.style.borderRadius = '40px';
                b.style.fontSize = '16px';
                b.style.fontFamily = '-apple-system, Segoe UI, Roboto, sans-serif';
                b.style.fontWeight = 'bold';
                b.style.boxShadow = '0 10px 30px rgba(0,0,0,0.35)';
                b.style.zIndex = '2147483647';
                b.style.border = '2px solid rgba(255,255,255,0.8)';
                b.style.pointerEvents = 'none';
                document.body.appendChild(b);
            }
            b.innerText = msg;
        }""", text)
    except Exception:
        pass
    time.sleep(duration)


def smooth_scroll(page, down: int = 500):
    """Smooth scroll the page so the user can see lower cards."""
    try:
        page.evaluate(f"window.scrollBy({{ top: {down}, behavior: 'smooth' }});")
        time.sleep(1.2)
        page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' });")
        time.sleep(0.8)
    except Exception:
        pass


def run_headed_browser_tour():
    """Runs a thorough headed browser test with visual banners and extended user pause."""
    print("=== Starting Career Copilot Headed Browser Testing ===")
    cp = setup_test_environment()
    port = console.free_port()
    server, thread, login_url = start_server(cp, port)
    print(f"\nServer listening at http://127.0.0.1:{port}")
    print(f"One-time launch token URL: {login_url}\n")

    with sync_playwright() as p:
        print("Launching visible browser window on your screen (headed mode)...")
        launch_args = ["--start-maximized"]
        try:
            # Try Google Chrome first
            browser = p.chromium.launch(channel="chrome", headless=False, slow_mo=800, args=launch_args)
            print("Using installed Google Chrome browser.")
        except Exception:
            # Fall back to bundled Chromium
            browser = p.chromium.launch(headless=False, slow_mo=800, args=launch_args)
            print("Using Chromium browser.")

        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # Step 1: Login & Today Dashboard
        print("1. [Today Dashboard] Navigating via one-time session token...")
        page.goto(login_url)
        page.wait_for_load_state("networkidle")
        page.bring_to_front()
        show_banner(page, "🚀 Step 1/7: Today Dashboard — Triage Counters & Prompt Exporter", 4.0)
        smooth_scroll(page, 400)
        ss1 = SCREENSHOT_DIR / "01_today_dashboard.png"
        page.screenshot(path=str(ss1), full_page=True)

        # Step 2: Review List
        print("2. [Review Screen] Inspecting pending drafts awaiting human approval...")
        page.click("a[href='/review']")
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 2/7: Review Screen — Human-in-the-Loop Approval Queue", 3.5)
        smooth_scroll(page, 300)
        ss2 = SCREENSHOT_DIR / "02_review_list.png"
        page.screenshot(path=str(ss2), full_page=True)

        # Step 3: Review Detail (Checking claims, links, safety)
        print("3. [Draft Verification] Confirming metrics, claims, and external URLs...")
        post_draft_link = page.locator("a[href*='/review/']").filter(has_text="post")
        if post_draft_link.count() > 0:
            post_draft_link.first.click()
        else:
            page.locator("a[href^='/review/']").first.click()
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 2b: Checking Verification Checkboxes for Metrics & Links", 3.0)

        checkboxes = page.locator("input[type='checkbox']")
        count = checkboxes.count()
        print(f"   Confirming {count} verification check items on screen...")
        for i in range(count):
            checkboxes.nth(i).check()
            time.sleep(0.5)

        note_input = page.locator("input[name='note'], textarea[name='note']")
        if note_input.count() > 0:
            note_input.first.fill("Fact-checked latency metrics and blog link verified.")
            time.sleep(1.0)

        smooth_scroll(page, 300)
        ss3 = SCREENSHOT_DIR / "03_review_detail_checks.png"
        page.screenshot(path=str(ss3), full_page=True)

        # Step 4: Jobs Board
        print("4. [Jobs Board] Inspecting multi-factor fit scoring...")
        page.click("a[href='/jobs']")
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 3/7: Jobs Board — Multi-factor Fit Scoring (Matched / Promising)", 4.0)
        smooth_scroll(page, 400)
        ss4 = SCREENSHOT_DIR / "04_jobs_board.png"
        page.screenshot(path=str(ss4), full_page=True)

        # Step 5: Job Detail - Matched Job with Fit Breakdown & UK Sponsor Card & Referrals
        print("5. [Job Detail] Inspecting Staff Backend Engineer at Monzo Bank...")
        page.locator("a[href^='/jobs/']").filter(has_text="Staff Backend Engineer").first.click()
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 4/7: Job Detail — Fit Breakdown, UK Sponsor Register & Referrals", 4.0)
        smooth_scroll(page, 600)
        ss5 = SCREENSHOT_DIR / "05_job_detail_matched.png"
        page.screenshot(path=str(ss5), full_page=True)

        # Step 6: Job Detail - LinkedIn compliance policy
        print("6. [Compliance Check] Inspecting anti-scraping policy for LinkedIn URLs...")
        page.click("a[href='/jobs']")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.locator("a[href^='/jobs/']").filter(has_text="Backend Architect").first.click()
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 4b: Anti-Scraping Policy — Refuses Automated LinkedIn Scraping", 3.5)
        smooth_scroll(page, 400)
        ss6 = SCREENSHOT_DIR / "06_job_detail_compliance.png"
        page.screenshot(path=str(ss6), full_page=True)

        # Step 7: Career Path - Gaps
        print("7. [Career Path] Inspecting blocking skill gaps...")
        page.click("a[href='/career']")
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 5/7: Career Path — Market Skill Demand (Kubernetes, Go, Terraform)", 4.0)
        smooth_scroll(page, 500)
        ss7 = SCREENSHOT_DIR / "07_career_gaps.png"
        page.screenshot(path=str(ss7), full_page=True)

        # Step 8: Career Path - Plan Projection
        print("8. [Learning Plan] Inspecting 12-week time-boxed capacity and tier promotions...")
        page.click("a[href*='tab=plan']")
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 5b: Learning Plan — 12-Week Time-Boxed Capacity & Tier Projections", 4.0)
        smooth_scroll(page, 600)
        ss8 = SCREENSHOT_DIR / "08_career_plan.png"
        page.screenshot(path=str(ss8), full_page=True)

        # Step 9: Inbox & Safety Flags
        print("9. [Inbox Triage] Inspecting recruiter triaging and scam detection...")
        page.click("a[href='/inbox']")
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 6/7: Inbox Triage — High-Priority Recruiter & Scam Detection Flags", 4.0)
        smooth_scroll(page, 300)
        ss9 = SCREENSHOT_DIR / "09_inbox_triage.png"
        page.screenshot(path=str(ss9), full_page=True)

        # Step 10: Activity Log (Append-only audit trail)
        print("10. [Activity Log] Inspecting immutable SQLite audit trail...")
        page.click("a[href='/activity']")
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 7/7: Activity Log — Append-Only Immutable SQLite Audit Trail", 4.0)
        smooth_scroll(page, 500)
        ss10 = SCREENSHOT_DIR / "10_activity_audit.png"
        page.screenshot(path=str(ss10), full_page=True)

        # Step 11: Data & Privacy
        print("11. [Data & Privacy] Inspecting local storage and purge controls...")
        page.click("a[href='/data']")
        page.wait_for_load_state("networkidle")
        show_banner(page, "🚀 Step 8/8: Data & Privacy — Local Storage & Granular Purge Controls", 4.0)
        smooth_scroll(page, 600)
        ss11 = SCREENSHOT_DIR / "11_data_privacy.png"
        page.screenshot(path=str(ss11), full_page=True)

        # Finish tour - leave open for user
        page.click("a[href='/']")
        page.wait_for_load_state("networkidle")
        show_banner(page, "🎉 Testing Tour Complete! Feel free to click around. Browser will close in 90 seconds.", 2.0)
        print("\n" + "="*70)
        print("Testing tour complete! The browser is now open on your screen.")
        print("You can interact with it, click tabs, and explore for the next 90 seconds.")
        print("="*70 + "\n")

        for remaining in range(90, 0, -10):
            print(f"Browser remains open for {remaining} seconds...")
            time.sleep(10)

        browser.close()

    server.should_exit = True
    print("\nHeaded testing successfully completed.")


if __name__ == "__main__":
    run_headed_browser_tour()
