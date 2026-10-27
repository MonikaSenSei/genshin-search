"use strict";
/* 原神全文检索 v1: literal + alias-expanded search fully in-browser.
   Mirrors scripts/query.py tiering: IDF per alias (log2(N/(df+1))),
   doc score = sum over distinct terms hit; strong = literal hit, or
   >=2 distinct aliases, or single alias with df<=5; else weak (cap 15). */

const state = { meta: null, g: null, s: null };

const TYPE_LABEL = {
  "textmap:dialog": "对白", "textmap:mainquest": "主线任务", "textmap:quest": "任务",
  "textmap:reminder": "调查短句", "textmap:codex": "图鉴", "textmap:materialcodex": "材料图鉴",
  "textmap:viewcodex": "场景图鉴", "textmap:talk": "角色闲聊", "textmap:dailytask": "每日任务",
  "textmap:item": "物品", "textmap:gadget": "环境物件", "textmap:food": "食物",
  "textmap:book": "书籍条目", "book": "书籍正文", "book_title": "书名条目", "subtitle": "过场字幕",
  "textmap:unreferenced": "未引用文本",
  "textmap:unreleased": "未上线文本",
  "textmap:ext": "其他文本（玩法/系统）",
  "book_obc": "书籍（观测枢转录）", "maptext": "世界文书", "maptext_obc": "世界文书（观测枢转录）",
  "maptext_title": "世界文书条目",
  "pickup": "世界文书（未收录）", "flavor": "物品故事",
};
// M4.12 user rule: world documents / item stories / wiki transcriptions rank
// strictly below the main corpus regardless of score.
const LOW_TIERS = new Set(["maptext", "maptext_obc", "pickup", "flavor"]);
const SRC_LABEL = { takumi: "官网新闻", mys: "米游社", bili: "B站" };
const KIND_LABEL = { weapon: "武器", artifact: "圣遗物套装", food: "料理", material: "材料" };

async function fetchDecompressed(base, onProgress) {
  const tryOne = async (url, fmt) => {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(resp.status);
    const total = Number(resp.headers.get("content-length")) || 0;
    let body;
    if (onProgress) {
      // report real downloaded bytes against the compressed content-length
      const reader = resp.body.getReader();
      const chunks = [];
      let got = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        got += value.length;
        onProgress("download", total ? Math.min(1, got / total) : -1, got);
      }
      const merged = new Uint8Array(got);
      let o = 0;
      for (const c of chunks) { merged.set(c, o); o += c.length; }
      body = new Response(merged).body;
    } else {
      body = resp.body;
    }
    const ds = new DecompressionStream(fmt);
    return new Uint8Array(await new Response(body.pipeThrough(ds)).arrayBuffer());
  };
  try { return await tryOne(base + ".zst", "zstd"); }
  catch (e) { return await tryOne(base + ".gz", "gzip"); }
}

function parseBin(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]) !== "GSBN")
    throw new Error("bad magic");
  const hlen = dv.getUint32(4, true);
  const header = JSON.parse(new TextDecoder("utf-8").decode(bytes.subarray(8, 8 + hlen)));
  let p = 8 + hlen;
  const sec = (n) => { const a = bytes.subarray(p, p + header.lens[n]); p += header.lens[n]; return a; };
  return { header, sec };
}

