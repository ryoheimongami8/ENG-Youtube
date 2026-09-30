"use strict";
// ---- IndexedDB ------------------------------------------------------------
const DB_NAME = "engyt", DB_VER = 1;
let dbp;
function db() {
  return (dbp ||= new Promise((res, rej) => {
    const r = indexedDB.open(DB_NAME, DB_VER);
    r.onupgradeneeded = () => {
      r.result.createObjectStore("lessons", { keyPath: "id" });
      r.result.createObjectStore("audio", { keyPath: "id" });
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  }));
}
async function tx(store, mode, fn) {
  const d = await db();
  return new Promise((res, rej) => {
    const t = d.transaction(store, mode), out = fn(t.objectStore(store));
    t.oncomplete = () => res(out && out.result);
    t.onerror = () => rej(t.error);
  });
}
const getAll = (s) => tx(s, "readonly", (o) => o.getAll());
const get = (s, id) => tx(s, "readonly", (o) => o.get(id));
const put = (s, v) => tx(s, "readwrite", (o) => o.put(v));
const del = (s, id) => tx(s, "readwrite", (o) => o.delete(id));

// ---- elements -------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const audio = $("audio"), sentEl = $("sentences");
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// ---- library --------------------------------------------------------------
async function renderLibrary() {
  const list = (await getAll("lessons")).sort((a, b) => b.added - a.added);
  const ul = $("lessons");
  ul.textContent = "";
  for (const l of list) {
    const li = document.createElement("li");
    li.className = "lesson";
    const open = document.createElement("button");
    open.className = "open";
    open.innerHTML = '<div class="t"></div><div class="m"></div>';
    open.firstChild.textContent = l.title;
    open.lastChild.textContent = `${fmt(l.duration)} ・ ${l.sentences.length}文 ・ 学習 ${l.plays || 0}回`;
    open.onclick = () => openLesson(l.id);
    const d = document.createElement("button");
    d.className = "del";
    d.textContent = "削除";
    d.onclick = async () => {
      if (!confirm(`「${l.title}」を削除しますか？`)) return;
      await del("lessons", l.id);
      await del("audio", l.id);
      renderLibrary();
    };
    li.append(open, d);
    ul.append(li);
  }
}

async function importZip(file) {
  const files = fflate.unzipSync(new Uint8Array(await file.arrayBuffer()));
  if (!files["lesson.json"] || !files["audio.mp3"]) throw new Error("lesson.json / audio.mp3 が見つかりません");
  const lesson = JSON.parse(new TextDecoder().decode(files["lesson.json"]));
  if (!lesson.id || !Array.isArray(lesson.sentences)) throw new Error("lesson.json の形式が不正です");
  const old = await get("lessons", lesson.id);
  lesson.added = old ? old.added : Date.now();
  lesson.lastPos = old ? old.lastPos : 0;
  lesson.plays = old ? old.plays : 0;
  await put("audio", { id: lesson.id, blob: new Blob([files["audio.mp3"]], { type: "audio/mpeg" }) });
  await put("lessons", lesson);
}

$("file").onchange = async (e) => {
  const msg = $("msg");
  msg.textContent = "";
  for (const f of e.target.files) {
    try {
      msg.textContent = `取り込み中: ${f.name}`;
      await importZip(f);
      msg.textContent = "";
    } catch (err) {
      msg.textContent = `${f.name}: ${err.message}`;
    }
  }
  e.target.value = "";
  renderLibrary();
};

// ---- player ---------------------------------------------------------------
let cur = null, active = -1, repeatDone = 0, url = null, saveT = 0;

async function openLesson(id) {
  const [l, a] = await Promise.all([get("lessons", id), get("audio", id)]);
  if (!l || !a) return;
  cur = l;
  if (url) URL.revokeObjectURL(url);
  url = URL.createObjectURL(a.blob);
  audio.src = url;
  audio.playbackRate = +$("rate").value;
  $("title").textContent = l.title;
  sentEl.textContent = "";
  l.sentences.forEach((s, i) => {
    const div = document.createElement("div");
    div.className = "s" + (s.flag ? " flag" : "");
    div.dataset.i = i;
    const en = document.createElement("div");
    en.className = "en";
    if (s.words && s.words.length) {
      // show original text with punctuation when token counts match; aligner words strip it
      const toks = s.en.split(/\s+/);
      const same = toks.length === s.words.length;
      s.words.forEach((w, k) => {
        const sp = document.createElement("span");
        sp.className = "w";
        sp.textContent = same ? toks[k] : w.w;
        en.append(sp, k < s.words.length - 1 ? " " : "");
      });
    } else en.textContent = s.en;
    const ja = document.createElement("div");
    ja.className = "ja";
    ja.textContent = s.ja;
    div.append(en, ja);
    sentEl.append(div);
  });
  active = -1;
  show("player");
  const resume = Math.max(0, findIdx(l.lastPos || 0));
  audio.addEventListener("loadedmetadata", () => { audio.currentTime = l.sentences[resume].start; setActive(resume, false); }, { once: true });
}

function show(view) {
  const p = view === "player";
  $("library").hidden = p;
  $("player").hidden = !p;
  $("controls").hidden = !p;
  $("back").hidden = !p;
  if (!p) $("title").textContent = "ENG-Youtube";
}

// index of sentence containing t (last sentence starting <= t)
function findIdx(t) {
  const S = cur.sentences;
  let lo = 0, hi = S.length - 1, r = 0;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (S[m].start <= t + 0.01) { r = m; lo = m + 1; } else hi = m - 1;
  }
  return r;
}

