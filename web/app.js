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
  };

  async function boot() {
    const init = await api().get_initial();
    state.versions = init.versions;
    state.viewer = (init.viewer && init.viewer.length) ? init.viewer : [init.primary].filter(Boolean);
    state.version = state.viewer[0] || init.primary;
    state.books = init.books;
    state.book = init.last.book;
    state.chapter = init.last.chapter;
    renderVerChips();
    state.chapters = await api().get_chapters(state.version, state.book);
    if (!state.chapters.includes(state.chapter)) {
      state.chapter = state.chapters[0] || 1;
    }
    await loadChapter();
    wireControls();
    wireMonitor();
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

  function renderVerChips() {
    const box = $("ver-chips");
    if (!box) return;
    box.innerHTML = state.viewer
      .map((name, i) => {
        const cls = "pill sel" + (i === 0 ? " primary" : "");
        // The last remaining version can't be removed (×만 빠짐).
        const x = state.viewer.length > 1 ? `<span class="x" title="제거">✕</span>` : "";
        return `<span class="${cls}" data-ver="${esc(name)}" title="${esc(displayName(name))}">${esc(name)}${x}</span>`;
      })
      .join("");
    box.querySelectorAll(".pill[data-ver]").forEach((chip) => {
      chip.addEventListener("click", () => {
        const name = chip.dataset.ver;
        if (state.viewer.length > 1) {
          setViewer(state.viewer.filter((n) => n !== name));
        }
      });
    });
  }

  async function setViewer(names) {
    const cleaned = await api().set_viewer_versions(names);
    const prevPrimary = state.version;
    state.viewer = (cleaned && cleaned.length) ? cleaned : state.viewer;
    state.version = state.viewer[0];
    renderVerChips();
    // Primary may have changed → its book/chapter lists might differ.
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
        return `<div class="${cls}"><span class="vnum">${n}</span>${lines}</div>`;
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
      row.addEventListener("click", () => {
        const e = refLog[Number(row.dataset.log)];
        if (e) goToRef(e.book_num, e.chapter, e.verses);
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
        goToRef(r.book_num, r.chapter, r.verses);
      },
      onKeyword(keyword) {
        refLog.push({ kind: "keyword", keyword });
        renderLog();
        flagUnread();
        toast(`키워드 "${keyword}" — 검색 기능 준비 중`);
      },
    };
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
