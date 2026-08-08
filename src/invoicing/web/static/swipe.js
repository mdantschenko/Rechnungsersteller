/* The month, week and day view sit side by side on a sliding track, like a
   carousel: [neighbour][current][neighbour]. Dragging moves the whole track,
   so the next view is simply already there; releasing lets the track glide
   one slot over and the real page takes over without animating again.
   The white pill of the switch and the heading follow the finger. */

(function () {
  "use strict";

  var segments = Array.prototype.slice.call(
    document.querySelectorAll(".segmented a")
  );
  if (!segments.length) return;
  var current = segments.findIndex(function (link) {
    return link.classList.contains("is-current");
  });
  var swap = document.querySelector(".swap");
  var segmented = document.querySelector(".segmented");
  var title = document.querySelector(".page-title");
  if (!swap) return;

  var SWIPE_THRESHOLD_PIXELS = 60;
  var CENTER = "translateX(-33.3333%)";

  var carousel = document.createElement("div");
  carousel.className = "carousel";
  var track = document.createElement("div");
  track.className = "swipe-track";
  carousel.appendChild(track);
  var CENTER_SLOT = 1;
  var slots = [];
  for (var slotIndex = 0; slotIndex < 3; slotIndex += 1) {
    var slot = document.createElement("div");
    slot.className =
      "swipe-slot" + (slotIndex === CENTER_SLOT ? "" : " swipe-slot-side");
    track.appendChild(slot);
    slots.push(slot);
  }
  swap.parentNode.insertBefore(carousel, swap);
  slots[1].appendChild(swap);

  var titles = {};

  function cacheKey(index) {
    return "swap:" + segments[index].getAttribute("href");
  }

  function readCache(index) {
    try {
      return JSON.parse(sessionStorage.getItem(cacheKey(index)));
    } catch (ignored) {
      return null;
    }
  }

  function writeCache(index, entry) {
    try {
      sessionStorage.setItem(cacheKey(index), JSON.stringify(entry));
    } catch (ignored) {}
  }

  function hydrate(index, slot) {
    if (index < 0 || index >= segments.length) return;
    var kept = readCache(index);
    if (kept) {
      slot.innerHTML = kept.html;
      titles[index] = kept.title;
    }
    fetch(segments[index].href, { credentials: "same-origin" })
      .then(function (answer) { return answer.text(); })
      .then(function (html) {
        var neighbourDocument = new DOMParser().parseFromString(html, "text/html");
        var neighbour = neighbourDocument.querySelector(".swap");
        if (!neighbour) return;
        slot.innerHTML = neighbour.innerHTML;
        var heading = neighbourDocument.querySelector(".page-title");
        titles[index] = heading ? heading.textContent : "";
        writeCache(index, { html: neighbour.innerHTML, title: titles[index] });
      })
      .catch(function () {});
  }

  writeCache(current, {
    html: swap.innerHTML,
    title: title ? title.textContent : "",
  });
  hydrate(current - 1, slots[0]);
  hydrate(current + 1, slots[2]);

  function remember(direction) {
    try { sessionStorage.setItem("nav-direction", direction); } catch (ignored) {}
  }

  segments.forEach(function (link, index) {
    link.addEventListener("click", function () {
      remember(index > current ? "forward" : "back");
    });
  });

  var pill = null;
  var titleGhost = null;

  function movePill(progress, target) {
    if (!segmented) return;
    if (!pill) {
      pill = document.createElement("span");
      pill.className = "segment-ghost";
      segmented.appendChild(pill);
    }
    var base = segmented.getBoundingClientRect();
    var from = segments[current].getBoundingClientRect();
    var to = segments[target].getBoundingClientRect();
    segmented.classList.add("dragging");
    pill.style.transform =
      "translateX(" + (from.left + (to.left - from.left) * progress - base.left) + "px)";
    pill.style.width = from.width + (to.width - from.width) * progress + "px";
    pill.style.opacity = "1";
  }

  function settlePill(target) {
    if (!pill) return;
    pill.style.transition = "transform 0.18s ease, width 0.18s ease";
    movePill(1, target === null ? current : target);
    if (target === null) {
      setTimeout(function () {
        segmented.classList.remove("dragging");
        pill.style.opacity = "0";
        pill.style.transition = "";
      }, 200);
    }
  }

  function moveTitle(progress, target) {
    if (!title) return;
    if (!titleGhost) {
      titleGhost = title.cloneNode(false);
      titleGhost.classList.add("title-ghost");
      titleGhost.style.top = title.offsetTop + "px";
      title.parentNode.insertBefore(titleGhost, title.nextSibling);
    }
    titleGhost.textContent = titles[target] || "";
    title.style.opacity = String(1 - progress);
    titleGhost.style.opacity = String(progress);
  }

  function settleTitle(kept) {
    if (!title) return;
    title.style.transition = "opacity 0.18s ease";
    title.style.opacity = kept ? "1" : "0";
    if (titleGhost) {
      titleGhost.style.transition = "opacity 0.18s ease";
      titleGhost.style.opacity = kept ? "0" : "1";
    }
  }

  function dragIntent(deltaX, deltaY) {
    if (Math.abs(deltaX) >= 12 && Math.abs(deltaX) >= 1.5 * Math.abs(deltaY)) {
      return "horizontal";
    }
    if (Math.abs(deltaY) > 16) return "vertical";
    return "undecided";
  }

  var startX = null;
  var startY = null;
  var dragging = false;

  document.addEventListener("touchstart", function (event) {
    if (event.target.closest("a, button, input, select, form, details, .peek")) {
      startX = null;
      return;
    }
    startX = event.touches[0].clientX;
    startY = event.touches[0].clientY;
    dragging = false;
  }, { passive: true });

  document.addEventListener("touchmove", function (event) {
    if (startX === null) return;
    var deltaX = event.touches[0].clientX - startX;
    var deltaY = event.touches[0].clientY - startY;
    if (!dragging) {
      var intent = dragIntent(deltaX, deltaY);
      if (intent === "vertical") {
        startX = null;
        return;
      }
      if (intent === "undecided") return;
      dragging = true;
      track.style.transition = "none";
    }
    var target = deltaX < 0 ? current + 1 : current - 1;
    var reachable = target >= 0 && target < segments.length;
    var shift = reachable ? deltaX : deltaX / 3;
    track.style.transform = "translateX(calc(-33.3333% + " + shift + "px))";
    if (reachable) {
      var progress = Math.min(1, Math.abs(deltaX) / (carousel.clientWidth * 0.8));
      movePill(progress, target);
      moveTitle(progress, target);
    }
  }, { passive: true });

  document.addEventListener("touchend", function (event) {
    if (startX === null) return;
    var deltaX = event.changedTouches[0].clientX - startX;
    startX = null;
    if (!dragging) return;
    dragging = false;
    var target = deltaX < 0 ? current + 1 : current - 1;
    var reachable = target >= 0 && target < segments.length;
    track.style.transition = "transform 0.2s ease-out";
    if (!reachable || Math.abs(deltaX) < SWIPE_THRESHOLD_PIXELS) {
      track.style.transform = CENTER;
      settlePill(null);
      settleTitle(true);
      setTimeout(function () { track.style.transition = ""; }, 240);
      return;
    }
    track.style.transform =
      deltaX < 0 ? "translateX(-66.6666%)" : "translateX(0%)";
    settlePill(target);
    settleTitle(false);
    try { sessionStorage.setItem("nav-skip", "1"); } catch (ignored) {}
    setTimeout(function () {
      window.location = segments[target].href;
    }, 210);
  }, { passive: true });

  document.addEventListener("touchcancel", function () {
    if (dragging) {
      track.style.transition = "transform 0.2s ease-out";
      track.style.transform = CENTER;
      settlePill(null);
      settleTitle(true);
    }
    startX = null;
    dragging = false;
  }, { passive: true });
})();
