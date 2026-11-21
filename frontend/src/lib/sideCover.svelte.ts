// Desktop: the cover of the playing track shown large at the bottom of the sidebar. Switched on
// and off from the cover in the player bar or the large cover itself; remembered per browser.

const KEY = "audium.sideCover";

function stored(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export const sideCover = $state({ open: stored() });

export function toggleSideCover() {
  sideCover.open = !sideCover.open;
  try {
    localStorage.setItem(KEY, sideCover.open ? "1" : "0");
  } catch {
    /* private mode */
  }
}
