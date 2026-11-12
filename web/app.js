import * as pdfjs from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.min.mjs";
pdfjs.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.worker.min.mjs";

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};

const MARK = "<<FOLLOWUPS>>";
const THINKING = ["Reading the pages…", "Skimming the footnotes…", "Checking the fine print…",
  "Arguing with the appendix…", "Highlighting the good bits…", "Cross-checking page numbers…"];

const state = {
  docs: [], messages: [], actions: [], limits: { docs: 5, file_mb: 25, pages: 400 },
  pending: [], active: null, busy: false, abort: null, style: "balanced",
};

const app = $("#app"), messagesEl = $("#messages"), input = $("#input"), slash = $("#slash");

// ---------- helpers ----------

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = "Something went wrong. Try again.";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
    } catch { /* keep default */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res;
}

function toast(text) {
  const t = el("div", "toast", text);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), 5200);
}

const fmtSize = (b) => b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
const docById = (id) => state.docs.find((d) => d.id === id);
const actionById = (id) => state.actions.find((a) => a.id === id);

function chip(action, tag = "button") {
  const c = el(tag, "chip");
  c.append(el("span", "key", action.key), document.createTextNode(action.label));
  if (tag === "button") { c.type = "button"; c.title = action.blurb; }
  return c;
}

// ---------- desk (document list) ----------

function renderDesk() {
  const { docs, pending, limits } = state;
  app.classList.toggle("is-empty", !docs.length && !pending.length);
  $("#slots").textContent = `${docs.length}/${limits.docs}`;
  const count = $("#deskCount");
  count.hidden = !docs.length;
  count.textContent = `${docs.length} of ${limits.docs} PDFs`;
  $("#addDoc").disabled = docs.length + pending.length >= limits.docs;

  const list = $("#docs");
  list.replaceChildren();
  for (const d of docs) {
    const li = el("li");
    const card = el("div", "doc" + (d.id === state.active ? " on" : ""));
    card.style.setProperty("--c", `var(--d${d.tag})`);
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    const body = el("div", "doc-body");
    body.append(el("div", "doc-name", d.name),
      el("div", "doc-meta", `${d.pages} ${d.pages === 1 ? "page" : "pages"} · ${fmtSize(d.size)}${d.ocr ? " · scanned" : ""}`));
    const x = el("button", "doc-x", "×");
    x.title = "Remove from desk";
    x.setAttribute("aria-label", `Remove ${d.name}`);
    x.onclick = (e) => { e.stopPropagation(); removeDoc(d); };
    card.append(el("div", "doc-tag", `D${d.tag}`), body, x);
    card.onclick = () => { setTab("reader"); openDoc(d.id); };
    card.onkeydown = (e) => { if (e.key === "Enter") card.click(); };
    li.append(card);
    list.append(li);
  }
  for (const name of pending) {
    const li = el("li");
    const card = el("div", "doc pending");
    const body = el("div", "doc-body");
    body.append(el("div", "doc-name", name), el("div", "doc-meta", "reading…"));
    card.append(el("div", "doc-tag", "··"), body);
    li.append(card);
    list.append(li);
  }

  const scope = $("#scope"), prev = scope.value;
  scope.replaceChildren(new Option(docs.length > 1 ? `All ${docs.length} PDFs` : "All", "all"));
  for (const d of docs) scope.add(new Option(`D${d.tag} ${d.name}`, d.id));
  scope.value = docs.some((d) => d.id === prev) ? prev : "all";
  scope.parentElement.hidden = docs.length < 2;
  renderShortcuts();
}

