// The landing page, rendered once per language by build.mjs. Texts come from i18n/<lang>.mjs;
// everything here is markup and the decorative bars (generated at build time, so the page needs
// no JavaScript to look right).

export const REPO = "https://github.com/mushroom-media/audium";

const INSTALL = [
  "mkdir audium && cd audium",
  `curl -fLO https://raw.githubusercontent.com/mushroom-media/audium/main/docker-compose.yml`,
  `curl -fL -o .env https://raw.githubusercontent.com/mushroom-media/audium/main/.env.example`,
  "# AUDIUM_MUSIC_PATH=/srv/music  (.env)",
  "docker compose up -d",
].join("\n");

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// Bar sets. Heights in px, delays in s; colours are classes so the CSS keeps the palette.
function spectrum(n = 150) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const x = (i - n / 2) / (n / 2);
    const env = Math.exp(-x * x * 2.2);
    const h = Math.round(10 + env * (60 + Math.abs(Math.sin(i * 0.57) * Math.cos(i * 0.19)) * 150));
    const ax = Math.abs(x);
    const tone = ax < 0.3 ? "hi" : ax < 0.65 ? "mid" : "lo";
    out.push(bar(h, ((i % 14) * 0.09).toFixed(2), tone));
  }
  return out.join("");
}

function mini(n = 48) {
  const out = [];
  for (let j = 0; j < n; j++) {
    const h = Math.round(8 + Math.abs(Math.sin(j * 0.9) * Math.cos(j * 0.31)) * 22);
    out.push(bar(h, ((j % 10) * 0.12).toFixed(2), j < 20 ? "hi" : "off"));
  }
  return out.join("");
}

function side(seed, reverse) {
  const out = [];
  for (let k = 0; k < 10; k++) {
    const h = Math.round(14 + Math.abs(Math.sin((k + seed) * 0.8)) * 62);
    out.push(bar(h, (k * 0.08).toFixed(2), k % 3 === 0 ? "hi" : "mid"));
  }
  return (reverse ? out.reverse() : out).join("");
}

const bar = (h, d, tone) => `<span class="eq ${tone}" style="--h:${h}px;--d:${d}s"></span>`;

const eqIcon = (heights, cls = "") =>
  `<span class="eq-icon ${cls}" aria-hidden="true">${heights
    .map((h, i) => `<span class="eqb" style="--h:${h}px;--d:${(i * 0.27) % 0.8}s"></span>`)
    .join("")}</span>`;

const icon = {
  lock: `<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/></svg>`,
  shield: `<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>`,
  star: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2l3 6.5 7 .8-5.2 4.8 1.4 7L12 17.6 5.8 21l1.4-7L2 9.3l7-.8z"/></svg>`,
  prev: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M19 20L9 12l10-8v16zM5 19V5"/></svg>`,
  next: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 4l10 8-10 8V4zM19 5v14"/></svg>`,
  pause: `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>`,
  logo: `<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="13" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="14" cy="14" r="8.5" fill="none" stroke="currentColor" stroke-width="1" opacity="0.6"/><circle cx="14" cy="14" r="3.5" fill="currentColor"/></svg>`,
};

const OS = ["windows", "mac", "linux"];

const dlIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>`;
const osIcon = {
  windows: `<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>`,
  mac: `<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="4" y="5" width="16" height="10" rx="1.5"/><path d="M2 18h20l-1.5 1.5h-17z"/></svg>`,
  linux: `<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/></svg>`,
};

// The desktop app downloads: one card per system. main.js marks the visitor's system
// (is-current); without JavaScript all cards look the same.
function downloadSection(t, d) {
  const cards = OS.map((os) => {
    const files = d ? d.files.filter((f) => f.os === os) : [];
    const o = t.download.os[os];
    const links = files.length
      ? files
          .map(
            (f, i) =>
              `<a class="btn ${i === 0 ? "btn-primary" : "btn-ghost"} dl-btn" href="${f.url}">${dlIcon}<span>${t.download.kinds[f.kind]}</span>${f.size ? `<small>${f.size}</small>` : ""}</a>`,
          )
          .join("")
      : `<a class="btn btn-ghost dl-btn" href="${REPO}/releases">${t.download.fallback}</a>`;
    return `<article class="dl" data-os="${os}">
      <div class="dl-head">${osIcon[os]}<span class="dl-badge">${t.download.recommended}</span></div>
      <h3>${o.name}</h3>
      <p>${o.note}</p>
      <div class="dl-links">${links}</div>
    </article>`;
  }).join("\n    ");

  const meta = d
    ? `<p class="dl-meta">${t.download.version} <b>${d.version}</b>${d.date ? ` · ${t.download.released} ${d.date}` : ""} · <a href="${d.releaseUrl}">${t.download.notes}</a></p>`
    : "";

  return `<section class="wrap section" id="download">
  <div class="head wide">
    <span class="kicker">${t.download.kicker}</span>
    <h2>${t.download.title}</h2>
    <p class="muted">${t.download.lead}</p>
    ${meta}
  </div>
  <p class="dl-mobile" hidden>${t.download.mobile}</p>
  <div class="downloads">
    ${cards}
  </div>
