"use strict";

// Animated waveform in the hero voice note.
(function wave() {
  const el = document.getElementById("hero-wave");
  if (!el) return;
  const heights = [10, 18, 26, 14, 30, 22, 12, 28, 20, 16, 26, 10, 22, 30, 14, 24, 12, 18];
  el.innerHTML = heights.map((h, i) => `<i style="height:${h}px;animation-delay:${(i % 6) * 0.12}s"></i>`).join("");
})();

// Nav: border once scrolled; "Open app" instead of "Sign in" for a signed-in visitor.
const nav = document.getElementById("site-nav");
addEventListener("scroll", () => nav.classList.toggle("scrolled", scrollY > 8), { passive: true });
fetch("/api/me", { credentials: "same-origin" }).then((res) => {
  if (!res.ok) return;
  const cta = document.getElementById("nav-cta");
  cta.textContent = "Open app";
  cta.href = "/app";
}).catch(() => {});

// Fade sections in as they enter the viewport.
const reveals = document.querySelectorAll(".reveal");
if ("IntersectionObserver" in window && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("in");
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  reveals.forEach((el, i) => { el.style.transitionDelay = `${(i % 4) * 70}ms`; io.observe(el); });
} else {
  reveals.forEach((el) => el.classList.add("in"));
}
