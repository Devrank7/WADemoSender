#!/usr/bin/env python3
"""
wa-outreach — WhatsApp outreach agent script.

Reads leads from Google Sheets, sends messages via Whapi.cloud API with
multi-account rotation, human-like timing, and anti-ban protection.

Usage:
    python3 send_wa.py validate <SPREADSHEET_ID>
    python3 send_wa.py send <SPREADSHEET_ID> [--limit N] [--live-notify]
    python3 send_wa.py dry-run <SPREADSHEET_ID>
    python3 send_wa.py report <SPREADSHEET_ID>
"""

import json
import math
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# --- Project paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env.local"
SERVICE_ACCOUNT_FILE = PROJECT_ROOT / "service_account.json"
DAILY_STATE_FILE = PROJECT_ROOT / "output" / "wa_daily_state.json"
BLOCK_LOG_FILE = PROJECT_ROOT / "output" / "wa_block_log.json"

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

# SSL context
try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()
    SSL_CONTEXT.check_hostname = False
    SSL_CONTEXT.verify_mode = ssl.CERT_NONE

# ============================================================================
# ANTI-BAN CONFIGURATION
# ============================================================================

# Daily limits per account
DEFAULT_DAILY_LIMIT = 60
HARD_MAX_DAILY_LIMIT = 80  # NEVER exceed

# Delays between messages from SAME account (seconds)
MIN_DELAY_SAME = 45
MAX_DELAY_SAME = 180
DELAY_MEAN = 90    # Gaussian mean
DELAY_STD = 30     # Gaussian std

# Delays when SWITCHING accounts (seconds)
MIN_DELAY_SWITCH = 20
MAX_DELAY_SWITCH = 45

# Batch breaks (pause after N messages)
BATCH_SIZE_MIN = 5
BATCH_SIZE_MAX = 8
BATCH_BREAK_MIN = 480    # 8 minutes
BATCH_BREAK_MAX = 1200   # 20 minutes

# Typing simulation (seconds)
TYPING_MIN = 2.0
TYPING_MAX = 6.0
TYPING_CHARS_PER_SEC = 25  # Average typing speed

# Block rate thresholds
BLOCK_RATE_YELLOW = 0.05   # 5%  → slow down
BLOCK_RATE_RED = 0.10      # 10% → emergency stop

# Brazil time zone
BRT = ZoneInfo("America/Sao_Paulo")

# Sending windows (BRT)
SENDING_WINDOWS = {
    "weekday": [
        (8, 30, 11, 30),   # Morning: 08:30–11:30
        (12, 30, 14, 0),   # Lunch: 12:30–14:00
        (17, 0, 19, 30),   # Evening: 17:00–19:30
    ],
    "saturday": [
        (9, 0, 12, 0),     # Saturday morning only
    ],
    "sunday": [],           # NO Sunday sending
}

# Phone number validation
COUNTRY_CODES = {
    "55": {"name": "Brazil", "lengths": [12, 13]},      # +55 XX 9XXXX-XXXX
    "353": {"name": "Ireland", "lengths": [11, 12]},     # +353 XX XXX XXXX
    "351": {"name": "Portugal", "lengths": [12]},        # +351 XXX XXX XXX
    "52": {"name": "Mexico", "lengths": [12]},           # +52 XX XXXX XXXX
    "57": {"name": "Colombia", "lengths": [12]},         # +57 XXX XXX XXXX
}
DEFAULT_COUNTRY_CODE = "55"

# Column name patterns for WhatsApp-specific columns
WA_COLUMN_PATTERNS = {
    "phone": [
        "phone", "phone number", "whatsapp", "wa number", "wa",
        "телефон", "номер телефона", "номер", "whatsapp number",
        "celular", "mobile", "número", "telefone",
    ],
    "start_message": [
        "start message", "start_message", "startmessage",
        "message", "initial message", "first message",
        "стартовое сообщение", "сообщение", "текст",
        "body", "wa message", "whatsapp message", "content",
    ],
    "demo": [
        "demo", "demo link", "demo url", "demo_link",
        "демо", "ссылка на демо", "preview",
    ],
    "whatsapp_demo": [
        "whatsapp demo", "whatsapp_demo", "wa demo", "wa_demo",
        "ватсап демо", "whatsapp demo link",
    ],
    "written": [
        "written", "sent", "отправлено", "статус", "status",
        "done", "completed", "wa sent", "wa_sent",
    ],
    "owner_name": [
        "owner", "owner name", "owner_name", "name", "contact name",
        "имя", "имя владельца", "nome",
    ],
    "business_name": [
        "business name", "business_name", "company name", "company",
        "название бизнеса", "empresa", "negócio",
    ],
}