</section>`;
}

export function render(t, { lang, path, alternates, siteUrl, downloads }) {
  const abs = (p) => (siteUrl ? siteUrl.replace(/\/$/, "") + p : p);
  const other = alternates.find((a) => a.lang !== lang);
  const playing = 2;

  return `<!doctype html>
<html lang="${lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(t.meta.title)}</title>
<meta name="description" content="${esc(t.meta.description)}">
<meta name="theme-color" content="#111214">
${siteUrl ? `<link rel="canonical" href="${abs(path)}">` : ""}
${alternates.map((a) => `<link rel="alternate" hreflang="${a.lang}" href="${abs(a.path)}">`).join("\n")}
<link rel="alternate" hreflang="x-default" href="${abs("/")}">
<meta property="og:type" content="website">
<meta property="og:title" content="${esc(t.meta.title)}">
<meta property="og:description" content="${esc(t.meta.description)}">
${siteUrl ? `<meta property="og:url" content="${abs(path)}">` : ""}
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="stylesheet" href="/assets/style.css">
<script src="/assets/main.js" defer></script>
</head>
<body>
<a class="skip" href="#main">${t.nav.skip}</a>

<header class="nav">
  <nav aria-label="${t.nav.label}" class="wrap nav-row">
    <a class="logo" href="${path}">${icon.logo}<span>audium</span></a>
    <div class="nav-links">
      <a href="#features">${t.nav.features}</a>
      <a href="#apps">${t.nav.apps}</a>
      <a href="#download">${t.nav.download}</a>
      <a href="#install">${t.nav.install}</a>
      <a href="${REPO}/tree/main/docs">${t.nav.docs}</a>
    </div>
    <div class="nav-actions">
      <a class="lang" href="${other.path}" hreflang="${other.lang}" lang="${other.lang}">${other.label}</a>
      <a class="btn btn-ghost btn-sm hide-sm" href="${REPO}">${icon.star}${t.nav.star}</a>
      <a class="btn btn-primary btn-sm" href="#install">${t.nav.start}</a>
    </div>
  </nav>
</header>

<main id="main">
<section class="wrap hero" id="top">
  <div class="hero-text">
    <span class="badge"><span class="pulse dot"></span>${t.hero.badge}</span>
    <h1>${t.hero.title}</h1>
    <p class="lead">${t.hero.lead}</p>
    <div class="row">
      <a class="btn btn-primary" href="#install">${t.hero.install}</a>
      <a class="btn btn-ghost" href="${REPO}">${t.hero.github}</a>
    </div>
    <ul class="facts">${t.hero.facts.map((f) => `<li>${f}</li>`).join("")}</ul>
  </div>
  <div class="hero-art">
    <div class="vinyl spin" aria-hidden="true">
      <div class="vinyl-label"><b>audium</b><small>SIDE A · 33⅓</small><i></i></div>
    </div>
    <div class="player" role="img" aria-label="${t.hero.playerLabel}">
      <div class="player-top">
        <div class="cover">${eqIcon([22, 28, 18, 24], "dark")}</div>
        <div class="player-meta"><b>${t.hero.track}</b><span>${t.hero.artist}</span></div>
        <span class="tag">FLAC</span>
      </div>
      <div class="mini" aria-hidden="true">${mini()}</div>
      <div class="times" aria-hidden="true"><span>1:47</span><span>4:12</span></div>
      <div class="controls" aria-hidden="true">
        <span class="ctl">${icon.prev}</span><span class="ctl play">${icon.pause}</span><span class="ctl">${icon.next}</span>
      </div>
    </div>
  </div>
</section>

<div class="spectrum" aria-hidden="true">${spectrum()}</div>

<section class="band" aria-label="${t.stats.label}">
  <div class="wrap stats">
    ${t.stats.items.map((s) => `<div><b>${s.v}</b><span>${s.l}</span></div>`).join("")}
  </div>
</section>

