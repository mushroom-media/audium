<script lang="ts">
  // A radio station's cover: the main colour of the cover it started from, that cover in a circle
  // in the middle, what it is the radio of top right, "Radio" bottom left and the radio sign
  // bottom right. Sizes follow the cover's width, so it reads the same as a card and as a hero;
  // as a small thumbnail only colour and circle are left.
  import { coverColor, nameColor } from "../coverColor";
  import { t } from "../i18n.svelte";
  import Cover from "./Cover.svelte";
  import Icon from "./Icon.svelte";

  let { hash, name, alt = "" }: { hash: string | null | undefined; name: string; alt?: string } = $props();

  let color = $state<string | null>(null);
  $effect(() => {
    const h = hash;
    color = null;
    if (!h) return;
    let current = true;
    coverColor(h).then((c) => current && (color = c));
    return () => {
      current = false;
    };
  });
  const bg = $derived(color ?? nameColor(name));
</script>

<div class="radio-cover" style:--bg={bg} role={alt ? "img" : undefined} aria-label={alt || undefined}>
  <span class="name">{name}</span>
  <span class="disc"><Cover {hash} size={256} round /></span>
  <span class="label">{t("Radio")}</span>
  <span class="sign" aria-hidden="true"><Icon name="radio" size={24} /></span>
</div>

<style>
  .radio-cover {
    position: relative;
    width: 100%;
    aspect-ratio: 1;
    border-radius: var(--radius-sm);
    overflow: hidden;
    container-type: inline-size;
    color: #fff;
    background:
      radial-gradient(circle at 50% 50%, rgb(255 255 255 / 0.14), transparent 62%),
      linear-gradient(160deg, transparent 30%, rgb(0 0 0 / 0.35)),
      var(--bg);
    transition: background-color 0.3s ease;
  }
  .disc {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 56%;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    box-shadow:
      0 0 0 1.5cqw rgb(255 255 255 / 0.18),
      0 3cqw 8cqw rgb(0 0 0 / 0.35);
  }
  .name,
  .label {
    position: absolute;
    font-weight: 700;
    line-height: 1.15;
    text-shadow: 0 1px 4px rgb(0 0 0 / 0.3);
  }
  .name {
    top: 6cqw;
    right: 7cqw;
    left: 30%;
    text-align: right;
    font-size: 7.5cqw;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    overflow-wrap: anywhere;
  }
  .label {
    left: 7cqw;
    bottom: 5.5cqw;
    font-size: 9cqw;
    letter-spacing: -0.01em;
  }
  .sign {
    position: absolute;
    right: 7cqw;
    bottom: 6cqw;
    display: grid;
  }
  .sign :global(svg) {
    width: 11cqw;
    height: 11cqw;
  }
  /* Thumbnails (phone rows): text this small cannot be read. */
  @container (max-width: 100px) {
    .name,
    .label,
    .sign {
      display: none;
    }
    .disc {
      width: 64%;
    }
  }
</style>
