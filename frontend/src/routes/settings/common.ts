import { locale } from "../../lib/i18n.svelte";

// Shared bits of the settings pages.

export interface Job {
  id: number;
  queue: string;
  type: string;
  status: string;
  progress: number;
  total: number;
  message: string | null;
  error: string | null;
  result: Record<string, number> | null;
  created_at: number;
  finished_at: number | null;
}

export const fmtDate = (ms: number | null) =>
  ms ? new Date(ms).toLocaleString(locale(), { dateStyle: "short", timeStyle: "short" }) : "–";

export const isBusy = (j: Job | null) => !!j && (j.status === "queued" || j.status === "running");
