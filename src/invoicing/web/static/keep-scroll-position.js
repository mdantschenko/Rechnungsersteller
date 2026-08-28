/* A form on a list page answers with a redirect back to the same page, and the
   browser starts that fresh page at the top. Remembering the offset across the
   redirect keeps the row you just acted on under your thumb. */

(function () {
  "use strict";

  var STORAGE_KEY = "scroll-back";
  var NEAR_THE_TOP_PIXELS = 4;

  function remember() {
    try {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ path: location.pathname, offset: window.scrollY })
      );
    } catch (ignored) {}
  }

  function whereWeWere() {
    try {
      var stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY));
      sessionStorage.removeItem(STORAGE_KEY);
      if (!stored || stored.path !== location.pathname || !stored.offset) {
        return null;
      }
      return stored.offset;
    } catch (ignored) {
      return null;
    }
  }

  document.addEventListener("submit", remember, true);

  var offset = whereWeWere();
  if (offset === null) return;
  window.scrollTo(0, offset);
  window.addEventListener("load", function () {
    if (window.scrollY < NEAR_THE_TOP_PIXELS) window.scrollTo(0, offset);
  });
})();
