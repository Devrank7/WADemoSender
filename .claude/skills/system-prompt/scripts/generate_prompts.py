#!/usr/bin/env python3
"""
System Prompt Generator — Dual-platform (Instagram + WhatsApp).

Auto-detects platform from sheet columns:
  - Instagram column present → IG mode (research IG profile + website)
  - Phone column present (no Instagram) → WA mode (research website + WhatsApp)

Agent mode commands:
    python3 generate_prompts.py validate <SPREADSHEET_ID>
    python3 generate_prompts.py list-pending <SPREADSHEET_ID>
    python3 generate_prompts.py get-row <SPREADSHEET_ID> <ROW_NUMBER>
    python3 generate_prompts.py save-prompt <SPREADSHEET_ID> <ROW_NUMBER> [--file PATH]
    python3 generate_prompts.py report <SPREADSHEET_ID>

save-prompt reads the prompt text from:
  --file PATH   read from a file
  stdin          pipe text via heredoc or echo
"""

import sys
from pathlib import Path

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
from _shared.scraper import scrape_website

# Conditionally import IG helpers (may not exist in WA-only sheets)
try:
    from _shared import parse_instagram_username, build_ig_profile_url
except ImportError:
    parse_instagram_username = None
    build_ig_profile_url = None


# ──────────────────────────────────────────
# Platform detection
# ──────────────────────────────────────────

def detect_platform(columns):
    """Auto-detect platform from available columns.

    Returns 'ig', 'wa', or 'both'.
    """
    has_ig = "instagram" in columns
    has_phone = "phone" in columns

    if has_ig and has_phone:
        return "both"
    elif has_ig:
        return "ig"
    elif has_phone:
        return "wa"
    else:
        return None


def get_lead_identifier(row, columns, platform):
    """Get the primary identifier for a lead based on platform.

    Returns (identifier_value, identifier_label) tuple.
    """
    if platform in ("ig", "both"):
        ig_col = columns.get("instagram", {}).get("index")
        if ig_col is not None:
            raw = row[ig_col].strip() if ig_col < len(row) else ""
            if parse_instagram_username:
                username = parse_instagram_username(raw)
            else:
                username = raw.lstrip("@").strip()
            if username:
                return username, "ig"

    if platform in ("wa", "both"):
        phone_col = columns.get("phone", {}).get("index")
        if phone_col is not None:
            phone = row[phone_col].strip() if phone_col < len(row) else ""
            if phone:
                return phone, "wa"

    return "", None


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def _ensure_prompt_column(service, spreadsheet_id, sheet_title, headers, columns):
    """Ensure System Prompt column exists. Returns column index."""
    if "system_prompt" not in columns:
        idx = add_column_if_missing(service, spreadsheet_id, sheet_title, headers, "System Prompt")
        headers.append("System Prompt")
    else:
        idx = columns["system_prompt"]["index"]
    return idx


def _has_prompt(row, prompt_idx):
    """Check if row has a non-empty system prompt."""
    return prompt_idx < len(row) and row[prompt_idx].strip() != ""


def _get_cell(row, col_idx):
    """Safely get a cell value."""
    if col_idx is not None and col_idx < len(row):
        return row[col_idx].strip()
    return ""


# ──────────────────────────────────────────
# Agent mode commands
# ──────────────────────────────────────────