async function addFiles(files) {
  const pdfs = [...files].filter((f) => f.type === "application/pdf" || /\.pdf$/i.test(f.name));
  if (!pdfs.length) return toast("Only PDF files can go on the desk.");
  const room = state.limits.docs - state.docs.length - state.pending.length;
  if (pdfs.length > room) {
    toast(room > 0 ? `Only ${room} free ${room === 1 ? "slot" : "slots"} on your desk; adding the first ${room}.`
      : `Your desk holds ${state.limits.docs} PDFs. Remove one to add another.`);
  }
  const batch = pdfs.slice(0, Math.max(0, room));
  state.pending.push(...batch.map((f) => f.name));
  renderDesk();
  let first = null;
  for (const f of batch) {
    try {
      const form = new FormData();
      form.append("file", f);
      const doc = await (await api("/api/docs", { method: "POST", body: form })).json();
      state.docs.push(doc);
      state.docs.sort((a, b) => a.tag - b.tag);
      first ??= doc;
      if (doc.thin) toast(`“${doc.name}” has very little readable text, so answers may be thin.`);
    } catch (e) {
      toast(`${f.name}: ${e.message}`);
    }
    state.pending.splice(state.pending.indexOf(f.name), 1);
    renderDesk();
  }
  if (first) openDoc(first.id);
  if (!state.messages.length) renderMessages();
}

async function removeDoc(d) {
  try {
    await api(`/api/docs/${d.id}`, { method: "DELETE" });
  } catch (e) { return toast(e.message); }
  state.docs = state.docs.filter((x) => x.id !== d.id);
  if (state.active === d.id) {
    state.active = null;
    if (state.docs[0]) openDoc(state.docs[0].id); else closeReader();
  }
  renderDesk();
  if (!state.messages.length) renderMessages();
}

// ---------- reader ----------

const reader = { pdf: null, zoom: 1, task: null, observer: null, ratio: 1.414, token: 0 };
const pagesEl = $("#pages");

function closeReader() {
  reader.task?.destroy();
  reader.pdf = reader.task = null;
  reader.observer?.disconnect();
  pagesEl.replaceChildren();
  $("#readerName").textContent = $("#readerPage").textContent = "";
  $("#readerTag").hidden = true;
}

async function openDoc(id, page) {
  const d = docById(id);
  if (!d) return;
  if (state.active !== id || !reader.pdf) {
    state.active = id;
    const token = ++reader.token;
    closeReader();
    renderDesk();
    const tag = $("#readerTag");
    tag.hidden = false;
    tag.textContent = `D${d.tag}`;
    tag.style.setProperty("--c", `var(--d${d.tag})`);
    $("#readerName").textContent = d.name;
    pagesEl.append(el("p", "reader-msg", "Opening…"));
    try {
      reader.task = pdfjs.getDocument({ url: `/api/docs/${id}/file` });
      const pdf = await reader.task.promise;
      if (token !== reader.token) return;
      reader.pdf = pdf;
      const vp = (await pdf.getPage(1)).getViewport({ scale: 1 });
      reader.ratio = vp.height / vp.width;
      layoutPages();
    } catch {
      if (token !== reader.token) return;
      pagesEl.replaceChildren(el("p", "reader-msg",
        "The preview for this PDF is not available, but its text is still on your desk and you can keep asking about it."));
      return;
    }
  }
  if (page) goToPage(page);
}

function pageWidth() {
  const fit = Math.min(pagesEl.clientWidth - 48, 920);
  return Math.max(240, Math.round(fit * reader.zoom));
}

function layoutPages() {
  const { pdf } = reader;
  if (!pdf) return;
  const keep = currentPage();
  reader.observer?.disconnect();
  reader.observer = new IntersectionObserver((entries) => {
    for (const en of entries) if (en.isIntersecting) drawPage(en.target);
  }, { root: pagesEl, rootMargin: "700px 0px" });
  const w = pageWidth();
  const frag = document.createDocumentFragment();
  for (let n = 1; n <= pdf.numPages; n++) {
    const pg = el("div", "pg");
    pg.dataset.n = n;
    pg.style.width = w + "px";
    pg.style.height = Math.round(w * reader.ratio) + "px";
    frag.append(pg);
    reader.observer.observe(pg);
  }
  pagesEl.replaceChildren(frag);
  if (keep > 1) pagesEl.children[keep - 1]?.scrollIntoView({ block: "start" });
  updatePageLabel();
}

