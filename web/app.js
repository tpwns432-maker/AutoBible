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
      root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
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

  function closeMenus() {
    document.querySelectorAll(".menu").forEach((m) => m.remove());
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
        closeMenus();
        onPick(it.value);
      });
      menu.appendChild(el);
    });
    document.body.appendChild(menu);
    const r = anchor.getBoundingClientRect();
    const top = Math.min(r.bottom + 5, window.innerHeight - menu.offsetHeight - 8);
    const left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8);
    menu.style.top = Math.max(8, top) + "px";
    menu.style.left = Math.max(8, left) + "px";
    const onScroll = () => closeMenus();
    setTimeout(() => {
      document.addEventListener("click", function h(e) {
        if (!menu.contains(e.target) && e.target !== anchor) {
          closeMenus();
          document.removeEventListener("click", h);
          window.removeEventListener("scroll", onScroll, true);
        }
      });
      window.addEventListener("scroll", onScroll, true);
    }, 0);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });

  // ---- Live mode ----

  function hasBridge() {
    return window.pywebview && window.pywebview.api;
  }

  const api = () => window.pywebview.api;
  const state = { version: null, book: null, chapter: null, versions: [], books: [], chapters: [] };

  async function boot() {
    const init = await api().get_initial();
    state.version = init.primary;
    state.versions = init.versions;
    state.books = init.books;
    state.book = init.last.book;
    state.chapter = init.last.chapter;
    updateVerChip();
    state.chapters = await api().get_chapters(state.version, state.book);
    if (!state.chapters.includes(state.chapter)) {
      state.chapter = state.chapters[0] || 1;
    }
    await loadChapter();
    wireControls();
  }

  function bookName(num) {
    const b = state.books.find((x) => x.num === num);
    return b ? b.long : "?";
  }

  function updateVerChip() {
    const c = $("ver-chip");
    if (c) c.textContent = state.version;
  }

  async function loadChapter() {
    $("book-pill").textContent = bookName(state.book);
    $("chapter-pill").textContent = state.chapter + "장";
    $("scripture-head").textContent =
      `성경 본문 · ${bookName(state.book)} ${state.chapter}`;
    $("scripture").innerHTML = `<div class="panel-loading">불러오는 중…</div>`;
    $("interlin").innerHTML = `<div class="panel-loading">불러오는 중…</div>`;
    resetLexicon();

    const [chap, inter] = await Promise.all([
      api().get_chapter(state.version, state.book, state.chapter),
      api().get_interlinear(state.book, state.chapter),
    ]);
    renderScripture(chap.verses);
    renderInterlinear(inter);
  }

  function renderScripture(verses) {
    if (!verses || !verses.length) {
      $("scripture").innerHTML = `<div class="panel-loading">본문 없음</div>`;
      return;
    }
    $("scripture").innerHTML = verses
      .map((v) => `<div class="v"><span class="vnum">${v.n}</span>${esc(v.text)}</div>`)
      .join("");
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
              ? `${esc(w.w)}<span class="strong" data-code="${esc(w.code)}">${esc(w.code)}</span>`
              : esc(w.w)
          )
          .join(" ");
        return `<div class="v"><span class="vnum">${row.n}</span>${words}</div>`;
      })
      .join("");
  }

  function resetLexicon() {
    $("lexicon").innerHTML =
      `<div class="panel-loading">원어 단어의 스트롱 번호를 클릭하세요</div>`;
  }

  async function showStrong(code) {
    $("lexicon").innerHTML = `<div class="panel-loading">[${esc(code)}] 불러오는 중…</div>`;
    const res = await api().lookup_strong(code);
    if (!res) {
      $("lexicon").innerHTML =
        `<span class="chip">${esc(code)}</span><div class="lex-body">사전 항목 없음</div>`;
      return;
    }
    $("lexicon").innerHTML =
      `<span class="chip">${esc(res.code)}</span><div class="lex-body">${res.html}</div>`;
  }

  function wireControls() {
    // Strong's chips (interlinear) + <num> cross-refs (lexicon) → lookup.
    document.querySelector(".main").addEventListener("click", (e) => {
      const t = e.target.closest("[data-code]");
      if (t) showStrong(t.dataset.code);
    });

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

    $("ver-chip").addEventListener("click", () => {
      openMenu(
        $("ver-chip"),
        state.versions.map((v) => ({ label: v.display, value: v.name, on: v.name === state.version })),
        async (name) => {
          state.version = name;
          updateVerChip();
          state.chapters = await api().get_chapters(state.version, state.book);
          if (!state.chapters.includes(state.chapter)) state.chapter = state.chapters[0] || 1;
          loadChapter();
        }
      );
    });

    const step = (delta) => {
      const i = state.chapters.indexOf(state.chapter);
      const j = i + delta;
      if (j >= 0 && j < state.chapters.length) {
        state.chapter = state.chapters[j];
        loadChapter();
      }
    };
    $("prev-ch").addEventListener("click", () => step(-1));
    $("next-ch").addEventListener("click", () => step(1));
  }

  if (hasBridge()) {
    boot();
  } else {
    window.addEventListener("pywebviewready", boot);
  }
})();
