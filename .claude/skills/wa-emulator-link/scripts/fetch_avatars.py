#!/usr/bin/env python3
"""
WA Avatar Fetcher — Downloads WhatsApp profile pictures via WhatsApp Web.

Uses Playwright with an existing Chrome profile (where WhatsApp Web is logged in)
to open each contact's chat and extract their profile picture.

Saves avatars to output/wa_avatars/{phone_digits}.jpg for the emulator to serve.

Commands:
    python3 fetch_avatars.py fetch <SPREADSHEET_ID>       # Fetch avatars for all leads
    python3 fetch_avatars.py fetch-one <PHONE_NUMBER>      # Fetch a single avatar
    python3 fetch_avatars.py status <SPREADSHEET_ID>       # Show which leads have avatars
"""

import base64
import json
import os
import re
import sys
import time
from pathlib import Path

# Add _shared to import path
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _shared import load_env, get_sheets_service, read_sheet, find_columns

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
AVATARS_DIR = PROJECT_ROOT / "output" / "wa_avatars"
AVATARS_DIR.mkdir(parents=True, exist_ok=True)


def normalize_phone(phone: str) -> str:
    """Keep only digits from phone number."""
    return re.sub(r'\D', '', phone)


def has_cached_avatar(phone: str) -> bool:
    """Check if avatar already exists locally."""
    phone_norm = normalize_phone(phone)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if (AVATARS_DIR / f"{phone_norm}{ext}").exists():
            return True
    return False


def fetch_single_avatar(page, phone: str, timeout_ms: int = 15000) -> bool:
    """
    Open a WhatsApp Web chat for the given phone number and extract the avatar.
    Returns True if avatar was successfully saved.
    """
    phone_norm = normalize_phone(phone)
    if not phone_norm:
        print(f"    Invalid phone: {phone}")
        return False

    # Check cache
    if has_cached_avatar(phone):
        print(f"    Cached: {phone_norm}")
        return True

    try:
        # Navigate to the contact's chat
        url = f"https://web.whatsapp.com/send?phone={phone_norm}"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for the chat to load (header avatar appears)
        # WhatsApp Web renders the avatar in the chat header
        page.wait_for_timeout(3000)

        # Try to find the avatar image in the chat header
        # WhatsApp Web uses an img tag inside the header with the contact's profile picture
        avatar_data = page.evaluate("""() => {
            // Strategy 1: Header avatar in the conversation panel
            const headerImgs = document.querySelectorAll('header img[src]');
            for (const img of headerImgs) {
                const src = img.src;
                // Skip default avatar (usually a data: URI or blob with the silhouette)
                if (src && !src.includes('dyn/') && src.startsWith('blob:')) {
                    // Convert blob to base64 via canvas
                    try {
                        const canvas = document.createElement('canvas');
                        canvas.width = img.naturalWidth || 150;
                        canvas.height = img.naturalHeight || 150;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                        return canvas.toDataURL('image/jpeg', 0.9);
                    } catch(e) {}
                }
                if (src && src.startsWith('https://pps.whatsapp.net/')) {
                    return src;
                }
            }

            // Strategy 2: Any profile picture visible
            const allImgs = document.querySelectorAll('img[src*="pps.whatsapp.net"]');
            if (allImgs.length > 0) {
                return allImgs[0].src;
            }

            return null;
        }""")

        if not avatar_data:
            # Try waiting a bit more and clicking on the contact header to open profile
            try:
                header = page.locator('header').first
                header.click(timeout=5000)
                page.wait_for_timeout(2000)

                avatar_data = page.evaluate("""() => {
                    const imgs = document.querySelectorAll('img[src*="pps.whatsapp.net"]');
                    if (imgs.length > 0) return imgs[0].src;

                    // Try all images with reasonable size (profile pics)
                    const allImgs = document.querySelectorAll('img[src]');
                    for (const img of allImgs) {
                        if (img.naturalWidth >= 50 && img.naturalHeight >= 50) {
                            const src = img.src;
                            if (src.startsWith('https://') && !src.includes('emoji')) {
                                return src;
                            }
                        }
                    }
                    return null;
                }""")
            except Exception:
                pass

        if not avatar_data:
            print(f"    No avatar found: {phone_norm} (may be private)")
            return False

        # Save avatar
        save_path = AVATARS_DIR / f"{phone_norm}.jpg"

        if avatar_data.startswith('data:image'):
            # Base64 encoded image
            b64_data = avatar_data.split(',', 1)[1]
            save_path.write_bytes(base64.b64decode(b64_data))
        elif avatar_data.startswith('https://'):
            # Direct URL — download it
            import urllib.request
            urllib.request.urlretrieve(avatar_data, str(save_path))
        else:
            print(f"    Unknown avatar format: {phone_norm}")
            return False

        # Verify file is not empty
        if save_path.stat().st_size < 500:
            save_path.unlink()
            print(f"    Avatar too small (likely default): {phone_norm}")
            return False

        print(f"    Saved: {phone_norm} ({save_path.stat().st_size // 1024}KB)")
        return True

    except Exception as e:
        print(f"    Error fetching {phone_norm}: {e}")
        return False