async function drawPage(pg) {
  if (pg.dataset.drawn || !reader.pdf) return;
  pg.dataset.drawn = "1";
  const pdf = reader.pdf;
  try {
    const page = await pdf.getPage(+pg.dataset.n);
    if (pdf !== reader.pdf || !pg.isConnected) return;
    const base = page.getViewport({ scale: 1 });
    const w = parseFloat(pg.style.width);
    pg.style.height = Math.round(w * base.height / base.width) + "px";
    const vp = page.getViewport({ scale: (w / base.width) * Math.min(window.devicePixelRatio || 1, 2) });
    const canvas = el("canvas");
    canvas.width = vp.width;
    canvas.height = vp.height;
    pg.append(canvas);
    await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
  } catch { delete pg.dataset.drawn; }
}

function currentPage() {
  const top = pagesEl.scrollTop + pagesEl.clientHeight * 0.35;
  for (const pg of pagesEl.children) {
    if (pg.classList.contains("pg") && pg.offsetTop + pg.offsetHeight > top) return +pg.dataset.n;
  }
  return pagesEl.querySelector(".pg") && reader.pdf ? reader.pdf.numPages : 1;
}

function updatePageLabel() {
  $("#readerPage").textContent = reader.pdf ? `p. ${currentPage()} / ${reader.pdf.numPages}` : "";
}

function goToPage(n) {
  const pg = pagesEl.querySelector(`.pg[data-n="${n}"]`);
  if (!pg) return;
  pagesEl.scrollTo({ top: pg.offsetTop - 12, behavior: "auto" });
  pg.classList.remove("flash");
  void pg.offsetWidth;
  pg.classList.add("flash");
}

let scrollTick = 0;
pagesEl.addEventListener("scroll", () => {
  cancelAnimationFrame(scrollTick);
  scrollTick = requestAnimationFrame(updatePageLabel);
});
$("#zoomIn").onclick = () => { reader.zoom = Math.min(2.5, reader.zoom * 1.2); layoutPages(); };
$("#zoomOut").onclick = () => { reader.zoom = Math.max(0.5, reader.zoom / 1.2); layoutPages(); };
let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(layoutPages, 200); });

// ---------- markdown + citations ----------

const CITE = /\[(D\d+)[\s,:]+((?:pp?\.?\s*)?\d+(?:\s*[-–,]\s*(?:pp?\.?\s*)?\d+)*)\]/g;

function renderMarkdown(target, text, tags = {}) {
  const html = window.DOMPurify.sanitize(window.marked.parse(text, { gfm: true }), { FORBID_TAGS: ["style", "form", "input"] });
  target.innerHTML = html;
  for (const table of target.querySelectorAll("table")) {
    const wrap = el("div", "table-wrap");
    table.replaceWith(wrap);
    wrap.append(table);
  }
  for (const a of target.querySelectorAll("a")) { a.target = "_blank"; a.rel = "noopener noreferrer"; }

  const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (n.nodeValue.includes("[D") && !n.parentElement.closest("code, pre, a")) nodes.push(n);
  }
  for (const node of nodes) {
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of node.nodeValue.matchAll(CITE)) {
      frag.append(node.nodeValue.slice(last, m.index));
      last = m.index + m[0].length;
      const ref = tags[m[1]];
      const live = ref && docById(ref.id);
      for (const num of m[2].match(/\d+/g)) {
        const c = el(live ? "button" : "span", "cite" + (live ? "" : " gone"), `${m[1]}·${num}`);
        if (live) {
          c.type = "button";
          c.dataset.doc = ref.id;
          c.dataset.page = num;
          c.title = `${ref.name}, page ${num}`;
          c.style.setProperty("--c", `var(--d${m[1].slice(1)})`);
        } else {
          c.title = ref ? `${ref.name} is no longer on your desk` : "Source not on your desk";
        }
        frag.append(c);
      }
    }
    if (last) {
      frag.append(node.nodeValue.slice(last));
      node.replaceWith(frag);
    }
  }
}

