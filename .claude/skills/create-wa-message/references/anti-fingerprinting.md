# Anti-Fingerprinting Rules — Defeating WhatsApp's ML Detection

WhatsApp uses message similarity detection, hash-based fingerprinting, and ML models to cluster templated messages. Surface-level word swapping doesn't help. You must vary the STRUCTURE and SEMANTICS.

## Rule 13a: STRUCTURAL VARIATION

**Never send two consecutive messages with the same element order.** Vary whether you lead with loss, compliment, observation, or the demo mention.

**Three element orders to rotate:**
- **Order X:** Loss scenario first -> what you built -> question
- **Order Y:** Observation/compliment first -> loss scenario -> what you built -> question
- **Order Z:** What you built first -> WHY you built it (loss scenario) -> question

**RULE: In a batch of 5+, use at least 2 different element orders.**

## Rule 13b: SENTENCE RHYTHM VARIATION

**WhatsApp's ML analyzes sentence cadence.** If every message follows the same rhythm pattern (medium, long, short), that's detectable.

- **Some messages:** Start long, then punch short. "Tava olhando seu site de coaching executivo e notei que nao tem ninguem pra responder quando alguem chega as 23h procurando mentoria. montei algo pra isso. quer ver?"
- **Some messages:** Start short, build. "Oi. montei um assistente AI pro seu site. ele responde quem chega procurando coaching fora do horario comercial, quando ninguem ta la pra responder. posso te mandar?"
- **Some messages:** Fragment-heavy. "seu site de coaching. muito bom. mas 23h, alguem chega com duvida sobre o programa. ninguem responde. montei algo que resolve isso. te interessa?"

**No two consecutive messages should have the same sentence rhythm pattern.**

## Rule 13c: SEMANTIC VARIATION

WhatsApp converts messages into vectors and clusters similar ones. Surface-level word swapping doesn't change the vector.

**What changes the vector (vary these):**
1. **Architecture** (1-8): genuinely different approach = different vector
2. **Loss angle** (Rule 2): "after-hours miss" vs "during-session miss" vs "speed gap" = genuinely different meanings
3. **Demo detail highlighted**: "answers at midnight" vs "qualifies leads" vs "books sessions" = different outcome emphasis
4. **Opening style**: greeting vs observation vs question vs loss vs demo-lead
5. **CTA variation**: "da uma olhada e me fala o que achou" vs "ve o video e me diz" vs "faz sentido?" vs "te interessa?"

**TEST: Summarize this message and the last 3 in one sentence each. If they all sound like "mentioned loss, said they built something, asked to send" — the vectors are too similar. At least 2 elements must genuinely differ.**

## Rule 13d: PAIN ANGLE ROTATION

**RULE: Never use the same pain angle (Rule 2) for two consecutive leads in a batch.** Rotate through all 6 B2B loss scenarios.

**Vary the PRONOUN for the lost lead** — don't always use "someone." Rotate: "alguem", "um lead", "uma pessoa", "um potencial cliente", "quem chega no site", "essa pessoa." Using the same pronoun in every message is a detectable pattern.

## Anti-Spam Uniqueness Rules

1. **No two messages start the same way.** Vary the opening STRUCTURE, not just the name.
2. **In a batch of 10: minimum 5 different architectures.**
3. **Vary word count:** some 35 words, some 65. Not all the same length.
4. **Match tone to niche:** softer for therapists/wellness, more direct for business consultants, casual for creative coaches.
5. **Never use "automacao"/"automation"** — say "funciona 24h", "responde sozinho", "agenda automaticamente".
6. **Never mention pricing.** Goal = start conversation, not close sale.
7. **Never mention company name "Winbix" in first message.** We're a person helping, not a company selling.
8. **Always mention both site AND WhatsApp** in the first message. Vary HOW — sometimes lead with site, sometimes with WhatsApp, sometimes mention both equally.

## Content Micro-Variation (Applied by wa-outreach script)

The sending script adds additional variation layers:
- Random punctuation normalization (period vs no period)
- Unicode zero-width spaces between some words
- Optional leading/trailing whitespace
- These are invisible but make each message "unique" to WhatsApp's hash detection
