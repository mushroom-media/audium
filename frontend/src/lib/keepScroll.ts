// Scroll position of a page or a sideways row (VirtualList has its own): back on it, it scrolls to
// where it was as soon as the content is long enough, unless the user started scrolling first.

import { recallScroll, rememberScroll } from "./router.svelte";

export function keepScroll(node: HTMLElement, id = "page") {
  const leftId = `${id}:left`;
  let top = recallScroll(id);
  let left = recallScroll(leftId);

  function restore() {
    if (top && node.scrollHeight - node.clientHeight >= top) {
      node.scrollTop = top;
      top = 0;
    }
    if (left && node.scrollWidth - node.clientWidth >= left) {
      node.scrollLeft = left;
      left = 0;
    }
    if (!top && !left) watcher.disconnect();
  }
  function cancel() {
    top = left = 0;
    watcher.disconnect();
  }
  function onScroll() {
    rememberScroll(id, node.scrollTop);
    rememberScroll(leftId, node.scrollLeft);
  }

  const watcher = new MutationObserver(restore);
  if (top || left) {
    watcher.observe(node, { childList: true, subtree: true });
    restore();
  }
  node.addEventListener("scroll", onScroll, { passive: true });
  node.addEventListener("pointerdown", cancel, { passive: true });
  node.addEventListener("wheel", cancel, { passive: true });
  return {
    destroy() {
      watcher.disconnect();
      node.removeEventListener("scroll", onScroll);
      node.removeEventListener("pointerdown", cancel);
      node.removeEventListener("wheel", cancel);
    },
  };
}
