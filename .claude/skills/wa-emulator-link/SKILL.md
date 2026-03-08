---
name: wa-emulator-link
description: >
  Generates WhatsApp emulator links for each lead in Google Sheets. Each link opens
  the WhatsApp chat emulator pre-configured with the lead's business name and AI system
  prompt. After links are generated, the user opens each link, chats with the AI, and
  records a screen recording as the WhatsApp demo video. The recorded demo link is then
  saved to the "WhatsApp Demo" column for use in outreach messages.
  MANDATORY TRIGGERS: WhatsApp emulator, wa emulator, wa demo link, generate wa links,
  WhatsApp demo, wa-emulator-link, эмулятор ватсап, ссылки на эмулятор ватсап.
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# WA Emulator Link — Generate WhatsApp Emulator URLs for Leads

You generate WhatsApp emulator links for each lead in Google Sheets. Each link opens
the WhatsApp chat emulator with the lead's business name pre-loaded. When visited, the
emulator automatically configures the AI system prompt from the spreadsheet so it
responds as the lead's AI assistant.

**Purpose:** After generating links, the user opens each link manually, chats with the
AI assistant (which responds as the prospect's WhatsApp business assistant), and records
the screen. The recording becomes the WhatsApp demo video. The demo link is then saved
to the "WhatsApp Demo" column and referenced in outreach messages by `create-wa-message`
and `wa-outreach` skills.

## Phase 1: START EMULATOR SERVER

Before doing anything else, ensure the WhatsApp emulator server is running on port 8889.

**Check if already running:**
```bash
curl -s http://localhost:8889/ > /dev/null 2>&1 && echo "running" || echo "not running"
```

**If not running — start it in background:**
```bash
python3 /Users/devlink007/DemoSender/.claude/skills/wa-demo-video/emulator/server.py > /tmp/wa_emulator.log 2>&1 &
echo $! > /tmp/wa_emulator.pid
sleep 2
curl -s http://localhost:8889/ > /dev/null 2>&1 && echo "Server started on port 8889" || echo "ERROR: server failed to start — check /tmp/wa_emulator.log"
```

If the server fails to start — show the error from `/tmp/wa_emulator.log` and stop.

## Phase 2: QUALIFICATION — Get the Google Sheets link

**CRITICAL: Do NOT proceed without a valid Google Sheets link.**

If the user did not provide a Google Sheets URL:
1. Ask: "Пришлите ссылку на Google Sheets таблицу с лидами."
2. Wait for the link.
3. Extract `SPREADSHEET_ID` from URL (string between `/d/` and next `/`).

## Phase 3: FETCH AVATARS (Optional but Recommended)

Before generating links, fetch WhatsApp profile pictures for all leads. This opens
WhatsApp Web via Playwright and downloads each contact's avatar to `output/wa_avatars/`.
The emulator will automatically display the avatar when the link is opened.

**Prerequisites:**
- Chrome must be closed (or the WA profile must not be in use by another process)
- WhatsApp Web must be logged in within the Chrome profile
- Set `WA_CHROME_PROFILE_PATH` or `IG_CHROME_PROFILE_PATH` in `.env.local`

**Check avatar status:**
```bash
python3 /Users/devlink007/DemoSender/.claude/skills/wa-emulator-link/scripts/fetch_avatars.py status <SPREADSHEET_ID>
```

**Fetch all avatars:**
```bash
python3 /Users/devlink007/DemoSender/.claude/skills/wa-emulator-link/scripts/fetch_avatars.py fetch <SPREADSHEET_ID>
```

**Fetch a single avatar (for testing):**
```bash
python3 /Users/devlink007/DemoSender/.claude/skills/wa-emulator-link/scripts/fetch_avatars.py fetch-one <PHONE_NUMBER>
```

This will:
1. Open Chrome with the WhatsApp Web session
2. Navigate to each contact's chat via `web.whatsapp.com/send?phone=X`
3. Extract the profile picture (if public)
4. Save to `output/wa_avatars/{phone_digits}.jpg`

If a QR code appears, tell the user to scan it with their phone to log in.
Avatars are cached — running again skips already-downloaded ones.

If the user skips this step, the emulator will show a default WhatsApp silhouette avatar.

## Phase 4: VALIDATION — Verify sheet structure

```bash
python3 /Users/devlink007/DemoSender/.claude/skills/wa-emulator-link/scripts/generate_links.py validate <SPREADSHEET_ID>
```

Required columns: **Phone** (or WhatsApp), **System Prompt**

The "WA Emulator Link" column will be auto-created if missing.
The "WhatsApp Demo" column will be auto-created if missing (for saving demo links later).

If validation fails — tell user which columns are missing.
If passes — show stats and ask for confirmation before generating.

## Phase 5: GENERATE LINKS

```bash
python3 /Users/devlink007/DemoSender/.claude/skills/wa-emulator-link/scripts/generate_links.py generate <SPREADSHEET_ID>
```

This command:
1. Reads all rows from the sheet
2. For each row that has Phone + System Prompt but no WA Emulator Link yet:
   - Extracts business name, phone number
   - Builds the emulator URL: `http://localhost:8889/?name={name}&phone={phone}&spreadsheet={ID}&row={N}`
   - Saves the URL to the "WA Emulator Link" column
3. Prints progress and summary

**The link includes `spreadsheet` and `row` params.** When opened in the browser:
- Displays the lead's business name in the WhatsApp header
- Auto-loads the lead's WhatsApp avatar (if fetched in Phase 3)
- Auto-configures the AI system prompt from the spreadsheet
- Is ready to chat immediately — the AI responds as the prospect's assistant

## Phase 6: RECORDING WORKFLOW

After links are generated, tell the user:

1. Open each link in the browser
2. Chat with the AI — it will respond as the prospect's WhatsApp business assistant
3. Record the screen (the emulator looks like a real WhatsApp chat)
4. Save the recording and paste the demo link into the "WhatsApp Demo" column

The "WhatsApp Demo" column is then picked up by:
- `create-wa-message` — mentions both site demo AND WhatsApp demo in the message
- `wa-outreach` — sends the message referencing both demos

## Phase 7: REPORTING

```bash
python3 /Users/devlink007/DemoSender/.claude/skills/wa-emulator-link/scripts/generate_links.py report <SPREADSHEET_ID>
```

## Error handling

- **Sheet not accessible**: Share with `aisheets@aisheets-486216.iam.gserviceaccount.com`
- **No Phone column**: Tell user to add one
- **No System Prompt**: Link will still work for name display, but AI won't have a prompt configured

## Important notes

- NEVER overwrite an existing emulator link (only fill empty ones)
- ALWAYS ask for confirmation before starting
- The process is resumable — only processes rows where WA Emulator Link is empty
- Links work only when the emulator server is running on localhost:8889
- The emulator auto-configures the system prompt on each visit (always fresh)
- Port 8889 for WhatsApp emulator (vs 8888 for Instagram emulator — both can run simultaneously)