messagesEl.addEventListener("click", (e) => {
  const c = e.target.closest("button.cite");
  if (c) { setTab("reader"); openDoc(c.dataset.doc, +c.dataset.page); }
});

// ---------- chat ----------

function renderShortcuts() {
  const inScope = $("#scope").value === "all" ? state.docs.length : 1;
  const usable = (a) => inScope >= (a.min_docs || 1);

  const strip = $("#strip");
  strip.replaceChildren();
  if (state.messages.length) {
    for (const a of state.actions) {
      const c = chip(a);
      c.disabled = !usable(a);
      c.onclick = () => send({ action: a.id });
      strip.append(c);
    }
  }
  for (const card of messagesEl.querySelectorAll(".card")) card.disabled = !usable(actionById(card.dataset.id));
}

function renderIntro() {
  const intro = el("div", "intro");
  const n = state.docs.length;
  intro.append(el("h3", null, n > 1 ? `${n} PDFs on your desk. Where to?` : "It's on your desk. Where to?"),
    el("p", null, "Pick a shortcut, or just ask in your own words below."));
  const groups = [...new Set(state.actions.map((a) => a.group))];
  for (const g of groups) {
    intro.append(el("p", "group-name", g));
    const cards = el("div", "cards");
    for (const a of state.actions.filter((x) => x.group === g)) {
      const card = el("button", "card");
      card.type = "button";
      card.dataset.id = a.id;
      card.append(el("span", "key", a.key), el("b", null, a.label), el("small", null, a.blurb));
      card.onclick = () => send({ action: a.id });
      cards.append(card);
    }
    intro.append(cards);
  }
  return intro;
}

function messageNode(m) {
  const node = el("article", `msg ${m.role === "user" ? "user" : "ai"}`);
  const bubble = el("div", "bubble");
  node.append(bubble);
  if (m.role === "user") {
    const a = m.action && actionById(m.action);
    if (a) bubble.append(chip(a, "span"));
    bubble.append(el("span", null, m.content));
  } else {
    bubble.classList.add("md");
    fillAnswer(node, m);
  }
  return node;
}

function fillAnswer(node, m) {
  renderMarkdown($(".bubble", node), m.content, m.tags);
  node.querySelector(".msg-foot")?.remove();
  node.querySelector(".followups")?.remove();
  const foot = el("div", "msg-foot");
  const copy = el("button", "text-btn", "Copy");
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(m.content); copy.textContent = "Copied"; }
    catch { copy.textContent = "Copy failed"; }
    setTimeout(() => (copy.textContent = "Copy"), 1500);
  };
  foot.append(copy);
  if (m.trimmed) foot.append(el("span", "note", "long PDFs: read the most relevant pages"));
  if (m.stopped) foot.append(el("span", "note", "stopped"));
  node.append(foot);
  if (m.followups?.length) {
    const box = el("div", "followups");
    for (const q of m.followups) {
      const b = el("button", "followup", q);
      b.onclick = () => send({ text: q });
      box.append(b);
    }
    node.append(box);
  }
}

function renderMessages() {
  messagesEl.replaceChildren();
  if (!state.messages.length) messagesEl.append(renderIntro());
  else for (const m of state.messages) messagesEl.append(messageNode(m));
  renderShortcuts();
  messagesEl.scrollTop = state.messages.length ? messagesEl.scrollHeight : 0;
}

function nearBottom() {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 120;
}

function setBusy(on) {
  state.busy = on;
  const btn = $("#send");
  btn.classList.toggle("stop", on);
  btn.textContent = on ? "■" : "↑";
  btn.setAttribute("aria-label", on ? "Stop" : "Send");
}

