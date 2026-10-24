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
};
const SRC_LABEL = { takumi: "官网新闻", mys: "米游社", bili: "B站" };

async function fetchDecompressed(base) {
  const tryOne = async (url, fmt) => {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(resp.status);
    const ds = new DecompressionStream(fmt);
    return new Uint8Array(await new Response(resp.body.pipeThrough(ds)).arrayBuffer());
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

async function loadGame() {
  const bytes = await fetchDecompressed("data/genshin.bin");
  const { header, sec } = parseBin(bytes);
  const offs = reinterp(sec(0), Uint32Array);
  const blob = new TextDecoder("utf-8").decode(sec(1));
  const cols = [reinterp(sec(2), Uint8Array), reinterp(sec(3), Uint16Array),
                reinterp(sec(4), Uint16Array), reinterp(sec(5), Uint16Array)];
  state.g = { n: header.n, offs, blob, cols, tbl: header };
}

async function loadSocial() {
  const bytes = await fetchDecompressed("data/social.bin");
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

function findDocs(blob, offs, term, hits) {
  // Index tokenizer ignores punctuation/whitespace between chars (FTS5
  // single-char CJK), so exact-substring and tolerant-regex results are
  // unioned; both count each doc once.
  const docs = new Set();
  const add = (pos) => {
    const d = bisectDoc(offs, pos);
    if (d >= 0 && !docs.has(d)) {
      docs.add(d);
      let s = hits.get(d); if (!s) hits.set(d, s = new Set());
      s.add(term);
    }
  };
  let pos = blob.indexOf(term);
  while (pos >= 0) { add(pos); pos = blob.indexOf(term, pos + term.length); }
  const re = term.length > 1 ? tolerantRegex(term) : null;
  if (re) {
    let m;
    while ((m = re.exec(blob))) {
      add(m.index);
      if (re.lastIndex === m.index) re.lastIndex++;
    }
  }
  return docs.size;
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
  for (const t of terms) {
    const df = findDocs(corpus.blob, corpus.offs, t, hits);
    weights.set(t, { idf: Math.log2(N / (df + 1)), df });
  }
  const results = [];
  for (const [doc, set] of hits) {
    const uniq = [...set];
    const aliasHits = uniq.filter((t) => t !== base);
    const strong = uniq.includes(base) || aliasHits.length >= 2 ||
      aliasHits.some((t) => weights.get(t).df <= 5);
    results.push({ doc, via: uniq, score: uniq.reduce((a, t) => a + weights.get(t).idf, 0), strong });
  }
  results.sort((a, b) => b.score - a.score || a.doc - b.doc);
  return { results, weights };
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

function renderGame(results, terms) {
  const box = document.getElementById("strong");
  const weakBox = document.getElementById("weak");
  box.replaceChildren(); weakBox.replaceChildren();
  const g = state.g;
  const seenBodies = new Set();
  const dedup = (rs) => rs.filter((r) => {
    const text = g.blob.slice(g.offs[r.doc], g.offs[r.doc + 1] - 1);
    if (seenBodies.has(text)) return false;
    seenBodies.add(text); return true;
  });
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

function gameCard(r, terms, g) {
  const text = g.blob.slice(g.offs[r.doc], g.offs[r.doc + 1] - 1);
  const card = el("div", "card");
  const meta = el("div", "meta");
  meta.append(el("span", "tag", TYPE_LABEL[g.tbl.ty[g.cols[0][r.doc]]] || g.tbl.ty[g.cols[0][r.doc]]));
  meta.append(el("span", "src", g.tbl.src[g.cols[1][r.doc]]));
  const jump = (g.tbl.src_url || [])[g.cols[1][r.doc]];
  if (jump) { const a = el("a", "link", "跳转原文"); a.href = jump; a.target = "_blank"; a.rel = "noopener"; meta.append(a); }
  const spk = g.tbl.spk[g.cols[2][r.doc]];
  if (spk) meta.append(el("span", "spk", "说话人：" + spk));
  const cast = g.tbl.cast[g.cols[3][r.doc]];
  if (cast) { const d = el("span", "cast", "在场：" + cast); d.title = cast; meta.append(d); }
  meta.append(el("span", "score", "得分 " + r.score.toFixed(1)));
  card.append(meta);
  const body = el("div", "body");
  highlightInto(body, text, terms, text.length > 400 ? 200 : 0);
  card.append(body);
  const via = el("div", "via", "命中词：" + r.via.join("、"));
  card.append(via);
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
  if (!q) return;
  const useAlias = document.getElementById("usealias").checked;
  let terms = [q];
  const entry = state.meta.aliases.find((a) => a.term === q);
  if (entry && useAlias) terms = [q, ...entry.aliases];
  const t0 = performance.now();
  const { results, weights } = searchCorpus(state.g, terms, q);
  renderGame(results, terms);
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

async function main() {
  const status = document.getElementById("status");
  try {
    const metaResp = await fetch("data/meta.json");
    state.meta = await metaResp.json();
    await loadSocial();
    status.textContent = "社媒已就绪，正在加载游戏语料（约 16 MB，仅首次）…";
    await loadGame();
    status.textContent = `就绪：游戏文本 ${state.meta.counts.docs} 篇 · 社媒 ${state.meta.counts.posts} 条`;
    setTimeout(() => status.remove(), 4000);
    setFooter();
  } catch (e) {
    status.textContent = "加载失败：" + e;
    return;
  }
  document.getElementById("searchform").addEventListener("submit", (ev) => {
    ev.preventDefault();
    runSearch(document.getElementById("q").value);
  });
}
main();
