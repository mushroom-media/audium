// The round initial that stands for a user. Its background is the accent color unless the user
// picked one of these (the server knows the names only, see users.AVATAR_COLORS).

export const AVATAR_COLORS: Record<string, [string, string]> = {
  red: ["#e5484d", "#a3243a"],
  orange: ["#f76b15", "#b2410e"],
  amber: ["#e8a317", "#a8640a"],
  green: ["#30a46c", "#17683f"],
  teal: ["#12a594", "#0a6461"],
  blue: ["#3e7bfa", "#2343ad"],
  indigo: ["#5b5bd6", "#35289b"],
  violet: ["#8e4ec6", "#56258e"],
  pink: ["#d6409f", "#94206b"],
  slate: ["#6f7a89", "#394150"],
};

/** Inline style for an avatar, or undefined to keep the page's accent look. */
export function avatarStyle(color: string | null | undefined): string | undefined {
  const c = color ? AVATAR_COLORS[color] : undefined;
  return c ? `background: linear-gradient(135deg, ${c[0]}, ${c[1]}); color: #fff` : undefined;
}

export const avatarInitial = (name: string | null | undefined) => (name ?? "").trim().charAt(0).toUpperCase() || "?";
