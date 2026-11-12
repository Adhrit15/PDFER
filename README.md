# PDFer

Drop in up to five PDFs, ask anything, and get answers that point at the page they came from.
Runs on the free Gemini API tier, so it costs nothing to use.

## What it does

- **Desk of 5 PDFs** read together or one at a time, with a side-by-side reader.
- **Page citations** on every claim (`D1·4`); click one and the reader jumps to that page.
- **14 one-click shortcuts**: TL;DR, section-by-section summary, explain like I'm 12, jargon buster,
  action items, numbers & dates, timeline, red flags, poke holes, compare PDFs, quiz, flashcards,
  study notes, team brief. Type `/` in the box to search them.
- **Answer controls**: Brief / Balanced / Deep, and a "PDF only" switch that stops the model
  from padding answers with outside knowledge.
- **Scanned PDFs** (photos of pages) are transcribed automatically, up to 40 pages.
- Streaming answers, suggested follow-ups, copy, export to Markdown, light and dark themes, works on phones.
- **Accounts and daily allowances**: anyone can try it without signing up (2 PDFs a day);
  a free account gets 5 PDFs, 500 pages and 100 questions a day, and the desk follows you across devices.
- **Bring your own key**: a visitor can paste their own free Gemini key, kept only in their browser,
  and their questions stop counting against the shared allowance.

## Run it

```bash
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # then put your free Gemini key in .env
uvicorn backend.main:app --reload
```

Open http://localhost:8000. Get a free key at https://aistudio.google.com/apikey.

## How it works

| Piece | Choice | Why |
| --- | --- | --- |
| Server | FastAPI | Streams answers, serves the web app, one small process |
| PDF text | pypdfium2, page by page | Accurate extraction and real page numbers for citations |
| Scans | Gemini reads the PDF directly | No OCR software to install |
| Context | Whole text when it fits (~100k tokens), otherwise BM25 page ranking | Summaries see the full document; no embedding quota needed |
| Model | Gemini Flash with automatic fallback to lighter models | Free tier; survives rate limits and slow models |
| Storage | SQLite by default, Postgres via `DATABASE_URL` | Zero setup locally, durable when hosted |
| Web app | Plain HTML/CSS/JS + pdf.js | No build step |

```
backend/   config.py  db.py  auth.py  pdf.py  context.py  prompts.py  llm.py  main.py
web/       index.html  styles.css  app.js
```

Shortcuts and the model's instructions live in `backend/prompts.py`; limits live in `backend/config.py`.

## Accounts and limits

- Sign-up is name, email and password. No email verification, so onboarding takes seconds.
  Passwords are stored as salted scrypt hashes; sessions are random tokens in an HttpOnly cookie,
  stored hashed.
- Whatever a visitor put on their desk before signing up moves onto the new account.
- Allowances reset at midnight UTC. Accounts are counted per user, guests per IP address.
  Change the numbers in `.env`:

| Setting | Default | Meaning |
| --- | --- | --- |
| `USER_PDFS_PER_DAY` / `GUEST_PDFS_PER_DAY` | 5 / 2 | PDFs uploaded per day |
| `USER_PAGES_PER_DAY` / `GUEST_PAGES_PER_DAY` | 500 / 100 | Pages read per day |
| `USER_MESSAGES_PER_DAY` / `GUEST_MESSAGES_PER_DAY` | 100 / 15 | Questions per day |
| `MAX_DOCS` | 5 | PDFs on the desk at once |

Known gaps: there is no email verification or password reset yet, so one person can register
several addresses; and the shared Gemini key has its own free-tier ceiling, which many simultaneous
users will hit (the bring-your-own-key option is the pressure valve).

## Hosting for free

The included `Dockerfile` runs anywhere that takes a container (Render, Koyeb, Hugging Face Spaces).
Free hosts wipe local disk on restart, so set `DATABASE_URL` to a free Postgres database
(Neon, Supabase) to keep accounts, documents and chats. Behind a host's proxy set `TRUST_PROXY=1`
(the Dockerfile does) so guest limits see real visitor addresses. Original PDF files are kept on local disk for the
reader; if the disk is wiped the text and chat still work, only the page preview is lost.
