---
name: create-wa-message
description: >
  Generate hyper-personalized WhatsApp cold outreach messages for B2B prospects
  (coaches, consultants, infobusiness) in Brazil, Ireland, Portugal, Colombia, Mexico.
  We sell an AI assistant that works on the prospect's website AND in their WhatsApp —
  booking appointments, answering FAQs, handling leads 24/7. We pre-build a working demo
  on each prospect's site and record a demo video showing it in action. Messages are sent
  as video+caption (single WhatsApp bubble). Reads prospect data from Google Sheets.
  MANDATORY TRIGGERS: WhatsApp message, outreach message, cold message, create-wa-message,
  write message, generate outreach, WhatsApp outreach, personalized message, B2B message,
  wa message, сообщение WhatsApp, написать сообщение.
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, WebFetch, WebSearch, Task
---

# create-wa-message — WhatsApp Cold Outreach Message Generator

You generate personalized WhatsApp cold outreach messages for B2B service professionals
(coaches, consultants, infobusiness). Each message references the working demo we already
built for the prospect's business.

Your single goal: **get a REPLY.** Not a sale. Not a booking. Just a reply.

**Key advantage:** We already built a working demo BEFORE contacting the prospect. The
message mentions this pre-built demo as proof we invested time in them specifically.

**VIDEO-FIRST MODEL:** Messages are sent as video+caption (single WhatsApp bubble). The
demo video is attached alongside the text caption. The text you generate is the VIDEO CAPTION
— it frames the context for why the prospect should watch the attached demo video. CTAs should
ask for their REACTION to the video ("have a look and lmk what you think"), NOT ask permission
to send something ("can I send it?").

## Phase 1: QUALIFICATION — Get the Google Sheets link

**CRITICAL: Do NOT proceed without a valid Google Sheets link.**

If the user did not provide a Google Sheets URL:

1. Ask: "Пришлите ссылку на Google Sheets таблицу с лидами."
2. Wait for the link.
3. Extract `SPREADSHEET_ID` from URL (string between `/d/` and next `/`).

## Phase 2: VALIDATION — Verify sheet structure

```bash
python3 /Users/devlink007/DemoSender/.claude/skills/create-wa-message/scripts/generate_messages.py validate <SPREADSHEET_ID>
```

Required: **Phone** column.

Recommended: **Company Info** (or Business Name), **Website**, **Demo** (demo link).

Start Message and Follow Up columns will be auto-created if missing.

If validation fails — tell user which columns are missing.
If passes — show stats and ask for confirmation before generating.

## Phase 3: PARALLEL MESSAGE GENERATION

**This skill uses parallel sub-agents to process multiple leads simultaneously (5 at a time).**

All message writing rules are in `RULES.md` (same directory as this file). Sub-agents read that file before generating.

Detailed references (sub-agents read only when needed):
- `references/architectures.md` — 8 message architectures with selection matrix
- `references/anti-fingerprinting.md` — WhatsApp ML detection avoidance rules
- `references/language-guides.md` — PT/EN/ES cultural and language guidelines

**Step 1:** Get the list of leads without start messages:

```bash
python3 /Users/devlink007/DemoSender/.claude/skills/create-wa-message/scripts/generate_messages.py list-pending <SPREADSHEET_ID>
```

**Step 2:** Split pending leads into batches of 5.

**Step 3:** For each batch, spawn **5 parallel Task agents** (one per lead) in a single message with 5 tool calls. Use `subagent_type: "general-purpose"` for each.

**Sub-agent prompt template** (fill in SPREADSHEET_ID, ROW, and ASSIGNED values for each):

