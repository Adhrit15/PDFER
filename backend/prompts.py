"""System instructions and the one-click actions."""

FOLLOWUP_MARK = "<<FOLLOWUPS>>"

BASE = """You are PDFer, a sharp, friendly reading partner. The user has put one or more PDFs on their desk and you have the page text, wrapped in <document> tags. Each page starts with a marker like [D1 p.4].

How to answer
- Lead with the answer. No preamble like "Based on the document".
- Cite as you go: after each claim taken from a PDF, add the page marker exactly in this form: [D1 p.4]. Several pages: [D1 p.4][D1 p.9]. Never invent a page; only cite markers you can see.
- Write GitHub-flavoured Markdown: short paragraphs, bullets, bold for the key phrase, tables when comparing or listing figures. No top-level "#" headings; use "###" at most.
- Quote sparingly and exactly, in quotation marks, with a citation.
- If the text of a page looks garbled (scanned or badly encoded), say so rather than guessing.
- If documents were trimmed to fit, work with what you have and mention anything you could not see only when it matters.
- Reply in the language the user writes in.
"""

STRICT = """Stay inside the PDFs. If the answer is not in them, say plainly that the PDFs do not cover it and point to the closest thing they do say. Do not fill gaps from general knowledge."""

OPEN = """Prefer the PDFs. When they do not cover something, you may add general knowledge, but put it in a separate paragraph that starts with "Beyond the PDF:" and carries no citation."""

STYLES = {
    "brief": "Length: as short as possible. A few lines or bullets. No padding.",
    "balanced": "Length: thorough but skimmable. Cover what matters and stop.",
    "deep": "Length: detailed. Walk through the reasoning, edge cases and supporting evidence.",
}

FOLLOWUPS = f"""After your answer, add a final line containing only {FOLLOWUP_MARK} followed by exactly three short follow-up questions the user might ask next, one per line, no numbering, under 60 characters each."""

# key is the little keycap shown on the button
ACTIONS = [
    dict(id="tldr", key="¶", label="TL;DR", group="Understand",
         blurb="The whole thing in five bullets",
         prompt="Give me the TL;DR: one sentence on what this is and who it is for, then the five most important points as bullets, each cited."),
    dict(id="summary", key="§", label="Section by section", group="Understand",
         blurb="A guided walk through every part",
         prompt="Summarise section by section, following the document's own structure. For each section: a ### heading with its title, two to four bullets, page citations. End with a two-line 'Bottom line'."),
    dict(id="eli12", key="12", label="Explain like I'm 12", group="Understand",
         blurb="Plain words, everyday examples",
         prompt="Explain this to a curious 12-year-old: plain words, one everyday analogy, no jargon (or explain it the moment you use it). Keep the citations."),
    dict(id="glossary", key="Aa", label="Jargon buster", group="Understand",
         blurb="Every term and acronym, decoded",
         prompt="List the technical terms, acronyms and jargon a newcomer would stumble on. Table: Term | Plain meaning | First appears. Up to 20 rows, most important first."),
    dict(id="actions", key="✓", label="Action items", group="Extract",
         blurb="To-dos, owners and deadlines",
         prompt="Extract every action item, obligation and deadline. Table: What | Who | By when | Page. Then list anything that is ambiguous or missing an owner or date."),
    dict(id="numbers", key="#", label="Numbers & dates", group="Extract",
         blurb="Every figure worth knowing, in a table",
         prompt="Pull out the important numbers, amounts, percentages and dates. Table: Figure | What it refers to | Page. Group related rows together and skip trivia like page numbers."),
    dict(id="timeline", key="→", label="Timeline", group="Extract",
         blurb="Events in order",
         prompt="Build a chronological timeline of the events, milestones and dates mentioned. One line each: **date or period** — what happened, with citation. Say so if the PDFs contain no real chronology."),
    dict(id="redflags", key="!", label="Red flags", group="Think",
         blurb="Risks, fine print and gotchas",
         prompt="Read this like a careful lawyer and a sceptical friend. List the red flags: risky clauses, hidden costs, one-sided terms, vague wording, missing information, things that contradict each other. For each: what it says (cited), why it matters, what to ask or do about it. Order by severity."),
    dict(id="critique", key="×", label="Poke holes", group="Think",
         blurb="Weak arguments and missing evidence",
         prompt="Critique this honestly. What are the main claims, how well is each supported, where is the reasoning weak, what is assumed without evidence, and what would a tough reviewer push back on? Finish with the three strongest and three weakest points."),
    dict(id="compare", key="≠", label="Compare PDFs", group="Think", min_docs=2,
         blurb="Where they agree, differ and clash",
         prompt="Compare the PDFs on my desk. Start with one line on what each one is. Then a table of the key dimensions (rows) against each PDF (columns) with citations, then bullets for: where they agree, where they differ, and where they directly contradict each other."),
    dict(id="quiz", key="?", label="Quiz me", group="Study",
         blurb="Eight questions, answers hidden",
         prompt="Write an 8-question quiz that tests real understanding, mixing multiple-choice (options A to D) and short-answer. Number the questions. Directly after each question, put the answer in this exact HTML so it stays hidden until clicked: <details><summary>Show answer</summary>the answer, a one-line why, and the page citation</details>"),
    dict(id="flashcards", key="▤", label="Flashcards", group="Study",
         blurb="Twelve cards to drill",
         prompt="Make 12 flashcards covering the most important facts and ideas. For each card write the front as a bold numbered question, and directly below it the back in this exact HTML: <details><summary>Flip</summary>the answer in one or two sentences, with the page citation</details>"),
    dict(id="notes", key="✎", label="Study notes", group="Study",
         blurb="Clean revision notes",
         prompt="Turn this into revision notes: ### headings per topic, nested bullets, **bold** key terms, formulas or definitions set apart, and a final 'If you remember only five things' list. Cite pages."),
    dict(id="email", key="@", label="Brief my team", group="Write",
         blurb="A ready-to-send summary email",
         prompt="Write a short email I could send to a colleague who has not read this: subject line, three-sentence summary, the key points as bullets, and what (if anything) they need to decide or do. Plain professional tone. Keep page citations in the bullets."),
]

ACTIONS_BY_ID = {a["id"]: a for a in ACTIONS}

OCR_PROMPT = """Transcribe this scanned PDF to plain text, page by page. Before each page write a line containing only <<<PAGE n>>> where n is the page number starting at 1. Keep the reading order, keep tables as rows with ' | ' between cells, and do not add commentary or summaries. If a page has no readable text, write the marker and leave it empty."""


def system_prompt(style: str, strict: bool) -> str:
    return "\n\n".join([BASE, STRICT if strict else OPEN, STYLES.get(style, STYLES["balanced"]), FOLLOWUPS])
