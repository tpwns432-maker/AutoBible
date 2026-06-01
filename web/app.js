// BibleClip web frontend — Phase 1 preview interactions only.
// Just enough JS to evaluate the design system (theme toggle, segmented
// controls, status badge). NO data is wired here — the Library core bridge
// arrives in Phase 2.

(function () {
  "use strict";

  // Theme toggle (light <-> dark) via the data-theme attribute on <html>.
  const root = document.documentElement;
  const themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    });
  }

  // Segmented controls: clicking an option moves the .on selection.
  document.querySelectorAll(".seg").forEach(function (seg) {
    seg.addEventListener("click", function (e) {
      const opt = e.target.closest(".opt");
      if (!opt || !seg.contains(opt)) return;
      seg.querySelectorAll(".opt").forEach((o) => o.classList.remove("on"));
      opt.classList.add("on");
    });
  });

  // Monitoring button toggles the status badge (visual demo only).
  const primaryBtn = document.querySelector(".btn.primary");
  const badge = document.getElementById("status-badge");
  if (primaryBtn && badge) {
    primaryBtn.addEventListener("click", function () {
      const on = badge.classList.toggle("on");
      badge.textContent = on ? "모니터링 중" : "대기 중";
      primaryBtn.textContent = on ? "모니터링 중지" : "모니터링 시작";
    });
  }
})();
