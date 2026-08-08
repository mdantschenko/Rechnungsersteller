async function shareOutPdf(anchor) {
  try {
    var loaded = await fetch(anchor.dataset.pdf);
    var file = new File([await loaded.blob()], anchor.dataset.title + ".pdf", {
      type: "application/pdf",
    });
    await navigator.share({ files: [file], title: anchor.dataset.title });
  } catch (ignored) {}
}

function savePdf(anchor) {
  var probe = new File([""], "probe.pdf", { type: "application/pdf" });
  var canShare =
    navigator.maxTouchPoints > 0 &&
    navigator.canShare &&
    navigator.canShare({ files: [probe] });
  if (!canShare) return true;
  shareOutPdf(anchor);
  return false;
}
