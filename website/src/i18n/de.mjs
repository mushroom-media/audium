// Deutsche Texte der Landingpage. Schlüssel gleich halten mit en.mjs.
export default {
  meta: {
    title: "audium – Musik-Streaming auf dem eigenen Server",
    description:
      "audium streamt deine eigene MP3- und FLAC-Sammlung aus einem Docker-Container: Web-Player, Subsonic-Apps, gebaut für 100.000+ Titel. Open Source, keine Telemetrie.",
  },
  nav: {
    skip: "Zum Inhalt springen",
    label: "Hauptmenü",
    features: "Funktionen",
    apps: "Apps",
    install: "Installation",
    docs: "Doku",
    star: "Auf GitHub",
    start: "Loslegen",
  },
  hero: {
    badge: "Musik-Streaming auf dem eigenen Server · Open Source",
    title: 'Deine Musik.<br>Dein Server.<br><span class="accent">Jeder Ton.</span>',
    lead: "audium streamt deine eigene MP3- und FLAC-Sammlung aus einem einzigen Docker-Container: ein schöner Web-Player im Browser, Subsonic-Apps auf dem Handy, gebaut für Bibliotheken mit 100.000+ Titeln.",
    install: "In 5 Minuten installiert",
    github: "Auf GitHub ansehen",
    facts: ["AGPL-3.0", "Keine Telemetrie", "Läuft offline", "x86_64 &amp; arm64"],
    playerLabel: "Der audium-Player spielt einen FLAC-Titel",
    track: "Titel",
    artist: "Künstler · Album",
  },
  stats: {
    label: "Auf einen Blick",
    items: [
      { v: "100.000+", l: "Titel, und trotzdem schnell" },
      { v: "1", l: "Docker-Container" },
      { v: "0", l: "Bytes nach Hause gefunkt" },
      { v: "2", l: "Architekturen: x86_64 &amp; arm64" },
    ],
  },
  why: {
    kicker: "WARUM AUDIUM",
    title: "Ein Plattenladen auf deinem eigenen Server.",
    cards: [
      {
        title: "Deine Dateien bleiben unberührt",
        text: "Die Musik wird nur lesend eingebunden. Alles, was audium anlegt, liegt in einem data-Ordner, leicht zu sichern.",
      },
      {
        title: "Privat von Anfang an",
        text: "Keine Telemetrie, kein Konto bei irgendwem. Läuft komplett in deinem Netz, auch ohne Internet.",
      },
      {
        title: "Gebaut für riesige Sammlungen",
        text: "Stöbern und hören, während der erste Scan noch läuft. 100.000 Dateien dauern Minuten, nicht Stunden.",
      },
    ],
  },
  tracks: {
    kicker: "DIE TRACKLIST",
    title: "Alles, was du erwartest. Nichts, was du nicht willst.",
    lead: "Ein Container, eine Oberfläche auf Deutsch und Englisch und die Funktionen, die eine große Sammlung wieder spannend machen.",
    nowPlaying: "Läuft gerade",
    items: [
      { title: "Web-Player &amp; PWA", text: "Im Browser hören oder als App auf dem Handy-Startbildschirm installieren.", len: "web" },
      { title: "Smarte &amp; automatische Playlists", text: "Playlists nach Regeln, die sich selbst aktuell halten.", len: "mix" },
      { title: "Radio &amp; Stimmungs-Mixe", text: "Die Audioanalyse erkennt Tempo und Stimmung für endlose Mixe (x86_64).", len: "auto" },
      { title: "Mit anderen teilen", text: "Mehrere Benutzer, Einladungslinks, geteilte Playlists, jeder in seiner Sprache.", len: "multi" },
      { title: "Ähnliche Künstler", text: "Optional über ListenBrainz, aus, bis du es einschaltest.", len: "opt-in" },
      { title: "Mehrere Musikordner", text: "Lokale Platten und Netzlaufwerke nebeneinander, alle nur lesend.", len: "ro" },
    ],
  },
  apps: {
    kicker: "FUNKTIONIERT MIT DEINEN APPS",
    title: "Nimm deinen Lieblings-Player mit.",
    lead: "audium spricht die (Open)Subsonic-API. Unter Einstellungen › Apps verbinden bekommst du ein einmaliges App-Passwort, und schon läuft die Musik. Dazu Desktop-Apps für Windows, macOS und Linux.",
    more: "So verbindest du eine App →",
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
    kicker: "INSTALLATION",
    title: "Läuft, bevor die erste Plattenseite zu Ende ist.",
    points: ["Synology, Unraid, TrueNAS, Portainer", "Raspberry Pi und Mini-PCs (arm64)", "Updates mit einem Befehl"],
    guide: "Zur vollständigen Anleitung →",
    copy: "Kopieren",
    copied: "Kopiert",
    step1: "zwei Dateien holen",
    step2: "Musikordner eintragen (.env)",
    step3: "Play drücken",
    done: "audium läuft auf",
  },
  cta: {
    title: "Drück Play auf deiner<br>eigenen Sammlung.",
    text: "Es verändert nie deine Musik. Es funkt nie nach Hause. Kostenlos und Open Source, kein Konto nötig.",
    start: "Loslegen",
    star: "Auf GitHub ansehen",
  },
  footer: {
    label: "Fußzeile",
    tagline: "Keine Cookies. Kein Tracking. Nur Musik.",
    license: "Lizenz",
  },
};
