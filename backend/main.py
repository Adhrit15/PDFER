"""PDFer API + static web app.  Run:  uvicorn backend.main:app --reload"""
import json
import re
import uuid
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from . import auth, config, context, db, llm, pdf, prompts
from .auth import Who
from .db import Document, Message, Page, SessionLocal, User

db.init()
app = FastAPI(title="PDFer", docs_url=None, redoc_url=None)


def own_key(request: Request) -> str | None:
    """Visitors may bring their own free Gemini key; it is sent per request and never stored."""
    key = request.headers.get("x-gemini-key", "").strip()
    return key if re.fullmatch(r"[\w-]{20,100}", key) else None


# ---------- serialisers ----------

def doc_json(d: Document) -> dict:
    return {"id": d.id, "tag": d.tag, "name": d.name, "pages": d.pages,
            "size": d.size, "ocr": d.ocr, "thin": d.chars < 40 * d.pages}


def msg_json(m: Message) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, **json.loads(m.meta or "{}")}


def state_json(s, w: Who) -> dict:
    docs = s.scalars(select(Document).where(Document.owner_id == w.owner).order_by(Document.tag)).all()
    msgs = s.scalars(select(Message).where(Message.owner_id == w.owner).order_by(Message.id)).all()
    return {
        "user": {"name": w.user.name, "email": w.user.email} if w.user else None,
        "usage": auth.usage_json(s, w),
        "account_limits": config.USER_LIMITS,
        "docs": [doc_json(d) for d in docs],
        "messages": [msg_json(m) for m in msgs],
        "actions": [{k: a.get(k) for k in ("id", "key", "label", "blurb", "group", "min_docs")}
                    for a in prompts.ACTIONS],
        "limits": {"docs": config.MAX_DOCS, "file_mb": config.MAX_FILE_MB, "pages": config.MAX_PAGES},
        "ai_ready": bool(config.GEMINI_API_KEY),
    }


# ---------- session and accounts ----------

@app.get("/api/state")
def get_state(request: Request, response: Response):
    w = auth.identify(request, auth.ensure_desk(request, response))
    with SessionLocal() as s:
        return state_json(s, w)


class SignUp(BaseModel):
    name: str = Field(max_length=60)
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class SignIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


@app.post("/api/auth/signup")
def signup(body: SignUp, request: Request, response: Response):
    auth.throttle(request)
    email, name = body.email.strip().lower(), body.name.strip()
    if not name:
        raise HTTPException(422, "Tell us what to call you.")
    if not auth.EMAIL.fullmatch(email):
        raise HTTPException(422, "That email address does not look right.")
    if len(body.password) < 8:
        raise HTTPException(422, "Use a password of at least 8 characters.")
    with SessionLocal() as s:
        if s.scalar(select(User).where(User.email == email)):
            raise HTTPException(409, "An account with that email already exists. Sign in instead.")
        user = User(email=email, name=name, password_hash=auth.hash_password(body.password))
        s.add(user)
        s.flush()
        auth.adopt_guest_desk(s, request, user)
        auth.start_session(s, response, user)
        s.commit()
    return {"ok": True}


@app.post("/api/auth/login")
def login(body: SignIn, request: Request, response: Response):
    auth.throttle(request)
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.email == body.email.strip().lower()))
        if not user or not auth.check_password(body.password, user.password_hash):
            raise HTTPException(401, "Wrong email or password.")
        auth.adopt_guest_desk(s, request, user)
        auth.start_session(s, response, user)
        s.commit()
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    with SessionLocal() as s:
        auth.end_session(s, request, response)
        s.commit()
    return {"ok": True}


# ---------- documents ----------

@app.post("/api/docs")
def upload_doc(request: Request, file: UploadFile = File(...), w: Who = Depends(auth.who)):
    limit = config.MAX_FILE_MB * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"That file is over {config.MAX_FILE_MB} MB.")
    if b"%PDF-" not in data[:1024]:
        raise HTTPException(415, "That is not a PDF file.")

    with SessionLocal() as s:
        used = set(s.scalars(select(Document.tag).where(Document.owner_id == w.owner)))
        free = [t for t in range(1, config.MAX_DOCS + 1) if t not in used]
        if not free:
            raise HTTPException(409, f"Your desk holds {config.MAX_DOCS} PDFs. Remove one to add another.")
        auth.require(s, w, "pdfs")
        s.commit()

    try:
        pages = pdf.extract_pages(data, config.MAX_PAGES)
    except pdf.PdfError as e:
        raise HTTPException(422, str(e))
    with SessionLocal() as s:
        auth.require(s, w, "pages", len(pages))
        s.commit()

    ocr = False
    if pdf.looks_scanned(pages):
        if len(pages) > config.OCR_MAX_PAGES:
            raise HTTPException(422, f"This PDF is scanned images with no text layer. Scanned PDFs "
                                     f"can be read up to {config.OCR_MAX_PAGES} pages; this one has {len(pages)}.")
        try:
            pages, ocr = llm.ocr(data, len(pages), own_key(request)), True
        except llm.LLMError as e:
            raise HTTPException(503, f"This PDF is scanned and needs AI text recognition, which failed: {e}")

    doc = Document(id=uuid.uuid4().hex, owner_id=w.owner, tag=free[0],
                   name=(file.filename or "document.pdf")[-200:], pages=len(pages),
                   chars=sum(len(p) for p in pages), size=len(data), ocr=ocr)
    doc.page_rows = [Page(num=i + 1, text=t) for i, t in enumerate(pages)]
    (config.UPLOAD_DIR / f"{doc.id}.pdf").write_bytes(data)
    with SessionLocal() as s:
        s.add(doc)
        auth.spend(s, w, pdfs=1, pages=len(pages))
        s.commit()
        return {"doc": doc_json(doc), "usage": auth.usage_json(s, w)}


