"""PDF text extraction, page by page, so answers can cite pages."""
import re
import threading

import pypdfium2 as pdfium

_lock = threading.Lock()  # pdfium is not thread-safe


class PdfError(Exception):
    pass


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = text.replace("￾", "").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join words hyphenated across lines
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(data: bytes, max_pages: int) -> list[str]:
    """Return the text of each page. Raises PdfError with a user-facing message."""
    with _lock:
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as e:
            if "password" in str(e).lower():
                raise PdfError("This PDF is password-protected. Remove the password and try again.")
            raise PdfError("This file could not be opened as a PDF. It may be damaged.")
        try:
            n = len(pdf)
            if n == 0:
                raise PdfError("This PDF has no pages.")
            if n > max_pages:
                raise PdfError(f"This PDF has {n} pages; the limit is {max_pages} per file.")
            out = []
            for i in range(n):
                page = pdf[i]
                try:
                    textpage = page.get_textpage()
                    try:
                        out.append(_clean(textpage.get_text_bounded()))
                    finally:
                        textpage.close()
                finally:
                    page.close()
            return out
        finally:
            pdf.close()


def looks_scanned(pages: list[str]) -> bool:
    """True when the PDF has (almost) no text layer, i.e. it is images of pages."""
    return sum(len(p) for p in pages) < 40 * len(pages)