def cmd_validate(spreadsheet_id: str):
    """Validate sheet structure and detect platform."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)

    if not rows:
        print("ERROR: Sheet is empty.")
        sys.exit(1)

    headers = rows[0]
    columns = find_columns(headers)

    platform = detect_platform(columns)

    print(f"\n{'='*60}")
    print(f"  SYSTEM PROMPT — SHEET VALIDATION")
    print(f"{'='*60}")
    print(f"\n  Columns found: {', '.join(h for h in headers if h.strip())}\n")

    # Platform detection
    if platform == "ig":
        print(f"  🔵 Platform detected: INSTAGRAM (sheet has Instagram column)")
    elif platform == "wa":
        print(f"  🟢 Platform detected: WHATSAPP (sheet has Phone column, no Instagram)")
    elif platform == "both":
        print(f"  🔵🟢 Platform detected: BOTH (sheet has Instagram + Phone columns)")
    else:
        print(f"  ✗ ERROR: No Instagram or Phone column found")
        print(f"    Need at least one of: Instagram, Phone")
        sys.exit(1)

    # Show identifier columns
    if "instagram" in columns:
        print(f"  ✓ {'INSTAGRAM':20s} → '{columns['instagram']['name']}' (col {columns['instagram']['index']})")

    if "phone" in columns:
        print(f"  ✓ {'PHONE':20s} → '{columns['phone']['name']}' (col {columns['phone']['index']})")

    # Website — required
    if "website" in columns:
        print(f"  ✓ {'WEBSITE':20s} → '{columns['website']['name']}' (col {columns['website']['index']})")
    else:
        print(f"  ⚠ {'WEBSITE':20s} → NOT FOUND (strongly recommended for quality prompts)")

    # System Prompt — will be created if missing
    if "system_prompt" in columns:
        print(f"  ✓ {'SYSTEM_PROMPT':20s} → '{columns['system_prompt']['name']}' (col {columns['system_prompt']['index']})")
    else:
        print(f"  ○ {'SYSTEM_PROMPT':20s} → not found (will be created)")

    # Optional info columns
    for key in ["business_name", "owner_name", "city", "niche", "company_info"]:
        if key in columns:
            print(f"  ✓ {key.upper():20s} → '{columns[key]['name']}' (col {columns[key]['index']})")

    # Stats
    total = len(rows) - 1
    prompt_col = columns.get("system_prompt", {}).get("index")
    has = sum(1 for r in rows[1:] if prompt_col is not None and _has_prompt(r, prompt_col))

    # Count leads with website
    website_col = columns.get("website", {}).get("index")
    has_website = sum(1 for r in rows[1:] if website_col is not None and _get_cell(r, website_col)) if website_col is not None else 0

    print(f"\n  {'─'*40}")
    print(f"  Total leads:         {total}")
    print(f"  With website:        {has_website}")
    print(f"  With system prompt:  {has}")
    print(f"  Need generation:     {total - has}")
    print(f"{'='*60}\n")


def cmd_list_pending(spreadsheet_id: str):
    """List leads that don't have a system prompt yet."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)
    sheet_title = get_sheet_title(service, spreadsheet_id)

    platform = detect_platform(columns)
    if not platform:
        print("ERROR: No Instagram or Phone column found")
        sys.exit(1)

    prompt_idx = _ensure_prompt_column(service, spreadsheet_id, sheet_title, headers, columns)
    website_col = columns.get("website", {}).get("index")
    biz_col = columns.get("business_name", {}).get("index")

    pending = []
    for row_idx, row in enumerate(rows[1:], start=1):
        if _has_prompt(row, prompt_idx):
            continue

        identifier, lead_platform = get_lead_identifier(row, columns, platform)
        if not identifier:
            continue

        website = _get_cell(row, website_col) if website_col is not None else ""
        biz = _get_cell(row, biz_col) if biz_col is not None else ""

        pending.append({
            "sheet_row": row_idx + 1,
            "identifier": identifier,
            "platform": lead_platform,
            "website": website,
            "business": biz,
        })

    print(f"\nLeads without system prompt: {len(pending)}\n")
    for p in pending:
        platform_icon = "🔵" if p["platform"] == "ig" else "🟢"
        id_label = f"@{p['identifier']}" if p["platform"] == "ig" else p["identifier"]
        biz_str = f" ({p['business']})" if p["business"] else ""
        website_str = f" 🌐" if p["website"] else " ⚠no website"

        print(f"  {platform_icon} Row {p['sheet_row']}: {id_label}{biz_str}{website_str}")
        if p["platform"] == "ig" and build_ig_profile_url:
            print(f"    Profile: {build_ig_profile_url(p['identifier'])}")
        if p["website"]:
            print(f"    Website: {p['website']}")
        print()

    if not pending:
        print("  All leads already have system prompts.")


