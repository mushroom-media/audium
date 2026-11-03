// Sideways swipes on touch screens. Scrolling stays with the browser: the element needs
// `touch-action: pan-y`, then a vertical move ends up as a pointercancel here.

const AXIS_LOCK_PX = 10;
const CLICK_AFTER_SWIPE_MS = 400;

export interface SwipeHandlers {
  enabled?: () => boolean;
  onmove: (dx: number) => void;
  /** `velocity` in px/ms; `cancelled`: the browser took over, nothing should happen. */
  onend: (dx: number, velocity: number, cancelled: boolean) => void;
}

/** Where nothing can happen, the content gives a little and less the further it is pulled. */
export function resist(dx: number, width: number, share = 0.3): number {
  return Math.sign(dx) * width * share * (1 - Math.exp(-Math.abs(dx) / width));
}

export function swipe(node: HTMLElement, initial: SwipeHandlers) {
  let handlers = initial;
  let g: { id: number; x: number; y: number; locked: boolean; samples: { x: number; t: number }[] } | null = null;

  function down(e: PointerEvent) {
    if (e.pointerType !== "touch" || !e.isPrimary || handlers.enabled?.() === false) return;
    g = { id: e.pointerId, x: e.clientX, y: e.clientY, locked: false, samples: [] };
  }

  function move(e: PointerEvent) {
    if (!g || e.pointerId !== g.id) return;
    const dx = e.clientX - g.x;
    if (!g.locked) {
      const dy = e.clientY - g.y;
      if (Math.hypot(dx, dy) < AXIS_LOCK_PX) return;
      if (Math.abs(dx) <= Math.abs(dy)) {
        g = null;
        return;
      }
      g.locked = true;
      // Start from here, so the content does not jump by the distance it took to tell the direction.
      g.x = e.clientX;
      try {
        node.setPointerCapture(e.pointerId);
      } catch {
        /* the pointer is gone already */
      }
    }
    g.samples.push({ x: e.clientX, t: e.timeStamp });
    while (g.samples.length > 2 && e.timeStamp - g.samples[0].t > 100) g.samples.shift();
    handlers.onmove(e.clientX - g.x);
  }

  function end(e: PointerEvent) {
    if (!g || e.pointerId !== g.id) return;
    const { locked, x, samples } = g;
    g = null;
    if (!locked) return;
    const first = samples[0];
    const last = samples[samples.length - 1];
    const velocity = last.t > first.t ? (last.x - first.x) / (last.t - first.t) : 0;
    swallowClick();
    handlers.onend(e.clientX - x, velocity, e.type === "pointercancel");
  }

  /** A swipe that ends on a link or button must not also press it. */
  function swallowClick() {
    const stop = (e: Event) => {
      e.preventDefault();
      e.stopPropagation();
    };
    node.addEventListener("click", stop, { capture: true, once: true });
    setTimeout(() => node.removeEventListener("click", stop, { capture: true }), CLICK_AFTER_SWIPE_MS);
  }

  node.addEventListener("pointerdown", down, { passive: true });
  node.addEventListener("pointermove", move, { passive: true });
  node.addEventListener("pointerup", end);
  node.addEventListener("pointercancel", end);
  return {
    update(next: SwipeHandlers) {
      handlers = next;
    },
    destroy() {
      node.removeEventListener("pointerdown", down);
      node.removeEventListener("pointermove", move);
      node.removeEventListener("pointerup", end);
      node.removeEventListener("pointercancel", end);
    },
  };
}
