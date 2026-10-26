<script lang="ts" module>
  // 24x24 icons, drawn for this app (no icon font, nothing loaded at runtime).
  const PATHS = {
    play: "M8 5.5v13a1 1 0 0 0 1.5.86l11-6.5a1 1 0 0 0 0-1.72l-11-6.5A1 1 0 0 0 8 5.5Z",
    pause: "M7 5h3.5v14H7zM13.5 5H17v14h-3.5z",
    next: "M6 6.2v11.6a.8.8 0 0 0 1.2.7l9-5.8a.8.8 0 0 0 0-1.4l-9-5.8a.8.8 0 0 0-1.2.7ZM17.5 6h2v12h-2z",
    prev: "M18 6.2v11.6a.8.8 0 0 1-1.2.7l-9-5.8a.8.8 0 0 1 0-1.4l9-5.8a.8.8 0 0 1 1.2.7ZM4.5 6h2v12h-2z",
    shuffle: "M4 7h3.5c2.2 0 3.3 1.3 4.5 3.5l1 2c1.2 2.2 2.3 3.5 4.5 3.5H20M17 13l3 3-3 3M4 17h3.5c1.2 0 2-.4 2.7-1.1M17 5l3 3-3 3M20 8h-2.5c-1.2 0-2 .4-2.7 1.1",
    repeat: "M5 11V9a3 3 0 0 1 3-3h11M16 3l3 3-3 3M19 13v2a3 3 0 0 1-3 3H5M8 21l-3-3 3-3",
    volume: "M4 9.5h3l4.5-4v13L7 14.5H4zM15 9a4 4 0 0 1 0 6M17.5 6.5a7.5 7.5 0 0 1 0 11",
    mute: "M4 9.5h3l4.5-4v13L7 14.5H4zM16 9.5l5 5M21 9.5l-5 5",
    queue: "M4 6h13M4 11h13M4 16h8M16 15.5v-5l4.5 2.5z",
    search: "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM15.5 15.5 20 20",
    home: "M4 11 12 4l8 7M6.5 9.5V20h4v-5.5h3V20h4V9.5",
    album: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z",
    artist: "M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM4.5 20a7.5 7.5 0 0 1 15 0",
    track: "M9 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0ZM9 18V5l11-2v12M20 15a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z",
    settings: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM19.4 13.5l1.6 1.2-2 3.4-1.9-.7a7 7 0 0 1-2 1.2L14.8 21h-4l-.3-2.4a7 7 0 0 1-2-1.2l-1.9.7-2-3.4 1.6-1.2a7 7 0 0 1 0-2.4L4.6 9.9l2-3.4 1.9.7a7 7 0 0 1 2-1.2L10.8 3h4l.3 2.4a7 7 0 0 1 2 1.2l1.9-.7 2 3.4-1.6 1.2a7 7 0 0 1 0 2.4Z",
    close: "M6 6l12 12M18 6 6 18",
    plus: "M12 5v14M5 12h14",
    more: "M6 12h.01M12 12h.01M18 12h.01",
    back: "M15 5l-7 7 7 7",
    heart: "M12 20s-7.5-4.6-9.2-9.3C1.6 7.4 3.7 4.5 6.9 4.5c2 0 3.5 1.1 4.3 2.5h1.6c.8-1.4 2.3-2.5 4.3-2.5 3.2 0 5.3 2.9 4.1 6.2C19.5 15.4 12 20 12 20Z",
    share: "M8 12h8M14 8l4 4-4 4M6 5H5a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h1",
    edit: "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4",
    trash: "M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13",
    drag: "M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01",
    list: "M5 6h14M5 12h14M5 18h9",
    grid: "M4.5 4.5h6v6h-6zM13.5 4.5h6v6h-6zM4.5 13.5h6v6h-6zM13.5 13.5h6v6h-6z",
    spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z",
    radio: "M4 9h16v11H4zM8 9l9-5M8 14.5a2 2 0 1 0 0 .01M14 13h3M14 16h3",
    compass: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM15.5 8.5l-2 5-5 2 2-5z",
    expand: "M14 4h6v6M20 4l-6.5 6.5M10 20H4v-6M4 20l6.5-6.5",
    down: "M6 9l6 6 6-6",
    image: "M4 5h16v14H4zM4 16l5-5 4 4 2.5-2.5L20 17M15.5 8.5h.01",
    upload: "M12 15V4M7.5 8.5 12 4l4.5 4.5M5 15v4h14v-4",
    tag: "M4 4h7.5l8.5 8.5-7.5 7.5L4 11.5zM8.5 8.5h.01",
    wave: "M3 12h1.5M7 9v6M10.5 5v14M14 8v8M17.5 10.5v3M21 12h-1",
    user: "M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM4.5 20a7.5 7.5 0 0 1 15 0",
    folder: "M3.5 6.5a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1z",
    users: "M9 5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7ZM2.5 19.5a6.5 6.5 0 0 1 13 0M16 5.3a3.5 3.5 0 0 1 0 6.4M18.5 13.5a6.5 6.5 0 0 1 3 6",
    jobs: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17ZM12 7.5V12l3 2",
    keyboard: "M3 6.5h18v11H3zM6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M8 14h8",
    palette: "M12 3.5a8.5 8.5 0 0 0 0 17c1.2 0 1.8-.8 1.8-1.7 0-1.3-1-1.5-1-2.6 0-.9.7-1.6 1.6-1.6h2.1a4 4 0 0 0 4-4C20.5 6.6 16.7 3.5 12 3.5ZM7.5 11.5h.01M9.5 7.5h.01M14.5 7.5h.01",
    logout: "M14 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 16l-4-4 4-4M6 12h10",
    chevron: "M9 5l7 7-7 7",
    phone: "M7.5 3h9a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1ZM11 18h2",
    desktop: "M3.5 5h17v11h-17zM9 20h6M12 16v4",
    devices: "M2.5 5h12v8.5h-12zM5.5 17.5h6M8.5 13.5v4M16.5 8.5h4.5v11h-4.5zM18.75 17h.01",
  } as const;
  export type IconName = keyof typeof PATHS;
</script>

<script lang="ts">
  let { name, size = 20, filled = false }: { name: IconName; size?: number; filled?: boolean } = $props();
  const solid = $derived(filled || name === "play" || name === "pause" || name === "next" || name === "prev");
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  aria-hidden="true"
  fill={solid ? "currentColor" : "none"}
  stroke={solid ? "none" : "currentColor"}
  stroke-width="1.7"
  stroke-linecap="round"
  stroke-linejoin="round"
>
  <path d={PATHS[name]} />
</svg>
