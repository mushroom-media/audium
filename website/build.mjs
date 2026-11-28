// Builds the static website into website/dist: one page per language plus the files in public/.
// No dependencies, just Node: `node website/build.mjs`. SITE_URL (e.g. https://audium.example)
// adds canonical and absolute hreflang links; without it the links stay relative.
import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import de from "./src/i18n/de.mjs";
import en from "./src/i18n/en.mjs";
import { REPO, render } from "./src/page.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const dist = join(root, "dist");
const siteUrl = process.env.SITE_URL || "";

// The desktop app downloads. The current version is the one the installed apps update to:
// latest.json in the fixed release "app-update" (written by .github/workflows/app.yml when an
// app release is published). The file names follow app.yml; each one is checked, so a platform
// whose build failed is left out. Offline or without a release the page links to the releases.
const RELEASES = `${REPO}/releases`;
const FILES = [
  { os: "windows", kind: "exe", name: (v) => `audium_${v}_x64-setup.exe` },
  { os: "mac", kind: "dmg", name: (v) => `audium_${v}_universal.dmg` },
  { os: "linux", kind: "appimage", name: (v) => `audium_${v}_amd64.AppImage` },
  { os: "linux", kind: "deb", name: (v) => `audium_${v}_amd64.deb` },
];

async function loadDownloads() {
  if (process.env.SKIP_DOWNLOADS) return null;
  try {
    const res = await fetch(`${RELEASES}/download/app-update/latest.json`, { signal: AbortSignal.timeout(15000) });
    if (!res.ok) throw new Error(`latest.json: HTTP ${res.status}`);
    const { version, pub_date: date } = await res.json();
    if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error(`latest.json: odd version ${version}`);
    const files = [];
    for (const f of FILES) {
      const url = `${RELEASES}/download/app-v${version}/${f.name(version)}`;
      const head = await fetch(url, { method: "HEAD", signal: AbortSignal.timeout(15000) });
      if (!head.ok) {
        console.warn(`download missing, left out: ${url} (HTTP ${head.status})`);
        continue;
      }
      const bytes = Number(head.headers.get("content-length")) || 0;
      files.push({ os: f.os, kind: f.kind, url, size: bytes ? `${Math.round(bytes / 1048576)} MB` : "" });
    }
    if (!files.length) throw new Error("no download found");
    return { version, date: date ? date.slice(0, 10) : "", files, releaseUrl: `${RELEASES}/tag/app-v${version}` };
  } catch (err) {
    console.warn(`downloads: ${err.message}; the page links to ${RELEASES} instead`);
    return null;
  }
}

const downloads = await loadDownloads();

const pages = [
  { lang: "en", path: "/", label: "English", texts: en },
  { lang: "de", path: "/de/", label: "Deutsch", texts: de },
];
const alternates = pages.map(({ lang, path, label }) => ({ lang, path, label }));

await rm(dist, { recursive: true, force: true });
await cp(join(root, "public"), dist, { recursive: true });

for (const page of pages) {
  const html = render(page.texts, { lang: page.lang, path: page.path, alternates, siteUrl, downloads });
  const dir = join(dist, page.path);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "index.html"), html);
}

if (siteUrl) {
  const base = siteUrl.replace(/\/$/, "");
  const urls = pages.map((p) => `  <url><loc>${base}${p.path}</loc></url>`).join("\n");
  await writeFile(
    join(dist, "sitemap.xml"),
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
  );
  await writeFile(join(dist, "robots.txt"), `User-agent: *\nAllow: /\nSitemap: ${base}/sitemap.xml\n`);
}

console.log(
  `website built: ${pages.map((p) => p.path).join(", ")}${siteUrl ? ` for ${siteUrl}` : ""}, ` +
    (downloads ? `app ${downloads.version} (${downloads.files.length} downloads)` : "no app downloads"),
);