function reinterp(b, Ctor) {
  return new Ctor(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
}

async function loadGame(onProgress) {
  const bytes = await fetchDecompressed("data/genshin.bin", onProgress);
  const { header, sec } = parseBin(bytes);
  const offs = reinterp(sec(0), Uint32Array);
  const blob = new TextDecoder("utf-8").decode(sec(1));
  const cols = [reinterp(sec(2), Uint8Array), reinterp(sec(3), Uint16Array),
                reinterp(sec(4), Uint16Array), reinterp(sec(5), Uint16Array)];
  // char-pair frequency table (pairs uint32 + counts uint16): lets the
  // scorer demote word-boundary glue hits (警长|正在 contains 长正)
  let bg = null;
  if (header.bgN > 0) {
    const raw = sec(6);
    const n = header.bgN;
    const pairs = new Uint32Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + n * 4));
    const counts = new Uint16Array(raw.buffer.slice(raw.byteOffset + n * 4, raw.byteOffset + raw.byteLength));
    bg = new Map();
    for (let i = 0; i < n; i++) bg.set(pairs[i], counts[i]);
  }
  // conversation context columns (M4.15): doc -> (seq, pos); chunk files
  // data/conv/<n>.json[.zst|.gz] hold [[speaker, line], ...] arrays and
  // load lazily when a card expands its dialogue.
  let cv = null;
  if (header.convChunk > 0 && header.convN > 0) {
    cv = { chunk: header.convChunk, nChunks: header.convChunks,
           n: header.convN, idx: null, files: new Map() };
  }
  state.g = { n: header.n, offs, blob, cols, cv, tbl: header, bg };
}

async function loadSocial(onProgress) {
  const bytes = await fetchDecompressed("data/social.bin", onProgress);
  const { header, sec } = parseBin(bytes);
  const offs = reinterp(sec(0), Uint32Array);
  const blob = new TextDecoder("utf-8").decode(sec(1));
  const cols = [reinterp(sec(2), Uint8Array), reinterp(sec(3), Uint16Array),
                reinterp(sec(4), Uint16Array)];
  state.s = { n: header.n, offs, blob, cols, tbl: header };
}

function bisectDoc(offs, pos) {
  let lo = 0, hi = offs.length - 1;
  while (lo + 1 < hi) { const m = (lo + hi) >> 1; if (offs[m] <= pos) lo = m; else hi = m; }
  return offs[lo] <= pos && pos < offs[lo + 1] - 1 ? lo : -1;
}

const ADDR_SUFFIX = /^(大人|先生|女士|小姐|将军|队长|团长|参谋|骑士|武士|前辈|师父|师傅|殿下|公子|管家|执事|老师)/;
const isCJKCode = (c) => c >= 0x4E00 && c <= 0x9FFF;
// single-char particles/suffixes: adjacency to one is a REAL word boundary,
// never glue evidence (长正的 = real name + 的; 的长正… = word starts after 的)
const PARTICLE = new Set("的了着过地得之其此该们个些吗呢吧啊呀嘛哦么哈".split(""));

