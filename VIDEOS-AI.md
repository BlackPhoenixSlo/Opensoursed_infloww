# Videos — the AI chatbot series

Short videos (20–60 s, one benefit each) about the AI: the bot that messages fans by itself, and the AI helpers chatters and owners click. They are recorded with `scripts/feature-videos/` on the **local** demo stack: fake OnlyFans, synthetic fans, the free `af_heart` voice, and music rotating pad, lofi and bright. Cards 0–9 in `VIDEOS.md` are the long tour; this file is the AI shorts.

Built from a read of the code on 2026-11-12. Every "recordable" call below is inferred: none of these videos has been recorded yet.

---

## 1. Rules for every AI video

- **Say "automatic", not "AI", for fixed-text senders.** Welcome, Purchased, Expiring/Expired/Resubscribe/Birthday and Nudge send text the owner wrote (`send_welcome.py`: "no LLM anywhere").
- **The AI does not "sell for you".** Auto-reply never sends a PPV. Get to know fans never pitches; its only sale is the one closing PPV. The old selling AI was removed on 2026-10-18.
- **"Not in Infloww"** may only appear for these AI items: **Mass exclude**, **Generated profile note (AI profile)** and **Persona claims**, the ones listed in `app/lib/openinflowwwwExtras.ts`. Adding more needs the owner's OK.
- **Never "only we have AI".** Infloww sells an AI Copilot (`VIDEOS.md` §4).
- **Off camera:**
  - the "Full AI Chatter" page (coming soon; it promises "sells to every fan")
  - `_outbound_guard`'s word spelling trick (OnlyFans terms risk)
  - any real key, fan or handle
- **Careful wording:**
  - The vault folder is "likely SFW", never "safe".
  - Vision flags are 28% precise by their own banner, so never call them "accurate".
  - "Do it for me" handles one form (Auto mass), creates it only, and always saves it OFF.
  - Translate is Google's free service, not AI.
- **Who pays:**
  - Copilot, FU, FM Suggest, customs brief, "Do it for me", the chat engines and gen_info all run on the agency's own key, with a daily soft cap.
  - The help bot switches to Claude Opus when an Anthropic key is set, which costs about 100× DeepSeek per question.

## 2. Already done (feature-videos, voiced)

AI Copilot (basic), FU follow-ups, FM script "Next in" bar, scripts with the "/" picker. Translate was dropped because the demo has no translator.

## 3. The series

Pri: P1 = record first. Demo: **yes** = records today; otherwise the line says what's missing (see §5).

### A · The AI that answers fans

