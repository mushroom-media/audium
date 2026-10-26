// Built-in playlist covers (the server stores only the number, 1-20). Each is the inner markup
// of a 100x100 SVG; "ID" is replaced per instance so gradient ids never collide (a gradient in a
// hidden element would otherwise break every other cover that references it).
// The look is 80s: synthwave neon on night purple, striped sunsets, grid floors, Memphis shapes.

export interface CoverPreset {
  name: string;
  svg: string;
}

const lin = (stops: string[], x2 = 1, y2 = 1) =>
  `<linearGradient id="ID-g" x1="0" y1="0" x2="${x2}" y2="${y2}">${stops
    .map((c, i) => `<stop offset="${i / (stops.length - 1)}" stop-color="${c}"/>`)
    .join("")}</linearGradient>`;

const bg = '<rect width="100" height="100" fill="url(#ID-g)"/>';

// Palette
const PINK = "#ff2a6d";
const MAGENTA = "#f706cf";
const CYAN = "#05d9e8";
const PURPLE = "#b026ff";
const YELLOW = "#ffd319";
const ORANGE = "#ff901f";
const MINT = "#01ffc3";
const NIGHT = "#1a0b2e";

/** Neon glow, applied with filter="url(#ID-f)". User-space bounds so flat lines still glow. */
const glow = (sd = 1.5) =>
  `<filter id="ID-f" filterUnits="userSpaceOnUse" x="-10" y="-10" width="120" height="120"><feGaussianBlur stdDeviation="${sd}" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`;

const stars =
  '<g fill="#fff" opacity=".75"><circle cx="12" cy="12" r=".9"/><circle cx="30" cy="22" r=".6"/><circle cx="84" cy="10" r=".8"/><circle cx="70" cy="24" r=".5"/><circle cx="92" cy="34" r=".6"/><circle cx="8" cy="36" r=".5"/></g>';

/** The striped retro sun: a yellow-to-pink disc with widening gaps across its lower half. */
const sun = (cx: number, cy: number, r: number) =>
  `<linearGradient id="ID-s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${YELLOW}"/><stop offset=".5" stop-color="${ORANGE}"/><stop offset="1" stop-color="${PINK}"/></linearGradient>
  <mask id="ID-m"><rect width="100" height="100" fill="#fff"/>${[0.12, 0.32, 0.52, 0.72]
    .map((t, i) => `<rect x="0" y="${cy + t * r}" width="100" height="${(1 + i * 0.7) * (r / 20)}" fill="#000"/>`)
    .join("")}</mask>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#ID-s)" mask="url(#ID-m)"/>`;

/** A neon perspective grid floor from the horizon down. */
const grid = (color: string, horizon = 66) =>
  `<rect y="${horizon}" width="100" height="${100 - horizon}" fill="#12052a"/>
  <g stroke="${color}" stroke-width=".8" fill="none" filter="url(#ID-f)">
    <path d="M0 ${horizon}h100" stroke-width="1.2"/>
    ${[0.06, 0.16, 0.32, 0.56, 0.9].map((t) => `<path d="M0 ${horizon + t * (100 - horizon)}h100"/>`).join("")}
    ${[-3, -2, -1, 0, 1, 2, 3].map((k) => `<path d="M${50 + k * 7} ${horizon}L${50 + k * 42} 100"/>`).join("")}
  </g>`;

const squiggle = (x: number, y: number, color: string, w = 2.5) =>
  `<path d="M${x} ${y}q4-6 8 0t8 0 8 0" fill="none" stroke="${color}" stroke-width="${w}" stroke-linecap="round"/>`;