function findDocs(corpus, term, hits, quality) {
  // Index tokenizer ignores punctuation/whitespace between chars (FTS5
  // single-char CJK), so exact-substring and tolerant-regex results are
  // unioned; both count each doc once.
  // Quality tracking (user rule 2026-10): a hit whose every occurrence is
  // word-glued on both sides (警长|正在 contains 长正; 擅长|正面 too) is a
  // cross-word accident -> demoted. Evidence: left pair (prev,term0) and
  // right pair (termLast,next) must both be real corpus words, and the
  // query term must be far rarer than the glue pair it accidentally forms.
  const blob = corpus.blob, offs = corpus.offs;
  const docs = new Set();
  const dem = new Set(); // docs whose every occurrence of term is glue-suspect
  let occ = 0;
  const touch = (d) => {
    docs.add(d);
    let s = hits.get(d); if (!s) hits.set(d, s = new Set());
    s.add(term);
    if (!quality.has(d)) quality.set(d, new Map());
    if (!quality.get(d).has(term)) quality.get(d).set(term, { clean: false, maxGlue: 0 });
    return quality.get(d).get(term);
  };
  let pos = blob.indexOf(term);
  while (pos >= 0) {
    occ++;
    const d = bisectDoc(offs, pos);
    if (d >= 0) {
      const st = touch(d);
      const prevC = pos > 0 ? blob.charCodeAt(pos - 1) : 0;
      const nIdx = pos + term.length;
      const nextC = nIdx < blob.length ? blob.charCodeAt(nIdx) : 0;
      if (!(isCJKCode(prevC) && isCJKCode(nextC)) || PARTICLE.has(blob[pos - 1]) ||
          PARTICLE.has(blob[nIdx]) || ADDR_SUFFIX.test(blob.slice(nIdx, nIdx + 3))) {
        st.clean = true; // real word boundary on at least one side
      } else if (term.length > 1 && corpus.bg) {
        // >>>0: JS bitwise ops are signed int32; pair keys are unsigned
        const lf = corpus.bg.get((prevC << 16 | term.charCodeAt(0)) >>> 0) || 0;
        if (lf > st.maxGlue) st.maxGlue = lf;
        const rf = corpus.bg.get((term.charCodeAt(term.length - 1) << 16 | nextC) >>> 0) || 0;
        if (rf > st.maxGlue) st.maxGlue = rf;
      } else {
        st.clean = true;
      }
    }
    pos = blob.indexOf(term, pos + term.length);
  }
  const re = term.length > 1 ? tolerantRegex(term) : null;
  if (re) {
    let m;
    while ((m = re.exec(blob))) {
      // only a real whitespace gap counts as wrap-recall; a zero-gap match
      // is the exact occurrence already classified above
      if (m[0].length > term.length) {
        const d = bisectDoc(offs, m.index);
        if (d >= 0) touch(d).clean = true;
      }
      if (re.lastIndex === m.index) re.lastIndex++;
    }
  }
  if (corpus.bg && term.length > 1) {
    // one strong side is enough (擅长|正向思考 — 正向 itself is not a bigram);
    // safety nets: glue pair must itself be a real common word (>=300) and
    // the query term must be 3x rarer than the glue it accidentally forms
    for (const [d, m] of quality) {
      const st = m.get(term);
      if (st && !st.clean && st.maxGlue >= 300 && occ <= 0.3 * st.maxGlue) dem.add(d);
    }
  }
  return { df: docs.size, occ, dem };
}

function tolerantRegex(term) {
  // Line-wrap tolerance only: the FTS tokenizer skips ALL punctuation, but
  // same-line punctuation gaps are almost always word-boundary accidents
  // ("当天，父亲" ~= 天父). Measured: 3/3 such gap matches in the alias
  // layer are false positives, 0 true hits depend on them. Whitespace/newline
  // gaps (real line-wraps in book/poem text) are kept.
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(term.split("").map(esc).join("[\\s]*"), "gu");
}

function searchCorpus(corpus, terms, base) {
  const N = corpus.n, hits = new Map(), weights = new Map();
  const quality = new Map(); // doc -> term -> {clean, maxPair}
  for (const t of terms) {
    const info = findDocs(corpus, t, hits, quality);
    weights.set(t, { idf: Math.log2(N / (info.df + 1)), df: info.df,
                     dem: info.dem });
  }
  // Title matches now live in their own top section (renderTitleMatches);
  // the game list keeps plain IDF ranking, with title-card docs suppressed
  // there to avoid duplicating the title section.
  const results = [];
  for (const [doc, set] of hits) {
    const uniq = [...set];
    const demoted = (t) => weights.get(t).dem.has(doc);
    const aliasHits = uniq.filter((t) => t !== base);
    const cleanAliases = aliasHits.filter((t) => !demoted(t));
    // word-boundary glue (警长|正在 for a name query) gets 0.35x weight and
    // never holds a doc up in the strong tier by itself
    const strong = (uniq.includes(base) && !demoted(base)) ||
      cleanAliases.length >= 2 ||
      cleanAliases.some((t) => weights.get(t).df <= 5);
    results.push({ doc, via: uniq, strong,
      demoted: uniq.includes(base) && demoted(base),
      score: uniq.reduce((a, t) => a + (demoted(t) ? weights.get(t).idf * 0.35
                                                   : weights.get(t).idf), 0) });
  }
  results.sort((a, b) => lowRank(corpus, a.doc) - lowRank(corpus, b.doc) ||
    b.score - a.score || a.doc - b.doc);
  return { results, weights };
}

