#!/usr/bin/env python3
"""
WA Emulator Link — Generates WhatsApp emulator URLs for each lead.

Each link opens the WhatsApp chat emulator pre-configured with the lead's
business name and auto-configures the AI system prompt.

Commands:
    python3 generate_links.py validate <SPREADSHEET_ID>
    python3 generate_links.py list-pending <SPREADSHEET_ID>
    python3 generate_links.py generate <SPREADSHEET_ID>
    python3 generate_links.py report <SPREADSHEET_ID>
"""

import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

# Add _shared to import path
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _shared import (
    load_env,
    get_sheets_service,
    read_sheet,
    find_columns,
    update_sheet_cell,
    add_column_if_missing,
    get_sheet_title,
    send_telegram_report,
)

EMULATOR_BASE = "http://localhost:8889"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
AVATARS_DIR = PROJECT_ROOT / "output" / "wa_avatars"

# WhatsApp-specific column patterns (supplement _shared patterns)
WA_LINK_PATTERNS = {
    "wa_emulator_link": [
        "wa emulator link", "wa_emulator_link", "whatsapp emulator link",
        "wa emulator", "whatsapp emulator", "ссылка на эмулятор wa",
        "эмулятор wa", "wa demo emulator",
    ],
    "whatsapp_demo": [
        "whatsapp demo", "whatsapp_demo", "wa demo", "wa_demo",
        "ватсап демо", "whatsapp demo link",
    ],
}


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def _get_cell(row, col_idx):
    """Safely get a cell value."""
    if col_idx is not None and col_idx < len(row):
        return row[col_idx].strip()
    return ""


def _find_wa_column(headers, pattern_key):
    """Find a WA-specific column by pattern matching."""
    for i, h in enumerate(headers):
        h_lower = h.lower().strip()
        if not h_lower:
            continue
        for pattern in WA_LINK_PATTERNS.get(pattern_key, []):
            if h_lower == pattern or (len(h_lower) > 3 and pattern in h_lower):
                return i
    return None


def _ensure_column(service, spreadsheet_id, sheet_title, headers, col_name, pattern_key):
    """Ensure a column exists. Returns column index."""
    idx = _find_wa_column(headers, pattern_key)
    if idx is None:
        idx = add_column_if_missing(service, spreadsheet_id, sheet_title, headers, col_name)
        headers.append(col_name)
    return idx


def _has_link(row, link_idx):
    """Check if row has a non-empty value at given index."""
    return link_idx < len(row) and row[link_idx].strip() != ""


def _has_cached_avatar(phone: str) -> bool:
    """Check if a cached avatar exists for this phone number."""
    phone_norm = re.sub(r'\D', '', phone)
    if not phone_norm:
        return False
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if (AVATARS_DIR / f"{phone_norm}{ext}").exists():
            return True
    return False


def _build_emulator_url(spreadsheet_id, row_number, business_name, phone=""):
    """Build the WhatsApp emulator URL with all params.
    Avatar is auto-fetched by the emulator frontend via /proxy/wa-avatar endpoint,
    so we don't need to include it in the URL anymore."""
    params = []
    params.append(f"name={quote_plus(business_name)}" if business_name else "name=Business")
    if phone:
        params.append(f"phone={quote_plus(phone)}")
    params.append(f"spreadsheet={quote_plus(spreadsheet_id)}")
    params.append(f"row={row_number}")
    params = [p for p in params if p]
    return f"{EMULATOR_BASE}/?{'&'.join(params)}"


# ──────────────────────────────────────────
# Commands
# ──────────────────────────────────────────

