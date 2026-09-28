// Applied before first paint so a dark-mode reload never flashes white.
try {
  var t = localStorage.getItem("naukri-theme");
  if (t && t !== "system") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