def get_chrome_profile_path() -> str:
    """Get Chrome profile path from env (same as IG or dedicated WA profile)."""
    env = load_env()
    # Try WA-specific first, then fall back to IG profile
    path = env.get("WA_CHROME_PROFILE_PATH") or env.get("IG_CHROME_PROFILE_PATH", "")
    if not path:
        print("ERROR: No Chrome profile path configured.")
        print("Set WA_CHROME_PROFILE_PATH or IG_CHROME_PROFILE_PATH in .env.local")
        sys.exit(1)
    return path


def launch_browser():
    """Launch Playwright with Chrome profile."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    profile_path = get_chrome_profile_path()
    print(f"  Chrome profile: {profile_path}")

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        profile_path,
        headless=False,
        channel="chrome",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        viewport={"width": 1280, "height": 900},
    )
    page = context.pages[0] if context.pages else context.new_page()
    return pw, context, page


def wait_for_whatsapp_ready(page, timeout: int = 60):
    """Wait for WhatsApp Web to be fully loaded and logged in."""
    print("  Waiting for WhatsApp Web to load...")
    page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=30000)

    start = time.time()
    while time.time() - start < timeout:
        # Check if the main chat list is visible (means logged in)
        is_ready = page.evaluate("""() => {
            // Check for the search bar or chat list — indicates logged in
            const search = document.querySelector('[data-testid="chat-list-search"]') ||
                          document.querySelector('[title="Search input textbox"]') ||
                          document.querySelector('[data-icon="search"]');
            return !!search;
        }""")

        if is_ready:
            print("  WhatsApp Web ready!")
            return True

        # Check if QR code is shown (needs scanning)
        has_qr = page.evaluate("""() => {
            return !!document.querySelector('[data-testid="qrcode"]') ||
                   !!document.querySelector('canvas[aria-label]');
        }""")

        if has_qr:
            print("  QR code detected — please scan with your phone to log in.")
            print("  Waiting for login...")

        time.sleep(2)

    print("  ERROR: WhatsApp Web did not load in time.")
    return False


# ──────────────────────────────────────────
# Commands
# ──────────────────────────────────────────

def cmd_fetch(spreadsheet_id: str):
    """Fetch avatars for all leads in the spreadsheet."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)

    phone_col = columns.get("phone", {}).get("index")
    if phone_col is None:
        print("ERROR: No Phone column found.")
        sys.exit(1)

    biz_col = columns.get("business_name", {}).get("index")

    # Collect all phone numbers that need avatars
    phones_to_fetch = []
    already_cached = 0
    no_phone = 0

    for row_idx, row in enumerate(rows[1:], start=1):
        phone = row[phone_col].strip() if phone_col < len(row) else ""
        if not phone:
            no_phone += 1
            continue

        biz = row[biz_col].strip() if biz_col is not None and biz_col < len(row) else ""

        if has_cached_avatar(phone):
            already_cached += 1
        else:
            phones_to_fetch.append({
                "row": row_idx + 1,
                "phone": phone,
                "business": biz,
            })

    print(f"\n{'='*60}")
    print(f"  WA AVATAR FETCHER")
    print(f"{'='*60}")
    print(f"  Total leads:     {len(rows) - 1}")
    print(f"  Already cached:  {already_cached}")
    print(f"  Need fetching:   {len(phones_to_fetch)}")
    print(f"  No phone:        {no_phone}")
    print(f"{'='*60}\n")

    if not phones_to_fetch:
        print("  All avatars already cached. Nothing to fetch.")
        return

    # Launch browser
    pw, context, page = launch_browser()

    try:
        if not wait_for_whatsapp_ready(page):
            return

        fetched = 0
        failed = 0

        for i, lead in enumerate(phones_to_fetch, start=1):
            biz_str = f" ({lead['business']})" if lead['business'] else ""
            print(f"\n  [{i}/{len(phones_to_fetch)}] Row {lead['row']}: {lead['phone']}{biz_str}")

            success = fetch_single_avatar(page, lead['phone'])
            if success:
                fetched += 1
            else:
                failed += 1

            # Small delay between requests to avoid rate limiting
            if i < len(phones_to_fetch):
                time.sleep(2)

        print(f"\n  {'─'*40}")
        print(f"  Fetched:  {fetched}")
        print(f"  Failed:   {failed}")
        print(f"  Cached:   {already_cached}")
        print(f"{'='*60}\n")

    finally:
        context.close()
        pw.stop()