def cmd_validate(spreadsheet_id: str):
    """Validate sheet structure."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)

    if not rows:
        print("ERROR: Sheet is empty.")
        sys.exit(1)

    headers = rows[0]
    columns = find_columns(headers)

    print(f"\n{'='*60}")
    print(f"  WA EMULATOR LINK — SHEET VALIDATION")
    print(f"{'='*60}")
    print(f"\n  Columns found: {', '.join(h for h in headers if h.strip())}\n")

    # Required: Phone
    phone_col = columns.get("phone", {}).get("index")
    if phone_col is not None:
        print(f"  ✓ {'PHONE':20s} → '{columns['phone']['name']}' (col {phone_col})")
    else:
        print(f"  ✗ {'PHONE':20s} → NOT FOUND")
        print(f"\n  ERROR: Missing required 'Phone' column.")
        sys.exit(1)

    # Recommended: System Prompt
    prompt_col = columns.get("system_prompt", {}).get("index")
    if prompt_col is not None:
        print(f"  ✓ {'SYSTEM_PROMPT':20s} → '{columns['system_prompt']['name']}' (col {prompt_col})")
    else:
        print(f"  ○ {'SYSTEM_PROMPT':20s} → not found (emulator will work, but AI won't auto-configure)")

    # WA Emulator Link — will be created if missing
    wa_link_idx = _find_wa_column(headers, "wa_emulator_link")
    if wa_link_idx is not None:
        print(f"  ✓ {'WA_EMULATOR_LINK':20s} → '{headers[wa_link_idx]}' (col {wa_link_idx})")
    else:
        print(f"  ○ {'WA_EMULATOR_LINK':20s} → not found (will be created)")

    # WhatsApp Demo — will be created if missing (for saving demo links later)
    wa_demo_idx = _find_wa_column(headers, "whatsapp_demo")
    if wa_demo_idx is None:
        wa_demo_idx = columns.get("whatsapp_demo", {}).get("index")
    if wa_demo_idx is not None:
        print(f"  ✓ {'WHATSAPP_DEMO':20s} → '{headers[wa_demo_idx]}' (col {wa_demo_idx})")
    else:
        print(f"  ○ {'WHATSAPP_DEMO':20s} → not found (will be created for saving demo links)")

    # Show optional columns
    for key in ["business_name", "owner_name", "website", "city", "niche"]:
        if key in columns:
            print(f"  ✓ {key.upper():20s} → '{columns[key]['name']}' (col {columns[key]['index']})")

    # Stats
    total = len(rows) - 1
    has_link_count = sum(1 for r in rows[1:] if wa_link_idx is not None and _has_link(r, wa_link_idx))
    has_prompt = sum(1 for r in rows[1:] if prompt_col is not None and _get_cell(r, prompt_col)) if prompt_col is not None else 0

    print(f"\n  {'─'*40}")
    print(f"  Total leads:         {total}")
    print(f"  With system prompt:  {has_prompt}")
    print(f"  With WA emulator link: {has_link_count}")
    print(f"  Need links:          {total - has_link_count}")
    print(f"{'='*60}\n")


def cmd_list_pending(spreadsheet_id: str):
    """List leads that don't have a WA emulator link yet."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)
    sheet_title = get_sheet_title(service, spreadsheet_id)

    link_idx = _ensure_column(service, spreadsheet_id, sheet_title, headers, "WA Emulator Link", "wa_emulator_link")
    phone_col = columns.get("phone", {}).get("index")
    biz_col = columns.get("business_name", {}).get("index")
    prompt_col = columns.get("system_prompt", {}).get("index")

    pending = []
    for row_idx, row in enumerate(rows[1:], start=1):
        if _has_link(row, link_idx):
            continue

        phone = _get_cell(row, phone_col) if phone_col is not None else ""
        if not phone:
            continue

        biz = _get_cell(row, biz_col) if biz_col is not None else ""
        has_prompt = bool(_get_cell(row, prompt_col)) if prompt_col is not None else False

        pending.append({
            "sheet_row": row_idx + 1,
            "phone": phone,
            "business": biz,
            "has_prompt": has_prompt,
        })

    print(f"\nLeads without WA emulator link: {len(pending)}\n")
    for p in pending:
        biz_str = f" ({p['business']})" if p['business'] else ""
        prompt_str = " ✓prompt" if p['has_prompt'] else " ○no prompt"
        print(f"  Row {p['sheet_row']}: {p['phone']}{biz_str}{prompt_str}")

    if not pending:
        print("  All leads already have WA emulator links.")


