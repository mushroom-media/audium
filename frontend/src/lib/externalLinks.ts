// Desktop app: links to other sites open in the system browser (tauri-plugin-opener), not in a
// bare WebView window of their own.

export function startExternalLinks() {
  document.addEventListener(
    "click",
    (e) => {
      if (e.defaultPrevented || e.button !== 0) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || !/^https?:$/.test(a.protocol) || a.origin === window.location.origin) return;
      e.preventDefault();
      import("@tauri-apps/api/core")
        .then(({ invoke }) => invoke("plugin:opener|open_url", { url: a.href }))
        .catch(() => window.open(a.href, "_blank", "noopener"));
    },
    true,
  );
}