export const COVER_PRESETS: CoverPreset[] = [
  {
    name: "Abendrot",
    svg: `<defs>${lin(["#0d0221", "#3b0a5e", "#a4166e"], 0, 1)}${glow(1.2)}</defs>${bg}
      ${stars}${sun(50, 50, 26)}${grid(MAGENTA)}`,
  },
  {
    name: "Wellen",
    svg: `<defs>${lin(["#0d0221", "#1b0f4a"])}${glow(1.6)}</defs>${bg}
      <g fill="none" stroke-width="3" stroke-linecap="round" filter="url(#ID-f)">
        <path d="M-5 35q13-12 26 0t26 0 26 0 26 0" stroke="${CYAN}"/>
        <path d="M-5 52q13-12 26 0t26 0 26 0 26 0" stroke="${MAGENTA}"/>
        <path d="M-5 69q13-12 26 0t26 0 26 0 26 0" stroke="${PURPLE}"/>
      </g>`,
  },
  {
    name: "Bögen",
    svg: `<defs>${lin(["#fde2f3", "#d6f6ff"])}</defs>${bg}
      ${squiggle(12, 22, NIGHT)}
      <path d="M72 14l10 16H62z" fill="none" stroke="${CYAN}" stroke-width="2.5" stroke-linejoin="round"/>
      <g fill="${PURPLE}"><circle cx="18" cy="48" r="2"/><circle cx="84" cy="46" r="2"/><circle cx="46" cy="36" r="1.6"/></g>
      <g fill="none" stroke-width="7">
        <path d="M14 100a36 36 0 0 1 72 0" stroke="${PINK}"/>
        <path d="M26 100a24 24 0 0 1 48 0" stroke="${YELLOW}"/>
        <path d="M38 100a12 12 0 0 1 24 0" stroke="${NIGHT}"/>
      </g>`,
  },
  {
    name: "Punkte",
    svg: `<defs>${lin([NIGHT, "#0d0221"])}<pattern id="ID-p" width="12.5" height="12.5" patternUnits="userSpaceOnUse"><circle cx="6.25" cy="6.25" r="2.2" fill="${MAGENTA}"/></pattern></defs>${bg}
      <rect width="100" height="100" fill="url(#ID-p)" opacity=".5"/>
      ${sun(66, 36, 20)}`,
  },
  {
    name: "Streifen",
    svg: `<defs>${lin([PINK, "#7a04eb"])}<pattern id="ID-p" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="14" fill="#fff" opacity=".16"/></pattern></defs>${bg}
      <rect width="100" height="100" fill="url(#ID-p)"/>
      <path d="M-2 66l10-9 10 9 10-9 10 9 10-9 10 9 10-9 10 9 10-9 10 9" fill="none" stroke="${YELLOW}" stroke-width="4" stroke-linejoin="round"/>
      <g fill="${CYAN}"><circle cx="22" cy="26" r="4"/><circle cx="78" cy="84" r="3"/></g>`,
  },
  {
    name: "Kreise",
    svg: `<defs>${lin(["#0d0221", "#2d0b4e"])}${glow(1.6)}</defs>${bg}
      <g fill="none" stroke-width="3.5" filter="url(#ID-f)">
        <circle cx="38" cy="40" r="22" stroke="${PINK}"/>
        <circle cx="62" cy="40" r="22" stroke="${CYAN}"/>
        <circle cx="50" cy="61" r="22" stroke="${YELLOW}"/>
      </g>`,
  },
  {
    name: "Berge",
    svg: `<defs>${lin(["#0d0221", "#2d0b4e", "#7a0b6e"], 0, 1)}${glow(1.2)}</defs>${bg}
      ${stars}${sun(50, 46, 20)}
      <path d="M0 66 20 42l14 14 16-24 18 22 12-10 20 22z" fill="#140a2a" stroke="${CYAN}" stroke-width="1.5" stroke-linejoin="round" filter="url(#ID-f)"/>
      ${grid(MAGENTA)}`,
  },
  {
    name: "Equalizer",
    svg: `<defs>${lin(["#0d0221", NIGHT])}${glow(1.4)}
      <linearGradient id="ID-b" x1="0" y1="20" x2="0" y2="84" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="${PINK}"/><stop offset=".5" stop-color="${PURPLE}"/><stop offset="1" stop-color="${CYAN}"/></linearGradient></defs>${bg}
      <g fill="url(#ID-b)" filter="url(#ID-f)">
        <rect x="16" y="44" width="9" height="40" rx="2"/><rect x="30" y="28" width="9" height="56" rx="2"/>
        <rect x="44" y="52" width="9" height="32" rx="2"/><rect x="58" y="20" width="9" height="64" rx="2"/>
        <rect x="72" y="38" width="9" height="46" rx="2"/>
      </g>
      <path d="M10 89h80" stroke="${CYAN}" stroke-width="1" opacity=".5"/>`,
  },
  {
    name: "Vinyl",
    svg: `<defs>${lin([MAGENTA, "#2d0b4e"])}
      <linearGradient id="ID-l" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${YELLOW}"/><stop offset="1" stop-color="${PINK}"/></linearGradient></defs>${bg}
      <circle cx="50" cy="50" r="34" fill="#0d0221"/>
      <g fill="none" stroke="#fff" stroke-opacity=".08"><circle cx="50" cy="50" r="29"/><circle cx="50" cy="50" r="24"/><circle cx="50" cy="50" r="19"/></g>
      <path d="M26 30a30 30 0 0 1 22-10" fill="none" stroke="${CYAN}" stroke-width="2" stroke-linecap="round" opacity=".6"/>
      <circle cx="50" cy="50" r="11" fill="url(#ID-l)"/><circle cx="50" cy="50" r="2" fill="#0d0221"/>`,
  },
  {
    name: "Mosaik",
    svg: `<defs>${lin([NIGHT, "#2d0b4e"])}<pattern id="ID-p" width="5" height="5" patternUnits="userSpaceOnUse"><circle cx="2.5" cy="2.5" r="1" fill="${NIGHT}"/></pattern></defs>${bg}
      <rect x="10" y="10" width="38" height="38" rx="3" fill="${CYAN}"/>
      <rect x="10" y="10" width="38" height="38" rx="3" fill="url(#ID-p)" opacity=".5"/>
      <rect x="52" y="10" width="38" height="18" rx="3" fill="${YELLOW}"/>
      <rect x="52" y="32" width="38" height="16" rx="3" fill="${PURPLE}"/>
      <rect x="10" y="52" width="18" height="38" rx="3" fill="${MINT}"/>
      <rect x="32" y="52" width="58" height="38" rx="3" fill="${PINK}"/>
      ${squiggle(46, 72, NIGHT, 3)}`,
  },
  {
    name: "Kaffee",
    svg: `<defs>${lin([NIGHT, "#3b0a5e"], 0, 1)}${glow(1.4)}</defs>${bg}
      <g fill="none" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" filter="url(#ID-f)">
        <path d="M40 32q-4-5 0-10t0-10M52 32q-4-5 0-10t0-10" stroke="${CYAN}"/>
        <path d="M68 48h4a9 9 0 0 1 0 18h-4" stroke="${PINK}"/>
        <path d="M28 40h40v30a12 12 0 0 1-12 12H40a12 12 0 0 1-12-12z" stroke="${PINK}"/>
        <path d="M18 89h60" stroke="${YELLOW}"/>
      </g>`,
  },
  {
    name: "Training",
    svg: `<defs>${lin(["#0d0221", "#2d0b4e"])}${glow(1.4)}</defs>${bg}
      <g stroke="${MAGENTA}" stroke-width="2" stroke-linecap="round" opacity=".55"><path d="M8 72h16M14 80h18M6 88h12"/></g>
      <g transform="rotate(-30 50 50)" filter="url(#ID-f)">
        <rect x="12" y="47" width="76" height="6" rx="3" fill="${CYAN}"/>
        <rect x="26" y="30" width="9" height="40" rx="2" fill="${PINK}"/><rect x="65" y="30" width="9" height="40" rx="2" fill="${PINK}"/>
        <rect x="17" y="36" width="8" height="28" rx="2" fill="${YELLOW}"/><rect x="75" y="36" width="8" height="28" rx="2" fill="${YELLOW}"/>
      </g>`,
  },
  {
    name: "Baum",
    svg: `<defs>${lin([NIGHT, "#7a0b6e", PINK], 0, 1)}</defs>${bg}
      ${sun(60, 60, 22)}
      <rect y="72" width="100" height="28" fill="#12052a"/>
      <g stroke="${CYAN}" stroke-width="1.4" stroke-linecap="round" opacity=".6"><path d="M48 77h24M52 83h16M56 89h8"/></g>
      <g fill="#0d0221">
        <path d="M30 98q-4-36 10-66" fill="none" stroke="#0d0221" stroke-width="4" stroke-linecap="round"/>
        <path d="M40 32q-14-6-26 4q12-4 26-4z"/><path d="M40 32q-6-14-20-14q12 4 20 14z"/>
        <path d="M40 32q10-14 26-10q-16 2-26 10z"/><path d="M40 32q16-2 24 12q-10-8-24-12z"/>
        <path d="M40 32q-12 4-18 18q4-12 18-18z"/>
      </g>`,
  },
  {
    name: "Cocktail",
    svg: `<defs>${lin(["#0d0221", "#3b0a5e"])}${glow(1.4)}</defs>${bg}
      <path d="M28 30h44L50 52z" fill="${CYAN}" opacity=".85"/>
      <g fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" filter="url(#ID-f)">
        <path d="M22 24h56L50 58zM50 58v22M36 82h28" stroke="${PINK}"/><path d="M68 14 56 38" stroke="${YELLOW}"/>
      </g>
      <circle cx="58" cy="34" r="5" fill="${MAGENTA}"/>`,
  },
  {
    name: "Party",
    svg: `<defs>${lin([NIGHT, "#4a0e6e"])}<clipPath id="ID-c"><path d="M30 82 50 22l20 60z"/></clipPath></defs>${bg}
      ${squiggle(10, 22, MINT, 2)}${squiggle(70, 78, YELLOW, 2)}
      <path d="M78 26l7 12h-14z" fill="${PINK}"/><path d="M14 62l6 10h-12z" fill="none" stroke="${CYAN}" stroke-width="2" stroke-linejoin="round"/>
      <g fill="${YELLOW}"><circle cx="76" cy="58" r="2"/><circle cx="22" cy="42" r="2" fill="${MAGENTA}"/></g>
      <path d="M30 82 50 22l20 60z" fill="${CYAN}"/>
      <g clip-path="url(#ID-c)" stroke="${PINK}" stroke-width="6"><path d="M20 72 80 52M20 54 80 34M20 90 80 70"/></g>
      <ellipse cx="50" cy="82" rx="21" ry="4" fill="${YELLOW}"/>
      <circle cx="50" cy="21" r="6" fill="${PINK}"/>`,
  },
  {
    name: "Sommer",
    svg: `<defs>${lin(["#7a04eb", PINK], 0, 1)}</defs>${bg}
      <g stroke="${YELLOW}" stroke-width="4" stroke-linecap="round">${Array.from(
        { length: 12 },
        (_, i) => `<path d="M50 24V14" transform="rotate(${i * 30} 50 50)"/>`,
      ).join("")}</g>
      ${sun(50, 50, 20)}`,
  },
  {
    name: "Herbst",
    svg: `<defs>${lin([NIGHT, "#3b0a5e"])}${glow(1.2)}</defs>${bg}
      <g filter="url(#ID-f)">${[
        [34, 36, -30, ORANGE, 1.1],
        [66, 44, 35, PINK, 1],
        [44, 70, 80, YELLOW, 0.9],
        [76, 76, -50, MAGENTA, 0.6],
      ]
        .map(
          ([x, y, r, c, s]) =>
            `<g transform="translate(${x} ${y}) rotate(${r}) scale(${s})"><path d="M0-18C12-10 12 10 0 18C-12 10-12-10 0-18z" fill="${c}"/><path d="M0-14V24" stroke="${NIGHT}" stroke-width="1.5" opacity=".5"/></g>`,
        )
        .join("")}</g>`,
  },
  {
    name: "Winter",
    svg: `<defs>${lin(["#0d0221", "#1b0f4a"], 0, 1)}${glow(1.5)}</defs>${bg}
      <g fill="${MAGENTA}" opacity=".7"><circle cx="16" cy="18" r="2"/><circle cx="84" cy="24" r="1.5"/><circle cx="20" cy="80" r="1.5"/><circle cx="82" cy="82" r="2"/></g>
      <g fill="none" stroke="${CYAN}" stroke-width="3" stroke-linecap="round" filter="url(#ID-f)">${Array.from(
        { length: 6 },
        (_, i) => `<path d="M50 50V20M50 30l-7-7M50 30l7-7M50 40l-5-5M50 40l5-5" transform="rotate(${i * 60} 50 50)"/>`,
      ).join("")}</g>`,
  },
  {
    name: "Frühling",
    svg: `<defs>${lin([NIGHT, "#2d0b4e"], 0, 1)}${glow(1.3)}</defs>${bg}
      <g filter="url(#ID-f)">
        <path d="M50 50q-3 20 0 38" fill="none" stroke="${MINT}" stroke-width="3" stroke-linecap="round"/>
        <ellipse cx="60" cy="72" rx="10" ry="4.5" fill="${MINT}" transform="rotate(-30 60 72)"/>
        <g fill="${MAGENTA}">${Array.from(
          { length: 6 },
          (_, i) => `<ellipse cx="50" cy="26" rx="7" ry="11" transform="rotate(${i * 60} 50 38)"/>`,
        ).join("")}</g>
        <circle cx="50" cy="38" r="7" fill="${YELLOW}"/>
      </g>`,
  },
  {
    name: "Lesen",
    svg: `<defs>${lin([YELLOW, ORANGE])}</defs>${bg}
      ${squiggle(10, 16, NIGHT)}${squiggle(66, 90, NIGHT)}
      <path d="M78 8l9 15H69z" fill="none" stroke="${CYAN}" stroke-width="2.5" stroke-linejoin="round"/>
      <g fill="${PURPLE}"><circle cx="14" cy="88" r="2"/><circle cx="88" cy="40" r="1.8"/></g>
      <g stroke="${NIGHT}" stroke-width="2.5" stroke-linejoin="round">
        <path d="M12 36v42c14-4 28-3 38 4 10-7 24-8 38-4V36z" fill="${PINK}"/>
        <path d="M50 32c-10-6-24-6-34-2v42c10-4 24-4 34 2zM50 32c10-6 24-6 34-2v42c-10-4-24-4-34 2z" fill="#fff"/>
      </g>
      <g fill="none" stroke="${NIGHT}" stroke-width="1.6" stroke-linecap="round" opacity=".35">
        <path d="M22 40q10-3 22 0M22 48q10-3 22 0M22 56q10-3 22 0M22 64q10-3 16 0"/>
        <path d="M56 40q12-3 22 0M56 48q12-3 22 0M56 56q12-3 22 0M56 64q12-3 16 0"/>
      </g>`,
  },
];

let instances = 0;

/** SVG markup of preset `n` (1-based) with ids unique to this call; null for unknown numbers. */
export function presetSvg(n: number): string | null {
  const preset = COVER_PRESETS[n - 1];
  if (!preset) return null;
  const id = `cp${n}-${++instances}`;
  return preset.svg.replace(/ID-/g, `${id}-`);
}