def cmd_generate(spreadsheet_id: str):
    """Generate WA emulator links for all pending leads."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)
    sheet_title = get_sheet_title(service, spreadsheet_id)

    # Ensure columns exist
    link_idx = _ensure_column(service, spreadsheet_id, sheet_title, headers, "WA Emulator Link", "wa_emulator_link")

    # Also ensure WhatsApp Demo column exists (for user to fill later)
    wa_demo_idx = _find_wa_column(headers, "whatsapp_demo")
    if wa_demo_idx is None and columns.get("whatsapp_demo") is None:
        wa_demo_idx = add_column_if_missing(service, spreadsheet_id, sheet_title, headers, "WhatsApp Demo")
        headers.append("WhatsApp Demo")
        print(f"  📝 Created 'WhatsApp Demo' column at index {wa_demo_idx}")

    phone_col = columns.get("phone", {}).get("index")
    biz_col = columns.get("business_name", {}).get("index")
    owner_col = columns.get("owner_name", {}).get("index")
    prompt_col = columns.get("system_prompt", {}).get("index")

    generated = 0
    skipped = 0
    errors = []

    print(f"\n{'='*60}")
    print(f"  GENERATING WA EMULATOR LINKS")
    print(f"{'='*60}\n")

    for row_idx, row in enumerate(rows[1:], start=1):
        sheet_row = row_idx + 1

        # Skip if already has link
        if _has_link(row, link_idx):
            continue

        # Get phone
        phone = _get_cell(row, phone_col) if phone_col is not None else ""
        if not phone:
            skipped += 1
            continue

        # Get business name (try business_name, then owner_name, then phone)
        biz = _get_cell(row, biz_col) if biz_col is not None else ""
        if not biz and owner_col is not None:
            biz = _get_cell(row, owner_col)
        biz = biz or phone

        # Build URL
        url = _build_emulator_url(spreadsheet_id, sheet_row, biz, phone)

        # Save to sheet
        try:
            update_sheet_cell(service, spreadsheet_id, sheet_title, row_idx, link_idx, url)
            generated += 1
            prompt_status = "✓" if (prompt_col is not None and _get_cell(row, prompt_col)) else "○"
            avatar_status = "🖼" if _has_cached_avatar(phone) else "○"
            print(f"  [{generated}] Row {sheet_row}: {phone} ({biz}) prompt:{prompt_status} avatar:{avatar_status}")
        except Exception as e:
            errors.append(f"Row {sheet_row} {phone}: {e}")
            print(f"  ✗ Row {sheet_row}: {phone} — ERROR: {e}")

    print(f"\n  {'─'*40}")
    print(f"  Generated: {generated}")
    print(f"  Skipped (no phone): {skipped}")
    print(f"  Errors: {len(errors)}")
    print(f"{'='*60}\n")

    if errors:
        print("  Errors:")
        for err in errors:
            print(f"    • {err}")


def cmd_report(spreadsheet_id: str):
    """Send Telegram report with current stats."""
    env_vars = load_env()
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)

    link_idx = _find_wa_column(headers, "wa_emulator_link")
    phone_col = columns.get("phone", {}).get("index")
    wa_demo_idx = _find_wa_column(headers, "whatsapp_demo")
    if wa_demo_idx is None:
        wa_demo_idx = columns.get("whatsapp_demo", {}).get("index")

    with_link = 0
    without_link = 0
    with_demo = 0

    for row in rows[1:]:
        phone = _get_cell(row, phone_col) if phone_col is not None else ""
        if not phone:
            continue

        if link_idx is not None and _has_link(row, link_idx):
            with_link += 1
        else:
            without_link += 1

        if wa_demo_idx is not None and _has_link(row, wa_demo_idx):
            with_demo += 1

    report = {
        "sent": with_link,
        "failed": 0,
        "remaining": without_link,
        "by_mailbox": {"with_demo": with_demo},
        "errors": [],
    }

    print(f"  With WA emulator link:  {with_link}")
    print(f"  Without WA emulator link: {without_link}")
    print(f"  With WhatsApp Demo:     {with_demo}")

    send_telegram_report(env_vars, report, title="WA Emulator Link")


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python3 generate_links.py validate <SPREADSHEET_ID>")
        print("  python3 generate_links.py list-pending <SPREADSHEET_ID>")
        print("  python3 generate_links.py generate <SPREADSHEET_ID>")
        print("  python3 generate_links.py report <SPREADSHEET_ID>")
        sys.exit(1)

    command = sys.argv[1].lower()
    spreadsheet_id = sys.argv[2]

    if command == "validate":
        cmd_validate(spreadsheet_id)
    elif command == "list-pending":
        cmd_list_pending(spreadsheet_id)
    elif command == "generate":
        cmd_generate(spreadsheet_id)
    elif command == "report":
        cmd_report(spreadsheet_id)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
