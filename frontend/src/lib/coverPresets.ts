// Built-in playlist covers (the server stores only the number, 1-25). Each is the inner markup
// of a 100x100 SVG; "ID" is replaced per instance so gradient ids never collide (a gradient in a
// hidden element would otherwise break every other cover that references it).
// The look is moody 80s vintage photo: faded warm colours, lifted blacks, film grain and a vignette
// (the grain/vignette layer is added to every design by presetSvg).

import { msg } from "./i18n.svelte";

export interface CoverPreset {
  name: string;
  svg: string;
}

const lin = (stops: string[], x2 = 1, y2 = 1, id = "g") =>
  `<linearGradient id="ID-${id}" x1="0" y1="0" x2="${x2}" y2="${y2}">${stops
    .map((c, i) => `<stop offset="${i / (stops.length - 1)}" stop-color="${c}"/>`)
    .join("")}</linearGradient>`;

/** A soft round glow that fades to nothing at its edge (sun haze, lamp light, light leaks). */
const haze = (id: string, color: string, opacity = 0.6) =>
  `<radialGradient id="ID-${id}"><stop offset="0" stop-color="${color}" stop-opacity="${opacity}"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></radialGradient>`;

const bg = '<rect width="100" height="100" fill="url(#ID-g)"/>';

// Palette: faded film colours, nothing saturated
const INK = "#1c1714";
const SEPIA = "#3a2a20";
const CREAM = "#eadcc0";
const ROSE = "#c46e6e";
const CHERRY = "#a3333d";
const MUSTARD = "#d6a446";
const RUST = "#c0622f";
const TEAL = "#4e8584";
const VIOLET = "#6c5a9c";
const OLIVE = "#7d8a5a";

const SUNSET = ["#2b1f3a", "#6b3a55", "#c0624a", "#e8a95c"];

/** Soft blur, applied with filter="url(#ID-f)". */
const soft = (sd = 1) =>
  `<filter id="ID-f" filterUnits="userSpaceOnUse" x="-10" y="-10" width="120" height="120"><feGaussianBlur stdDeviation="${sd}"/></filter>`;

/** Sun reflections on water: shrinking streaks below a horizon. */
const glitter = (cx: number, y: number, color: string) =>
  `<g fill="${color}" opacity=".7">${[
    [2, 30],
    [6, 22],
    [11, 15],
    [17, 9],
    [24, 5],
  ]
    .map(([dy, w]) => `<rect x="${cx - w / 2}" y="${y + dy}" width="${w}" height="1.3" rx=".65"/>`)
    .join("")}</g>`;

const r1 = (n: number) => Math.round(n * 10) / 10;