async function send({ text = "", action = null }) {
  text = text.trim();
  if (state.busy || (!text && !action)) return;
  if (!state.docs.length) return toast("Add a PDF first.");
  setTab("chat");

  const scope = $("#scope").value;
  const userMsg = { role: "user", content: text, action };
  const aiMsg = { role: "assistant", content: "", tags: {}, followups: [] };
  if (!state.messages.length) messagesEl.replaceChildren();
  state.messages.push(userMsg);
  const userNode = messageNode(userMsg);
  const aiNode = el("article", "msg ai");
  const bubble = el("div", "bubble md");
  const thinking = el("div", "thinking");
  const line = el("span", null, THINKING[0]);
  thinking.append(el("i"), line);
  bubble.append(thinking);
  aiNode.append(bubble);
  messagesEl.append(userNode, aiNode);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  renderShortcuts();

  let step = 0;
  const ticker = setInterval(() => { line.textContent = THINKING[++step % THINKING.length]; }, 2200);
  setBusy(true);
  state.abort = new AbortController();
  let raw = "", frame = 0, failed = null;

  const paint = () => {
    frame = 0;
    const stick = nearBottom();
    aiMsg.content = raw.split(MARK)[0].replace(/<{1,2}[A-Z]*$/, "").trimEnd();
    renderMarkdown(bubble, aiMsg.content, aiMsg.tags);
    if (stick) messagesEl.scrollTop = messagesEl.scrollHeight;
  };

  try {
    const res = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text, action, doc_ids: scope === "all" ? null : [scope],
        style: state.style, strict: $("#strict").checked,
      }),
      signal: state.abort.signal,
    });
    const stream = res.body.getReader(), decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await stream.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const l of lines) {
        if (!l.trim()) continue;
        const ev = JSON.parse(l);
        if (ev.type === "meta") { aiMsg.tags = ev.tags; aiMsg.trimmed = ev.trimmed; }
        else if (ev.type === "delta") { raw += ev.text; clearInterval(ticker); frame ||= requestAnimationFrame(paint); }
        else if (ev.type === "done") aiMsg.followups = ev.followups || [];
        else if (ev.type === "error") failed = ev.message;
      }
    }
  } catch (e) {
    if (e.name === "AbortError") aiMsg.stopped = true;
    else if (e.status) {
      // rejected before anything was saved: take the question back out
      clearInterval(ticker);
      setBusy(false);
      state.messages.pop();
      userNode.remove();
      aiNode.remove();
      if (!state.messages.length) renderMessages();
      input.value = text;
      return toast(e.message);
    } else failed = "The connection dropped. Check that the server is running and try again.";
  }

  clearInterval(ticker);
  cancelAnimationFrame(frame);
  setBusy(false);
  if (raw) {
    paint();
    state.messages.push(aiMsg);
    fillAnswer(aiNode, aiMsg);
  } else {
    bubble.replaceChildren();
  }
  if (failed || !raw) bubble.append(el("p", "error", failed || (aiMsg.stopped ? "Stopped before an answer arrived." : "No answer came back. Try again.")));
  renderShortcuts();
  if (nearBottom()) messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ---------- composer ----------

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

let slashItems = [], slashSel = 0;
function renderSlash() {
  const v = input.value;
  if (!v.startsWith("/") || v.includes("\n")) { slash.hidden = true; return; }
  const q = v.slice(1).toLowerCase().trim();
  slashItems = state.actions.filter((a) => !q || (a.label + " " + a.blurb + " " + a.id).toLowerCase().includes(q));
  if (!slashItems.length) { slash.hidden = true; return; }
  slashSel = Math.min(slashSel, slashItems.length - 1);
  slash.replaceChildren(...slashItems.map((a, i) => {
    const b = el("button", i === slashSel ? "sel" : "");
    b.type = "button";
    b.append(el("span", "key", a.key), el("b", null, a.label), el("small", null, a.blurb));
    b.onclick = () => pickSlash(a);
    return b;
  }));
  slash.hidden = false;
  slash.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
}

