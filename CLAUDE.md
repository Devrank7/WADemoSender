# WADemoSender

WhatsApp cold outreach automation for B2B coaches, consultants, and infobusiness leads in Brazil, Ireland, Portugal, Colombia, and Mexico. Researches leads, generates system prompts, records demo videos, generates messages, and sends via Whapi.cloud API.

## Workflow

```text
/system-prompt     → Research leads, generate AI assistant system prompts
/create-wa-message → Generate personalized WhatsApp messages per lead
/wa-emulator-link  → Start emulator server + generate links for video recording
/wa-outreach       → Send WhatsApp messages (video + caption) via Whapi.cloud API
```

Every skill sends a Telegram report after finishing.

## Project structure

```text
WADemoSender/
├── .env.local                          # All credentials (never commit)
├── service_account.json                # Google Sheets service account (never commit)
├── outreach_agent_system_prompt.md     # Sales agent conversation framework
├── output/                             # Avatars, tracking files
├── .claude/
│   ├── settings.json                   # Hooks config
│   ├── hooks/
│   │   ├── notify-progress.sh          # Per-action Telegram notification
│   │   └── notify-complete.sh          # Session completion notification
│   └── skills/
│       ├── _shared/                    # Shared Python utilities
│       │   ├── __init__.py
│       │   ├── config.py               # load_env(), paths, constants
│       │   ├── sheets.py               # Google Sheets API, column matching
│       │   └── telegram.py             # Telegram report sending
│       ├── system-prompt/              # /system-prompt skill (lead research)
│       ├── create-wa-message/          # /create-wa-message skill
│       ├── wa-emulator-link/           # /wa-emulator-link skill
│       ├── wa-demo-video/              # /wa-demo-video skill (emulator server)
│       └── wa-outreach/                # /wa-outreach skill
```

## Skills

### `/system-prompt` — Lead Research & System Prompt Generation

Researches each lead's website, social media, services, prices. Generates a detailed AI assistant system prompt. Works for B2B coaches, consultants, infobusiness.

**Parallel processing:** Sub-agent architecture (3 leads at a time) for faster research.

Script: `generate_prompts.py` — commands: `validate`, `list-pending`, `get-row`, `save-prompt`, `report`

### `/create-wa-message` — WhatsApp Message Generation

Generates personalized WhatsApp cold outreach messages (video + caption format).

Targets: coaches, consultants, infobusiness in Brazil, Ireland, Portugal, Colombia, Mexico.

Key rules: 30-50 words ideal (70 hard limit), signal-anchored personalization, "already built for you" reciprocity, loss aversion, low-friction CTA, "AI assistant" only product name. Target: 30% reply rate.

**Parallel processing:** Sub-agent architecture. Core rules in `RULES.md`, detailed references in `references/` (architectures, anti-fingerprinting, language guides).

Script: `generate_messages.py` — commands: `validate`, `list-pending`, `get-row`, `save-message`, `save-followup`, `report`

### `/wa-emulator-link` — Emulator Link Generator

Starts emulator server on `localhost:8889`, generates emulator URLs per lead. Optional avatar fetching via Playwright from WhatsApp Web.

Script: `generate_links.py` — commands: `validate`, `list-pending`, `generate`, `report`
Script: `fetch_avatars.py` — commands: `status`, `fetch`, `fetch-one`

### `/wa-demo-video` — Demo Video Recording

WhatsApp-styled chat emulator for recording demo videos. Server on port 8889.

Emulator: `emulator/server.py` serves HTML/CSS/JS WhatsApp chat interface.

### `/wa-outreach` — WhatsApp Sending

Sends via Whapi.cloud REST API with multi-account rotation and comprehensive anti-ban protection.

Message types: text-only or video + caption (single WhatsApp bubble).

**Anti-ban protection:**
- Up to 10 Whapi channels with round-robin rotation + geographic matching
- Gaussian delays: 45-180s same account, 20-45s switch
- Batch breaks: every 5-8 messages, 8-20 min pause
- Timezone-aware activity windows (BRT/IST/COT/CST/WET per recipient country)
- Block rate monitoring: >10% = emergency stop
- Reply rate monitoring: target 30%, alert if <15%
- Typing simulation: 2-6 seconds "typing..." indicator
- Number warm-up schedule: 3-10 day gradual ramp
- Feedback loop: session results logged to `output/wa_outreach_log.json`

Limits: 60/channel/day (80 hard cap). Max 2 msg/min (Whapi.cloud recommendation).

Script: `send_wa.py` — commands: `validate`, `send`, `dry-run`, `report`. Flag: `--live-notify`

## Shared module (`_shared/`)

- `load_env()` — loads `.env.local`
- `get_sheets_service()` — Google Sheets API
- `read_sheet()`, `find_columns()`, `update_sheet_cell()`, `add_column_if_missing()` — sheets CRUD
- `send_telegram_report()` — Telegram reports
- `COLUMN_PATTERNS` — fuzzy column matching

Import pattern:
```python
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))
from _shared import load_env, get_sheets_service, ...
```

## Google Sheets

Sheet must be shared with `aisheets@aisheets-486216.iam.gserviceaccount.com` (Editor access).

## Credentials (.env.local)

| Variable | Used by |
|----------|---------|
| `TELEGRAM_BOT_TOKEN` | All skills (reporting) |
| `TELEGRAM_REPORT_CHAT_ID` | All skills |
| `GEMINI_API_KEY` | system-prompt (lead research) |
| `WHAPI_CHANNEL_{1-N}_TOKEN` | wa-outreach (Whapi.cloud API) |
| `WHAPI_CHANNEL_{1-N}_PHONE` | wa-outreach (channel phone number) |
| `WA_DEFAULT_COUNTRY_CODE` | wa-outreach (default: 55 for Brazil) |
| `WA_DAILY_LIMIT_PER_ACCOUNT` | wa-outreach (default: 60) |

## Important conventions

- Never commit `.env.local` or `service_account.json`
- Scripts are idempotent — safe to re-run
- Cold messages must pass anti-AI detection
- Activity windows are timezone-aware per recipient country (BRT/IST/COT/CST/WET)
- Video URLs must be direct file links (not Loom share pages)
- Phone numbers auto-normalized to international format