export const COVER_PRESETS: CoverPreset[] = [
  {
    name: msg("Abendrot"),
    svg: `<defs>${lin(SUNSET, 0, 1)}${lin(["#4a2d3c", "#1c1420"], 0, 1, "w")}${haze("h", "#f3c07a", 0.7)}</defs>${bg}
      <circle cx="50" cy="62" r="36" fill="url(#ID-h)"/>
      <g fill="#e3926a" opacity=".45"><rect x="8" y="28" width="38" height="2.2" rx="1.1"/><rect x="58" y="36" width="34" height="1.8" rx=".9"/><rect x="20" y="45" width="26" height="1.4" rx=".7"/></g>
      <circle cx="50" cy="64" r="17" fill="#f2c27c"/>
      <rect y="64" width="100" height="36" fill="url(#ID-w)"/>
      ${glitter(50, 64, "#eaa864")}`,
  },
  {
    name: msg("Wellen"),
    svg: `<defs>${lin(["#3c4a5c", "#8a7f86", "#d4a27e"], 0, 1)}${haze("h", "#f0dcb4", 0.5)}</defs>${bg}
      <circle cx="72" cy="24" r="18" fill="url(#ID-h)"/><circle cx="72" cy="24" r="8" fill="#f0dcb4" opacity=".9"/>
      ${[
        [0, 46, "#6f9692"],
        [-12.5, 61, "#3f6670"],
        [0, 77, "#26404a"],
      ]
        .map(
          ([x, y, c]) =>
            `<path d="M${x} ${y}q12.5-8 25 0t25 0 25 0 25 0 25 0V100H${x}z" fill="${c}"/>
             <path d="M${x} ${y}q12.5-8 25 0t25 0 25 0 25 0 25 0" fill="none" stroke="${CREAM}" stroke-width="1.4" opacity=".55"/>`,
        )
        .join("")}`,
  },
  {
    name: msg("Bögen"),
    svg: `<defs>${lin(["#ece0c6", "#d8c39c"])}</defs>${bg}
      <g fill="none" stroke-width="8">${[
        [38, RUST],
        [30, MUSTARD],
        [22, TEAL],
        [14, ROSE],
      ]
        .map(([r, c]) => `<path d="M${50 - +r} 90a${r} ${r} 0 0 1 ${2 * +r} 0" stroke="${c}"/>`)
        .join("")}</g>
      <rect y="90" width="100" height="10" fill="${SEPIA}"/>
      <g fill="${SEPIA}" opacity=".5"><circle cx="16" cy="20" r="1.6"/><circle cx="84" cy="26" r="1.3"/><circle cx="74" cy="12" r="1"/></g>`,
  },
  {
    name: msg("Punkte"),
    svg: `<defs>${lin(["#2a1d2e", "#4a2b45"], 0, 1)}${lin(["#ecbc66", RUST], 0, 1, "s")}</defs>${bg}
      <g fill="${ROSE}" opacity=".5">${Array.from({ length: 100 }, (_, i) => {
        const row = Math.floor(i / 10);
        return `<circle cx="${(i % 10) * 10 + 5}" cy="${row * 10 + 5}" r="${r1(0.4 + row * 0.24)}"/>`;
      }).join("")}</g>
      <circle cx="64" cy="38" r="20" fill="url(#ID-s)"/>`,
  },
  {
    name: msg("Streifen"),
    svg: `<defs>${lin(["#2b2420", SEPIA])}</defs>${bg}
      <g transform="rotate(-28 50 50)">${[CREAM, MUSTARD, RUST, CHERRY]
        .map((c, i) => `<rect x="-30" y="${36 + i * 9}" width="160" height="7" fill="${c}"/>`)
        .join("")}</g>`,
  },
  {
    name: msg("Kreise"),
    svg: `<defs>${lin(["#2a2433", "#3d3348"])}</defs>${bg}
      <g opacity=".8" style="mix-blend-mode:screen">
        <circle cx="38" cy="40" r="22" fill="${ROSE}"/>
        <circle cx="62" cy="40" r="22" fill="${TEAL}"/>
        <circle cx="50" cy="61" r="22" fill="${MUSTARD}"/>
      </g>`,
  },
  {
    name: msg("Berge"),
    svg: `<defs>${lin(["#3b2f4a", "#8a5e78", "#d99a6c"], 0, 1)}${haze("h", "#f0c890", 0.6)}</defs>${bg}
      <circle cx="60" cy="40" r="26" fill="url(#ID-h)"/><circle cx="60" cy="40" r="11" fill="#f0c890"/>
      <path d="M0 58 14 44l12 8 16-16 16 14 14-10 16 12 12-6v54H0z" fill="#7a5a78"/>
      <path d="M0 70 18 54l14 10 18-16 16 14 14-8 20 12v34H0z" fill="#4e3a55"/>
      <path d="M0 84 22 68l18 12 20-10 18 12 22-8v26H0z" fill="#2a1f30"/>`,
  },
  {
    name: msg("Equalizer"),
    svg: `<defs>${lin(["#1e1b18", "#2b2622"])}${haze("h", MUSTARD, 0.25)}</defs>${bg}
      <rect x="10" y="16" width="80" height="68" rx="4" fill="#121614" stroke="#4a443c" stroke-width="1.5"/>
      <ellipse cx="50" cy="56" rx="40" ry="30" fill="url(#ID-h)"/>
      ${[6, 9, 5, 11, 8, 4, 7]
        .map((level, col) =>
          Array.from({ length: 12 }, (_, seg) => {
            const c = seg < 8 ? "#d9a441" : seg < 10 ? "#e07a3a" : "#c9433a";
            return `<rect x="${17 + col * 9.6}" y="${r1(74 - seg * 4.6)}" width="7" height="3.2" fill="${c}" opacity="${seg < level ? 0.9 : 0.12}"/>`;
          }).join(""),
        )
        .join("")}`,
  },
  {
    name: msg("Vinyl"),
    svg: `<defs>${lin(["#3a2a20", "#2a1e17"])}</defs>${bg}
      <circle cx="46" cy="52" r="37" fill="#000" opacity=".3"/>
      <circle cx="44" cy="50" r="36" fill="#141110"/>
      <g fill="none" stroke="#fff" stroke-opacity=".06" stroke-width=".6">${[33, 30, 27, 24, 21, 18]
        .map((r) => `<circle cx="44" cy="50" r="${r}"/>`)
        .join("")}</g>
      <path d="M44 50 18 25a36 36 0 0 1 16-9z" fill="#fff" opacity=".06"/><path d="M44 50 70 75a36 36 0 0 1-16 9z" fill="#fff" opacity=".05"/>
      <circle cx="44" cy="50" r="12" fill="#d9822f"/><circle cx="44" cy="50" r="8" fill="none" stroke="#b8662a" stroke-width="1"/>
      <circle cx="44" cy="50" r="1.6" fill="${INK}"/>
      <circle cx="86" cy="16" r="6" fill="#6e665c"/><circle cx="86" cy="16" r="2.5" fill="#a39a8c"/>
      <path d="M86 16 82 48 68 58" fill="none" stroke="#bdb5a6" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
      <rect x="62" y="56" width="8" height="5" rx="1" fill="#8a8278" transform="rotate(-35 66 58)"/>`,
  },
  {
    name: msg("Mosaik"),
    svg: `<defs>${lin(["#2a221c", "#231c17"])}</defs>${bg}
      <rect x="10" y="10" width="38" height="38" rx="2" fill="${TEAL}"/>
      <rect x="52" y="10" width="38" height="18" rx="2" fill="${MUSTARD}"/>
      <rect x="52" y="32" width="38" height="16" rx="2" fill="${VIOLET}"/>
      <rect x="10" y="52" width="18" height="38" rx="2" fill="${OLIVE}"/>
      <rect x="32" y="52" width="58" height="38" rx="2" fill="${ROSE}"/>
      <g fill="#fff" opacity=".1"><rect x="10" y="10" width="38" height="6" rx="2"/><rect x="52" y="10" width="38" height="4" rx="2"/><rect x="32" y="52" width="58" height="6" rx="2"/></g>`,
  },
  {
    name: msg("Kaffee"),
    svg: `<defs>${lin(["#2e2219", "#4a3324"])}${haze("h", "#e8a95c", 0.35)}${soft(1.2)}</defs>${bg}
      <circle cx="18" cy="14" r="40" fill="url(#ID-h)"/>
      <g fill="none" stroke="${CREAM}" stroke-width="2.5" stroke-linecap="round" opacity=".4" filter="url(#ID-f)">
        <path d="M42 34q-4-5 0-10t0-10M54 34q-4-5 0-10t0-10"/>
      </g>
      <ellipse cx="48" cy="82" rx="30" ry="5.5" fill="#cbb994"/>
      <path d="M68 48h4a9 9 0 0 1 0 18h-4" fill="none" stroke="#e3d3b4" stroke-width="4"/>
      <path d="M28 40h40v30a10 10 0 0 1-10 10H38a10 10 0 0 1-10-10z" fill="#e3d3b4"/>
      <rect x="28" y="52" width="40" height="6" fill="${RUST}"/>
      <path d="M30 42v28a8 8 0 0 0 5 7" fill="none" stroke="#fff" stroke-width="1.5" opacity=".35"/>
      <ellipse cx="48" cy="40" rx="20" ry="4" fill="#3a2418" stroke="#f0e4cc" stroke-width="1.2"/>`,
  },
  {
    name: msg("Training"),
    svg: `<defs>${lin(["#1f2533", "#3a4560"], 0, 1)}${lin(["#d8d2c6", "#8a8478"], 0, 1, "m")}</defs>${bg}
      <g opacity=".85"><rect y="72" width="100" height="4" fill="${RUST}"/><rect y="78" width="100" height="4" fill="${MUSTARD}"/><rect y="84" width="100" height="4" fill="${CREAM}"/></g>
      <g transform="rotate(-30 50 50)">
        <rect x="12" y="47" width="76" height="6" rx="3" fill="url(#ID-m)"/>
        <rect x="26" y="30" width="9" height="40" rx="2" fill="#2a2420" stroke="#4a423a"/><rect x="65" y="30" width="9" height="40" rx="2" fill="#2a2420" stroke="#4a423a"/>
        <rect x="17" y="36" width="8" height="28" rx="2" fill="${RUST}"/><rect x="75" y="36" width="8" height="28" rx="2" fill="${RUST}"/>
      </g>`,
  },
  {
    name: msg("Baum"),
    svg: `<defs>${lin(["#3a2a4a", "#a4566a", "#e39a62"], 0, 1)}${haze("h", "#f2c27c", 0.6)}</defs>${bg}
      <circle cx="62" cy="62" r="34" fill="url(#ID-h)"/><circle cx="62" cy="64" r="20" fill="#f2c27c"/>
      <rect y="72" width="100" height="28" fill="#2a1f2e"/>
      ${glitter(62, 72, "#e8a35e")}
      <g fill="#1a1218">
        <path d="M30 98q-4-36 10-66" fill="none" stroke="#1a1218" stroke-width="4" stroke-linecap="round"/>
        <path d="M40 32q-14-6-26 4q12-4 26-4z"/><path d="M40 32q-6-14-20-14q12 4 20 14z"/>
        <path d="M40 32q10-14 26-10q-16 2-26 10z"/><path d="M40 32q16-2 24 12q-10-8-24-12z"/>
        <path d="M40 32q-12 4-18 18q4-12 18-18z"/>
      </g>`,
  },
  {
    name: msg("Cocktail"),
    svg: `<defs>${lin(["#2a1d2e", "#4a2b45"])}${haze("h", ROSE, 0.45)}</defs>${bg}
      <circle cx="50" cy="44" r="38" fill="url(#ID-h)"/>
      <path d="M28 30h44L50 52z" fill="${ROSE}" opacity=".9"/>
      <g fill="none" stroke="${CREAM}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" opacity=".85">
        <path d="M22 24h56L50 58zM50 58v22M36 82h28"/>
      </g>
      <path d="M27 27 47 50" stroke="#fff" stroke-width="1.2" opacity=".3"/>
      <path d="M68 14 56 38" stroke="${MUSTARD}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="58" cy="34" r="5" fill="${CHERRY}"/><circle cx="56.5" cy="32.5" r="1.4" fill="#fff" opacity=".35"/>`,
  },
  {
    name: msg("Party"),
    svg: `<defs>${lin(["#2a1d2e", "#3e2a3c"])}<clipPath id="ID-c"><path d="M30 82 50 22l20 60z"/></clipPath></defs>${bg}
      <g opacity=".85">${[
        [16, 22, 20, MUSTARD],
        [80, 30, -30, TEAL],
        [20, 64, 50, ROSE],
        [82, 66, 10, CREAM],
        [72, 16, 70, RUST],
        [12, 84, -40, TEAL],
      ]
        .map(([x, y, r, c]) => `<rect x="-3" y="-1.2" width="6" height="2.4" fill="${c}" transform="translate(${x} ${y}) rotate(${r})"/>`)
        .join("")}</g>
      <path d="M30 82 50 22l20 60z" fill="${TEAL}"/>
      <g clip-path="url(#ID-c)" stroke="${CREAM}" stroke-width="5"><path d="M20 72 80 52M20 54 80 34M20 90 80 70"/></g>
      <ellipse cx="50" cy="82" rx="21" ry="4" fill="${MUSTARD}"/>
      <circle cx="50" cy="21" r="6" fill="${ROSE}"/>`,
  },
  {
    name: msg("Sommer"),
    svg: `<defs>${lin(["#e2b057", "#cf8a3e"], 0, 1)}</defs>${bg}
      <g fill="${RUST}" opacity=".5">${Array.from({ length: 12 }, (_, i) => {
        const a = (i * 30 * Math.PI) / 180;
        const d = (7.5 * Math.PI) / 180;
        const p = (t: number) => `${r1(50 + 130 * Math.cos(t))} ${r1(78 + 130 * Math.sin(t))}`;
        return `<path d="M50 78L${p(a - d)}L${p(a + d)}z"/>`;
      }).join("")}</g>
      <circle cx="50" cy="78" r="18" fill="#f2dcae"/>
      <rect y="78" width="100" height="22" fill="${SEPIA}"/>`,
  },
  {
    name: msg("Herbst"),
    svg: `<defs>${lin(["#2e2219", "#3d2f1e"])}</defs>${bg}
      ${[
        [34, 36, -30, RUST, 1.1],
        [66, 44, 35, MUSTARD, 1],
        [44, 70, 80, CHERRY, 0.9],
        [76, 76, -50, OLIVE, 0.6],
      ]
        .map(
          ([x, y, r, c, s]) =>
            `<g transform="translate(${x} ${y}) rotate(${r}) scale(${s})"><path d="M0-18C12-10 12 10 0 18C-12 10-12-10 0-18z" fill="${c}"/><path d="M0-14V24" stroke="${INK}" stroke-width="1.5" opacity=".45"/></g>`,
        )
        .join("")}
      <g fill="${RUST}" opacity=".4"><circle cx="16" cy="88" r="1.5"/><circle cx="88" cy="20" r="1.2"/><circle cx="60" cy="90" r="1"/></g>`,
  },
  {
    name: msg("Winter"),
    svg: `<defs>${lin(["#1d2330", "#3a4560"], 0, 1)}${haze("h", "#a8b8c8", 0.3)}</defs>${bg}
      <circle cx="50" cy="50" r="40" fill="url(#ID-h)"/>
      <g fill="${CREAM}" opacity=".5"><circle cx="16" cy="18" r="1.6"/><circle cx="84" cy="24" r="1.2"/><circle cx="20" cy="80" r="1.2"/><circle cx="82" cy="82" r="1.6"/><circle cx="10" cy="50" r="1"/><circle cx="90" cy="56" r="1"/></g>
      <g fill="none" stroke="${CREAM}" stroke-width="2.6" stroke-linecap="round" opacity=".9">${Array.from(
        { length: 6 },
        (_, i) => `<path d="M50 50V20M50 30l-7-7M50 30l7-7M50 40l-5-5M50 40l5-5" transform="rotate(${i * 60} 50 50)"/>`,
      ).join("")}</g>`,
  },
  {
    name: msg("Frühling"),
    svg: `<defs>${lin(["#24302c", "#3e5048"], 0, 1)}</defs>${bg}
      <path d="M50 50q-3 20 0 38" fill="none" stroke="${OLIVE}" stroke-width="3" stroke-linecap="round"/>
      <ellipse cx="60" cy="72" rx="10" ry="4.5" fill="${OLIVE}" transform="rotate(-30 60 72)"/>
      <g fill="#d48a8a">${Array.from(
        { length: 6 },
        (_, i) => `<ellipse cx="50" cy="26" rx="7" ry="11" transform="rotate(${i * 60} 50 38)"/>`,
      ).join("")}</g>
      <circle cx="50" cy="38" r="7" fill="${MUSTARD}"/>`,
  },
  {
    name: msg("Lesen"),
    svg: `<defs>${lin(["#2b2a1e", "#4a4630"], 0, 1)}${haze("h", "#e8b45c", 0.45)}</defs>${bg}
      <circle cx="50" cy="20" r="46" fill="url(#ID-h)"/>
      <g stroke="#2a2018" stroke-width="2" stroke-linejoin="round">
        <path d="M12 36v42c14-4 28-3 38 4 10-7 24-8 38-4V36z" fill="#8a2e36"/>
        <path d="M50 32c-10-6-24-6-34-2v42c10-4 24-4 34 2zM50 32c10-6 24-6 34-2v42c-10-4-24-4-34 2z" fill="${CREAM}"/>
      </g>
      <g fill="none" stroke="#2a2018" stroke-width="1.4" stroke-linecap="round" opacity=".35">
        <path d="M22 40q10-3 22 0M22 48q10-3 22 0M22 56q10-3 22 0M22 64q10-3 16 0"/>
        <path d="M56 40q12-3 22 0M56 48q12-3 22 0M56 56q12-3 22 0M56 64q12-3 16 0"/>
      </g>`,
  },
  {
    name: msg("Kassette"),
    svg: `<defs>${lin(["#3b3266", "#7a5a98", "#c98aa8"])}</defs>${bg}
      <g transform="rotate(-12 50 50)">
        <rect x="15" y="28" width="72" height="48" rx="4" fill="#000" opacity=".3"/>
        <rect x="13" y="26" width="72" height="48" rx="4" fill="#d9cfc0"/>
        <rect x="18" y="30" width="62" height="28" rx="2" fill="#f0e6d2"/>
        <rect x="18" y="30" width="62" height="6" fill="${RUST}"/><rect x="18" y="36" width="62" height="2" fill="${MUSTARD}"/>
        <path d="M22 44q4-2 8 0t8 0 8 0" fill="none" stroke="${SEPIA}" stroke-width="1" stroke-linecap="round" opacity=".7"/>
        <rect x="31" y="44" width="36" height="12" rx="6" fill="#2a2420"/>
        <rect x="42" y="46" width="14" height="8" fill="#5a3a28"/>
        <g fill="${CREAM}"><circle cx="39" cy="50" r="4.5"/><circle cx="59" cy="50" r="4.5"/></g>
        <g fill="#2a2420"><circle cx="39" cy="50" r="2"/><circle cx="59" cy="50" r="2"/></g>
        <path d="M25 74 29 63h40l4 11z" fill="#c4b9a8"/>
        <g fill="#8a8278"><circle cx="37" cy="69" r="1.6"/><circle cx="61" cy="69" r="1.6"/><circle cx="16.5" cy="29.5" r="1"/><circle cx="81.5" cy="29.5" r="1"/><circle cx="16.5" cy="70.5" r="1"/><circle cx="81.5" cy="70.5" r="1"/></g>
      </g>`,
  },
  {
    name: msg("Kopfhörer"),
    svg: `<defs>${lin(["#2a2620", "#3d3628"], 0, 1)}${haze("h", "#e8b45c", 0.25)}</defs>${bg}
      <circle cx="80" cy="12" r="40" fill="url(#ID-h)"/>
      ${Array.from({ length: 14 }, (_, i) => {
        const c = ["#5c5a3a", SEPIA, "#8a7a58", "#2a2420", "#6b5a40", "#a8946a", "#4a3a2c"][(i * 3) % 7];
        return `<rect x="${(i * 5) % 7 - 6}" y="${58 + i * 3}" width="112" height="3" fill="${c}"/>`;
      }).join("")}
      <path d="M24 60a26 26 0 0 1 52 0" fill="none" stroke="#141110" stroke-width="6"/>
      <path d="M27 54a24 24 0 0 1 46 0" fill="none" stroke="#6a625a" stroke-width="1" opacity=".6"/>
      <rect x="21" y="54" width="6" height="8" rx="1" fill="#2a2420"/><rect x="73" y="54" width="6" height="8" rx="1" fill="#2a2420"/>
      <rect x="14" y="58" width="18" height="28" rx="8" fill="#171310"/><rect x="68" y="58" width="18" height="28" rx="8" fill="#171310"/>
      <g fill="none" stroke="#fff" stroke-width="1" stroke-linecap="round" opacity=".18"><path d="M18 64v14M72 64v14"/></g>`,
  },
  {
    name: msg("Gitarre"),
    svg: `<defs>${lin(["#1a2238", "#2c3a5c"], 0, 1)}${haze("h", "#d9c7a3", 0.35)}
      <radialGradient id="ID-b" cx=".45" cy=".4" r=".7"><stop offset="0" stop-color="#d0503e"/><stop offset=".6" stop-color="${CHERRY}"/><stop offset="1" stop-color="#5a141c"/></radialGradient></defs>${bg}
      <g stroke="#9ab0d0" stroke-width=".6">${Array.from(
        { length: 33 },
        (_, i) => `<path d="M${i * 3 + 1} 0v${60 + ((i * 37) % 40)}" opacity="${0.1 + ((i * 7) % 5) * 0.06}"/>`,
      ).join("")}</g>
      <ellipse cx="50" cy="0" rx="40" ry="34" fill="url(#ID-h)"/>
      <g transform="rotate(32 50 52) translate(50 52) scale(1.18) translate(-50 -44)">
        <rect x="47.5" y="8" width="5" height="44" fill="#3a2418"/>
        <g stroke="#b8b0a2" stroke-width=".5" opacity=".6">${[14, 20, 25, 30, 34, 38, 42]
          .map((y) => `<path d="M47.5 ${y}h5"/>`)
          .join("")}</g>
        <path d="M46 0h8l-1 9h-6z" fill="#1a1210"/>
        <path d="M50 38c-8 0-16 4-15 12 1 4-4 6-4 14 0 10 9 16 19 16s19-6 19-16c0-8-5-10-4-14 1-8-7-12-15-12z" fill="url(#ID-b)"/>
        <g fill="#2a0c10"><path d="M38 58q-2 6 1 12q-1-6-1-12zM62 58q2 6-1 12q1-6 1-12z"/></g>
        <g fill="#d0c8b8"><rect x="43" y="50" width="14" height="4" rx="1"/><rect x="43" y="58" width="14" height="4" rx="1"/></g>
        <rect x="44" y="66" width="12" height="2" fill="#b8b0a2"/><rect x="45" y="72" width="10" height="2.5" rx="1" fill="#b8b0a2"/>
        <g fill="${MUSTARD}"><circle cx="60" cy="68" r="1.6"/><circle cx="62" cy="73" r="1.6"/><circle cx="40" cy="68" r="1.6"/><circle cx="38" cy="73" r="1.6"/></g>
        <g stroke="${CREAM}" stroke-width=".25" opacity=".6">${[48.6, 49.5, 50.5, 51.4].map((x) => `<path d="M${x} 6V73"/>`).join("")}</g>
      </g>`,
  },
  {
    name: msg("Boombox"),
    svg: `<defs>${lin(["#4a3024", "#a8683a"], 0, 1)}${haze("h", "#f0c890", 0.3)}</defs>${bg}
      <circle cx="78" cy="14" r="36" fill="url(#ID-h)"/>
      <path d="M24 34v-8h52v8" fill="none" stroke="#5a5c5e" stroke-width="3"/>
      <rect x="10" y="36" width="84" height="46" rx="4" fill="#000" opacity=".3"/>
      <rect x="8" y="34" width="84" height="46" rx="4" fill="#2a2c2e"/>
      <rect x="8" y="34" width="84" height="2" rx="1" fill="#5a5c5e"/>
      <g fill="#8a8c8e">${[40, 45, 50, 55].map((x) => `<rect x="${x}" y="31" width="3.5" height="3"/>`).join("")}</g>
      <rect x="14" y="38" width="72" height="7" rx="1" fill="#c8b98a" opacity=".9"/>
      <g stroke="${SEPIA}" stroke-width=".5">${Array.from({ length: 13 }, (_, i) => `<path d="M${18 + i * 5} 40v${i % 2 ? 2 : 3}"/>`).join("")}</g>
      <path d="M58 38.5v6" stroke="${CHERRY}" stroke-width=".9"/>
      ${[26, 74]
        .map(
          (cx) =>
            `<circle cx="${cx}" cy="62" r="14" fill="#1a1c1e"/><circle cx="${cx}" cy="62" r="10.5" fill="#5e8a88"/><circle cx="${cx}" cy="62" r="6" fill="#4a7270"/><circle cx="${cx}" cy="62" r="2.5" fill="#1a1c1e"/>`,
        )
        .join("")}
      <rect x="41" y="52" width="18" height="16" rx="1" fill="#151618"/>
      <rect x="44" y="56" width="12" height="6" rx="1" fill="${CREAM}" opacity=".8"/>
      <g fill="#151618"><circle cx="47" cy="59" r="1.4"/><circle cx="53" cy="59" r="1.4"/></g>
      <g fill="#8a8c8e"><rect x="42" y="71" width="4" height="3"/><rect x="48" y="71" width="4" height="3"/><rect x="54" y="71" width="4" height="3"/></g>`,
  },
  {
    name: msg("Walkman"),
    svg: `<defs>${lin(["#5a4a8a", "#a87aa8", "#d9a0a8"])}${lin(["#5a7ab8", "#344c84"], 1, 1, "d")}</defs>${bg}
      <path d="M54 84q10 6 24 0" fill="none" stroke="#c8c8cc" stroke-width="1.6"/>
      <path d="M44 16q-6-8 4-12t26 6 14 50" fill="none" stroke="${INK}" stroke-width="1" opacity=".6"/>
      <g transform="rotate(-14 46 50)">
        <rect x="24" y="18" width="46" height="66" rx="4" fill="#000" opacity=".3" transform="translate(2 2)"/>
        <rect x="24" y="18" width="46" height="66" rx="4" fill="url(#ID-d)"/>
        <g fill="#c8c8cc"><rect x="30" y="15" width="7" height="3"/><rect x="39" y="15" width="7" height="3"/><rect x="48" y="15" width="7" height="3"/></g>
        <rect x="29" y="24" width="36" height="28" rx="2" fill="#1e2230"/>
        <rect x="32" y="27" width="30" height="8" fill="${CREAM}" opacity=".8"/><rect x="32" y="27" width="30" height="2.5" fill="${RUST}" opacity=".8"/>
        <g fill="${CREAM}" opacity=".7"><circle cx="40" cy="43" r="3.5"/><circle cx="54" cy="43" r="3.5"/></g>
        <g fill="#1e2230"><circle cx="40" cy="43" r="1.4"/><circle cx="54" cy="43" r="1.4"/></g>
        <path d="M30 26 44 50" stroke="#fff" stroke-width="1.5" opacity=".12"/>
        <rect x="24" y="58" width="46" height="6" fill="#c8c8cc"/>
        <path d="M30 72h20M30 76h14" stroke="#c8c8cc" stroke-width="1.2" opacity=".5"/>
      </g>
      <circle cx="54" cy="84" r="6" fill="#d9822f"/><circle cx="78" cy="84" r="6" fill="#d9822f"/>
      <g fill="#b8662a"><circle cx="54" cy="84" r="2.5"/><circle cx="78" cy="84" r="2.5"/></g>`,
  },
];

