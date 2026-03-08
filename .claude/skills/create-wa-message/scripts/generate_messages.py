#!/usr/bin/env python3
"""
Create WA Message — Generates personalized WhatsApp cold outreach messages.

Reads prospect data from Google Sheets, provides data to the agent for message
generation, and saves generated messages back to the sheet.

Agent mode commands:
    python3 generate_messages.py validate <SPREADSHEET_ID>
    python3 generate_messages.py list-pending <SPREADSHEET_ID>
    python3 generate_messages.py get-row <SPREADSHEET_ID> <ROW_NUMBER>
    python3 generate_messages.py save-message <SPREADSHEET_ID> <ROW_NUMBER> [--file PATH]
    python3 generate_messages.py save-followup <SPREADSHEET_ID> <ROW_NUMBER> [--file PATH]
    python3 generate_messages.py report <SPREADSHEET_ID>

save-message / save-followup reads text from:
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


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def _get_cell(row, col_idx):
    """Safely get a cell value."""
    if col_idx is not None and col_idx < len(row):
        return row[col_idx].strip()
    return ""


def _ensure_column(service, spreadsheet_id, sheet_title, headers, columns, key, name):
    """Ensure a column exists. Returns column index."""
    if key in columns:
        return columns[key]["index"]
    idx = add_column_if_missing(service, spreadsheet_id, sheet_title, headers, name)
    headers.append(name)
    return idx


def _has_message(row, msg_idx):
    """Check if row has a non-empty message at given index."""
    return msg_idx < len(row) and row[msg_idx].strip() != ""


def _read_message_input(file_path=None):
    """Read message text from --file or stdin."""
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    elif not sys.stdin.isatty():
        return sys.stdin.read().strip()
    else:
        print("ERROR: No message text provided.")
        print("  Option 1: python3 generate_messages.py save-message <ID> <ROW> --file /path/to/msg.txt")
        print("  Option 2: echo 'text' | python3 generate_messages.py save-message <ID> <ROW>")
        print("  Option 3: python3 generate_messages.py save-message <ID> <ROW> <<'EOF'")
        print("            message text here")
        print("            EOF")
        sys.exit(1)


# ──────────────────────────────────────────
# Commands
# ──────────────────────────────────────────

def cmd_validate(spreadsheet_id: str):
    """Validate sheet structure for WhatsApp message generation."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)

    if not rows:
        print("ERROR: Sheet is empty.")
        sys.exit(1)

    headers = rows[0]
    columns = find_columns(headers)

    print(f"\n{'='*60}")
    print(f"  CREATE WA MESSAGE — SHEET VALIDATION")
    print(f"{'='*60}")
    print(f"\n  Columns found: {', '.join(h for h in headers if h.strip())}\n")

    # Required: Phone (for identifying lead) OR company_info (for personalization)
    phone_col = columns.get("phone", {}).get("index")
    info_col = columns.get("company_info", {}).get("index")
    website_col = columns.get("website", {}).get("index")
    demo_col = columns.get("demo", {}).get("index")

    # Show required columns
    if phone_col is not None:
        print(f"  ✓ {'PHONE':20s} → '{columns['phone']['name']}' (col {phone_col})")
    else:
        print(f"  ✗ {'PHONE':20s} → NOT FOUND")

    if info_col is not None:
        print(f"  ✓ {'COMPANY_INFO':20s} → '{columns['company_info']['name']}' (col {info_col})")
    else:
        print(f"  ○ {'COMPANY_INFO':20s} → not found (personalization will be limited)")

    if website_col is not None:
        print(f"  ✓ {'WEBSITE':20s} → '{columns['website']['name']}' (col {website_col})")
    else:
        print(f"  ○ {'WEBSITE':20s} → not found")

    if demo_col is not None:
        print(f"  ✓ {'DEMO':20s} → '{columns['demo']['name']}' (col {demo_col})")
    else:
        print(f"  ○ {'DEMO':20s} → not found (messages won't reference a demo)")

    if phone_col is None:
        print(f"\n  ERROR: Missing required 'Phone' column.")
        sys.exit(1)

    # Start Message
    if "start_message" in columns:
        print(f"  ✓ {'START_MESSAGE':20s} → '{columns['start_message']['name']}' (col {columns['start_message']['index']})")
    else:
        print(f"  ○ {'START_MESSAGE':20s} → not found (will be created)")

    # Follow-up Message
    if "follow_up_message" in columns:
        print(f"  ✓ {'FOLLOW_UP':20s} → '{columns['follow_up_message']['name']}' (col {columns['follow_up_message']['index']})")
    else:
        print(f"  ○ {'FOLLOW_UP':20s} → not found (will be created)")

    # WhatsApp Demo
    wa_demo_col = columns.get("whatsapp_demo", {}).get("index")
    if wa_demo_col is not None:
        print(f"  ✓ {'WHATSAPP_DEMO':20s} → '{columns['whatsapp_demo']['name']}' (col {wa_demo_col})")

    # Optional personalization columns
    for key in ["business_name", "owner_name", "city", "niche",
                 "language", "pain_point", "instagram", "system_prompt"]:
        if key in columns:
            print(f"  ✓ {key.upper():20s} → '{columns[key]['name']}' (col {columns[key]['index']})")

    # Stats
    total = len(rows) - 1
    msg_col = columns.get("start_message", {}).get("index")
    has_msg = sum(1 for r in rows[1:] if msg_col is not None and _has_message(r, msg_col))
    has_demo = sum(1 for r in rows[1:] if demo_col is not None and _get_cell(r, demo_col))
    has_wa_demo = sum(1 for r in rows[1:] if wa_demo_col is not None and _get_cell(r, wa_demo_col))

    # Detect languages
    lang_col = columns.get("language", {}).get("index")
    lang_dist = {}
    if lang_col is not None:
        for r in rows[1:]:
            lang = _get_cell(r, lang_col).lower() or "pt"
            lang_dist[lang] = lang_dist.get(lang, 0) + 1

    print(f"\n  {'─'*40}")
    print(f"  Total leads:         {total}")
    print(f"  With message:        {has_msg}")
    print(f"  Need generation:     {total - has_msg}")
    print(f"  With site demo:      {has_demo}")
    print(f"  With WhatsApp demo:  {has_wa_demo}")
    if lang_dist:
        lang_str = ", ".join(f"{k}: {v}" for k, v in sorted(lang_dist.items()))
        print(f"  Languages:           {lang_str}")
    print(f"{'='*60}\n")