```text
Process one lead and generate a personalized WhatsApp outreach message.

SPREADSHEET: {SPREADSHEET_ID}
ROW: {ROW_NUMBER}
SCRIPT: /Users/devlink007/DemoSender/.claude/skills/create-wa-message/scripts/generate_messages.py

ASSIGNED ARCHITECTURE: {ARCH_NUMBER} (1-8, pre-assigned by orchestrator to ensure diversity)
ASSIGNED LOSS ANGLE: {LOSS_ANGLE} (1-6, pre-assigned to ensure no two consecutive leads share the same angle)
ASSIGNED ELEMENT ORDER: {X/Y/Z} (pre-assigned for anti-fingerprinting)

Steps:
1. Read the rules: /Users/devlink007/DemoSender/.claude/skills/create-wa-message/RULES.md
   PAY SPECIAL ATTENTION to: Rule 2 (Loss Aversion), Rule 8 (Two Variants), Rule 10 (Product Naming), Rule 11 (I vs We), Rule 12 (Curiosity Gap), Rule 13 (Anti-Fingerprinting)
2. Get lead data:
   python3 {SCRIPT} get-row {SPREADSHEET_ID} {ROW_NUMBER}
3. Analyze the lead:
   - Parse company_info for: niche, services, clients, location, unique angle
   - Check demo_link (website demo link from Demo column) — determines Variant A or B (Rule 8)
   - whatsapp_demo = video URL for sending (used by wa-outreach, NOT referenced in message text)
   - Note the language (default: "pt")
   - If website is present, WebFetch it for additional personalization data
4. Use the ASSIGNED architecture, loss angle, and element order.
5. Determine VARIANT (Rule 8):
   - **Variant A** (demo_link EXISTS): mention BOTH site + WhatsApp, CTA = reaction-based ("have a look and lmk what you think")
   - **Variant B** (NO demo_link): still mention both site + WhatsApp, CTA = offer-based ("can send you a link to test live")
6. Write the FIRST MESSAGE (this is a VIDEO CAPTION — the demo video is attached alongside):
   - 30-50 words ideal, hard limit 70 words, 5th-7th grade reading level
   - Contains "already built for you" reciprocity trigger (Rule 1)
   - Contains a SPECIFIC loss scenario relevant to their niche (Rule 2) using the assigned loss angle
   - References specific details from company_info (Rule 6)
   - ALWAYS mentions BOTH site AND WhatsApp (Rule 8 — both variants)
   - CTA matches variant: reaction-based (A) or offer-based (B) (Rule 8)
   - Only use "AI assistant" / "assistente AI" for product naming — no chatbot, bot, automation, demo, solution (Rule 10)
   - Use "I" for personal actions, "we" only for team references (Rule 11)
   - Frame context for the video — don't over-explain (the video shows the demo) (Rule 12)
   - No links, no company name, no pitch, max 1 emoji
   - Matches language from the language column (pt/en/es, default pt)
   - Vary sentence rhythm from the assigned element order (Rule 13b)
   - SIGNAL-ANCHORED: Reference at least ONE specific detail from their business (program name, service, method) — not generic niche references
7. Write the FOLLOW-UP MESSAGE (sent ONLY to non-responders after 3-4 days):
   - References the video that was already sent
   - **Variant A** (demo_link exists): includes demo link for live testing
   - **Variant B** (no demo_link): offers to arrange a live test
   - Soft question at end
8. Save first message:
   python3 {SCRIPT} save-message {SPREADSHEET_ID} {ROW_NUMBER} <<'EOF'
   {first message here}
   EOF
9. Save follow-up:
   python3 {SCRIPT} save-followup {SPREADSHEET_ID} {ROW_NUMBER} <<'EOF'
   {follow-up message here}
   EOF
10. Return a one-line summary: "Row {ROW_NUMBER}: {business_name} - done ({word_count} words, arch #{N}, loss #{ANGLE}, order {X/Y/Z}, variant {A/B}, {lang})"
```

**Step 4:** Wait for all 5 agents to complete. Print batch summary.

**Step 5:** Move to next batch. Repeat steps 3-4 until all leads are processed.

**Step 6:** After all batches complete, proceed to Phase 4 (reporting).

**IMPORTANT:**

- Each sub-agent works independently and saves its own message directly to the sheet.
- If a sub-agent fails or can't find enough info to personalize, it should skip and report "skipped."
- NEVER overwrite an existing start message (only fill empty ones).
- The process is resumable: re-running `list-pending` only shows rows still missing messages.
- ALWAYS ask user for confirmation before starting the parallel generation.
- **Anti-fingerprinting diversity requirements (pre-assign BEFORE spawning agents):**
  - Across the full batch, ensure architecture diversity (5+ different architectures per 10 messages).
  - No two consecutive leads may share the same loss angle (Rule 2 — 6 angles available).
  - No two consecutive leads may share the same element order (Rule 13a — X/Y/Z rotation).
  - The orchestrator pre-assigns architecture, loss angle, and element order to each sub-agent to guarantee diversity.
  - Every message MUST contain a loss scenario (Rule 2) — this is mandatory, not optional.
  - Every message MUST use "AI assistant" / "assistente AI" as the only product name (Rule 10).

---

## Phase 4: REPORTING

After all messages are generated, send the Telegram report:

```bash
python3 /Users/devlink007/DemoSender/.claude/skills/create-wa-message/scripts/generate_messages.py report <SPREADSHEET_ID>
```

## Error handling

- **Sheet not accessible**: Share with `aisheets@aisheets-486216.iam.gserviceaccount.com`
- **No Phone column**: Tell user to add one
- **No company_info or website**: Use whatever is available. If truly nothing to personalize, skip that lead.
- **Message too long**: Rewrite shorter. Target 30-50 words, hard limit 70 words.

## Configuration

All config in `/Users/devlink007/DemoSender/.env.local`.

## Important notes

- NEVER overwrite an existing start message (only fill empty ones)
- ALWAYS ask for confirmation before starting
- EVERY message must be unique — different architecture, different phrasing, different opening
- If you can't personalize it, don't generate it. Skip that lead.
- The process is resumable — only processes rows where Start Message is empty
- NEVER copy example messages from RULES.md. They're for inspiration only.
