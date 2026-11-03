// A page's title shown centered in the top bar once the page's own heading has scrolled away.

/** What the top bar shows; `shown` fades it in and out. */
export const headerTitle = $state({ text: "", shown: false });

/** The page whose heading is watched; an old page leaving must not clear a new page's title. */
let owner: object | null = null;

/** `use:pageTitle={album.title}` on a page's heading: the top bar shows `text` while that
 * heading is scrolled out of view above. */
export function pageTitle(node: HTMLElement, text: string) {
  const me = {};
  owner = me;
  headerTitle.text = text;
  headerTitle.shown = false;
  // Gone once it slides under the top bar (phones lay the bar over the page, see App.svelte).
  const top = getComputedStyle(document.documentElement).getPropertyValue("--top-h").trim() || "0px";
  const io = new IntersectionObserver(
    ([e]) => {
      // Only above: a heading not yet reached (below the fold) does not count as gone.
      if (owner === me) headerTitle.shown = !e.isIntersecting && e.boundingClientRect.bottom < window.innerHeight / 2;
    },
    { rootMargin: `-${top} 0px 0px 0px` },
  );
  io.observe(node);
  return {
    update(next: string) {
      if (owner === me) headerTitle.text = next;
    },
    destroy() {
      io.disconnect();
      if (owner !== me) return;
      owner = null;
      headerTitle.text = "";
      headerTitle.shown = false;
    },
  };
}
