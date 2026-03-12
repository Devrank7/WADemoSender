---
name: system-prompt
description: Researches leads from Google Sheets — analyzes their website, Instagram or WhatsApp profile, services, prices, and branding — then generates detailed AI assistant system prompts. Works for both Instagram and WhatsApp outreach. Use when the user wants to generate system prompts, analyze leads, or fill in missing prompts for outreach.
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, WebFetch, WebSearch
---

# System Prompt — Lead Research & Prompt Generation

Research leads and generate personalized AI assistant system prompts.

**Supports:** Instagram (IG DM assistant) and WhatsApp (WA chat assistant). Auto-detected from sheet columns.

**Reference:** `references/prompt-templates.md` — full prompt templates and quality guidelines.

## Phase 1: Get Google Sheets Link

If no URL provided, ask: "Пришлите ссылку на Google Sheets таблицу с лидами."
Extract `SPREADSHEET_ID` from URL (string between `/d/` and next `/`).

## Phase 2: Validate Sheet

```bash
python3 /Users/devlink007/DemoSender/.claude/skills/system-prompt/scripts/generate_prompts.py validate <SPREADSHEET_ID>
```

Platform auto-detected: **Instagram** column → IG mode | **Phone** column → WA mode.
Required: Instagram OR Phone + Website. System Prompt column auto-created if missing.

Ask: "Готово. Начинаю исследование лидов и генерацию системных промтов?"

## Phase 3: Parallel Research & Generation

**3 parallel sub-agents per batch.**

**Step 1:** Get pending leads:
```bash
python3 /Users/devlink007/DemoSender/.claude/skills/system-prompt/scripts/generate_prompts.py list-pending <SPREADSHEET_ID>
```

**Step 2:** Split into batches of 3, spawn parallel Task agents (`subagent_type: "general-purpose"`):

```text
Research one lead and generate a personalized AI assistant system prompt.

SPREADSHEET: {SPREADSHEET_ID}
ROW: {ROW_NUMBER}
SCRIPT: /Users/devlink007/DemoSender/.claude/skills/system-prompt/scripts/generate_prompts.py

Steps:
1. Get lead data:
   python3 {SCRIPT} get-row {SPREADSHEET_ID} {ROW_NUMBER}

2. Research the lead using the SCRAPER (replaces manual WebFetch — saves tokens):
   python3 {SCRIPT} scrape <WEBSITE_URL>
   This returns a structured summary with business name, services, prices, contact info,
   and key page content. Use this as your PRIMARY research source.

   For additional research only if scraper output is thin:
   - WebSearch for Google Maps listing, reviews, social profiles
   - WebFetch ONLY for specific pages the scraper missed (max 1-2 additional fetches)

3. Read the prompt template:
   Read /Users/devlink007/DemoSender/.claude/skills/system-prompt/references/prompt-templates.md
   Use the template matching the detected platform (IG or WA).

4. Generate the system prompt:
   - Fill in ALL sections from the template using scraped data
   - 600-1200 words, include all services/prices found
   - Include 5+ example responses + 5+ anti-examples
   - NO placeholders — omit section if data is missing

5. Save:
   python3 {SCRIPT} save-prompt {SPREADSHEET_ID} {ROW_NUMBER} --file /tmp/prompt_row{ROW_NUMBER}.txt

6. Return: "Row {ROW_NUMBER}: {business_name} - done ({X} chars, {Y} services, platform: {IG/WA})"
```

Wait for batch to complete, print summary, repeat until all leads processed.

**Rules:**
- Never overwrite existing prompts (only fill empty ones)
- Resumable: `list-pending` skips rows with prompts
- If sub-agent can't find enough info, skip and report "skipped"

## Phase 4: Report

```bash
python3 /Users/devlink007/DemoSender/.claude/skills/system-prompt/scripts/generate_prompts.py report <SPREADSHEET_ID>
```

## Error Handling

- **Sheet not accessible**: Share with `aisheets@aisheets-486216.iam.gserviceaccount.com`
- **Website down**: Use WebSearch for additional data. Not a hard block.
- **No info at all**: Skip and log error.

## Config

All credentials in `/Users/devlink007/DemoSender/.env.local`.
