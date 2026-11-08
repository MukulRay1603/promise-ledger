// Runs before first paint (loaded without defer from <head>). A file, not inline, so the CSP needs no 'unsafe-inline'.
// Apply saved display settings before first paint.
document.documentElement.classList.add("js");
try {
  const theme = localStorage.getItem("pl-theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  if (localStorage.getItem("pl-text") === "large") document.documentElement.classList.add("text-large");
} catch (err) { /* Storage can be blocked. Defaults still apply. */ }
// Shared links open the read-only view without drawing the home page first.
if (/^\/r\//.test(location.pathname) || /^#\/r\//.test(location.hash)) document.documentElement.classList.add("route-shared");
else if (/^#\/./.test(location.hash) || /^#[a-z]/.test(location.hash)) document.documentElement.classList.add("route-app");
// The hero receipt assembles itself; hide its rows from the first paint so they do not flash.
if (!document.documentElement.classList.contains("route-app") && !document.documentElement.classList.contains("route-shared")
  && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.documentElement.classList.add("hero-anim");
