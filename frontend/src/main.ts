import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

mount(App, { target: document.getElementById("app")! });

// Installable app (PWA) + offline app shell. Only in production builds: during development the
// worker would cache files that Vite serves fresh.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js", { scope: "./" }).catch(() => {
      /* e.g. plain HTTP on a LAN IP: browsers allow service workers only on HTTPS and localhost */
    });
  });
}
