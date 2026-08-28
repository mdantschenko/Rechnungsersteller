(function () {
  "use strict";

  var SWIPE_AWAY_PIXELS = 90;
  var DIRECTION_LOCK_PIXELS = 10;

  function submit(action) {
    var form = document.createElement("form");
    form.method = "post";
    form.action = action;
    document.body.appendChild(form);
    form.submit();
  }

  function prepare(row) {
    var face = row.querySelector(".swipe-away-face");
    if (!face) return;
    var startX = 0;
    var startY = 0;
    var shift = 0;
    var dragging = false;
    var decided = false;

    function reset() {
      face.style.transition = "transform 0.2s ease";
      face.style.transform = "";
      dragging = false;
      decided = false;
      shift = 0;
    }

    face.addEventListener(
      "touchstart",
      function (event) {
        if (event.touches.length !== 1) return;
        startX = event.touches[0].clientX;
        startY = event.touches[0].clientY;
        dragging = true;
        decided = false;
        face.style.transition = "";
      },
      { passive: true }
    );

    face.addEventListener(
      "touchmove",
      function (event) {
        if (!dragging) return;
        var moveX = event.touches[0].clientX - startX;
        var moveY = event.touches[0].clientY - startY;
        if (!decided) {
          if (Math.abs(moveX) < DIRECTION_LOCK_PIXELS &&
              Math.abs(moveY) < DIRECTION_LOCK_PIXELS) {
            return;
          }
          if (Math.abs(moveY) > Math.abs(moveX)) {
            dragging = false;
            return;
          }
          decided = true;
        }
        shift = Math.min(0, moveX);
        face.style.transform = "translateX(" + shift + "px)";
      },
      { passive: true }
    );

    face.addEventListener("touchend", function () {
      if (!dragging) return;
      if (shift < -SWIPE_AWAY_PIXELS) {
        face.style.transition = "transform 0.2s ease";
        face.style.transform = "translateX(-100%)";
        submit(row.dataset.action);
        return;
      }
      reset();
    });

    face.addEventListener("touchcancel", reset);
  }

  Array.prototype.forEach.call(
    document.querySelectorAll(".swipe-away[data-action]"),
    prepare
  );
})();
