"""Decides which page text goes to the model.

Small desks are sent whole (best answers, nothing missed). When the text is larger
than the budget, questions get the most relevant pages (BM25 ranking, no embedding
API needed) and whole-document tasks get an even sample of every page.
"""
import math
import re
from collections import Counter

_word = re.compile(r"[a-z0-9]+")
_stop = set("a an and are as at be by for from has have in is it its of on or that the this to was "
            "were what when where which who why will with how do does did can could should would "
            "about into than then there their them they you your me my i we our".split())


def _tokens(text: str) -> list[str]:
    return [w for w in _word.findall(text.lower()) if w not in _stop and len(w) > 1]


def _rank(pages: list[tuple[str, int, str]], query: str) -> list[float]:
    q = set(_tokens(query))
    if not q:
        return [0.0] * len(pages)
    docs = [Counter(_tokens(text)) for _, _, text in pages]
    lengths = [sum(c.values()) or 1 for c in docs]
    avg = sum(lengths) / len(lengths)
    n = len(docs)
    scores = [0.0] * n
    for term in q:
        df = sum(1 for c in docs if term in c)
        if not df:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, c in enumerate(docs):
            tf = c.get(term, 0)
            if tf:
                scores[i] += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * lengths[i] / avg))
    return scores


def build(docs: list, query: str, whole: bool, budget: int) -> tuple[str, bool]:
    """docs: Document rows with page_rows loaded. Returns (context text, was_trimmed)."""
    pages = [(f"D{d.tag}", p.num, p.text) for d in docs for p in d.page_rows]
    total = sum(len(t) for _, _, t in pages)
    keep: dict[tuple[str, int], str] = {}
    trimmed = total > budget

    if not trimmed:
        keep = {(tag, num): text for tag, num, text in pages}
    else:
        scores = [0.0] * len(pages) if whole else _rank(pages, query)
        if any(scores):
            used = 0
            for i in sorted(range(len(pages)), key=lambda i: -scores[i]):
                tag, num, text = pages[i]
                if scores[i] <= 0 or used + len(text) > budget:
                    continue
                keep[(tag, num)] = text
                used += len(text)
        else:
            cap = max(200, budget // max(1, len(pages)))
            for tag, num, text in pages:
                keep[(tag, num)] = text if len(text) <= cap else text[:cap] + " […]"

    out = []
    for d in docs:
        tag = f"D{d.tag}"
        out.append(f'<document tag="{tag}" name="{d.name}" pages="{d.pages}">')
        for p in d.page_rows:
            text = keep.get((tag, p.num))
            if text:
                out.append(f"[{tag} p.{p.num}]\n{text}")
        out.append("</document>")
    return "\n\n".join(out), trimmed
