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
backend/   config.py  db.py  pdf.py  context.py  prompts.py  llm.py  main.py
web/       index.html  styles.css  app.js
```

Shortcuts and the model's instructions live in `backend/prompts.py`; limits live in `backend/config.py`.

## Hosting for free

The included `Dockerfile` runs anywhere that takes a container (Render, Koyeb, Hugging Face Spaces).
Free hosts wipe local disk on restart, so set `DATABASE_URL` to a free Postgres database
(Neon, Supabase) to keep documents and chats. Original PDF files are kept on local disk for the
reader; if the disk is wiped the text and chat still work, only the page preview is lost.
