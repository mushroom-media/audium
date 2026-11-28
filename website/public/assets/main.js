// The page works without JavaScript; this only adds two conveniences.

// 1. Desktop downloads: highlight the visitor's system. On a phone or tablet no desktop download
//    fits, so the page points to the web app and the Subsonic apps instead.
function detectSystem() {
  const ua = navigator.userAgent;
  const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  const p = `${platform} ${ua}`.toLowerCase();
  // iPadOS reports itself as a Mac; touch points give it away.
  if (/android|iphone|ipad|ipod/.test(p) || (/mac/.test(p) && navigator.maxTouchPoints > 1)) return "mobile";
  if (/win/.test(p)) return "windows";
  if (/mac/.test(p)) return "mac";
  if (/linux|x11|cros/.test(p)) return "linux";
  return "";
}

const system = detectSystem();
if (system === "mobile") {
  for (const el of document.querySelectorAll(".dl-mobile")) el.hidden = false;
} else if (system) {
  const card = document.querySelector(`.dl[data-os="${system}"]`);
  if (card) card.classList.add("is-current");
}

// 2. The copy button of the install commands.
for (const button of document.querySelectorAll("button[data-copy]")) {
  const label = button.textContent;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = button.dataset.done;
    } catch {
      return;
    }
    setTimeout(() => (button.textContent = label), 1600);
  });
}
