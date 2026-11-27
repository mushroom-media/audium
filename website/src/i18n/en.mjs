// English texts of the landing page. Keep the keys in step with de.mjs.
export default {
  meta: {
    title: "audium – self-hosted music streaming for your own collection",
    description:
      "audium streams your own MP3 and FLAC collection from one Docker container: web player, Subsonic apps, built for 100,000+ tracks. Open source, no telemetry.",
  },
  nav: {
    skip: "Skip to content",
    label: "Main",
    features: "Features",
    apps: "Apps",
    install: "Install",
    docs: "Docs",
    star: "Star on GitHub",
    start: "Get started",
  },
  hero: {
    badge: "Self-hosted music streaming · open source",
    title: 'Your music.<br>Your server.<br><span class="accent">Every note.</span>',
    lead: "audium streams your own MP3 and FLAC collection from a single Docker container: a beautiful web player in the browser, Subsonic apps on your phone, built for libraries of 100,000+ tracks.",
    install: "Install in 5 minutes",
    github: "View on GitHub",
    facts: ["AGPL-3.0", "No telemetry", "Works offline", "x86_64 &amp; arm64"],
    playerLabel: "The audium player playing a FLAC track",
    track: "Track title",
    artist: "Artist · Album",
  },
  stats: {
    label: "At a glance",
    items: [
      { v: "100,000+", l: "tracks, and still fast" },
      { v: "1", l: "Docker container" },
      { v: "0", l: "bytes sent home" },
      { v: "2", l: "architectures: x86_64 &amp; arm64" },
    ],
  },
  why: {
    kicker: "WHY AUDIUM",
    title: "A record shop that lives on your own server.",
    cards: [
      {
        title: "Your files stay untouched",
        text: "Music is mounted read-only. Everything audium creates lives in one data folder, easy to back up.",
      },
      {
        title: "Private by design",
        text: "No telemetry, no account with anyone. It runs entirely on your network, even without internet.",
      },
      {
        title: "Made for huge libraries",
        text: "Browse and play while the first scan is still running. 100,000 files take minutes, not hours.",
      },
    ],
  },
  tracks: {
    kicker: "THE TRACKLIST",
    title: "Everything you'd expect. Nothing you didn't ask for.",
    lead: "One container, a web interface in English and German, and the features that make a big collection fun again.",
    nowPlaying: "Now playing",
    items: [
      { title: "Web player &amp; PWA", text: "Listen in any browser, install it on your phone’s home screen.", len: "web" },
      { title: "Smart &amp; auto playlists", text: "Rules-based playlists that keep themselves up to date.", len: "mix" },
      { title: "Radio &amp; mood mixes", text: "Audio analysis finds tempo and mood for endless mixes (x86_64).", len: "auto" },
      { title: "Share with your people", text: "Multiple users, invite links, shared playlists, each in their own language.", len: "multi" },
      { title: "Similar artists", text: "Optional ListenBrainz lookups, off until you switch them on.", len: "opt-in" },
      { title: "Several music folders", text: "Local disks and network shares side by side, all read-only.", len: "ro" },
    ],
  },
  apps: {
    kicker: "WORKS WITH YOUR APPS",
    title: "Bring your favorite player.",
    lead: "audium speaks the (Open)Subsonic API. Open Settings › Connect apps, get a one-time app password, and you're listening. Desktop apps for Windows, macOS and Linux too.",
    more: "How to connect an app →",
    items: [
      { name: "Symfonium", os: "Android" },
      { name: "Tempo", os: "Android" },
      { name: "DSub", os: "Android" },
      { name: "Ultrasonic", os: "Android" },
      { name: "Amperfy", os: "iOS" },
      { name: "play:Sub", os: "iOS" },
      { name: "Feishin", os: "Desktop" },
      { name: "Supersonic", os: "Desktop" },
    ],
  },
  install: {
    kicker: "INSTALL",
    title: "Up and running before the first side ends.",
    points: ["Synology, Unraid, TrueNAS, Portainer", "Raspberry Pi and mini PCs (arm64)", "Update with one command"],
    guide: "Full install guide →",
    copy: "Copy",
    copied: "Copied",
    step1: "grab two files",
    step2: "point it at your music (.env)",
    step3: "press play",
    done: "audium is listening on",
  },
  cta: {
    title: "Press play on your<br>own library.",
    text: "It never changes your music. It never phones home. Free and open source, no account needed.",
    start: "Get started",
    star: "Star on GitHub",
  },
  footer: {
    label: "Footer",
    tagline: "No cookies. No tracking. Just music.",
    license: "License",
  },
};