function pickSlash(a) {
  input.value = "";
  slash.hidden = true;
  autosize();
  send({ action: a.id });
}

input.addEventListener("input", () => { slashSel = 0; autosize(); renderSlash(); });
input.addEventListener("keydown", (e) => {
  if (!slash.hidden) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      slashSel = (slashSel + (e.key === "ArrowDown" ? 1 : slashItems.length - 1)) % slashItems.length;
      return renderSlash();
    }
    if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); return pickSlash(slashItems[slashSel]); }
    if (e.key === "Escape") { slash.hidden = true; return; }
  }
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
});

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.busy) return state.abort?.abort();
  const text = input.value;
  if (!text.trim()) return;
  input.value = "";
  autosize();
  send({ text });
});

$("#style").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.style = b.dataset.v;
  for (const x of $("#style").children) x.classList.toggle("on", x === b);
});
$("#scope").addEventListener("change", renderShortcuts);

$("#clearBtn").onclick = async () => {
  if (!state.messages.length || state.busy) return;
  if (!confirm("Delete this conversation? Your PDFs stay on the desk.")) return;
  try { await api("/api/chat", { method: "DELETE" }); } catch (e) { return toast(e.message); }
  state.messages = [];
  renderMessages();
};

$("#exportBtn").onclick = () => {
  if (!state.messages.length) return toast("Nothing to export yet.");
  const parts = [`# PDFer notes\n\nPDFs: ${state.docs.map((d) => `D${d.tag} = ${d.name}`).join("; ")}\n`];
  for (const m of state.messages) {
    if (m.role === "user") {
      const a = m.action && actionById(m.action);
      parts.push(`## ${[a?.label, m.content].filter(Boolean).join(": ")}\n`);
    } else parts.push(m.content + "\n");
  }
  const url = URL.createObjectURL(new Blob([parts.join("\n")], { type: "text/markdown" }));
  const a = el("a");
  a.href = url;
  a.download = "pdfer-notes.md";
  a.click();
  URL.revokeObjectURL(url);
};

// ---------- uploads, theme, tabs ----------

const fileInput = $("#file");
const pick = () => fileInput.click();
$("#heroDrop").onclick = pick;
$("#addDoc").onclick = pick;
fileInput.onchange = () => { addFiles(fileInput.files); fileInput.value = ""; };

let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (e) => { if (hasFiles(e)) { dragDepth++; $("#veil").classList.add("on"); } });
window.addEventListener("dragleave", (e) => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; $("#veil").classList.remove("on"); } });
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("#veil").classList.remove("on");
  addFiles(e.dataTransfer.files);
});

$("#themeBtn").onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("pdfer-theme", next); } catch { /* private mode */ }
};

function setTab(tab) {
  app.dataset.tab = tab;
  for (const b of $("#tabs").children) b.classList.toggle("on", b.dataset.tab === tab);
  // the reader may have been laid out while hidden (small screens); fix its width once visible
  const first = pagesEl.querySelector(".pg");
  if (tab === "reader" && first && parseFloat(first.style.width) !== pageWidth()) layoutPages();
}
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  setTab(b.dataset.tab);
});

// ---------- boot ----------

async function boot() {
  try {
    const data = await (await api("/api/state")).json();
    Object.assign(state, { docs: data.docs, messages: data.messages, actions: data.actions, limits: data.limits });
    $("#heroMax").textContent = data.limits.docs;
    $("#heroLimits").textContent = `up to ${data.limits.file_mb} MB each · scanned pages are read too`;
    $("#heroActions").replaceChildren(...state.actions.map((a) => chip(a, "span")));
    setTab("chat");
    renderDesk();
    renderMessages();
    if (state.docs[0]) openDoc(state.docs[0].id);
    if (!data.ai_ready) toast("No Gemini API key found. Add GEMINI_API_KEY to the .env file and restart.");
  } catch {
    toast("Could not reach the PDFer server. Is it running?");
  }
}
boot();