def _own_doc(s, doc_id: str, w: Who) -> Document:
    doc = s.get(Document, doc_id)
    if not doc or doc.owner_id != w.owner:
        raise HTTPException(404, "PDF not found.")
    return doc


@app.get("/api/docs/{doc_id}/file")
def doc_file(doc_id: str, w: Who = Depends(auth.who)):
    with SessionLocal() as s:
        doc = _own_doc(s, doc_id, w)
    path = config.UPLOAD_DIR / f"{doc.id}.pdf"
    if not path.exists():
        raise HTTPException(404, "The original file is no longer stored; its text is still available to chat.")
    return FileResponse(path, media_type="application/pdf", headers={"Cache-Control": "private, max-age=3600"})


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str, w: Who = Depends(auth.who)):
    with SessionLocal() as s:
        s.delete(_own_doc(s, doc_id, w))
        s.commit()
    (config.UPLOAD_DIR / f"{doc_id}.pdf").unlink(missing_ok=True)
    return {"ok": True}


# ---------- chat ----------

@app.delete("/api/chat")
def clear_chat(w: Who = Depends(auth.who)):
    with SessionLocal() as s:
        s.execute(delete(Message).where(Message.owner_id == w.owner))
        s.commit()
    return {"ok": True}


class ChatIn(BaseModel):
    message: str = Field("", max_length=4000)
    action: str | None = None
    doc_ids: list[str] | None = None  # None = every PDF on the desk
    style: Literal["brief", "balanced", "deep"] = "balanced"
    strict: bool = True


def _line(**obj) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


@app.post("/api/chat")
async def chat(body: ChatIn, request: Request, w: Who = Depends(auth.who)):
    text = body.message.strip()
    action = prompts.ACTIONS_BY_ID.get(body.action or "")
    if body.action and not action:
        raise HTTPException(400, "Unknown action.")
    if not text and not action:
        raise HTTPException(400, "Type a question or pick an action.")
    key = own_key(request)

    with SessionLocal() as s:
        q = select(Document).where(Document.owner_id == w.owner).order_by(Document.tag) \
            .options(selectinload(Document.page_rows))
        docs = s.scalars(q).all()
        if body.doc_ids is not None:
            docs = [d for d in docs if d.id in body.doc_ids]
        if not docs:
            raise HTTPException(400, "Add a PDF first.")
        if action and len(docs) < action.get("min_docs", 1):
            raise HTTPException(400, f"“{action['label']}” needs at least {action['min_docs']} PDFs in scope.")
        if not key:  # questions on your own key do not count against the shared allowance
            auth.require(s, w, "messages")
            auth.spend(s, w, messages=1)

        history = s.scalars(select(Message).where(Message.owner_id == w.owner)
                            .order_by(Message.id.desc()).limit(config.HISTORY_TURNS)).all()[::-1]
        user_meta = {"action": action["id"]} if action else {}
        s.add(Message(owner_id=w.owner, role="user", content=text, meta=json.dumps(user_meta)))
        s.commit()
        usage = auth.usage_json(s, w)

    request_text = action["prompt"] if action else text
    if action and text:
        request_text += f"\n\nExtra instruction from the user: {text}"
    ctx, trimmed = context.build(docs, text, whole=bool(action), budget=config.CONTEXT_CHARS)

    contents = []
    for m in history:
        label = m.content
        if m.role == "user":
            act = prompts.ACTIONS_BY_ID.get(json.loads(m.meta or "{}").get("action", ""))
            if act:
                label = f"[{act['label']}] {m.content}".strip()
        if label and (contents or m.role == "user"):  # history must start with a user turn
            contents.append(llm.turn("user" if m.role == "user" else "model", label[:6000]))
    note = "\n(Note: the PDFs are longer than fits in one request, so only part of the text is included.)" if trimmed else ""
    contents.append(llm.turn("user", f"PDFs on my desk:{note}\n\n{ctx}\n\n---\nMy request: {request_text}"))

    tags = {f"D{d.tag}": {"id": d.id, "name": d.name} for d in docs}
    system = prompts.system_prompt(body.style, body.strict)
    owner = w.owner

    async def run():
        full, error, followups = "", None, []
        yield _line(type="meta", tags=tags, trimmed=trimmed, usage=usage)
        try:
            async for piece in llm.stream(system, contents, key):
                full += piece
                yield _line(type="delta", text=piece)
        except llm.LLMError as e:
            error = str(e)
        except Exception:
            error = "Something went wrong while answering. Try again."
        finally:  # also runs when the reader presses Stop, so partial answers are kept
            answer, _, tail = full.partition(prompts.FOLLOWUP_MARK)
            answer = answer.strip()
            followups = [re.sub(r"^[-*\d.\s]+", "", q).strip() for q in tail.splitlines()]
            followups = [q for q in followups if q][:3]
            saved = None
            if answer:
                meta = {"tags": tags, "followups": followups, "trimmed": trimmed}
                with SessionLocal() as s:
                    row = Message(owner_id=owner, role="assistant", content=answer, meta=json.dumps(meta))
                    s.add(row)
                    s.commit()
                    saved = row.id
        if error:
            yield _line(type="error", message=error)
        else:
            yield _line(type="done", id=saved, followups=followups)

    return StreamingResponse(run(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- web app ----------

class Fresh(StaticFiles):
    """Static files that browsers re-check on every load, so updates show up at once."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/", Fresh(directory=config.WEB_DIR), name="web")