function sentEnd(i) {
  const S = cur.sentences, next = S[i + 1];
  // small tail padding, but never into the next sentence
  const e = S[i].end + 0.15;
  return next ? Math.min(e, next.start) : e;
}

function setActive(i, scroll = true) {
  if (i === active) return;
  sentEl.children[active]?.classList.remove("active");
  sentEl.children[active]?.querySelectorAll(".w.cur").forEach((w) => w.classList.remove("cur"));
  active = i;
  const el = sentEl.children[i];
  el.classList.add("active");
  if (scroll) el.scrollIntoView({ block: "center", behavior: "smooth" });
  repeatDone = 0;
  cur.plays = (cur.plays || 0) + (audio.paused ? 0 : 1);
}

function playSentence(i, autoplay = true) {
  i = Math.min(Math.max(i, 0), cur.sentences.length - 1);
  audio.currentTime = cur.sentences[i].start;
  setActive(i);
  if (autoplay) audio.play();
}

function highlightWord(t) {
  const s = cur.sentences[active];
  if (!s || !s.words) return;
  const spans = sentEl.children[active].querySelectorAll(".w");
  let k = -1;
  for (let j = 0; j < s.words.length; j++) if (s.words[j].start <= t) k = j; else break;
  spans.forEach((sp, j) => sp.classList.toggle("cur", j === k));
}

function tick() {
  if (!cur) return;
  const t = audio.currentTime;
  if ($("repeat").checked && active >= 0 && !audio.paused && t >= sentEnd(active)) {
    const n = +$("rcount").value;
    if (n === 0 || repeatDone + 1 < n) {
      repeatDone++;
      audio.currentTime = cur.sentences[active].start;
    } else if (active + 1 < cur.sentences.length) {
      playSentence(active + 1);
    } else audio.pause();
    return;
  }
  const i = findIdx(t);
  if (i !== active) setActive(i);
  highlightWord(t);
  const now = Date.now();
  if (now - saveT > 2000 && !audio.paused) { saveT = now; cur.lastPos = t; put("lessons", cur); }
}

function loop() { tick(); requestAnimationFrame(loop); }
requestAnimationFrame(loop);

sentEl.onclick = (e) => {
  const s = e.target.closest(".s");
  if (s) playSentence(+s.dataset.i);
};
$("play").onclick = () => (audio.paused ? audio.play() : audio.pause());
$("prev").onclick = () => playSentence(active - 1, !audio.paused);
$("next").onclick = () => playSentence(active + 1, !audio.paused);
$("rate").onchange = () => (audio.playbackRate = +$("rate").value);
$("showJa").onchange = () => document.body.classList.toggle("no-ja", !$("showJa").checked);
audio.onplay = () => ($("play").textContent = "⏸");
audio.onpause = () => { $("play").textContent = "▶"; if (cur) { cur.lastPos = audio.currentTime; put("lessons", cur); } };
audio.onended = () => ($("play").textContent = "▶");
$("back").onclick = () => { audio.pause(); cur = null; show("library"); renderLibrary(); };

// preserve pitch when slowing down
audio.preservesPitch = true;

renderLibrary();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
