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