function lowRank(corpus, doc) {
  const ty = corpus.tbl.ty[corpus.cols[0][doc]];
  return LOW_TIERS.has(ty) ? 1 : 0;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function highlightInto(node, text, terms, window) {
  // render text with <mark> on first region containing a term hit
  let start = 0, end = text.length;
  if (window) {
    let at = -1;
    for (const t of terms) { const i = text.indexOf(t); if (i >= 0 && (at < 0 || i < at)) at = i; }
    if (at >= 0) { start = Math.max(0, at - window); end = Math.min(text.length, at + window); }
  }
  if (start > 0) node.append("…");
  const marks = [];
  for (const t of terms) {
    let i = text.indexOf(t, start);
    while (i >= 0 && i < end) { marks.push([i, i + t.length]); i = text.indexOf(t, i + t.length); }
  }
  marks.sort((a, b) => a[0] - b[0]);
  let cur = start;
  for (const [a, b] of marks) {
    if (a < cur) continue;
    node.append(text.slice(cur, a));
    const m = el("mark"); m.textContent = text.slice(a, b); node.append(m);
    cur = b;
  }
  node.append(text.slice(cur, end));
  if (end < text.length) node.append("…");
}

function renderLinkGrid(box, header, matches, tagLabel, wide) {
  // Shared grid of link cards (books / characters / creatures): clicking a
  // card opens the 观测枢 (or BWiki) entry in a new tab — no in-site modal.
  box.append(el("h3", null, header));
  const grid = el("div", "item-grid");
  if (wide) grid.classList.add("wide-grid");
  for (const m of matches) {
    const card = el("a", "item-card book-card");
    card.title = m.name;
    card.href = m.url || "#";
    card.target = "_blank"; card.rel = "noopener";
    if (!m.url) card.classList.add("no-link");
    if (m.icon) { const img = el("img"); img.src = m.icon; img.loading = "lazy"; img.alt = ""; card.append(img); }
    card.append(el("div", "item-name", m.disp || m.name));
    const meta = el("div", "item-meta");
    meta.append(el("span", "tag", tagLabel(m)));
    card.append(meta);
    grid.append(card);
  }
  box.append(grid);
}

function renderTitleSection(q) {
  // Dedicated top section: books whose title contains the query. Rendered as
  // an icon grid like the items section; cards open the 观测枢 entry directly
  // (no in-site modal). Data = books.bin (titles joined to OBC entries, cover
  // icons from the book-channel listing); falls back to the old src-label
  // scan when the books layer is absent.
  const sec = document.getElementById("titles-sec");
  const box = document.getElementById("titles");
  box.replaceChildren();
  let matches;
  if (state.books && state.books.length) {
    matches = state.books.filter((b) => b.title.includes(q))
      .map((b) => ({ name: b.title, disp: b.disp || `《${b.title}》`,
                     url: b.url, icon: b.icon }));
  } else {
    const PREFIX = "书籍:";
    const UNRESOLVED = /^[A-Za-z]+\d/; // BookNNN/WeaponNNN… = title not joined back
    const seen = new Set();
    matches = [];
    (state.g.tbl.src || []).forEach((s, i) => {
      if (!s.startsWith(PREFIX)) return;
      const title = s.slice(PREFIX.length);
      if (UNRESOLVED.test(title) || !title.includes(q) || seen.has(title)) return;
      seen.add(title);
      matches.push({ name: title, disp: `《${title}》`,
                     url: (state.g.tbl.src_url || [])[i] || "", icon: "" });
    });
  }
  if (!matches.length) { sec.hidden = true; return; }
  matches.sort((a, b) => a.name.localeCompare(b.name, "zh"));
  sec.hidden = false;
  renderLinkGrid(box, `书名含「${q}」 · ${matches.length} 本`, matches,
    (m) => m.url.includes("biligame") ? "BWiki" : "观测枢原文", true);
}

function renderEntrySection(q, terms, key, secId, boxId, unit) {
  // characters.bin / creatures.bin: name-variant match (through the alias
  // table too: 「仆人」→阿蕾奇诺), cards link to the 观测枢 entry page.
  const sec = document.getElementById(secId);
  const box = document.getElementById(boxId);
  box.replaceChildren();
  const list = state[key] || [];
  const matches = list.filter((e) =>
    terms.some((t) =>
      (e.alias || "").includes(t) ||
      (e.match || []).some((v) => v.includes(t))));
  if (!matches.length) { sec.hidden = true; return; }
  matches.sort((a, b) => a.name.localeCompare(b.name, "zh"));
  sec.hidden = false;
  renderLinkGrid(box, `${unit}名含「${q}」 · ${matches.length} 个`, matches,
    () => "观测枢词条", true);
}

async function loadItems() {
  try {
    const bytes = await fetchDecompressed("data/items.bin");
    state.items = JSON.parse(new TextDecoder("utf-8").decode(bytes));
  } catch (e) { state.items = []; } // site built without the items layer
}

async function loadBooks() {
  try {
    const bytes = await fetchDecompressed("data/books.bin");
    state.books = JSON.parse(new TextDecoder("utf-8").decode(bytes));
  } catch (e) { state.books = []; } // site built without the books layer
}

async function loadLayer(key) {
  try {
    const bytes = await fetchDecompressed(`data/${key}.bin`);
    state[key] = JSON.parse(new TextDecoder("utf-8").decode(bytes));
  } catch (e) { state[key] = []; } // site built without this layer
}

function starHtml(n) {
  return "★".repeat(n) + '<span class="star-off">' + "☆".repeat(Math.max(0, 5 - n)) + "</span>";
}

function openItemModal(it) {
  const old = document.getElementById("item-modal");
  if (old) old.remove();
  const ov = el("div", "modal"); ov.id = "item-modal";
  const box = el("div", "modal-box");
  const close = el("button", "modal-close", "×");
  close.addEventListener("click", () => ov.remove());
  box.append(close);
  const head = el("div", "modal-head");
  if (it.icon) { const img = el("img"); img.src = it.icon; img.alt = ""; head.append(img); }
  const hi = el("div");
  hi.append(el("div", "modal-name", it.name));
  const meta = el("div", "meta");
  if (KIND_LABEL[it.kind]) meta.append(el("span", "tag", KIND_LABEL[it.kind]));
  if (it.star) { const s = el("span", "item-star"); s.innerHTML = starHtml(it.star); meta.append(s); }
  if (it.rarity) meta.append(el("span", "src", it.rarity));
  if (it.category) meta.append(el("span", "src", it.category));
  if (it.alias) meta.append(el("span", "src", "别名：" + it.alias));
  hi.append(meta);
  head.append(hi);
  box.append(head);
  const sect = (title, text) => {
    if (!text) return;
    box.append(el("h4", "modal-h", title));
    const b = el("div", "body"); b.textContent = text; box.append(b);
  };
  if (it.desc) sect("描述", it.desc);
  if (it.effect) sect("效果", it.effect);
  for (const s of it.slots || [])
    sect(`${s.slot}：${s.name}`, [s.desc, s.story].filter(Boolean).join("\n\n"));
  if (it.story) sect("故事", it.story);
  if (it.obtain) sect("获取方式", it.obtain);
  if (it.url) {
    const a = el("a", "link", "在观测枢查看完整词条（数值/推荐角色）");
    a.href = it.url; a.target = "_blank"; a.rel = "noopener";
    box.append(a);
  }
  ov.append(box);
  ov.addEventListener("click", (ev) => { if (ev.target === ov) ov.remove(); });
  document.addEventListener("keydown", function esc(ev) {
    if (ev.key === "Escape") { ov.remove(); document.removeEventListener("keydown", esc); }
  });
  document.body.append(ov);
}

function renderItemsSection(q) {
  const sec = document.getElementById("items-sec");
  const box = document.getElementById("items");
  box.replaceChildren();
  const matches = (state.items || []).filter(
    (it) => it.name.includes(q) || (it.alias || "").includes(q));
  if (!matches.length) { sec.hidden = true; return; }
  sec.hidden = false;
  matches.sort((a, b) => (b.star - a.star) || a.name.localeCompare(b.name, "zh"));
  box.append(el("h3", null, `物品名含「${q}」 · ${matches.length} 个`));
  const grid = el("div", "item-grid");
  for (const it of matches) {
    const card = el("div", "item-card");
    card.title = it.name;
    if (it.icon) { const img = el("img"); img.src = it.icon; img.loading = "lazy"; img.alt = ""; card.append(img); }
    card.append(el("div", "item-name", it.name));
    const meta = el("div", "item-meta");
    if (KIND_LABEL[it.kind]) meta.append(el("span", "tag", KIND_LABEL[it.kind]));
    if (it.star) { const s = el("span", "item-star"); s.innerHTML = starHtml(it.star); meta.append(s); }
    card.append(meta);
    card.addEventListener("click", () => openItemModal(it));
    grid.append(card);
  }
  box.append(grid);
}

async function renderGame(results, terms) {
  const box = document.getElementById("strong");
  const weakBox = document.getElementById("weak");
  box.replaceChildren(); weakBox.replaceChildren();
  const g = state.g;
  // title-card docs are represented by the 书名匹配 section, not here
  results = results.filter((r) => g.tbl.ty[g.cols[0][r.doc]] !== "book_title");
  const seenBodies = new Set();
  const dedup = (rs) => rs.filter((r) => {
    const text = g.blob.slice(g.offs[r.doc], g.offs[r.doc + 1] - 1);
    if (seenBodies.has(text)) return false;
    seenBodies.add(text); return true;
  });
  if (g.cv && !g.cv.idx) { try { await ensureConvIdx(g.cv); } catch (e) { g.cv = null; } }
  const strong = dedup(results.filter((r) => r.strong)).slice(0, 50);
  const weakAll = results.filter((r) => !r.strong);
  const weak = dedup(weakAll).slice(0, 15);
  box.append(el("h3", null, `强相关 · ${results.filter((r) => r.strong).length} 篇`));
  for (const r of strong) box.append(gameCard(r, terms, g));
  if (weakAll.length) {
    const note = el("h3", null, `弱相关（仅单一常用别名命中）· ${weakAll.length} 篇，展示 ${weak.length}，可能为噪声`);
    weakBox.append(note);
    for (const r of weak) weakBox.append(gameCard(r, terms, g));
  }
}

async function ensureConvIdx(cv) {
  if (cv.idx) return cv.idx;
  const bytes = await fetchDecompressed("data/conv-index.bin");
  cv.idx = new Uint32Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
  return cv.idx;
}

function convLookup(idx, doc) {
  // flat sorted triples (doc, seq, pos); binary search on doc
  let lo = 0, hi = idx.length / 3 - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1, d = idx[mid * 3];
    if (d === doc) return { seq: idx[mid * 3 + 1], pos: idx[mid * 3 + 2] };
    if (d < doc) lo = mid + 1; else hi = mid - 1;
  }
  return null;
}

