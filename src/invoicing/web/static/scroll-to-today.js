/* The week view lists every day under the other. Opening it scrolls down to
   today, unless the page already starts somewhere else (for example after a
   form sent you back to the row you just edited).

   This runs before the first paint on purpose: the page transition takes its
   picture of the new page at that moment, and a later scroll would make the
   view switch glide a second time. */

(function () {
  "use strict";

  var NEAR_THE_TOP_PIXELS = 4;
  var ROOM_ABOVE_TODAY_PIXELS = 16;

  var today = document.querySelector(".day-heading.is-today");
  if (!today || window.scrollY >= NEAR_THE_TOP_PIXELS) return;

  var top = today.getBoundingClientRect().top + window.scrollY;
  window.scrollTo(0, top - ROOM_ABOVE_TODAY_PIXELS);
})();