def cmd_fetch_one(phone: str):
    """Fetch avatar for a single phone number."""
    phone_norm = normalize_phone(phone)
    if not phone_norm:
        print(f"ERROR: Invalid phone number: {phone}")
        sys.exit(1)

    print(f"\n  Fetching avatar for: {phone_norm}")

    if has_cached_avatar(phone):
        print(f"  Already cached!")
        return

    pw, context, page = launch_browser()

    try:
        if not wait_for_whatsapp_ready(page):
            return

        success = fetch_single_avatar(page, phone)
        if success:
            print(f"\n  Avatar saved to: {AVATARS_DIR / f'{phone_norm}.jpg'}")
        else:
            print(f"\n  Could not fetch avatar (may be private or not on WhatsApp)")

    finally:
        context.close()
        pw.stop()


def cmd_status(spreadsheet_id: str):
    """Show avatar status for all leads."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)

    phone_col = columns.get("phone", {}).get("index")
    if phone_col is None:
        print("ERROR: No Phone column found.")
        sys.exit(1)

    biz_col = columns.get("business_name", {}).get("index")

    cached = 0
    missing = 0
    no_phone = 0

    print(f"\n{'='*60}")
    print(f"  WA AVATAR STATUS")
    print(f"{'='*60}\n")

    for row_idx, row in enumerate(rows[1:], start=1):
        phone = row[phone_col].strip() if phone_col < len(row) else ""
        if not phone:
            no_phone += 1
            continue

        biz = row[biz_col].strip() if biz_col is not None and biz_col < len(row) else ""
        biz_str = f" ({biz})" if biz else ""

        if has_cached_avatar(phone):
            cached += 1
            phone_norm = normalize_phone(phone)
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                p = AVATARS_DIR / f"{phone_norm}{ext}"
                if p.exists():
                    size = p.stat().st_size // 1024
                    print(f"  Row {row_idx + 1}: {phone}{biz_str} — cached ({size}KB)")
                    break
        else:
            missing += 1
            print(f"  Row {row_idx + 1}: {phone}{biz_str} — missing")

    print(f"\n  {'─'*40}")
    print(f"  Cached:   {cached}")
    print(f"  Missing:  {missing}")
    print(f"  No phone: {no_phone}")
    print(f"{'='*60}\n")


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 fetch_avatars.py fetch <SPREADSHEET_ID>    # Fetch all avatars")
        print("  python3 fetch_avatars.py fetch-one <PHONE_NUMBER>  # Fetch one avatar")
        print("  python3 fetch_avatars.py status <SPREADSHEET_ID>   # Show status")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "fetch" and len(sys.argv) >= 3:
        cmd_fetch(sys.argv[2])
    elif command == "fetch-one" and len(sys.argv) >= 3:
        cmd_fetch_one(sys.argv[2])
    elif command == "status" and len(sys.argv) >= 3:
        cmd_status(sys.argv[2])
    else:
        print(f"Unknown command or missing args: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
