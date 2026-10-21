// Random-access view of a server-side list for virtual scrolling.
//
// Only the pages around what is visible are fetched (by offset, so dragging the scrollbar to
// the middle of 100k tracks costs one request) and at most MAX_PAGES are kept in memory.

import type { Page } from "./api";

const MAX_PAGES = 40;

export type Fetcher<T> = (offset: number, limit: number, signal: AbortSignal) => Promise<Page<T>>;

export class PagedList<T> {
  total = $state<number | null>(null);
  error = $state<string | null>(null);
  /** Bumped whenever a page arrives; reading it makes callers reactive. */
  version = $state(0);

  #pages = new Map<number, T[]>();
  #loading = new Map<number, AbortController>();
  #lastPage = 0;
  #fetch: Fetcher<T>;
  readonly pageSize: number;

  constructor(fetch: Fetcher<T>, pageSize = 100) {
    this.#fetch = fetch;
    this.pageSize = pageSize;
    this.#load(0);
  }

  get(index: number): T | undefined {
    void this.version;
    return this.#pages.get(Math.floor(index / this.pageSize))?.[index % this.pageSize];
  }

  /** Make sure the items [start, end) are (being) loaded. */
  ensure(start: number, end: number) {
    const first = Math.floor(start / this.pageSize);
    const last = Math.floor(Math.max(start, end - 1) / this.pageSize);
    this.#lastPage = first;
    for (let p = first; p <= last; p++) this.#load(p);
    // Requests for pages that scrolled far out of view are pointless; cancel them.
    for (const [p, ctrl] of this.#loading) if (p < first - 2 || p > last + 2) ctrl.abort();
  }

  /** Items [start, start+count), loading what is missing (e.g. "play from here"). */
  async slice(start: number, count: number): Promise<T[]> {
    const out: T[] = [];
    const total = this.total ?? start + count;
    const end = Math.min(total, start + count);
    for (let i = start; i < end; i += this.pageSize) {
      const page = Math.floor(i / this.pageSize);
      let items = this.#pages.get(page);
      if (!items) {
        const res = await this.#fetch(page * this.pageSize, this.pageSize, new AbortController().signal);
        items = res.items;
      }
      out.push(...items.slice(i % this.pageSize));
    }
    return out.slice(0, end - start);
  }

  #load(page: number) {
    if (this.#pages.has(page) || this.#loading.has(page)) return;
    if (this.total !== null && page * this.pageSize >= this.total) return;
    const ctrl = new AbortController();
    this.#loading.set(page, ctrl);
    this.#fetch(page * this.pageSize, this.pageSize, ctrl.signal)
      .then((res) => {
        this.#pages.set(page, res.items);
        if (res.total !== null) this.total = res.total;
        else if (page === 0) this.total = res.items.length;
        this.#evict();
        this.version++;
      })
      .catch((e) => {
        if (e?.name !== "AbortError") this.error = String(e?.message ?? e);
      })
      .finally(() => this.#loading.delete(page));
  }

  #evict() {
    if (this.#pages.size <= MAX_PAGES) return;
    const far = [...this.#pages.keys()].sort((a, b) => Math.abs(b - this.#lastPage) - Math.abs(a - this.#lastPage));
    for (const p of far.slice(0, this.#pages.size - MAX_PAGES)) this.#pages.delete(p);
  }
}