function gameCard(r, terms, g) {
  const text = g.blob.slice(g.offs[r.doc], g.offs[r.doc + 1] - 1);
  const card = el("div", "card");
  const meta = el("div", "meta");
  meta.append(el("span", "tag", TYPE_LABEL[g.tbl.ty[g.cols[0][r.doc]]] || g.tbl.ty[g.cols[0][r.doc]]));
  meta.append(el("span", "src", g.tbl.src[g.cols[1][r.doc]]));
  const jump = (g.tbl.doc_url || {})[r.doc] || (g.tbl.src_url || [])[g.cols[1][r.doc]];
  if (jump) { const a = el("a", "link", "跳转原文"); a.href = jump; a.target = "_blank"; a.rel = "noopener"; meta.append(a); }
  const spk = g.tbl.spk[g.cols[2][r.doc]];
  if (spk) meta.append(el("span", "spk", "说话人：" + spk));
  const cast = g.tbl.cast[g.cols[3][r.doc]];
  if (cast) { const d = el("span", "cast", "在场：" + cast); d.title = cast; meta.append(d); }
  meta.append(el("span", "score", "得分 " + r.score.toFixed(1)));
  if (r.demoted) {
    const d = el("span", "src", "（疑似跨词拼接命中，已降权）");
    d.title = "查询词在文中由相邻两词的尾首拼成（如「警长|正在」含「长正」），按语料字对频率降权";
    meta.append(d);
  }
  card.append(meta);
  const body = el("div", "body");
  highlightInto(body, text, terms, text.length > 400 ? 200 : 0);
  card.append(body);
  const via = el("div", "via", "命中词：" + r.via.join("、"));
  card.append(via);
  const cv = g.cv;
  const cvHit = cv && cv.idx ? convLookup(cv.idx, r.doc) : null;
  if (cvHit) {
    const link = el("a", "link", "展开对话上下文");
    link.href = "javascript:void(0)";
    const panel = el("div", "conv");
    panel.hidden = true;
    link.addEventListener("click", async () => {
      if (!panel.hidden) { panel.hidden = true; link.textContent = "展开对话上下文"; return; }
      if (!panel.dataset.built) {
        link.textContent = "载入中…";
        try {
          const seq = cvHit.seq;
          const c = Math.floor(seq / cv.chunk);
          let chunkArr = cv.files.get(c);
          if (!chunkArr) {
            const [bytes, mbytes] = await Promise.all([
              fetchDecompressed(`data/conv/${c}.json`),
              fetchDecompressed(`data/conv/${c}.meta.json`).catch(() => null)]);
            chunkArr = JSON.parse(new TextDecoder("utf-8").decode(bytes));
            chunkArr.meta = mbytes ? JSON.parse(new TextDecoder("utf-8").decode(mbytes)) : [];
            cv.files.set(c, chunkArr);
          }
          const conv = chunkArr[seq - c * cv.chunk];
          panel.dataset.built = "1";
          link.textContent = "收起对话上下文";
          panel.append(el("div", "conv-h", "对话上下文 · " + conv.length + " 句（出处见上方标签）"));
          for (let i = 0; i < conv.length; i++) {
            const [sp, t] = conv[i];
            const row = el("div", "conv-line" + (i === cvHit.pos ? " conv-here" : ""));
            if (sp) row.append(el("span", "conv-spk", sp + "："));
            const bodySpan = el("span", "conv-txt");
            highlightInto(bodySpan, t, terms, t.length > 400 ? 200 : 0);
            row.append(bodySpan);
            panel.append(row);
          }
          if (chunkArr.meta[seq - c * cv.chunk]) {
            panel.append(el("div", "conv-note", "（对话到此结束后仍有分支选项未展开）"));
          }
        } catch (e) {
          link.textContent = "对话载入失败";
          return;
        }
      } else {
        link.textContent = "收起对话上下文";
      }
      panel.hidden = false;
    });
    card.append(link);
    card.append(panel);
  }
  return card;
}