def cmd_list_pending(spreadsheet_id: str):
    """List leads that don't have a start message yet."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)
    sheet_title = get_sheet_title(service, spreadsheet_id)

    msg_idx = _ensure_column(service, spreadsheet_id, sheet_title, headers, columns,
                             "start_message", "Start Message")
    phone_col = columns.get("phone", {}).get("index")
    biz_col = columns.get("business_name", {}).get("index")
    info_col = columns.get("company_info", {}).get("index")
    demo_col = columns.get("demo", {}).get("index")
    wa_demo_col = columns.get("whatsapp_demo", {}).get("index")
    lang_col = columns.get("language", {}).get("index")

    pending = []
    for row_idx, row in enumerate(rows[1:], start=1):
        if _has_message(row, msg_idx):
            continue

        phone = _get_cell(row, phone_col) if phone_col is not None else ""
        if not phone:
            continue

        biz = _get_cell(row, biz_col) if biz_col is not None else ""
        if not biz:
            biz = _get_cell(row, info_col) if info_col is not None else ""
            if biz and len(biz) > 40:
                biz = biz[:40] + "..."

        has_demo = bool(_get_cell(row, demo_col)) if demo_col is not None else False
        has_wa_demo = bool(_get_cell(row, wa_demo_col)) if wa_demo_col is not None else False
        lang = _get_cell(row, lang_col).lower() if lang_col is not None else "pt"

        pending.append({
            "sheet_row": row_idx + 1,
            "phone": phone,
            "business": biz,
            "has_demo": has_demo,
            "has_wa_demo": has_wa_demo,
            "lang": lang or "pt",
        })

    print(f"\nLeads without start message: {len(pending)}\n")
    for p in pending:
        biz_str = f" ({p['business']})" if p['business'] else ""
        demo_str = " demo:✓" if p['has_demo'] else " demo:○"
        wa_str = " wa_demo:✓" if p['has_wa_demo'] else ""
        print(f"  Row {p['sheet_row']}: {p['phone']}{biz_str} [{p['lang']}]{demo_str}{wa_str}")

    if not pending:
        print("  All leads already have start messages.")


def cmd_get_row(spreadsheet_id: str, row_number: int):
    """Get ALL available data for a specific row."""
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)

    data_idx = row_number - 1
    if data_idx < 1 or data_idx >= len(rows):
        print(f"ERROR: Row {row_number} out of range (sheet has {len(rows)} rows)")
        sys.exit(1)

    row = rows[data_idx]

    print(f"Row {row_number}:")

    # Output all known columns with labels
    col_display = {
        "phone": ("Phone", None),
        "company_info": ("Company Info", None),
        "business_name": ("Business Name", None),
        "owner_name": ("Owner/Contact", None),
        "website": ("Website", None),
        "demo": ("Demo Link", None),
        "whatsapp_demo": ("WhatsApp Demo", None),
        "city": ("City", None),
        "niche": ("Niche", None),
        "language": ("Language", None),
        "pain_point": ("Pain Point", None),
        "instagram": ("Instagram", None),
        "system_prompt": ("System Prompt", lambda v: v[:300] + "..." if len(v) > 300 else v),
        "start_message": ("Current Message", lambda v: v[:200] + "..." if len(v) > 200 else v),
        "follow_up_message": ("Follow-Up", lambda v: v[:200] + "..." if len(v) > 200 else v),
    }

    for key, (label, transform) in col_display.items():
        col_info = columns.get(key)
        if col_info:
            val = _get_cell(row, col_info["index"])
            if val:
                display_val = transform(val) if transform else val
                print(f"  {label}: {display_val}")

    # Output any columns NOT matched by known patterns
    known_indices = {info["index"] for info in columns.values()}
    extra = []
    for i, header in enumerate(headers):
        if i not in known_indices and i < len(row) and row[i].strip():
            extra.append(f"  {header}: {row[i].strip()}")
    if extra:
        print(f"  --- Additional columns ---")
        for e in extra:
            print(e)


def cmd_save_message(spreadsheet_id: str, row_number: int, file_path: str = None):
    """Save a generated first message to the sheet."""
    message_text = _read_message_input(file_path)

    if not message_text:
        print("ERROR: Message text is empty")
        sys.exit(1)

    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)
    sheet_title = get_sheet_title(service, spreadsheet_id)

    msg_idx = _ensure_column(service, spreadsheet_id, sheet_title, headers, columns,
                             "start_message", "Start Message")

    data_idx = row_number - 1
    if data_idx < 1 or data_idx >= len(rows):
        print(f"ERROR: Row {row_number} out of range")
        sys.exit(1)

    row = rows[data_idx]
    phone_col = columns.get("phone", {}).get("index")
    biz_col = columns.get("business_name", {}).get("index")
    phone = _get_cell(row, phone_col) if phone_col is not None else ""
    biz = _get_cell(row, biz_col) if biz_col is not None else ""
    lead_id = biz or phone or f"row {row_number}"

    update_sheet_cell(service, spreadsheet_id, sheet_title, data_idx, msg_idx, message_text)

    word_count = len(message_text.split())
    print(f"  ✓ {lead_id} (row {row_number}) — message saved ({word_count} words, {len(message_text)} chars)")
    print(f"    Preview: {message_text[:150]}...")


def cmd_save_followup(spreadsheet_id: str, row_number: int, file_path: str = None):
    """Save a generated follow-up message to the sheet."""
    message_text = _read_message_input(file_path)

    if not message_text:
        print("ERROR: Follow-up text is empty")
        sys.exit(1)

    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)
    sheet_title = get_sheet_title(service, spreadsheet_id)

    fu_idx = _ensure_column(service, spreadsheet_id, sheet_title, headers, columns,
                            "follow_up_message", "Follow Up")

    data_idx = row_number - 1
    if data_idx < 1 or data_idx >= len(rows):
        print(f"ERROR: Row {row_number} out of range")
        sys.exit(1)

    row = rows[data_idx]
    phone_col = columns.get("phone", {}).get("index")
    biz_col = columns.get("business_name", {}).get("index")
    phone = _get_cell(row, phone_col) if phone_col is not None else ""
    biz = _get_cell(row, biz_col) if biz_col is not None else ""
    lead_id = biz or phone or f"row {row_number}"

    update_sheet_cell(service, spreadsheet_id, sheet_title, data_idx, fu_idx, message_text)

    word_count = len(message_text.split())
    print(f"  ✓ {lead_id} (row {row_number}) — follow-up saved ({word_count} words, {len(message_text)} chars)")
    print(f"    Preview: {message_text[:150]}...")


def cmd_report(spreadsheet_id: str):
    """Send Telegram report with current stats."""
    env_vars = load_env()
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = find_columns(headers)

    msg_col = columns.get("start_message", {}).get("index")
    fu_col = columns.get("follow_up_message", {}).get("index")
    phone_col = columns.get("phone", {}).get("index")
    lang_col = columns.get("language", {}).get("index")

    with_msg = 0
    without_msg = 0
    with_followup = 0
    by_lang = {}

    for row in rows[1:]:
        phone = _get_cell(row, phone_col) if phone_col is not None else ""
        if not phone:
            continue

        lang = _get_cell(row, lang_col).lower() if lang_col is not None else "pt"
        lang = lang or "pt"

        if msg_col is not None and _has_message(row, msg_col):
            with_msg += 1
            by_lang[lang] = by_lang.get(lang, 0) + 1
        else:
            without_msg += 1

        if fu_col is not None and _has_message(row, fu_col):
            with_followup += 1

    report = {
        "sent": with_msg,
        "failed": 0,
        "remaining": without_msg,
        "by_mailbox": by_lang,
        "errors": [],
    }

    print(f"  With message:    {with_msg} ({', '.join(f'{k}: {v}' for k, v in sorted(by_lang.items()))})")
    print(f"  With follow-up:  {with_followup}")
    print(f"  Without message: {without_msg}")

    send_telegram_report(env_vars, report, title="Create WA Message")


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python3 generate_messages.py validate <SPREADSHEET_ID>")
        print("  python3 generate_messages.py list-pending <SPREADSHEET_ID>")
        print("  python3 generate_messages.py get-row <SPREADSHEET_ID> <ROW>")
        print("  python3 generate_messages.py save-message <SPREADSHEET_ID> <ROW> [--file PATH]")
        print("  python3 generate_messages.py save-followup <SPREADSHEET_ID> <ROW> [--file PATH]")
        print("  python3 generate_messages.py report <SPREADSHEET_ID>")
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
    elif command == "save-message":
        if len(sys.argv) < 4:
            print("ERROR: save-message requires ROW number")
            sys.exit(1)
        file_path = None
        if "--file" in sys.argv:
            fi = sys.argv.index("--file")
            if fi + 1 < len(sys.argv):
                file_path = sys.argv[fi + 1]
        cmd_save_message(spreadsheet_id, int(sys.argv[3]), file_path)
    elif command == "save-followup":
        if len(sys.argv) < 4:
            print("ERROR: save-followup requires ROW number")
            sys.exit(1)
        file_path = None
        if "--file" in sys.argv:
            fi = sys.argv.index("--file")
            if fi + 1 < len(sys.argv):
                file_path = sys.argv[fi + 1]
        cmd_save_followup(spreadsheet_id, int(sys.argv[3]), file_path)
    elif command == "report":
        cmd_report(spreadsheet_id)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