# ============================================================================
# WHAPI.CLOUD API
# ============================================================================

WHAPI_BASE_URL = "https://gate.whapi.cloud"


def whapi_request(endpoint: str, token: str, payload: dict = None, method: str = "POST") -> dict:
    """Make a request to Whapi.cloud API."""
    url = f"{WHAPI_BASE_URL}/{endpoint}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        response = urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT)
        return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        raise Exception(f"Whapi API error {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise Exception(f"Network error: {e.reason}")


def send_whapi_message(token: str, phone_whapi: str, text: str, typing_time: float = 3.0) -> dict:
    """Send a text message via Whapi.cloud API.

    Args:
        token: Whapi.cloud channel API token
        phone_whapi: Phone number in format '5511999990000' (no + or @)
        text: Message text
        typing_time: Seconds to show 'typing...' indicator before sending

    Returns:
        API response dict with message ID and status
    """
    payload = {
        "to": f"{phone_whapi}",
        "body": text,
        "typing_time": typing_time,
    }
    return whapi_request("messages/text", token, payload)


def send_whapi_video_message(
    token: str, phone_whapi: str, video_url: str, caption: str,
    typing_time: float = 3.0,
) -> dict:
    """Send a video message with caption via Whapi.cloud API.

    The video + caption render as a SINGLE WhatsApp bubble (not two messages).

    Args:
        token: Whapi.cloud channel API token
        phone_whapi: Phone number in format '5511999990000' (no + or @)
        video_url: Public URL of the video file (mp4, webm, etc.)
        caption: Text caption displayed below the video
        typing_time: Seconds to show 'typing...' indicator before sending

    Returns:
        API response dict with message ID and status
    """
    payload = {
        "to": f"{phone_whapi}",
        "media": {"url": video_url},
        "caption": caption,
        "typing_time": typing_time,
    }
    return whapi_request("messages/video", token, payload)


def check_whapi_health(token: str) -> dict:
    """Check Whapi.cloud channel health and status."""
    try:
        return whapi_request("health", token, method="GET")
    except Exception:
        return {"status": "error"}


# ============================================================================
# PHONE NUMBER UTILITIES
# ============================================================================

def normalize_phone(raw: str, default_code: str = DEFAULT_COUNTRY_CODE) -> str:
    """Normalize phone number to digits-only international format.

    Examples:
        '+55 (11) 99999-0000' → '5511999990000'
        '11999990000' → '5511999990000'  (with default_code='55')
        '353 89 999 0000' → '353899990000'
    """
    # Strip everything except digits and leading +
    digits = re.sub(r"[^\d]", "", raw)

    if not digits:
        return ""

    # Check if already has a known country code
    for code in sorted(COUNTRY_CODES.keys(), key=len, reverse=True):
        if digits.startswith(code):
            return digits

    # No country code found — prepend default
    return default_code + digits


def validate_phone(phone: str) -> tuple:
    """Validate normalized phone number. Returns (is_valid, country, reason)."""
    if not phone or len(phone) < 10:
        return False, None, "too short"

    for code, info in sorted(COUNTRY_CODES.items(), key=lambda x: len(x[0]), reverse=True):
        if phone.startswith(code):
            number_part = phone[len(code):]
            total_len = len(phone)
            if total_len in info["lengths"] or total_len in [l - 1 for l in info["lengths"]] or total_len in [l + 1 for l in info["lengths"]]:
                return True, info["name"], "ok"
            else:
                return False, info["name"], f"invalid length {total_len} for {info['name']} (expected {info['lengths']})"

    # Unknown country code — allow if reasonable length
    if 10 <= len(phone) <= 15:
        return True, "Unknown", "ok"

    return False, None, f"invalid length {len(phone)}"


# ============================================================================
# TIMING ENGINE
# ============================================================================

def gaussian_delay(mean: float = DELAY_MEAN, std: float = DELAY_STD,
                   min_val: float = MIN_DELAY_SAME, max_val: float = MAX_DELAY_SAME) -> float:
    """Generate a human-like Gaussian random delay."""
    delay = random.gauss(mean, std)
    delay = max(min_val, min(max_val, delay))
    # Add jitter ±15%
    jitter = delay * random.uniform(-0.15, 0.15)
    return delay + jitter


def switch_account_delay() -> float:
    """Delay when switching between accounts."""
    return random.uniform(MIN_DELAY_SWITCH, MAX_DELAY_SWITCH)


def batch_break_delay() -> float:
    """Long pause between batches to mimic human behavior."""
    return random.uniform(BATCH_BREAK_MIN, BATCH_BREAK_MAX)


def typing_time_for_message(text: str) -> float:
    """Calculate realistic typing time based on message length."""
    char_count = len(text)
    base_time = char_count / TYPING_CHARS_PER_SEC
    # Clamp to realistic range and add variance
    base_time = max(TYPING_MIN, min(TYPING_MAX, base_time))
    return base_time + random.uniform(-0.5, 0.5)


def is_in_sending_window() -> tuple:
    """Check if current time (BRT) is within a sending window.

    Returns: (is_allowed, minutes_until_next_window, window_name)
    """
    now = datetime.now(BRT)
    weekday = now.weekday()  # 0=Mon, 6=Sun

    if weekday == 6:  # Sunday
        # Next window: Monday 08:30
        tomorrow = now + timedelta(days=1)
        next_window = tomorrow.replace(hour=8, minute=30, second=0, microsecond=0)
        minutes_until = (next_window - now).total_seconds() / 60
        return False, minutes_until, "Sunday — no sending"

    if weekday == 5:  # Saturday
        windows = SENDING_WINDOWS["saturday"]
    else:
        windows = SENDING_WINDOWS["weekday"]

    for h_start, m_start, h_end, m_end in windows:
        window_start = now.replace(hour=h_start, minute=m_start, second=0, microsecond=0)
        window_end = now.replace(hour=h_end, minute=m_end, second=0, microsecond=0)
        if window_start <= now <= window_end:
            return True, 0, f"{h_start:02d}:{m_start:02d}–{h_end:02d}:{m_end:02d} BRT"

    # Not in any window — find next one
    for h_start, m_start, h_end, m_end in windows:
        window_start = now.replace(hour=h_start, minute=m_start, second=0, microsecond=0)
        if now < window_start:
            minutes_until = (window_start - now).total_seconds() / 60
            return False, minutes_until, f"next: {h_start:02d}:{m_start:02d} BRT"

    # Past all windows today — next is tomorrow
    if weekday == 4:  # Friday → Saturday
        next_windows = SENDING_WINDOWS["saturday"]
    elif weekday == 5:  # Saturday → Monday
        tomorrow = now + timedelta(days=2)
        next_windows = SENDING_WINDOWS["weekday"]
    else:
        tomorrow = now + timedelta(days=1)
        next_windows = SENDING_WINDOWS["weekday"]

    if weekday == 5:
        tomorrow = now + timedelta(days=2)
    else:
        tomorrow = now + timedelta(days=1)

    if next_windows:
        h_start, m_start = next_windows[0][0], next_windows[0][1]
        next_window = tomorrow.replace(hour=h_start, minute=m_start, second=0, microsecond=0)
        minutes_until = (next_window - now).total_seconds() / 60
        return False, minutes_until, f"next: {tomorrow.strftime('%A')} {h_start:02d}:{m_start:02d} BRT"

    return False, 60, "no windows available"


def wait_for_sending_window():
    """Wait until we're inside a valid sending window."""
    while True:
        allowed, minutes_until, window_name = is_in_sending_window()
        if allowed:
            return window_name
        print(f"  ⏳ Outside sending window ({window_name}). Waiting {int(minutes_until)} min...")
        # Wait in chunks (check every 5 min in case clock changes)
        wait_sec = min(minutes_until * 60, 300)
        time.sleep(wait_sec)


# ============================================================================
# STATE MANAGEMENT (persistent across restarts)
# ============================================================================

def load_daily_state() -> dict:
    """Load persistent daily send state. Resets if date changed."""
    today = datetime.now().strftime("%Y-%m-%d")
    if DAILY_STATE_FILE.exists():
        try:
            with open(DAILY_STATE_FILE) as f:
                data = json.load(f)
            if data.get("date") == today:
                return data
        except (json.JSONDecodeError, KeyError):
            pass
    return {
        "date": today,
        "accounts": {},       # phone → send count
        "blocks": {},         # phone → block/fail count
        "total_sent": 0,
        "last_account": None,
    }


def save_daily_state(state: dict):
    """Save daily state to disk."""
    DAILY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DAILY_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def record_send_state(state: dict, account_phone: str):
    """Record a successful send."""
    state["accounts"][account_phone] = state["accounts"].get(account_phone, 0) + 1
    state["total_sent"] = state.get("total_sent", 0) + 1
    state["last_account"] = account_phone
    save_daily_state(state)


def record_block_state(state: dict, account_phone: str):
    """Record a block/failure."""
    state["blocks"][account_phone] = state["blocks"].get(account_phone, 0) + 1
    save_daily_state(state)


def get_block_rate(state: dict, account_phone: str) -> float:
    """Calculate block rate for an account."""
    sent = state["accounts"].get(account_phone, 0)
    blocks = state["blocks"].get(account_phone, 0)
    if sent == 0:
        return 0.0
    return blocks / sent


# ============================================================================
# ACCOUNT MANAGEMENT
# ============================================================================

def load_whapi_channels(env_vars: dict) -> list:
    """Load Whapi.cloud channel configurations from env vars."""
    state = load_daily_state()
    channels = []

    for i in range(1, 11):  # Support up to 10 channels
        token_key = f"WHAPI_CHANNEL_{i}_TOKEN"
        phone_key = f"WHAPI_CHANNEL_{i}_PHONE"
        if token_key in env_vars:
            phone = env_vars.get(phone_key, f"channel_{i}")
            already_sent = state.get("accounts", {}).get(phone, 0)
            channels.append({
                "token": env_vars[token_key],
                "phone": phone,
                "sent_today": already_sent,
                "index": i,
            })

    return channels


def select_next_channel(channels: list, state: dict, daily_limit: int,
                        slowdown: bool = False) -> dict:
    """Select the next channel to send from.

    Round-robin rotation, skipping channels that hit their daily limit or have
    high block rates.
    """
    last_account = state.get("last_account")

    # Sort channels by sent count (least-used first for even distribution)
    available = []
    for ch in channels:
        sent = state.get("accounts", {}).get(ch["phone"], 0)
        if sent >= daily_limit:
            continue  # Hit daily limit

        block_rate = get_block_rate(state, ch["phone"])
        if block_rate >= BLOCK_RATE_RED:
            print(f"  🚫 Channel {ch['phone']} blocked (block rate {block_rate:.1%}). Skipping.")
            continue  # Emergency: too many blocks

        if ch["phone"] == last_account and len(channels) > 1:
            continue  # Don't send consecutive from same account

        available.append((ch, sent, block_rate))

    if not available:
        # Fallback: allow same account if it's the only one
        for ch in channels:
            sent = state.get("accounts", {}).get(ch["phone"], 0)
            if sent < daily_limit:
                block_rate = get_block_rate(state, ch["phone"])
                if block_rate < BLOCK_RATE_RED:
                    available.append((ch, sent, block_rate))

    if not available:
        return None  # All channels exhausted

    # Pick least-used channel
    available.sort(key=lambda x: x[1])
    return available[0][0]


# ============================================================================
# GOOGLE SHEETS INTEGRATION
# ============================================================================

def wa_match_column(header: str, pattern_key: str) -> bool:
    """Check if a column header matches a WA pattern key."""
    header_lower = header.lower().strip()
    if not header_lower:
        return False
    for pattern in WA_COLUMN_PATTERNS.get(pattern_key, []):
        if header_lower == pattern:
            return True
        if len(header_lower) > 3 and pattern in header_lower:
            return True
    return False


def wa_find_columns(headers: list) -> dict:
    """Find column indices using WA-specific patterns."""
    columns = {}
    assigned = set()

    # Pass 1: exact matches
    for i, header in enumerate(headers):
        header_lower = header.lower().strip()
        if not header_lower:
            continue
        for key in WA_COLUMN_PATTERNS:
            if key in columns:
                continue
            if header_lower in WA_COLUMN_PATTERNS[key]:
                columns[key] = {"index": i, "name": header}
                assigned.add(i)
                break

    # Pass 2: substring matches
    for i, header in enumerate(headers):
        if i in assigned:
            continue
        for key in WA_COLUMN_PATTERNS:
            if key in columns:
                continue
            if wa_match_column(header, key):
                columns[key] = {"index": i, "name": header}
                assigned.add(i)
                break

    return columns


def get_cell(row: list, col_info: dict) -> str:
    """Safely get cell value from row."""
    if col_info is None:
        return ""
    idx = col_info["index"]
    if idx < len(row):
        return row[idx].strip()
    return ""


# ============================================================================
# CONTENT VARIATION (micro-uniqueness)
# ============================================================================

def add_micro_variation(text: str) -> str:
    """Add invisible micro-variations to make each message unique to WhatsApp's hash.

    - Random zero-width spaces (invisible)
    - Optional trailing period/no period
    - Minor whitespace variations
    """
    # 1. Randomly insert zero-width space between 1-2 random word boundaries
    words = text.split()
    if len(words) > 5:
        positions = random.sample(range(1, len(words)), min(2, len(words) - 1))
        for pos in sorted(positions, reverse=True):
            words.insert(pos, "\u200b")  # Zero-width space
        text = " ".join(words).replace(" \u200b ", "\u200b")

    # 2. Trailing punctuation variation
    if text.endswith("?"):
        pass  # Keep questions as-is
    elif text.endswith("."):
        if random.random() < 0.3:
            text = text[:-1]  # Remove period 30% of time
    elif not text[-1] in ".!?":
        if random.random() < 0.2:
            text = text + "."  # Add period 20% of time

    return text


# ============================================================================
# TELEGRAM NOTIFICATIONS
# ============================================================================

def send_live_notification(env_vars: dict, message: str):
    """Send a short Telegram notification (for live progress)."""
    token = env_vars.get("TELEGRAM_BOT_TOKEN")
    chat_ids_str = env_vars.get("TELEGRAM_REPORT_CHAT_ID", "")

    if not token or not chat_ids_str:
        return

    chat_ids = [cid.strip() for cid in chat_ids_str.split(",") if cid.strip()]

    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = json.dumps({
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT)
        except Exception:
            pass


# ============================================================================
# MAIN COMMANDS
# ============================================================================

def cmd_validate(spreadsheet_id: str, env_vars: dict):
    """Validate sheet structure and Whapi.cloud channels."""
    print("=" * 60)
    print("VALIDATION: Checking sheet and channels")
    print("=" * 60)

    # 1. Check Whapi channels
    channels = load_whapi_channels(env_vars)
    if not channels:
        print("\n❌ ERROR: No Whapi.cloud channels configured in .env.local")
        print("Add at least one channel:")
        print("  WHAPI_CHANNEL_1_TOKEN=your_token")
        print("  WHAPI_CHANNEL_1_PHONE=5511999990000")
        sys.exit(1)

    print(f"\n✅ Found {len(channels)} Whapi.cloud channel(s):")
    for ch in channels:
        health = check_whapi_health(ch["token"])
        status = health.get("status", {})
        print(f"  • Channel {ch['index']}: {ch['phone']} — {status}")

    # 2. Check sheet
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)

    if not rows:
        print("\n❌ ERROR: Sheet is empty.")
        sys.exit(1)

    headers = rows[0]
    columns = wa_find_columns(headers)

    print(f"\n📊 Sheet columns found: {[h for h in headers if h.strip()]}")

    # Check required columns (WhatsApp Demo is MANDATORY — video-first model)
    required = ["phone", "start_message", "whatsapp_demo"]
    missing = [r for r in required if r not in columns]

    if missing:
        print(f"\n❌ ERROR: Missing required columns: {missing}")
        if "whatsapp_demo" in missing:
            print("❌ WhatsApp Demo column is MANDATORY — must contain direct video file URLs (.mp4)")
            print("   Add a column named 'WhatsApp Demo' with public URLs to demo videos.")
        print("Required: Phone + Start Message + WhatsApp Demo (video URL)")
        print(f"Found columns: {list(columns.keys())}")
        sys.exit(1)

    print(f"\n✅ Required columns found:")
    for key, info in columns.items():
        print(f"  • {key} → column '{info['name']}' (index {info['index']})")

    # Video-first: all messages sent as video+caption
    print(f"\n🎬 VIDEO-FIRST MODE: All messages will be sent as video+caption (single bubble)")
    print(f"   Rows without a video URL in WhatsApp Demo will be SKIPPED.")

    # 3. Count rows
    data_rows = rows[1:]
    written_col = columns.get("written")
    total = len(data_rows)
    sent = 0
    pending = 0

    default_code = env_vars.get("WA_DEFAULT_COUNTRY_CODE", DEFAULT_COUNTRY_CODE)
    invalid_phones = 0

    for row in data_rows:
        phone_raw = get_cell(row, columns["phone"])
        message = get_cell(row, columns["start_message"])
        is_sent = get_cell(row, written_col).lower() in ("yes", "да", "sent", "done", "true", "1")

        if is_sent:
            sent += 1
        elif phone_raw and message:
            phone = normalize_phone(phone_raw, default_code)
            is_valid, country, reason = validate_phone(phone)
            if is_valid:
                pending += 1
            else:
                invalid_phones += 1

    print(f"\n📈 Summary:")
    print(f"  Total rows: {total}")
    print(f"  Already sent: {sent}")
    print(f"  Pending to send: {pending}")
    if invalid_phones:
        print(f"  ⚠️  Invalid phones: {invalid_phones}")
    print(f"  Empty (no phone/message): {total - sent - pending - invalid_phones}")

    state = load_daily_state()
    print(f"\n📅 Today's sends:")
    for ch in channels:
        ch_sent = state.get("accounts", {}).get(ch["phone"], 0)
        print(f"  • {ch['phone']}: {ch_sent} sent today")

    print("\n✅ Validation passed. Ready to send.")


def cmd_send(spreadsheet_id: str, env_vars: dict, daily_limit: int = None,
             live_notify: bool = False, dry_run: bool = False):
    """Send WhatsApp messages with full anti-ban protection."""

    mode = "DRY RUN" if dry_run else "SENDING"
    print("=" * 60)
    print(f"WA-OUTREACH: {mode}")
    print("=" * 60)

    # Load config overrides from env
    if daily_limit is None:
        daily_limit = int(env_vars.get("WA_DAILY_LIMIT_PER_ACCOUNT", DEFAULT_DAILY_LIMIT))
    daily_limit = min(daily_limit, HARD_MAX_DAILY_LIMIT)

    default_code = env_vars.get("WA_DEFAULT_COUNTRY_CODE", DEFAULT_COUNTRY_CODE)

    # Override timing from env if present
    min_delay_same = int(env_vars.get("WA_MIN_DELAY_SAME_ACCOUNT", MIN_DELAY_SAME))
    max_delay_same = int(env_vars.get("WA_MAX_DELAY_SAME_ACCOUNT", MAX_DELAY_SAME))
    batch_min = int(env_vars.get("WA_BATCH_SIZE_MIN", BATCH_SIZE_MIN))
    batch_max = int(env_vars.get("WA_BATCH_SIZE_MAX", BATCH_SIZE_MAX))
    break_min = int(env_vars.get("WA_BATCH_BREAK_MIN", BATCH_BREAK_MIN))
    break_max = int(env_vars.get("WA_BATCH_BREAK_MAX", BATCH_BREAK_MAX))

    # Load channels
    channels = load_whapi_channels(env_vars)
    if not channels:
        print("❌ No Whapi.cloud channels configured.")
        sys.exit(1)

    print(f"📱 Channels: {len(channels)} | Limit: {daily_limit}/channel/day")

    # Check channel health
    for ch in channels:
        if not dry_run:
            health = check_whapi_health(ch["token"])
            print(f"  • {ch['phone']}: {health.get('status', 'unknown')}")

    # Load sheet
    service = get_sheets_service()
    rows = read_sheet(service, spreadsheet_id)
    headers = rows[0]
    columns = wa_find_columns(headers)
    sheet_title = get_sheet_title(service, spreadsheet_id)

    # Ensure "Written" column exists
    if "written" not in columns:
        col_idx = add_column_if_missing(service, spreadsheet_id, sheet_title, headers, "WA Sent")
        columns["written"] = {"index": col_idx, "name": "WA Sent"}
        headers.append("WA Sent")
        print(f"  📝 Added 'WA Sent' column at index {col_idx}")

    # Video-first: WhatsApp Demo column is MANDATORY
    if "whatsapp_demo" not in columns:
        print(f"❌ ERROR: WhatsApp Demo column not found. Cannot send without video URLs.")
        print(f"   Add a column named 'WhatsApp Demo' with direct video file URLs (.mp4).")
        sys.exit(1)

    print(f"🎬 VIDEO-FIRST MODE: All messages sent as video+caption (single bubble)")

    # Build send queue
    data_rows = rows[1:]
    queue = []
    video_count = 0
    no_video_count = 0

    for row_idx, row in enumerate(data_rows):
        phone_raw = get_cell(row, columns["phone"])
        message = get_cell(row, columns["start_message"])
        is_sent = get_cell(row, columns.get("written")).lower() in ("yes", "да", "sent", "done", "true", "1")

        if is_sent or not phone_raw or not message:
            continue

        phone = normalize_phone(phone_raw, default_code)
        is_valid, country, reason = validate_phone(phone)

        if not is_valid:
            print(f"  ⚠️  Row {row_idx + 2}: Invalid phone '{phone_raw}' ({reason}). Skipping.")
            continue

        owner = get_cell(row, columns.get("owner_name"))
        business = get_cell(row, columns.get("business_name"))
        video_url = get_cell(row, columns.get("whatsapp_demo"))

        if not video_url:
            no_video_count += 1
            print(f"  ⚠️  Row {row_idx + 2}: No video URL in WhatsApp Demo. Skipping.")
            continue

        video_count += 1

        queue.append({
            "row_index": row_idx + 1,  # 0-based in data (row 0 = header)
            "phone": phone,
            "phone_raw": phone_raw,
            "message": message,
            "owner": owner,
            "business": business,
            "country": country,
            "video_url": video_url,
        })

    print(f"\n📋 Queue: {len(queue)} video+caption messages to send")
    if no_video_count:
        print(f"  ⚠️  Skipped {no_video_count} rows without video URL in WhatsApp Demo")

    if not queue:
        print("✅ Nothing to send. All rows processed.")
        return

    # --- SENDING LOOP ---
    state = load_daily_state()
    session_stats = {
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "by_account": defaultdict(int),
        "errors": [],
        "video_sent": 0,
    }
    batch_counter = 0
    batch_size = random.randint(batch_min, batch_max)
    slowdown_mode = False

    for i, item in enumerate(queue):
        # 1. Check sending window
        if not dry_run:
            window_name = wait_for_sending_window()

        # 2. Select channel
        channel = select_next_channel(channels, state, daily_limit, slowdown_mode)
        if channel is None:
            print(f"\n🔒 All channels exhausted (daily limit reached).")
            break

        # 3. Check block rate
        block_rate = get_block_rate(state, channel["phone"])
        if block_rate >= BLOCK_RATE_RED:
            print(f"\n🚨 EMERGENCY STOP: Block rate {block_rate:.1%} for {channel['phone']}")
            send_live_notification(env_vars,
                f"🚨 <b>WA-OUTREACH EMERGENCY STOP</b>\n"
                f"Block rate: {block_rate:.1%}\n"
                f"Account: {channel['phone']}\n"
                f"Sent: {session_stats['sent']}")
            break

        if block_rate >= BLOCK_RATE_YELLOW:
            if not slowdown_mode:
                print(f"  ⚠️  Block rate {block_rate:.1%} for {channel['phone']} — slowing down")
                slowdown_mode = True

        # 4. Apply message variation
        message_text = add_micro_variation(item["message"])
        typing_sec = typing_time_for_message(message_text)

        # 5. Send or simulate
        label = item.get("owner") or item.get("business") or item["phone"]

        # All messages are video+caption (video-first model)
        video_url = item["video_url"]

        if dry_run:
            print(f"  [{i+1}/{len(queue)}] 🔍 DRY RUN 🎬 → {label} ({item['phone'][:8]}...)")
            print(f"    Channel: {channel['phone']} | Typing: {typing_sec:.1f}s")
            print(f"    Video: {video_url[:80]}...")
            print(f"    Caption: {message_text[:80]}...")
            session_stats["sent"] += 1
            session_stats["by_account"][channel["phone"]] += 1
            session_stats["video_sent"] += 1
        else:
            try:
                print(f"  [{i+1}/{len(queue)}] 🎬 Sending video+caption → {label} ({item['phone'][:8]}...)")

                result = send_whapi_video_message(
                    channel["token"], item["phone"], video_url,
                    message_text, typing_sec
                )

                msg_id = result.get("message", {}).get("id", result.get("id", "unknown"))
                print(f"    ✅ Sent via {channel['phone']} (msg: {msg_id})")

                # Mark as sent in sheet
                update_sheet_cell(
                    service, spreadsheet_id, sheet_title,
                    item["row_index"] + 1,  # +1 because row_index is 0-based data, header is row 0
                    columns["written"]["index"],
                    "yes"
                )

                record_send_state(state, channel["phone"])
                session_stats["sent"] += 1
                session_stats["by_account"][channel["phone"]] += 1
                session_stats["video_sent"] += 1

            except Exception as e:
                error_msg = str(e)
                print(f"    ❌ Failed: {error_msg[:100]}")
                session_stats["failed"] += 1
                session_stats["errors"].append(f"{label}: {error_msg[:80]}")

                # Track as potential block
                if "blocked" in error_msg.lower() or "ban" in error_msg.lower() or "spam" in error_msg.lower():
                    record_block_state(state, channel["phone"])

                # Retry logic: skip after 3 consecutive failures
                continue

        batch_counter += 1

        # 6. Live notification
        if live_notify and session_stats["sent"] > 0 and session_stats["sent"] % 10 == 0:
            send_live_notification(env_vars,
                f"📤 <b>WA-Outreach Progress</b>\n"
                f"Sent: {session_stats['sent']}/{len(queue)}\n"
                f"Failed: {session_stats['failed']}\n"
                f"Current channel: {channel['phone']}")

        # 7. Delays
        if not dry_run and i < len(queue) - 1:
            # Batch break?
            if batch_counter >= batch_size:
                break_time = batch_break_delay()
                print(f"\n  ☕ Batch break: {int(break_time)}s ({int(break_time/60)}min)...")
                time.sleep(break_time)
                batch_counter = 0
                batch_size = random.randint(batch_min, batch_max)
            else:
                # Normal delay
                next_channel = select_next_channel(channels, state, daily_limit, slowdown_mode)
                if next_channel and next_channel["phone"] != channel["phone"]:
                    delay = switch_account_delay()
                    if slowdown_mode:
                        delay += 30  # Extra 30s in slowdown
                    print(f"    ⏱️  Switch delay: {int(delay)}s")
                else:
                    delay = gaussian_delay(
                        mean=DELAY_MEAN,
                        std=DELAY_STD,
                        min_val=min_delay_same,
                        max_val=max_delay_same,
                    )
                    if slowdown_mode:
                        delay += 30
                    print(f"    ⏱️  Delay: {int(delay)}s")
                time.sleep(delay)

    # --- REPORT ---
    remaining = len(queue) - session_stats["sent"] - session_stats["failed"]

    print(f"\n{'=' * 60}")
    print(f"SESSION COMPLETE")
    print(f"{'=' * 60}")
    print(f"  ✅ Sent: {session_stats['sent']} (all video+caption)")
    print(f"  ❌ Failed: {session_stats['failed']}")
    print(f"  ⏳ Remaining: {remaining}")
    print(f"\n  By account:")
    for acc, count in session_stats["by_account"].items():
        block_rate = get_block_rate(state, acc)
        status = "🟢" if block_rate < BLOCK_RATE_YELLOW else ("🟡" if block_rate < BLOCK_RATE_RED else "🔴")
        print(f"    {status} {acc}: {count} sent (block rate: {block_rate:.1%})")

    # Send Telegram report
    if not dry_run:
        send_telegram_report(env_vars, {
            "sent": session_stats["sent"],
            "failed": session_stats["failed"],
            "remaining": remaining,
            "by_mailbox": dict(session_stats["by_account"]),
            "errors": session_stats["errors"],
            "daily_limit_reached": channel is None if 'channel' in dir() else False,
        }, title="WA-Outreach")


def cmd_report(spreadsheet_id: str, env_vars: dict):
    """Show current state report without sending."""
    print("=" * 60)
    print("WA-OUTREACH: STATUS REPORT")
    print("=" * 60)

    state = load_daily_state()
    channels = load_whapi_channels(env_vars)

    print(f"\n📅 Date: {state.get('date', 'unknown')}")
    print(f"📊 Total sent today: {state.get('total_sent', 0)}")

    print(f"\n📱 Channels:")
    for ch in channels:
        sent = state.get("accounts", {}).get(ch["phone"], 0)
        blocks = state.get("blocks", {}).get(ch["phone"], 0)
        block_rate = blocks / sent if sent > 0 else 0
        status = "🟢" if block_rate < BLOCK_RATE_YELLOW else ("🟡" if block_rate < BLOCK_RATE_RED else "🔴")
        print(f"  {status} {ch['phone']}: {sent} sent, {blocks} blocks ({block_rate:.1%})")

    # Check sending window
    allowed, minutes_until, window_name = is_in_sending_window()
    if allowed:
        print(f"\n🟢 Currently in sending window: {window_name}")
    else:
        print(f"\n🔴 Outside sending window. {window_name} (in {int(minutes_until)} min)")


# ============================================================================
# CLI ENTRYPOINT
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    # Load environment
    env_vars = load_env(ENV_FILE)

    if command == "validate":
        if len(sys.argv) < 3:
            print("Usage: python3 send_wa.py validate <SPREADSHEET_ID>")
            sys.exit(1)
        cmd_validate(sys.argv[2], env_vars)

    elif command in ("send", "dry-run"):
        if len(sys.argv) < 3:
            print(f"Usage: python3 send_wa.py {command} <SPREADSHEET_ID> [--limit N] [--live-notify]")
            sys.exit(1)

        spreadsheet_id = sys.argv[2]
        daily_limit = None
        live_notify = False

        # Parse optional flags
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--limit" and i + 1 < len(sys.argv):
                daily_limit = int(sys.argv[i + 1])
                if daily_limit > HARD_MAX_DAILY_LIMIT:
                    print(f"❌ Limit {daily_limit} exceeds hard max {HARD_MAX_DAILY_LIMIT}. Capping.")
                    daily_limit = HARD_MAX_DAILY_LIMIT
                i += 2
            elif sys.argv[i] == "--live-notify":
                live_notify = True
                i += 1
            else:
                i += 1

        cmd_send(
            spreadsheet_id, env_vars,
            daily_limit=daily_limit,
            live_notify=live_notify,
            dry_run=(command == "dry-run"),
        )

    elif command == "report":
        if len(sys.argv) < 3:
            print("Usage: python3 send_wa.py report <SPREADSHEET_ID>")
            sys.exit(1)
        cmd_report(sys.argv[2], env_vars)

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
