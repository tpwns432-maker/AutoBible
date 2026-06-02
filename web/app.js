// BibleClip web frontend.
// - Preview interactions (theme, segments) always run.
// - LIVE mode: when running inside pywebview (window.pywebview.api present),
//   pull real data from the Library bridge and render book/chapter/원어/사전.
//   In a plain browser the bridge is absent, so the static sample in
//   index.html stays as a design preview (graceful fallback).

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;

  // ---- Preview interactions (work with or without the bridge) ----

  const themeBtn = $("theme-toggle");
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const dark = root.dataset.theme !== "dark";
      root.dataset.theme = dark ? "dark" : "light";
      if (window.pywebview && window.pywebview.api) window.pywebview.api.set_dark_mode(dark);
    });
  }

  document.querySelectorAll(".seg").forEach((seg) => {
    seg.addEventListener("click", (e) => {
      const opt = e.target.closest(".opt");
      if (!opt || !seg.contains(opt)) return;
      seg.querySelectorAll(".opt").forEach((o) => o.classList.remove("on"));
      opt.classList.add("on");
    });
  });

  // ---- Helpers ----

  const esc = (s) =>
    String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  // Tears down the listeners (scroll/click) registered by the open menu, so they
  // don't leak across opens. (A stale scroll listener from a previous menu would
  // otherwise close the next one — its closed-over menu no longer contains the
  // new menu, so it'd treat an inside-scroll as a background scroll.)
  let menuCleanup = null;
  function closeMenus() {
    document.querySelectorAll(".menu").forEach((m) => m.remove());
    if (menuCleanup) { menuCleanup(); menuCleanup = null; }
  }

  // Anchored popup menu. items: [{label, value, on}], onPick(value).
  function openMenu(anchor, items, onPick, opts = {}) {
    closeMenus();
    const menu = document.createElement("div");
    menu.className = "menu" + (opts.grid ? " chapters" : "");
    items.forEach((it) => {
      const el = document.createElement("div");
      el.className = "menu-item" + (it.on ? " on" : "");
      el.textContent = it.label;
      el.addEventListener("click", () => {
        if (opts.multi) {
          // Menu stays open for more selections; reflect the actual result
          // (onPick returns the new on/off state, or undefined for no change).
          const res = onPick(it.value);
          if (res === true) el.classList.add("on");
          else if (res === false) el.classList.remove("on");
        } else {
          closeMenus();
          onPick(it.value);
        }
      });
      menu.appendChild(el);
    });
    document.body.appendChild(menu);
    const r = anchor.getBoundingClientRect();
    const top = Math.min(r.bottom + 5, window.innerHeight - menu.offsetHeight - 8);
    const left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8);
    menu.style.top = Math.max(8, top) + "px";
    menu.style.left = Math.max(8, left) + "px";
    // Close on background scroll (the anchored menu would detach), but NOT when
    // scrolling inside the menu itself (long book/chapter lists are scrollable).
    const onScroll = (e) => { if (!menu.contains(e.target)) closeMenus(); };
    const onDocClick = (e) => {
      if (!menu.contains(e.target) && e.target !== anchor) closeMenus();
    };
    // Registered (and torn down by closeMenus) as a pair so neither leaks.
    menuCleanup = () => {
      document.removeEventListener("click", onDocClick);
      window.removeEventListener("scroll", onScroll, true);
    };
    setTimeout(() => {
      document.addEventListener("click", onDocClick);
      window.addEventListener("scroll", onScroll, true);
    }, 0);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });

  // ---- Activity log drawer + toast (UI only; work without the bridge) ----

  const drawer = $("log-drawer");
  function openDrawer() {
    if (!drawer) return;
    drawer.hidden = false;
    $("log-toggle").classList.add("on");
    const dot = $("log-dot");
    if (dot) dot.hidden = true;
  }
  function closeDrawer() {
    if (!drawer) return;
    drawer.hidden = true;
    $("log-toggle").classList.remove("on");
  }
  if ($("log-toggle")) {
    $("log-toggle").addEventListener("click", () =>
      drawer.hidden ? openDrawer() : closeDrawer()
    );
  }
  if ($("log-close")) $("log-close").addEventListener("click", closeDrawer);

  function flagUnread() {
    if (drawer && drawer.hidden) {
      const dot = $("log-dot");
      if (dot) dot.hidden = false;
    }
  }

  function toast(msg) {
    const wrap = $("toast-wrap");
    if (!wrap) return;
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = msg;
    wrap.appendChild(el);
    setTimeout(() => {
      el.classList.add("fade");
      setTimeout(() => el.remove(), 320);
    }, 2400);
  }

  // ---- Live mode ----

  function hasBridge() {
    return window.pywebview && window.pywebview.api;
  }

  const api = () => window.pywebview.api;
  // viewer = versions shown in parallel (first = primary, drives nav + 원어).
  // state.version is kept as an alias for the primary so the existing
  // navigation/interlinear code is unchanged.
  const state = {
    version: null, book: null, chapter: null,
    versions: [], viewer: [], books: [], chapters: [], monitoring: false,
    fontSize: 11,
    searchVersion: null,      // version used for keyword search (default = primary)
    searchClickNav: false,    // search hit click also jumps the viewer
  };

  function applyFontScale() {
    root.style.setProperty("--reading-scale", (state.fontSize / 11).toFixed(3));
  }

  async function boot() {
    const init = await api().get_initial();
    state.versions = init.versions;
    state.viewer = (init.viewer && init.viewer.length) ? init.viewer : [init.primary].filter(Boolean);
    state.version = state.viewer[0] || init.primary;
    state.books = init.books;
    state.book = init.last.book;
    state.chapter = init.last.chapter;
    // Restore persisted UI prefs (shared with the desktop app).
    root.dataset.theme = init.dark_mode ? "dark" : "light";
    state.fontSize = init.font_size || 11;
    applyFontScale();
    lexLang = init.lex_lang === "en" ? "en" : "ko";
    syncLangSeg();
    state.searchClickNav = !!init.search_click_navigates;
    state.searchVersion = state.version;   // default search version = primary
    const verLabel = $("app-ver");
    if (verLabel && init.version) verLabel.textContent = "v" + init.version;
    renderVerChips();
    state.chapters = await api().get_chapters(state.version, state.book);
    if (!state.chapters.includes(state.chapter)) {
      state.chapter = state.chapters[0] || 1;
    }
    await loadChapter();
    wireControls();
    wireMonitor();
    wireTabs();
    wireUpdate();
    wireAppSettings();
    if (init.auto_update_check) checkUpdate(true); // silent startup check
  }

  function bookName(num) {
    const b = state.books.find((x) => x.num === num);
    return b ? b.long : "?";
  }

  function displayName(name) {
    const v = state.versions.find((x) => x.name === name);
    return v ? v.display : name;
  }

  // ---- Version chips (multi-version parallel viewing) ----

  // Live drag-reorder state. dragGeo snapshots each chip's width/left at
  // dragstart so the others can slide open a gap that tracks the cursor.
  const DRAG_GAP = 6; // must match .ver-chips { gap }
  let chipDrag = null, dragGeo = null, dragInsert = 0, suppressChipClick = false;

  // FLIP for the chip row: capture each chip's x before a re-render so they can
  // slide from old → new position (drag-reorder / add / remove).
  function chipLefts() {
    const m = new Map();
    const box = $("ver-chips");
    if (box) box.querySelectorAll(".pill[data-ver]").forEach((el) => {
      m.set(el.dataset.ver, el.getBoundingClientRect().left);
    });
    return m;
  }
  function flipChips(prev) {
    const box = $("ver-chips");
    if (!box) return;
    const chips = box.querySelectorAll(".pill[data-ver]");
    chips.forEach((el) => {
      const before = prev.get(el.dataset.ver);
      if (before == null) return;
      const dx = before - el.getBoundingClientRect().left;
      if (!dx) return;
      el.style.transition = "none";
      el.style.transform = `translateX(${dx}px)`;
    });
    requestAnimationFrame(() => {
      chips.forEach((el) => {
        if (!el.style.transform) return;
        el.style.transition = "transform .22s cubic-bezier(.2,.8,.25,1)";
        el.style.transform = "";
      });
    });
  }

  function renderVerChips() {
    const box = $("ver-chips");
    if (!box) return;
    const prev = chipLefts();
    const draggable = state.viewer.length > 1;
    box.innerHTML = state.viewer
      .map((name, i) => {
        const cls = "pill sel" + (i === 0 ? " primary" : "");
        // The last remaining version can't be removed (×만 빠짐).
        const x = state.viewer.length > 1 ? `<span class="x" title="제거">✕</span>` : "";
        return `<span class="${cls}" data-ver="${esc(name)}" ${draggable ? 'draggable="true"' : ""} title="${esc(displayName(name))}">${esc(name)}${x}</span>`;
      })
      .join("");
    box.querySelectorAll(".pill[data-ver]").forEach((chip) => {
      const name = chip.dataset.ver;
      // Click the ✕ (or chip) removes; drag-reorder is handled on the box.
      chip.addEventListener("click", () => {
        if (suppressChipClick) { suppressChipClick = false; return; }
        if (state.viewer.length > 1) setViewer(state.viewer.filter((n) => n !== name));
      });
    });
    flipChips(prev);
  }

  // Live drag-reorder (delegated on the chip row, wired once). While dragging,
  // the other chips slide to open a gap at the cursor's insertion point so the
  // drop target is always visible; on drop the new order is committed.
  function wireChipDnD() {
    const box = $("ver-chips");
    if (!box) return;

    box.addEventListener("dragstart", (e) => {
      const chip = e.target.closest(".pill[data-ver]");
      if (!chip || state.viewer.length < 2) return;
      chipDrag = chip.dataset.ver;
      dragGeo = [...box.querySelectorAll(".pill[data-ver]")].map((el) => {
        const r = el.getBoundingClientRect();
        return { name: el.dataset.ver, el, w: r.width, left: r.left };
      });
      dragInsert = dragGeo.findIndex((g) => g.name === chipDrag);
      e.dataTransfer.effectAllowed = "move";
      chip.classList.add("dragging");
    });

    box.addEventListener("dragover", (e) => {
      if (!chipDrag) return;
      e.preventDefault();          // allow drop
      layoutDragGap(e.clientX);
    });

    box.addEventListener("drop", (e) => {
      if (!chipDrag) return;
      e.preventDefault();
      const others = dragGeo.map((g) => g.name).filter((n) => n !== chipDrag);
      const order = others.slice();
      order.splice(dragInsert, 0, chipDrag);
      suppressChipClick = true;    // the drop is followed by a click on the chip
      const changed = order.join(" ") !== state.viewer.join(" ");
      chipDrag = null;
      if (changed) { reorderViewer(order); dragGeo = null; } // rebuild + flipChips settles the gap
      else clearDragGap();
    });

    box.addEventListener("dragend", () => {
      // Fires after drop (handled) or on cancel (animate everything back).
      if (chipDrag) { chipDrag = null; clearDragGap(); }
    });
  }

  function layoutDragGap(clientX) {
    const others = dragGeo.filter((g) => g.name !== chipDrag);
    let t = others.length;
    for (let i = 0; i < others.length; i++) {
      if (clientX < others[i].left + others[i].w / 2) { t = i; break; }
    }
    dragInsert = t;
    const finalNames = others.map((g) => g.name);
    finalNames.splice(t, 0, chipDrag);
    const target = {};
    let x = dragGeo[0].left;
    finalNames.forEach((nm) => {
      const g = dragGeo.find((z) => z.name === nm);
      target[nm] = x;
      x += g.w + DRAG_GAP;
    });
    dragGeo.forEach((g) => {
      const dx = target[g.name] - g.left;
      g.el.style.transition = "transform .16s ease";
      g.el.style.transform = dx ? `translateX(${dx}px)` : "";
    });
  }

  function clearDragGap() {
    if (!dragGeo) return;
    dragGeo.forEach((g) => {
      g.el.style.transition = "transform .16s ease";
      g.el.style.transform = "";
      g.el.classList.remove("dragging");
    });
    dragGeo = null;
  }

  // Shared tail: re-render chips, refresh primary-dependent lists, reload.
  async function applyViewer(cleaned) {
    const prevPrimary = state.version;
    state.viewer = cleaned && cleaned.length ? cleaned : state.viewer;
    state.version = state.viewer[0];
    renderVerChips();
    if (state.version !== prevPrimary) {
      state.books = await api().get_books(state.version);
      if (!state.books.some((b) => b.num === state.book)) {
        state.book = state.books[0] ? state.books[0].num : state.book;
      }
    }
    state.chapters = await api().get_chapters(state.version, state.book);
    if (!state.chapters.includes(state.chapter)) state.chapter = state.chapters[0] || 1;
    await loadChapter();
  }

  async function setViewer(names) {
    await applyViewer(await api().set_viewer_versions(names));
  }

  async function reorderViewer(order) {
    await applyViewer(await api().set_viewer_order(order));
  }

  async function loadChapter(highlight) {
    $("book-pill").textContent = bookName(state.book);
    $("chapter-pill").textContent = state.chapter + "장";
    $("scripture-head").textContent =
      `성경 본문 · ${bookName(state.book)} ${state.chapter}`;
    $("scripture").innerHTML = `<div class="panel-loading">불러오는 중…</div>`;
    $("interlin").innerHTML = `<div class="panel-loading">불러오는 중…</div>`;
    resetLexicon();

    // Fetch every viewer version's chapter in parallel + the (version-
    // independent) interlinear in one batch.
    const want = state.viewer.slice();
    const [chaps, inter] = await Promise.all([
      Promise.all(want.map((v) => api().get_chapter(v, state.book, state.chapter))),
      api().get_interlinear(state.book, state.chapter),
    ]);
    const cols = want.map((name, i) => ({ name, verses: (chaps[i] && chaps[i].verses) || [] }));
    renderScripture(cols, highlight);
    renderInterlinear(inter);
    api().note_position(state.book, state.chapter); // remembered, saved on close
  }

  // cols: [{name, verses:[{n,text}]}], in display order. The first column's
  // verse set leads; verses missing from a column are simply skipped there.
  function renderScripture(cols, highlight) {
    const hasAny = cols.some((c) => c.verses && c.verses.length);
    if (!hasAny) {
      $("scripture").innerHTML = `<div class="panel-loading">본문 없음</div>`;
      return;
    }
    // Union of verse numbers across all columns, sorted.
    const nums = new Set();
    const maps = cols.map((c) => {
      const m = new Map();
      (c.verses || []).forEach((v) => { m.set(v.n, v.text); nums.add(v.n); });
      return m;
    });
    const sorted = [...nums].sort((a, b) => a - b);
    const hl = new Set(highlight || []);
    const multi = cols.length > 1;

    $("scripture").innerHTML = sorted
      .map((n) => {
        const lines = cols
          .map((c, i) => {
            if (!maps[i].has(n)) return "";
            const badge = multi ? `<span class="vver">${esc(c.name)}</span>` : "";
            return `<span class="vline">${badge}${esc(maps[i].get(n))}</span>`;
          })
          .filter(Boolean)
          .join("");
        const cls = "v" + (multi ? " multi" : "") + (hl.has(n) ? " hl" : "");
        return `<div class="${cls}" data-v="${n}"><span class="vnum">${n}</span>${lines}</div>`;
      })
      .join("");

    if (hl.size) {
      const first = $("scripture").querySelector(".v.hl");
      if (first) first.scrollIntoView({ block: "center" });
    }
  }

  function renderInterlinear(data) {
    if (!data || !data.length) {
      $("interlin").innerHTML = `<div class="panel-loading">원어 데이터 없음</div>`;
      return;
    }
    $("interlin").innerHTML = data
      .map((row) => {
        const words = row.words
          .map((w) =>
            w.code
              ? `${esc(w.w)}<span class="strong" data-code="${esc(w.code)}" data-v="${row.n}">${esc(w.code)}</span>`
              : esc(w.w)
          )
          .join(" ");
        return `<div class="v" data-v="${row.n}"><span class="vnum">${row.n}</span>${words}</div>`;
      })
      .join("");
  }

  // One-way scroll sync: scripture → interlinear (align the same verse at top).
  function syncInterlinToScripture() {
    const host = $("scripture"), il = $("interlin");
    if (!host || !il) return;
    const top = host.getBoundingClientRect().top;
    let v = null;
    for (const el of host.querySelectorAll(".v[data-v]")) {
      if (el.getBoundingClientRect().bottom > top + 1) { v = el.dataset.v; break; }
    }
    if (v == null) return;
    const row = il.querySelector(`.v[data-v="${v}"]`);
    if (row) il.scrollTop += row.getBoundingClientRect().top - il.getBoundingClientRect().top;
  }

  function resetLexicon() {
    $("lexicon").innerHTML =
      `<div class="panel-loading">원어 단어의 스트롱 번호를 클릭하세요</div>`;
  }

  let lexLang = "ko";       // dictionary language (한글/영어 toggle)
  let lexCur = null;        // {code, verse} currently shown — for re-lookup

  function renderMorph(morph) {
    if (!morph || !morph.length) return "";
    const rows = morph
      .map((w) => {
        let s = `<b>${esc(w.lemma)}</b>`;
        if (w.translit) s += ` ${esc(w.translit)}`;
        if (w.pos) s += ` · ${esc(w.pos)}`;
        if (w.gloss && w.gloss !== "_") s += ` · ${esc(w.gloss)}`;
        return s;
      })
      .join("<br>");
    return `<div class="morph"><div class="morph-h">형태소 분석</div>${rows}</div>`;
  }

  function renderLexEntry(code, res) {
    if (!res) {
      $("lexicon").innerHTML =
        `<span class="chip">${esc(code)}</span><div class="lex-body">사전 항목 없음</div>`;
      return;
    }
    const head = res.headword
      ? `<div class="lex-head"><span class="heb">${esc(res.headword)}</span>` +
        `<span class="rom">${esc(res.reading)}</span></div>`
      : "";
    $("lexicon").innerHTML =
      `<span class="chip">${esc(res.code)}</span>${head}${renderMorph(res.morph)}` +
      `<div class="lex-body">${res.html || "사전 항목 없음"}</div>`;
  }

  // code from an interlinear chip carries a verse (data-v); lexicon cross-refs
  // (.lex-num) don't — verse is then undefined and morphology is skipped.
  async function showStrong(code, verse) {
    lexCur = { code, verse: verse || null };
    $("lexicon").innerHTML = `<div class="panel-loading">[${esc(code)}] 불러오는 중…</div>`;
    const res = await api().lookup_strong(code, lexLang, state.book, state.chapter, lexCur.verse);
    renderLexEntry(code, res);
  }

  // ---- Hover tooltip over original-language words ----

  let tipTimer = null, tipEl = null, tipKey = null;

  function hideTip() {
    if (tipTimer) { clearTimeout(tipTimer); tipTimer = null; }
    if (tipEl) { tipEl.remove(); tipEl = null; }
    tipKey = null;
  }

  function scheduleTip(code, verse, x, y) {
    const key = code + ":" + verse;
    if (key === tipKey) return;
    hideTip();
    tipKey = key;
    tipTimer = setTimeout(async () => {
      const res = await api().hover_summary(code, state.book, state.chapter, verse || null);
      if (tipKey !== key) return; // pointer moved away while loading
      const head = res.headword
        ? `<div class="tip-head"><span class="tip-heb">${esc(res.headword)}</span>` +
          (res.reading ? `<span class="tip-rom">${esc(res.reading)}</span>` : "") + `</div>`
        : "";
      const lines = (res.lines || []).map(esc).join("<br>");
      tipEl = document.createElement("div");
      tipEl.className = "lex-tip";
      tipEl.innerHTML = `${head}<span class="tip-code">[${esc(code)}]</span>${lines ? "<br>" + lines : ""}`;
      document.body.appendChild(tipEl);
      const tx = Math.min(x + 14, window.innerWidth - tipEl.offsetWidth - 10);
      const ty = Math.min(y + 16, window.innerHeight - tipEl.offsetHeight - 10);
      tipEl.style.left = Math.max(8, tx) + "px";
      tipEl.style.top = Math.max(8, ty) + "px";
    }, 400);
  }

  // ---- Update check (GitHub releases) ----

  let updateInfo = null;

  async function checkUpdate(silent) {
    if (!silent) toast("업데이트 확인 중…");
    let r = null;
    try { r = await api().check_update(); } catch (e) { r = null; }
    if (!r || !r.ok) { if (!silent) toast("업데이트 확인 실패"); return; }
    // Manual check always surfaces an available update; the silent startup
    // check respects a previously skipped version.
    if (r.has_update && !(silent && r.skipped)) {
      updateInfo = r;
      $("ub-text").textContent = `새 버전 v${r.latest} 사용 가능 — 현재 v${r.current}`;
      $("update-banner").hidden = false;
    } else if (!silent) {
      toast(`최신 버전입니다 (v${r.current})`);
    }
  }

  function wireUpdate() {
    if ($("update-btn")) $("update-btn").addEventListener("click", () => checkUpdate(false));
    if ($("ub-open")) $("ub-open").addEventListener("click", () => api().open_releases_page());
    if ($("ub-skip")) $("ub-skip").addEventListener("click", () => {
      if (updateInfo) api().skip_update(updateInfo.latest);
      $("update-banner").hidden = true;
    });
    if ($("ub-close")) $("ub-close").addEventListener("click", () => { $("update-banner").hidden = true; });
    if ($("ub-install")) $("ub-install").addEventListener("click", async () => {
      const r = await api().install_update();
      if (!r || !r.ok) { toast(r && r.error ? r.error : "자동 설치를 시작할 수 없습니다"); return; }
      $("ub-text").textContent = "업데이트 다운로드 준비 중…";
      $("ub-install").disabled = true;
    });
  }

  // Update progress/result pushed from Python during install_update().
  function onUpdateProgress(pct, kb, total) {
    const t = $("ub-text");
    if (t) t.textContent = total ? `다운로드 중… ${pct}% (${kb.toLocaleString()} / ${total.toLocaleString()} KB)`
                                 : `다운로드 중… ${kb.toLocaleString()} KB`;
  }
  function onUpdateReady() {
    const t = $("ub-text");
    if (t) t.textContent = "설치 적용 중… 앱이 곧 재시작됩니다.";
  }
  function onUpdateError(msg) {
    toast("업데이트 실패: " + msg);
    const b = $("ub-install");
    if (b) b.disabled = false;
  }

  // ---- App settings modal (⚙ gear) ----

  // Reflect the dictionary default-language onto the viewer's 한글/영어 segment.
  function syncLangSeg() {
    const seg = document.querySelector('.seg[data-seg="lang"]');
    if (!seg) return;
    const opts = seg.querySelectorAll(".opt");
    if (opts[0]) opts[0].classList.toggle("on", lexLang === "ko");
    if (opts[1]) opts[1].classList.toggle("on", lexLang === "en");
  }

  // Highlight the .opt whose data-val matches `current` and wire click→onPick.
  // `eq` customizes matching (e.g. numeric for the poll interval).
  function setSeg(seg, current, onPick, eq) {
    if (!seg) return;
    const same = eq || ((a, b) => a === b);
    seg.querySelectorAll(".opt").forEach((opt) => {
      opt.classList.toggle("on", same(opt.dataset.val, current));
      opt.onclick = () => {
        seg.querySelectorAll(".opt").forEach((o) => o.classList.remove("on"));
        opt.classList.add("on");
        onPick(opt.dataset.val);
      };
    });
  }

  function setSwitch(row, on, onToggle) {
    if (!row) return;
    const sw = row.querySelector(".switch");
    sw.classList.toggle("on", !!on);
    row.onclick = () => {
      const next = !sw.classList.contains("on");
      sw.classList.toggle("on", next);
      onToggle(next);
    };
  }

  function closeAppSettings() {
    const m = $("settings-modal");
    if (m) m.hidden = true;
  }

  async function openAppSettings() {
    const m = $("settings-modal");
    if (!m) return;
    const s = await api().get_app_settings();
    const ver = $("set-version");
    if (ver) ver.textContent = "v" + s.version;

    setSeg($("opt-poll"), s.poll_interval,
      (val) => api().set_app_setting("poll_interval", parseFloat(val)),
      (a, b) => parseFloat(a) === parseFloat(b));

    setSeg($("opt-lex-lang"), s.lex_lang, (val) => {
      lexLang = val;
      syncLangSeg();
      if (lexCur) showStrong(lexCur.code, lexCur.verse);
      api().set_app_setting("lex_lang", val);
    });

    setSwitch($("opt-search-nav"), s.search_click_navigates, (on) => {
      state.searchClickNav = on;
      api().set_app_setting("search_click_navigates", on);
    });
    setSwitch($("opt-auto-update"), s.auto_update_check,
      (on) => api().set_app_setting("auto_update_check", on));

    wireSettingsActions();
    m.hidden = false;
  }

  // Action buttons are re-wired on each open so the reset confirm re-arms.
  function wireSettingsActions() {
    const df = $("act-data-folder");
    if (df) df.onclick = async () => {
      const r = await api().open_data_folder();
      if (!r || !r.ok) toast("폴더를 열 수 없습니다");
    };
    const gh = $("act-github");
    if (gh) gh.onclick = () => api().open_github();
    const rs = $("act-reset");
    if (rs) {
      rs.textContent = "설정 초기화";
      let armed = false;
      rs.onclick = async () => {
        if (!armed) { armed = true; rs.textContent = "한 번 더 누르면 초기화"; return; }
        await api().reset_settings();
        location.reload();   // re-read the fresh defaults
      };
    }
  }

  function wireAppSettings() {
    const gear = $("nav-app-settings");
    if (gear) gear.addEventListener("click", openAppSettings);
    const close = $("settings-close");
    if (close) close.addEventListener("click", closeAppSettings);
    const overlay = $("settings-modal");
    if (overlay) overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeAppSettings();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAppSettings();
    });
  }

  // ---- Clipboard monitoring ----

  function setStatus(active) {
    const badge = $("status-badge");
    const btn = $("monitor-btn");
    if (badge) {
      badge.textContent = active ? "모니터링 중" : "대기 중";
      badge.classList.toggle("on", active);
    }
    if (btn) btn.textContent = active ? "모니터링 중지" : "모니터링 시작";
  }

  // Navigate the viewer to a caught reference and highlight its verses.
  async function goToRef(book, chapter, verses) {
    state.book = book;
    state.chapters = await api().get_chapters(state.version, book);
    // Fall back to the first available chapter if this version lacks it.
    state.chapter = state.chapters.includes(chapter) ? chapter : state.chapters[0] || chapter;
    await loadChapter(verses && verses.length ? verses : null);
  }

  const refLog = [];  // caught references, newest last (index === log row order)

  function vlist(verses) {
    if (!verses || !verses.length) return "전체";
    return verses.join(", ");
  }

  function renderLog() {
    const list = $("log-list");
    if (!list) return;
    if (!refLog.length) {
      list.innerHTML = `<div class="log-empty">모니터링 중 인식한 구절이 여기에 쌓입니다.</div>`;
      return;
    }
    // Newest first.
    list.innerHTML = refLog
      .map((e, i) => {
        if (e.kind === "keyword") {
          return `<div class="log-row keyword"><div class="log-ref"># ${esc(e.keyword)}</div><div class="log-meta">키워드 검색</div></div>`;
        }
        return `<div class="log-row" data-log="${i}"><div class="log-ref">${esc(e.short_name)} ${e.chapter}:${esc(vlist(e.verses))}</div><div class="log-meta"><span class="log-count">${e.n_parts}개 역본</span></div></div>`;
      })
      .reverse()
      .join("");
    list.querySelectorAll("[data-log]").forEach((row) => {
      row.addEventListener("click", async () => {
        const e = refLog[Number(row.dataset.log)];
        if (!e) return;
        goToRef(e.book_num, e.chapter, e.verses);
        const r = await api().copy_reference(e.book_num, e.chapter, e.verses || []);
        if (r && r.ok) toast(`${e.short_name} ${e.chapter}:${vlist(e.verses)} 다시 복사됨`);
      });
    });
  }

  function wireMonitor() {
    const btn = $("monitor-btn");
    if (!btn) return;
    let busy = false;
    btn.addEventListener("click", async () => {
      if (busy) return;
      busy = true;
      try {
        if (!state.monitoring) {
          const res = await api().start_monitoring();
          if (res && res.ok) {
            state.monitoring = true;
            setStatus(true);
          } else {
            toast("클립보드 모니터링을 시작할 수 없습니다");
          }
        } else {
          await api().stop_monitoring();
          state.monitoring = false;
          setStatus(false);
        }
      } finally {
        busy = false;
      }
    });

    // Python → JS event channel (clipboard monitor runs on a worker thread).
    window.bibleclip = {
      onReference(r) {
        refLog.push({ kind: "reference", ...r });
        renderLog();
        flagUnread();
        toast(`${r.short_name} ${r.chapter}:${vlist(r.verses)} 변환·복사됨`);
        showView("viewer"); // a caught reference always returns to the bible view
        goToRef(r.book_num, r.chapter, r.verses);
      },
      onKeyword(keyword) {
        refLog.push({ kind: "keyword", keyword });
        renderLog();
        flagUnread();
        toast(`키워드 "${keyword}" 검색`);
        showView("search");
        runSearch(keyword);
      },
      onUpdateProgress,
      onUpdateReady,
      onUpdateError,
    };
  }

  // ---- Output settings tab (출력 설정) ----

  const FORMAT_ROWS = [
    { key: "book_name", label: "책 이름",
      opts: [["long_ko", "한글 정식"], ["short_ko", "한글 약칭"], ["long_en", "영문 정식"], ["short_en", "영문 약칭"]] },
    { key: "chapter_verse_format", label: "장절 표기",
      opts: [["colon", "1:1"], ["korean", "1장 1절"]] },
    { key: "bracket_style", label: "괄호",
      opts: [["none", "없음"], ["[]", "[ ]"], ["()", "( )"]] },
    { key: "ref_position", label: "표기 위치",
      opts: [["before", "본문 앞"], ["after", "본문 뒤"]] },
    { key: "range_symbol", label: "범위 기호",
      opts: [["-", "-"], ["~", "~"]] },
    { key: "ref_body_separator", label: "구분 기호",
      opts: [[" - ", "하이픈"], [": ", "콜론"], [" ", "띄어쓰기"]] },
    { key: "output_mode", label: "출력 방식",
      opts: [["inline", "한 줄로"], ["newline", "줄마다"]] },
  ];
  const TOGGLE_ROWS = [
    { key: "newline_show_cv", label: "줄마다 장:절 표시" },
    { key: "show_version_header", label: "버전 헤더 출력" },
    { key: "hide_reference", label: "장절 표기 숨기기 (본문만)" },
  ];

  let settingsLoaded = false;
  let setState = null; // {format:{...}, output_order:[...], versions:[...]}

  function dispOf(name) {
    const v = (setState.versions || []).find((x) => x.name === name);
    return v ? v.display : "";
  }

  async function refreshPreview() {
    const pre = $("set-preview");
    if (pre) pre.textContent = await api().get_preview();
  }

  function renderFormat() {
    const host = $("set-format");
    host.innerHTML = "";
    FORMAT_ROWS.forEach((row) => {
      const r = document.createElement("div");
      r.className = "set-row";
      const lab = document.createElement("span");
      lab.className = "set-label";
      lab.textContent = row.label;
      const seg = document.createElement("div");
      seg.className = "seg";
      row.opts.forEach(([val, label]) => {
        const opt = document.createElement("div");
        opt.className = "opt" + (setState.format[row.key] === val ? " on" : "");
        opt.textContent = label;
        opt.addEventListener("click", async () => {
          seg.querySelectorAll(".opt").forEach((o) => o.classList.remove("on"));
          opt.classList.add("on");
          setState.format[row.key] = val;
          await api().set_setting(row.key, val);
          refreshPreview();
        });
        seg.appendChild(opt);
      });
      r.appendChild(lab);
      r.appendChild(seg);
      host.appendChild(r);
    });
    TOGGLE_ROWS.forEach((row) => {
      const t = document.createElement("div");
      t.className = "set-toggle";
      const lab = document.createElement("span");
      lab.className = "set-label";
      lab.textContent = row.label;
      const sw = document.createElement("span");
      sw.className = "switch" + (setState.format[row.key] ? " on" : "");
      sw.innerHTML = `<span class="knob"></span>`;
      t.appendChild(lab);
      t.appendChild(sw);
      t.addEventListener("click", async () => {
        const next = !setState.format[row.key];
        setState.format[row.key] = next;
        sw.classList.toggle("on", next);
        await api().set_setting(row.key, next);
        refreshPreview();
      });
      host.appendChild(t);
    });
  }

  function orderBtn(txt, disabled, fn) {
    const b = document.createElement("button");
    b.className = "order-btn";
    b.textContent = txt;
    b.title = txt;
    if (disabled) b.disabled = true;
    else b.addEventListener("click", fn);
    return b;
  }

  // Snapshot each order-row's vertical position (by version) for FLIP animation.
  function rowTops() {
    const m = new Map();
    $("set-order").querySelectorAll(".order-row").forEach((el) => {
      m.set(el.dataset.ver, el.getBoundingClientRect().top);
    });
    return m;
  }

  // FLIP: rows present before & after slide from their old position to the new
  // one, so a ↑/↓ swap reads as the two rows visibly trading places.
  function flipReorder(prev) {
    const rows = $("set-order").querySelectorAll(".order-row");
    rows.forEach((el) => {
      const before = prev.get(el.dataset.ver);
      if (before == null) return; // newly added row — just appears
      const dy = before - el.getBoundingClientRect().top;
      if (!dy) return;
      el.style.transition = "none";
      el.style.transform = `translateY(${dy}px)`;
    });
    requestAnimationFrame(() => {
      rows.forEach((el) => {
        if (!el.style.transform) return;
        el.style.transition = "transform .22s cubic-bezier(.2,.8,.25,1)";
        el.style.transform = "";
      });
    });
  }

  // Optimistic reorder: update + render + animate immediately, persist in the
  // background, and reconcile only if the backend disagrees (it shouldn't).
  function commitOrder(next) {
    const prev = rowTops();
    setState.output_order = next.slice();
    renderOrder();
    flipReorder(prev);
    refreshPreview();
    api().set_output_order(next).then((cleaned) => {
      if (cleaned && cleaned.join(" ") !== next.join(" ")) {
        setState.output_order = cleaned;
        renderOrder();
      }
    });
  }

  function renderOrder() {
    const host = $("set-order");
    host.innerHTML = "";
    const order = setState.output_order;
    if (!order.length) {
      const e = document.createElement("div");
      e.className = "order-empty";
      e.textContent = "복사 시 사용할 역본이 없습니다. 아래에서 추가하세요.";
      host.appendChild(e);
    } else {
      order.forEach((name, i) => {
        const row = document.createElement("div");
        row.className = "order-row";
        row.dataset.ver = name;
        row.innerHTML =
          `<span class="order-idx">${i + 1}</span>` +
          `<span class="order-name">${esc(name)}<span class="order-disp">${esc(dispOf(name))}</span></span>`;
        row.appendChild(orderBtn("↑", i === 0, () => moveOrder(i, -1)));
        row.appendChild(orderBtn("↓", i === order.length - 1, () => moveOrder(i, 1)));
        row.appendChild(orderBtn("✕", false, () => removeOrder(i)));
        host.appendChild(row);
      });
    }
    const avail = (setState.versions || []).filter((v) => !order.includes(v.name));
    if (avail.length) {
      const add = document.createElement("button");
      add.className = "set-add";
      add.textContent = "＋ 역본 추가";
      add.addEventListener("click", () => {
        openMenu(
          add,
          avail.map((v) => ({ label: v.display, value: v.name, on: false })),
          (name) => commitOrder([...setState.output_order, name])
        );
      });
      host.appendChild(add);
    }
  }

  function moveOrder(i, d) {
    const o = setState.output_order.slice();
    const j = i + d;
    if (j < 0 || j >= o.length) return;
    [o[i], o[j]] = [o[j], o[i]];
    commitOrder(o);
  }
  function removeOrder(i) {
    const o = setState.output_order.slice();
    o.splice(i, 1);
    commitOrder(o);
  }

  async function loadSettings() {
    setState = await api().get_settings();
    renderFormat();
    renderOrder();
    refreshPreview();
  }

  // ---- Keyword search ----

  let searchHits = [];

  async function runSearch(kw) {
    const input = $("search-input");
    if (typeof kw === "string") input.value = kw;
    const q = input.value.trim();
    if (!q) return;
    $("search-meta").textContent = "";
    $("search-results").innerHTML = `<div class="panel-loading">검색 중…</div>`;
    renderSearch(await api().search(q, state.searchVersion || undefined));
  }

  function renderSearch(res) {
    const host = $("search-results");
    searchHits = res.hits || [];
    if (!searchHits.length) {
      $("search-meta").textContent = `"${res.keyword}" 검색 결과 없음`;
      host.innerHTML = `<div class="panel-loading">검색 결과가 없습니다.</div>`;
      return;
    }
    $("search-meta").textContent =
      `"${res.keyword}" 결과 ${searchHits.length}건 · ${res.display} — 구절 클릭 시 ` +
      (state.searchClickNav ? "복사 + 본문 이동" : "복사");
    host.innerHTML = searchHits
      .map(
        (h, i) =>
          `<div class="sr" data-i="${i}"><span class="sr-ref">${esc(h.short)} ${h.chapter}:${h.verse}</span><span class="sr-text">${esc(h.text)}</span></div>`
      )
      .join("");
    host.querySelectorAll(".sr").forEach((el) => {
      el.addEventListener("click", async () => {
        const h = searchHits[Number(el.dataset.i)];
        const r = await api().copy_reference(h.book, h.chapter, [h.verse]);
        if (r && r.ok) {
          toast(`${h.short} ${h.chapter}:${h.verse} 복사됨`);
          el.classList.add("copied");
          setTimeout(() => el.classList.remove("copied"), 700);
        }
        if (state.searchClickNav) {
          showView("viewer");
          goToRef(h.book, h.chapter, [h.verse]);
        }
      });
    });
  }

  function updateSearchVerLabel() {
    const sv = $("search-ver");
    if (sv) sv.textContent = state.searchVersion || state.version || "—";
  }

  function wireSearch() {
    const go = $("search-go"), input = $("search-input");
    if (go) go.addEventListener("click", () => runSearch());
    if (input) {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") runSearch();
      });
    }
    // Search version picker (defaults to the primary; changing it re-runs).
    const sv = $("search-ver");
    if (sv) {
      sv.addEventListener("click", () => {
        openMenu(
          sv,
          state.versions.map((v) => ({
            label: v.display, value: v.name, on: v.name === state.searchVersion,
          })),
          (name) => {
            state.searchVersion = name;
            updateSearchVerLabel();
            if ($("search-input").value.trim()) runSearch();
          }
        );
      });
    }
    updateSearchVerLabel();
  }

  // ---- View switching (viewer / settings / search) ----

  async function showView(name) {
    $("viewer-view").hidden = name !== "viewer";
    $("settings-view").hidden = name !== "settings";
    $("search-view").hidden = name !== "search";
    $("viewer-controls").hidden = name !== "viewer";
    // rail active state (viewer / settings / search are rail icons)
    [["nav-viewer", "viewer"], ["nav-settings", "settings"], ["nav-search", "search"]]
      .forEach(([id, v]) => { const el = $(id); if (el) el.classList.toggle("on", name === v); });

    if (name === "settings") {
      if (!settingsLoaded) { settingsLoaded = true; await loadSettings(); }
      else refreshPreview(); // output_order may have changed elsewhere
    } else if (name === "search") {
      const input = $("search-input");
      if (input) input.focus();
    }
  }

  function wireTabs() {
    if ($("nav-viewer")) $("nav-viewer").addEventListener("click", () => showView("viewer"));
    if ($("nav-settings")) $("nav-settings").addEventListener("click", () => showView("settings"));
    if ($("nav-search")) $("nav-search").addEventListener("click", () => showView("search"));
    wireSearch();
  }

  function wireControls() {
    const main = document.querySelector(".main");
    // Strong's chips (interlinear) + <num> cross-refs (lexicon) → lookup.
    main.addEventListener("click", (e) => {
      const t = e.target.closest("[data-code]");
      if (t) showStrong(t.dataset.code, t.dataset.v);
    });
    // Right-click an original-language word / cross-ref → independent window.
    main.addEventListener("contextmenu", (e) => {
      const t = e.target.closest("[data-code]");
      if (!t) return;
      e.preventDefault();
      hideTip();
      api().open_dict_window(
        t.dataset.code, lexLang, state.book, state.chapter, t.dataset.v || null,
        document.documentElement.dataset.theme || "light"
      );
    });
    // Hover an interlinear word → delayed preview tooltip.
    const il = $("interlin");
    il.addEventListener("mouseover", (e) => {
      const t = e.target.closest(".strong[data-code]");
      if (t) scheduleTip(t.dataset.code, t.dataset.v, e.clientX, e.clientY);
    });
    il.addEventListener("mouseout", (e) => {
      if (e.target.closest(".strong[data-code]")) hideTip();
    });
    il.addEventListener("scroll", hideTip);
    // Dictionary language toggle (한글/영어).
    const langSeg = document.querySelector('.seg[data-seg="lang"]');
    if (langSeg) {
      langSeg.querySelectorAll(".opt").forEach((opt, i) => {
        opt.addEventListener("click", () => {
          lexLang = i === 0 ? "ko" : "en";
          if (lexCur) showStrong(lexCur.code, lexCur.verse);
        });
      });
    }
    wireChipDnD(); // delegated live drag-reorder for the version chips

    // Font size A− / A+ (persisted as viewer_font_size).
    const changeFont = (d) => {
      const n = Math.max(8, Math.min(30, state.fontSize + d));
      if (n === state.fontSize) return;
      state.fontSize = n;
      applyFontScale();
      api().set_font_size(n);
    };
    if ($("font-dec")) $("font-dec").addEventListener("click", () => changeFont(-1));
    if ($("font-inc")) $("font-inc").addEventListener("click", () => changeFont(1));

    $("book-pill").addEventListener("click", () => {
      openMenu(
        $("book-pill"),
        state.books.map((b) => ({ label: b.long, value: b.num, on: b.num === state.book })),
        async (num) => {
          state.book = num;
          state.chapters = await api().get_chapters(state.version, num);
          state.chapter = state.chapters[0] || 1;
          loadChapter();
        }
      );
    });

    $("chapter-pill").addEventListener("click", () => {
      openMenu(
        $("chapter-pill"),
        state.chapters.map((c) => ({ label: String(c), value: c, on: c === state.chapter })),
        (c) => { state.chapter = c; loadChapter(); },
        { grid: true }
      );
    });

    // "＋" → multi-select menu: toggle versions in/out of the viewer set.
    $("ver-add").addEventListener("click", () => {
      openMenu(
        $("ver-add"),
        state.versions.map((v) => ({
          label: v.display, value: v.name, on: state.viewer.includes(v.name),
        })),
        (name) => {
          const on = state.viewer.includes(name);
          const next = on
            ? state.viewer.filter((n) => n !== name)
            : [...state.viewer, name];
          if (!next.length) return true;   // refuse to remove the last → stays on
          setViewer(next);
          return !on;                      // new checked state
        },
        { multi: true }
      );
    });

    $("prev-ch").addEventListener("click", () => chapStep(-1));
    $("next-ch").addEventListener("click", () => chapStep(1));

    // Manual copy from the scripture panel: click a verse (or drag-select a
    // range) → copy in the viewer's versions, like the desktop app.
    const scr = $("scripture");
    scr.addEventListener("mouseup", () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount || !sel.toString().trim()) return;
      const range = sel.getRangeAt(0);
      const verses = [...scr.querySelectorAll(".v[data-v]")]
        .filter((el) => range.intersectsNode(el))
        .map((el) => +el.dataset.v);
      if (verses.length) copyVerses(verses);
    });
    scr.addEventListener("click", (e) => {
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed) return; // a range was handled on mouseup
      const v = e.target.closest(".v[data-v]");
      if (v) copyVerses([+v.dataset.v]);
    });
    // Scroll sync: scripture drives the interlinear panel (rAF-throttled).
    let syncPending = false;
    scr.addEventListener("scroll", () => {
      if (syncPending) return;
      syncPending = true;
      requestAnimationFrame(() => { syncPending = false; syncInterlinToScripture(); });
    });

    // DB rescan (settings tab). Refreshes available versions everywhere.
    if ($("db-refresh")) $("db-refresh").addEventListener("click", refreshDbs);

    // Keyboard: ←/→ steps chapters when the viewer is active and not typing.
    document.addEventListener("keydown", (e) => {
      if (e.target.closest("input, textarea")) return;
      if ($("viewer-view").hidden) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); chapStep(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); chapStep(1); }
    });
  }

  function chapStep(delta) {
    const i = state.chapters.indexOf(state.chapter);
    const j = i + delta;
    if (j >= 0 && j < state.chapters.length) {
      state.chapter = state.chapters[j];
      loadChapter();
    }
  }

  function bookShort() {
    const b = state.books.find((x) => x.num === state.book);
    return b ? b.short : "?";
  }

  async function copyVerses(verses) {
    if (!verses.length) return;
    const r = await api().copy_reference(state.book, state.chapter, verses, state.viewer);
    if (!r || !r.ok) return;
    toast(`${bookShort()} ${state.chapter}:${verses.join(",")} 복사됨`);
    verses.forEach((n) => {
      const el = $("scripture").querySelector(`.v[data-v="${n}"]`);
      if (el) { el.classList.add("copied"); setTimeout(() => el.classList.remove("copied"), 700); }
    });
  }

  async function refreshDbs() {
    const res = await api().refresh_databases();
    state.versions = res.versions;
    if (setState) { setState.versions = res.versions; renderOrder(); }
    toast(res.added && res.added.length ? `${res.added.length}개 역본 추가됨` : "새 역본 없음");
  }

  if (hasBridge()) {
    boot();
  } else {
    window.addEventListener("pywebviewready", boot);
  }
})();
