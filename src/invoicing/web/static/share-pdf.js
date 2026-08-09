/* Handing a stored PDF to the system share sheet — for saving it into the
   Files app or passing it on through WhatsApp. One fetch-to-file helper
   serves both paths. */

async function pdfAsFile(url, title) {
  var loaded = await fetch(url);
  return new File([await loaded.blob()], title + ".pdf", {
    type: "application/pdf",
  });
}

async function shareOutPdf(anchor) {
  try {
    var file = await pdfAsFile(anchor.dataset.pdf, anchor.dataset.title);
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

function flash(message) {
  var note = document.createElement("div");
  note.className = "toast";
  note.textContent = message;
  var main = document.querySelector(".app-content");
  main.insertBefore(note, main.firstChild.nextSibling);
  setTimeout(function () { note.remove(); }, 4000);
}

async function sendWhatsApp(button) {
  // The text goes to the clipboard, because WhatsApp accepts either a file
  // or a text, never both. Paste it into the chat next to the PDF.
  try {
    await navigator.clipboard.writeText(button.dataset.text);
    flash("Text kopiert — im Chat einfach einfügen.");
  } catch (error) {}
  try {
    var file = await pdfAsFile(button.dataset.pdf, button.dataset.title);
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file], title: button.dataset.title });
      return;
    }
  } catch (error) {
    if (error.name === "AbortError") return;
  }
  // No share sheet on this device: at least open the chat, PDF by hand.
  if (button.dataset.phone) {
    window.open("https://wa.me/" + button.dataset.phone, "_blank");
  }
}