function renderSocial(results) {
  const box = document.getElementById("social");
  box.replaceChildren();
  const s = state.s;
  if (!results.length) return;
  box.append(el("h3", null, `命中 ${results.length} 条公告`));
  for (const r of results.slice(0, 30)) {
    const doc = s.blob.slice(s.offs[r.doc], s.offs[r.doc + 1] - 1);
    const [title, bodyText] = doc.split("\u0001");
    const card = el("div", "card");
    const meta = el("div", "meta");
    meta.append(el("span", "tag", SRC_LABEL[s.tbl.so[s.cols[0][r.doc]]] || s.tbl.so[s.cols[0][r.doc]]));
    const pub = s.tbl.pu[s.cols[1][r.doc]];
    if (pub) meta.append(el("span", "src", pub));
    card.append(meta);
    card.append(el("div", "title-line", title));
    const body = el("div", "body");
    if (bodyText) highlightInto(body, bodyText, r.via, bodyText.length > 300 ? 150 : 0);
    card.append(body);
    const url = s.tbl.ur[s.cols[2][r.doc]];
    if (url) { const a = el("a", "link", "原文"); a.href = url; a.target = "_blank"; a.rel = "noopener"; card.append(a); }
    box.append(card);
  }
}

async function runSearch(rawQ) {
  const q = rawQ.trim();
  if (!q || !state.g) return; // ignore until corpora are actually loaded
  const useAlias = document.getElementById("usealias").checked;
  let terms = [q];
  const entry = state.meta.aliases.find((a) => a.term === q);
  if (entry && useAlias) terms = [q, ...entry.aliases];
  const t0 = performance.now();
  if (state.books == null) await loadBooks();
  renderTitleSection(q);
  if (state.characters == null) await loadLayer("characters");
  if (state.creatures == null) await loadLayer("creatures");
  renderEntrySection(q, terms, "characters", "chars-sec", "chars", "角色");
  renderEntrySection(q, terms, "creatures", "creatures-sec", "creatures", "生物");
  if (state.items == null) await loadItems();
  renderItemsSection(q);
  const { results, weights } = searchCorpus(state.g, terms, q);
  await renderGame(results, terms);
  const soc = searchCorpus(state.s, [q], q);
  renderSocial(soc.results);
  const known = terms.length > 1;
  let s = `「${q}」${known ? "（已按别名表扩展 " + (terms.length - 1) + " 个词形）" : ""} · 游戏语料命中 ${results.length} 篇 · 用时 ${Math.round(performance.now() - t0)} ms`;
  const sum = document.getElementById("summary");
  sum.replaceChildren(el("div", "status", s));
  if (known) {
    const det = el("div", "aliasdetail", terms.map((t) => `${t}(${weights.get(t).df})`).join(" · "));
    sum.append(det);
  }
}