def cmd_get_row(spreadsheet_id: str, row_number: int):
    """Get data for a specific row (1-based sheet row number)."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)

    platform = detect_platform(columns)

    data_idx = row_number - 1
    if data_idx < 1 or data_idx >= len(rows):
        print(f"ERROR: Row {row_number} out of range (sheet has {len(rows)} rows)")
        sys.exit(1)

    row = rows[data_idx]
    identifier, lead_platform = get_lead_identifier(row, columns, platform)
    prompt_col = columns.get("system_prompt", {}).get("index")
    website_col = columns.get("website", {}).get("index")
    current_prompt = _get_cell(row, prompt_col)
    website = _get_cell(row, website_col)

    platform_name = "Instagram" if lead_platform == "ig" else "WhatsApp"
    id_label = f"@{identifier}" if lead_platform == "ig" else identifier

    print(f"Row {row_number} ({platform_name}):")
    print(f"  Identifier:     {id_label}")

    if lead_platform == "ig" and build_ig_profile_url:
        print(f"  Profile URL:    {build_ig_profile_url(identifier)}")

    if website:
        print(f"  Website:        {website}")
    else:
        print(f"  Website:        (none — research via WebSearch)")

    if current_prompt:
        print(f"  Current Prompt: {current_prompt[:200]}...")
    else:
        print(f"  Current Prompt: (empty — needs generation)")

    # Show other available columns
    for key in ["business_name", "owner_name", "city", "niche", "company_info", "phone"]:
        col_info = columns.get(key)
        if col_info:
            val = _get_cell(row, col_info["index"])
            if val:
                print(f"  {key.replace('_', ' ').title()}: {val[:150]}")


def cmd_save_prompt(spreadsheet_id: str, row_number: int, file_path: str = None):
    """Save a generated system prompt to the sheet. Reads from --file or stdin."""
    # Read prompt text
    if file_path:
        prompt_text = Path(file_path).read_text(encoding="utf-8").strip()
    elif not sys.stdin.isatty():
        prompt_text = sys.stdin.read().strip()
    else:
        print("ERROR: No prompt text provided.")
        print("  Option 1: python3 generate_prompts.py save-prompt <ID> <ROW> --file /path/to/prompt.txt")
        print("  Option 2: echo 'text' | python3 generate_prompts.py save-prompt <ID> <ROW>")
        print("  Option 3: python3 generate_prompts.py save-prompt <ID> <ROW> <<'EOF'")
        print("            prompt text here")
        print("            EOF")
        sys.exit(1)

    if not prompt_text:
        print("ERROR: Prompt text is empty")
        sys.exit(1)

    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)
    sheet_title = get_sheet_title(service, spreadsheet_id)

    platform = detect_platform(columns)
    prompt_idx = _ensure_prompt_column(service, spreadsheet_id, sheet_title, headers, columns)

    data_idx = row_number - 1
    if data_idx < 1 or data_idx >= len(rows):
        print(f"ERROR: Row {row_number} out of range")
        sys.exit(1)

    row = rows[data_idx]
    identifier, lead_platform = get_lead_identifier(row, columns, platform)
    id_label = f"@{identifier}" if lead_platform == "ig" else identifier
    platform_name = "IG" if lead_platform == "ig" else "WA"

    update_sheet_cell(service, spreadsheet_id, sheet_title, data_idx, prompt_idx, prompt_text)

    print(f"  ✓ {id_label} (row {row_number}, {platform_name}) — system prompt saved ({len(prompt_text)} chars)")
    print(f"    Preview: {prompt_text[:150]}...")


def cmd_scrape(url: str):
    """Scrape a website and print structured summary for sub-agent consumption."""
    result = scrape_website(url)
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print(result["summary"])


def cmd_report(spreadsheet_id: str):
    """Send Telegram report with current stats."""
    env_vars = load_env()
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)

    platform = detect_platform(columns)
    prompt_col = columns.get("system_prompt", {}).get("index")

    with_prompt = 0
    without_prompt = 0
    ig_count = 0
    wa_count = 0

    for row in rows[1:]:
        identifier, lead_platform = get_lead_identifier(row, columns, platform)
        if not identifier:
            continue

        if lead_platform == "ig":
            ig_count += 1
        elif lead_platform == "wa":
            wa_count += 1

        if prompt_col is not None and _has_prompt(row, prompt_col):
            with_prompt += 1
        else:
            without_prompt += 1

    report = {
        "sent": with_prompt,
        "failed": 0,
        "remaining": without_prompt,
        "by_mailbox": {
            "ig_leads": ig_count,
            "wa_leads": wa_count,
            "prompts_generated": with_prompt,
        },
        "errors": [],
    }

    platform_str = "IG" if platform == "ig" else "WA" if platform == "wa" else "IG+WA"
    print(f"  Platform:       {platform_str}")
    print(f"  IG leads:       {ig_count}")
    print(f"  WA leads:       {wa_count}")
    print(f"  With prompt:    {with_prompt}")
    print(f"  Without prompt: {without_prompt}")

    send_telegram_report(env_vars, report, title="System Prompt")


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python3 generate_prompts.py validate <SPREADSHEET_ID>")
        print("  python3 generate_prompts.py list-pending <SPREADSHEET_ID>")
        print("  python3 generate_prompts.py get-row <SPREADSHEET_ID> <ROW>")
        print("  python3 generate_prompts.py save-prompt <SPREADSHEET_ID> <ROW> [--file PATH]")
        print("  python3 generate_prompts.py report <SPREADSHEET_ID>")
        print()
        print("Platform auto-detected from sheet columns:")
        print("  Instagram column → IG mode")
        print("  Phone column (no IG) → WA mode")
        print("  Both columns → mixed mode")
        sys.exit(1)

    command = sys.argv[1].lower()
    spreadsheet_id = sys.argv[2]

    if command == "validate":
        cmd_validate(spreadsheet_id)
    elif command == "list-pending":
        cmd_list_pending(spreadsheet_id)
    elif command == "get-row":
        if len(sys.argv) < 4:
            print("ERROR: get-row requires ROW number")
            sys.exit(1)
        cmd_get_row(spreadsheet_id, int(sys.argv[3]))
    elif command == "save-prompt":
        if len(sys.argv) < 4:
            print("ERROR: save-prompt requires ROW number")
            sys.exit(1)
        file_path = None
        if "--file" in sys.argv:
            fi = sys.argv.index("--file")
            if fi + 1 < len(sys.argv):
                file_path = sys.argv[fi + 1]
        cmd_save_prompt(spreadsheet_id, int(sys.argv[3]), file_path)
    elif command == "scrape":
        # Special: scrape takes a URL, not a spreadsheet_id
        cmd_scrape(spreadsheet_id)  # arg is URL here
    elif command == "report":
        cmd_report(spreadsheet_id)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
