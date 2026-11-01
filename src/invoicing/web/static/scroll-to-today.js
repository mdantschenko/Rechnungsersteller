/* The week view lists every day under the other. Opening it scrolls down to
   today, unless the page already starts somewhere else (for example after a
   form sent you back to the row you just edited). */

(function () {
  "use strict";

  var NEAR_THE_TOP_PIXELS = 4;
  var ROOM_ABOVE_TODAY_PIXELS = 16;

  var today = document.querySelector(".day-heading.is-today");
  if (!today) return;

  function scrollToToday() {
    if (window.scrollY >= NEAR_THE_TOP_PIXELS) return;
    var top = today.getBoundingClientRect().top + window.scrollY;
    window.scrollTo(0, top - ROOM_ABOVE_TODAY_PIXELS);
  }

  window.addEventListener("load", scrollToToday);
})();