function setFooter() {
  const m = state.meta;
  document.getElementById("footer").textContent =
    `语料基线 ${m.baseline} · 游戏文本 ${m.counts.docs.toLocaleString()} 篇 · ` +
    `社媒 ${m.counts.posts.toLocaleString()} 条（官网新闻；米游社与B站正文将在风控解除后由每日维护自动补齐） · ` +
    `别名表 ${m.aliases.length} 词条 · 索引构建于本次导出`;
}

const mb = (n) => (n / 1048576).toFixed(1) + " MB";

async function main() {
  const loader = document.getElementById("loader");
  const line = document.getElementById("load-status");
  const bar = document.getElementById("load-bar-fill");
  const setBar = (frac, got, total) => {
    bar.style.width = (frac >= 0 ? Math.round(frac * 100) : 0) + "%";
    if (got != null) line.textContent = `下载语料 ${mb(got)}${total ? " / " + mb(total) : ""}…`;
  };
  try {
    const metaResp = await fetch("data/meta.json");
    state.meta = await metaResp.json();
    line.textContent = "正在加载社媒公告…";
    await loadSocial((_, frac, got) => setBar(frac, got, null));
    line.textContent = "正在加载游戏语料（约 16 MB，仅首次，之后走浏览器缓存）…";
    await loadGame((_, frac, got) => setBar(frac, got, null));
    bar.style.width = "100%";
    line.textContent = "正在解析索引…";
    // yield one frame so the "parsing" line paints before the sync parse blocks
    await new Promise((r) => setTimeout(r, 30));
    setFooter();
  } catch (e) {
    loader.classList.add("fail");
    line.textContent = "加载失败：" + e + "（刷新重试）";
    return;
  }
  // corpora ready: lift the curtain, only now open the search box
  loader.classList.add("gone");
  setTimeout(() => loader.remove(), 400);
  document.getElementById("q").disabled = false;
  document.querySelector("#searchform button").disabled = false;
  document.getElementById("q").focus();
  document.getElementById("searchform").addEventListener("submit", (ev) => {
    ev.preventDefault();
    runSearch(document.getElementById("q").value);
  });
}
main();
