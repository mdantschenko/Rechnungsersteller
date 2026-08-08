self.addEventListener("push", function (event) {
  var data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (ignored) {}
  event.waitUntil(
    self.registration.showNotification(data.title || "Nachhilfe", {
      body: data.body || "",
      tag: data.tag || "wecker",
      data: { url: data.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});
