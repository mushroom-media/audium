// Back and forward by swiping, in the desktop app. Browsers do this themselves, but the WebView of
// the app (Tauri turns WebView2's swipe navigation off) does not, so the app does it here:
// - touch screen: a swipe that starts at the left or right edge of the window,
// - touchpad: two fingers sideways, where nothing under them scrolls sideways.
// While the swipe goes on, SwipeHint.svelte shows an arrow at the edge. Touch goes back or forward
// when the finger lets go with the arrow full; the touchpad as soon as the arrow is full (its
// events do not say when the fingers lift).
import { router } from "./router.svelte";

export const swipe = $state({ dir: null as "back" | "forward" | null, progress: 0 });

const EDGE_PX = 28; // touch: where a swipe has to start
const TOUCH_PX = 110; // touch: how far until it counts
const WHEEL_PX = 160; // touchpad: how much sideways scrolling until it counts
const WHEEL_END_MS = 160; // touchpad: no more events this long = fingers off

type Nav = { canGoForward?: boolean };
const canGo = (dir: "back" | "forward") =>
  dir === "back" ? router.depth > 0 : ((window as unknown as { navigation?: Nav }).navigation?.canGoForward ?? true);

function show(dir: "back" | "forward" | null, amount: number, full: number) {
  if (!dir || !canGo(dir)) {
    swipe.dir = null;
    swipe.progress = 0;
    return;
  }
  swipe.dir = dir;
  swipe.progress = Math.min(1, Math.max(0, amount / full));
}

function finish() {
  const go = swipe.progress >= 1 ? swipe.dir : null;
  swipe.dir = null;
  swipe.progress = 0;
  if (go === "back") history.back();
  else if (go === "forward") history.forward();
}

// --- touch screen ------------------------------------------------------------------------------

let touch: { x: number; y: number; from: "left" | "right" } | null = null;

function touchStart(e: TouchEvent) {
  touch = null;
  if (e.touches.length !== 1) return;
  const { clientX: x, clientY: y } = e.touches[0];
  if (x <= EDGE_PX) touch = { x, y, from: "left" };
  else if (x >= window.innerWidth - EDGE_PX) touch = { x, y, from: "right" };
}

function touchMove(e: TouchEvent) {
  if (!touch || e.touches.length !== 1) return;
  const dx = e.touches[0].clientX - touch.x;
  const dy = e.touches[0].clientY - touch.y;
  // Mostly up and down: that is scrolling, not a swipe.
  if (Math.abs(dy) > 30 && Math.abs(dy) > Math.abs(dx)) {
    touch = null;
    show(null, 0, 1);
    return;
  }
  if (touch.from === "left") show("back", dx, TOUCH_PX);
  else show("forward", -dx, TOUCH_PX);
}

function touchEnd() {
  if (!touch) return;
  touch = null;
  finish();
}

function touchCancel() {
  touch = null;
  show(null, 0, 1);
}

// --- touchpad ----------------------------------------------------------------------------------

let wheelSum = 0;
let wheelTimer: ReturnType<typeof setTimeout> | undefined;
let wheelDone = false; // one step per gesture, also when it scrolls on after the step

/** Something under the pointer can still scroll that way: the swipe is meant for it. */
function scrollsSideways(target: EventTarget | null, dx: number): boolean {
  for (let el = target instanceof Element ? target : null; el; el = el.parentElement) {
    if (el.scrollWidth <= el.clientWidth) continue;
    const overflow = getComputedStyle(el).overflowX;
    if (overflow !== "auto" && overflow !== "scroll") continue;
    if (dx < 0 ? el.scrollLeft > 0 : el.scrollLeft + el.clientWidth < el.scrollWidth - 1) return true;
  }
  return false;
}

function wheel(e: WheelEvent) {
  clearTimeout(wheelTimer);
  wheelTimer = setTimeout(() => {
    wheelDone = false;
    if (wheelSum !== 0) {
      wheelSum = 0;
      finish();
    }
  }, WHEEL_END_MS);
  if (wheelDone || e.ctrlKey || e.shiftKey || e.deltaMode !== 0) return;
  // Mostly up and down, or meant for a row that scrolls sideways.
  if (Math.abs(e.deltaX) <= Math.abs(e.deltaY) * 1.5 || (wheelSum === 0 && scrollsSideways(e.target, e.deltaX))) return;
  wheelSum += e.deltaX;
  // Fingers to the right (scrolling to the left) = back, as in the browsers.
  show(wheelSum < 0 ? "back" : "forward", Math.abs(wheelSum), WHEEL_PX);
  if (swipe.progress >= 1) {
    wheelDone = true;
    wheelSum = 0;
    finish();
  }
}

export function startSwipeNav() {
  window.addEventListener("touchstart", touchStart, { passive: true });
  window.addEventListener("touchmove", touchMove, { passive: true });
  window.addEventListener("touchend", touchEnd, { passive: true });
  window.addEventListener("touchcancel", touchCancel, { passive: true });
  window.addEventListener("wheel", wheel, { passive: true });
}