| # | Video | Benefit | Where (labels) | Not in Infloww | Demo | Pri |
|---|---|---|---|---|---|---|
| A1 | New fans answered in under a minute | New subs never wait | My AI Chatter › **Get to know fans** (`/growth/get-to-know-fans`) switch → thread with the "Info-gather" label | – | yes (inject `subscribed` + `dm`) | P1 |
| A2 | Auto-reply: no fan left on read | Covers slow chatters, never a PPV | My AI Chatter › **Auto-reply** (`/growth/auto-reply`) → "When to reply": "If nobody answered within __ min", "Randomise" | – | yes (1 min delay, a fan Get to know fans doesn't take) | P1 |
| A3 | Choose who the AI answers | Big spenders stay with humans | Auto-reply › "Who to reply to": "Fans in folders" + "Only if he spent less than $", "New fans" | – | yes | P1 |
| A4 | Texts like a real person | Fewer "are you a bot?" | Auto-reply › "Human style": "Realistic typos", "Non-native English", 'Space before "?"' | – | page yes; the bubble burst needs fake_llm | P1 |
| A5 | Tell the AI who she is | Same persona in every chat | Get to know fans › "Model info" (Name / From / Likes / Won't do) › Save | – | save yes; the reply using "From" needs fake_llm | P1 |
| A6 | See which messages the AI sent | Trust and audit | Bubble labels "Auto-reply" / "Info-gather" → Analytics › Message dashboard › Sender | – | yes, after A1/A2 | P1 |
| A7 | Keep a fan out of every mass | Protect a VIP with one switch | Fan insights › "Mass exclude" › MASSdmEXCLUDE (or the chat header "+") | **yes** | yes | P1 |
| A8 | End the chat with one PPV | The get-to-know chat ends on an offer | Get to know fans › "When the chat ends": "Stop after __", "Closing PPV" | – | settings yes; the live send needs prep | P2 |
| A9 | Pick the model, on your own key | Your cost, your choice | Auto-reply › "Model", "Effort" → Settings › **AI keys** (view only) | – | yes (don't press Save on keys: locked) | P2 |
| A10 | What the AI knows about, and told, each fan | No contradictions | Fan insights › Notes › "AI profile" + "Creator facts" / "What this fan was told" | **yes** | needs a profile + claims seed | P2 |
| A11 | Your chatter replied first, so the AI stays quiet | No double replies | Auto-reply tip "A human reply first always wins" → reply before the delay runs out | – | yes (timer overlay; the demo's simulated chatters may interfere) | P2 |
| A12 | Reacts to photos fans send | Replies that fit the photo | Auto-reply › "Photos he sends" | – | needs `inbound_describe` in fake_llm + a photo DM | P3 |
| A13 | Funnel steps written by AI | Varied follow-ups | My Automations › **Auto Funnel** › step "Generate the reply with AI" | – | editor yes; live run unchecked | P3 |

### B · Automatic messages (not AI, say "automatic")

| # | Video | Benefit | Where | Demo | Pri |
|---|---|---|---|---|---|
| B1 | Every new subscriber welcomed | Greeted even at 3 am | Smart Messages › "Delayed welcome" | yes (inject `subscribed`) | P2 |
| B2 | Thank buyers right after a PPV | Ask for part 2 while he's hot | Smart Messages › "Purchased" › "Message on purchase" (`{name}`) | Save once first: the seeded rule may not be enabled | P2 |
| B3 | Message fans the moment they come online | Catch them while they're active | "New Message" › **Nudge**: Timing, Quiet hours, Preview, Share to models | editor/Preview/Share yes; live firing no | P2 |
| B4 | Expiring / expired / resubscribe / birthday | Win back lapsing fans | Smart Messages lifecycle rows | editor yes; sending needs an expiring fan | P3 |
| B5 | One banned-words list | One list for chatters and automations | Growth › **Sensitive words** › Add → composer warning | yes (blocking automations: caption only) | P2 |

### C · AI helpers chatters and owners click

| # | Video | Benefit | Where (labels) | Demo | Pri |
|---|---|---|---|---|---|
| C1 | Ask the help bot | Answer + a link to the page | Corner "Help assistant" → composer "Ask a question…" | needs canned help answers | P1 |
| C2 | "Do it for me": an Auto mass from one sentence | It fills the form; you switch it on | Launcher → "Do it for me" → plan card → "Do it" → "Created OFF" | needs a `help_assistant_do` JSON answer + SFW-tier vault seed (or reuse slop `2026-11-11-assistant-do-auto-mass --set video=1`) | P1 |
| C3 | "Why didn't the AI reply to him?" | The reason, from stored records | Launcher → paste the fan → ask | needs canned help answers | P1 |
| C4 | FM Suggest when a fan goes off-script | A reply that steers back, never auto-sent | Messages Pro › FM fan › "Next in" › **Suggest** | yes after `prep.py`; better with a script-aware fake line | P1 |
| C5 | Customs work order | Reads the thread, writes the order, copies the handoff | `/customs` › **Read** › "His words:" › **Copy handoff** | needs an owed-custom seed + `customs_brief` JSON | P2 |
| C7 | The help bot knows your setup | "Is my welcome on?" answered from the live rules | Launcher › "Currently selected:" Ava → ask | needs canned help answers | P2 |
| C8 | AI descriptions on vault thumbs | Know what's in it without opening it | Vault picker › "Show AI descriptions on thumbs" | needs AI tags on demo vault items | P2 |
| C9 | Copilot: Re-engage, Tip request, Regenerate | Replies matched to the goal | Composer **AI** › "Reply style" › Regenerate | needs style-aware fake lines | P3 |
| C10 | Build AI folders | Vault sorted into shoots and lanes, previewed first | Vault Pro › Inflowwww extras › **Build AI folders** | needs an AI-description seed; lane names are a content risk | P3 |
| C11 | Find vault content by what's in it | Search by AI tags | Vault Pro search | needs a tag seed (same as C8) | P3 |
| C12 | Help bot: earlier conversations | Pick up an old thread | Launcher › "Earlier conversations" | needs canned help answers | P3 |

Left out:
- Smart-list preview (a rule counter, not AI)
- Vision-model check (28% precision, not a selling point)
- Daily AI cost cap (no UI)
- Full AI Chatter (coming soon)
- `send_followup` (no page)
- Missing-key warning (the demo seeds keys, so it never shows)

## 4. Beats (P1)

- **A1:** Get to know fans switch On ("Your AI greets every new fan") → subscribe toast → fan writes "hey" → AI bubble 15–45 s later with the "Info-gather" label ("In her voice, around the clock") → "Runs on your own AI key."
- **A2:** `/growth/auto-reply`, Ava ("Each creator has her own settings") → "If nobody answered within" 1, Randomise ("Not a robotic timer") → switch on, Save → an unanswered DM → "Auto-reply" bubble ("Never leaves a fan on read. Never sends a PPV.")
- **A3:** "Who to reply to" → Fans in folders, tick a list → "Only if he spent less than $" 50 ("Big spenders stay with your team") → New fans 72 h / $10 → Save.
- **A4:** Human style block → hover the hints ("Short lowercase bursts, up to 3 bubbles") → Non-native English on → a thread with 2–3 bubbles and a "*fix" typo ("Reads like a real person typing").
- **A5:** Model info template → fill Name / From / Likes / Won't do → Save, with the counter on screen ("A few lines; every AI chat reads them") → fan asks "where are u from?" and the AI answers with "From".
- **A6:** A thread with mixed bubbles → zoom on the "Auto-reply" / "Info-gather" labels ("You always see who sent what") → Message dashboard › Sender column → filter one creator.
- **A7:** Fan insights › Mass exclude → flip MASSdmEXCLUDE ("Never in any mass send. Not in Infloww.") → the same switch in the chat header "+" → "He still gets welcomes and 1-to-1 replies."
- **C1:** Launcher → type in "Ask a question…" → "how do I schedule a mass?" → answer with a page link → click it and land on the page ("Answers from the manual, with a link") → "It says 'not supported' when that's the truth."
- **C2:** `/growth/auto-post` → "Do it for me" → type the sentence → plan card ("Check the plan first") → "Do it": the cursor fills the form → "Created OFF" ("You switch it on") → Esc stops it at any time.
- **C3:** Launcher → paste a fan's handle → "why didn't the AI chatter reply to him?" → answer cites stored facts, e.g. "on skip list" ("From your records, not guesses").
- **C4:** FM fan writes something off-script → **Suggest** ("Thinking…") → draft lands in the composer ("Nothing is sent") → edit and send ("Back on script").

## 5. Demo work before recording

1. **`demo/fake_llm.py`, canned answers per purpose:**
   - help Q&A, matched by question, for C1, C3, C7 and C12
   - a `help_assistant_do` JSON plan for C2 (port `INTENT` from `slop/lib/assistant_do_relay.py`)
   - `customs_brief` JSON for C5
   - style-aware Copilot lines for C9
   - a script-aware FM Suggest line for C4
   - multi-bubble replies that echo Model info for A4 and A5
   - `inbound_describe` for A12
2. **Seeds:**
   - fan AI profiles and persona claims (A10)
   - AI tags and descriptions on vault items (C8, C11)
   - SFW tiers on one folder (C2; port `slop/seed/assistant_do_vault.py`)
   - an owed custom with its thread (C5)
   - an expiring subscriber (B4)
   - the Purchased rule armed (B2)
3. **Owner decisions:**
   - `VIDEOS.md` card 1 says "Don't show: Help center", which conflicts with C1–C3, C7 and C12.
   - Should more AI features join the "Not in Infloww" list?
4. **Recorder:**
   - inject helpers for `subscribed` and photo DMs in `scripts/feature-videos/videos.py`
   - a timer overlay for A11

## 6. Order

Week 1 (records today): A1, A2, A3, A6, A7, C4, then B1 and B5.
Week 2, after the §5 fake/seed work: A4, A5, C1, C2, C3, then A10, C5, C8.