/** Film look laid over every design: a faint warm lift of the blacks, grain and a vignette. */
const FILM = `<defs>
  <filter id="ID-n" filterUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
    <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="7" stitchTiles="stitch"/>
    <feColorMatrix values="1.8 0 0 0 -.4  1.8 0 0 0 -.4  1.8 0 0 0 -.4  0 0 0 0 1"/>
  </filter>
  <radialGradient id="ID-v" r=".75"><stop offset=".5" stop-color="#140c08" stop-opacity="0"/><stop offset="1" stop-color="#140c08" stop-opacity=".65"/></radialGradient>
</defs>
<rect width="100" height="100" fill="#e9c9a0" opacity=".1" style="mix-blend-mode:screen"/>
<rect width="100" height="100" filter="url(#ID-n)" opacity=".32" style="mix-blend-mode:overlay"/>
<rect width="100" height="100" fill="url(#ID-v)"/>`;

let instances = 0;

/** SVG markup of preset `n` (1-based) with ids unique to this call; null for unknown numbers. */
export function presetSvg(n: number): string | null {
  const preset = COVER_PRESETS[n - 1];
  if (!preset) return null;
  const id = `cp${n}-${++instances}`;
  return (preset.svg + FILM).replace(/ID-/g, `${id}-`);
}
