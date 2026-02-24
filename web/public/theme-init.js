// Prevent theme flash (respect saved preference).
(function () {
  try {
    var theme = localStorage.getItem("theme");
    if (theme === "dark") {
      document.documentElement.classList.add("dark");
    }
  } catch (err) {
    // Ignore localStorage access errors (privacy mode, blocked storage, etc.).
  }
})();