<section class="wrap section" id="features">
  <div class="head">
    <span class="kicker">${t.why.kicker}</span>
    <h2>${t.why.title}</h2>
  </div>
  <div class="cards">
    <article class="card">${icon.lock}<h3>${t.why.cards[0].title}</h3><p>${t.why.cards[0].text}</p></article>
    <article class="card">${icon.shield}<h3>${t.why.cards[1].title}</h3><p>${t.why.cards[1].text}</p></article>
    <article class="card">${eqIcon([16, 30, 22, 36, 18], "big")}<h3>${t.why.cards[2].title}</h3><p>${t.why.cards[2].text}</p></article>
  </div>
</section>

<section class="wrap section split">
  <div class="head">
    <span class="kicker">${t.tracks.kicker}</span>
    <h2>${t.tracks.title}</h2>
    <p class="muted">${t.tracks.lead}</p>
  </div>
  <ol class="tracklist">
    ${t.tracks.items
      .map(
        (it, i) => `<li${i === playing ? ' class="playing"' : ""}>
      <span class="num">${i === playing ? `<span role="img" aria-label="${t.tracks.nowPlaying}">${eqIcon([12, 16, 9], "tiny")}</span>` : String(i + 1).padStart(2, "0")}</span>
      <div><h3>${it.title}</h3><p>${it.text}</p></div>
      <span class="len">${it.len}</span>
    </li>`,
      )
      .join("\n    ")}
  </ol>
</section>

<section class="band" id="apps">
  <div class="wrap section">
    <div class="head wide">
      <span class="kicker">${t.apps.kicker}</span>
      <h2>${t.apps.title}</h2>
      <p class="muted">${t.apps.lead}</p>
    </div>
    <ul class="apps">
      ${t.apps.items.map((a) => `<li><b>${a.name}</b><span>${a.os}</span></li>`).join("")}
    </ul>
    <p><a href="${REPO}/blob/main/docs/apps.md">${t.apps.more}</a></p>
  </div>
</section>

${downloadSection(t, downloads)}

<section class="wrap section split" id="install">
  <div class="head">
    <span class="kicker">${t.install.kicker}</span>
    <h2>${t.install.title}</h2>
    <ul class="checks">${t.install.points.map((p) => `<li>${p}</li>`).join("")}</ul>
    <a class="strong" href="${REPO}#readme">${t.install.guide}</a>
  </div>
  <div class="terminal">
    <div class="term-bar">
      <span></span><span></span><span></span>
      <code>~/audium</code>
      <button type="button" class="copy" data-copy="${esc(INSTALL)}" data-done="${t.install.copied}">${t.install.copy}</button>
    </div>
<pre><span class="c"># 1 · ${t.install.step1}</span>
<span class="k">mkdir</span> audium &amp;&amp; <span class="k">cd</span> audium
<span class="k">curl</span> -fLO https://raw.githubusercontent.com/mushroom-media/audium/main/docker-compose.yml
<span class="k">curl</span> -fL -o .env https://raw.githubusercontent.com/mushroom-media/audium/main/.env.example

<span class="c"># 2 · ${t.install.step2}</span>
AUDIUM_MUSIC_PATH=/srv/music

<span class="c"># 3 · ${t.install.step3}</span>
<span class="k">docker</span> compose up -d
<span class="k">✓ ${t.install.done} http://&lt;server-ip&gt;:8091</span><span class="cursor pulse" aria-hidden="true"></span></pre>
  </div>
</section>

<section class="cta">
  <div class="wrap-narrow">
    <div class="cta-art" aria-hidden="true">
      <div class="bars">${side(0, true)}</div>
      <div class="vinyl small spin"><i></i></div>
      <div class="bars">${side(3, false)}</div>
    </div>
    <h2>${t.cta.title}</h2>
    <p class="muted">${t.cta.text}</p>
    <div class="row center">
      <a class="btn btn-primary" href="#install">${t.cta.start}</a>
      <a class="btn btn-ghost" href="${REPO}">${t.cta.star}</a>
    </div>
  </div>
</section>
</main>

<footer class="footer">
  <div class="wrap footer-row">
    <span><b>audium</b> · ${t.footer.tagline}</span>
    <nav aria-label="${t.footer.label}">
      <a href="${REPO}/tree/main/docs">${t.nav.docs}</a>
      <a href="${REPO}">GitHub</a>
      <a href="${REPO}/blob/main/CHANGELOG.md">Changelog</a>
      <a href="${REPO}/blob/main/LICENSE">${t.footer.license}</a>
      <a href="${other.path}" hreflang="${other.lang}" lang="${other.lang}">${other.label}</a>
    </nav>
  </div>
</footer>
</body>
</html>
`;
}
