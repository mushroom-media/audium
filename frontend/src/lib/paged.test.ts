import { describe, expect, it, vi } from "vitest";
import type { Page } from "./api";
import { keptList, PagedList } from "./paged.svelte";

const tick = () => new Promise((r) => setTimeout(r));

function server(items: string[]) {
  const data = { items };
  const fetch = vi.fn(async (offset: number, limit: number): Promise<Page<string>> => ({
    items: data.items.slice(offset, offset + limit),
    total: data.items.length,
    next_cursor: null,
  }));
  return { data, fetch };
}

describe("PagedList.refresh", () => {
  it("keeps showing the old items until the fresh ones arrive", async () => {
    const { data, fetch } = server(["a", "b"]);
    const list = new PagedList<string>(fetch, 2);
    await tick();
    data.items = ["x", "y"];
    list.refresh();
    expect(list.get(0)).toBe("a");
    await tick();
    expect(list.get(0)).toBe("x");
  });

  it("fetches the pages in view, the others when they come into view", async () => {
    const { data, fetch } = server(["a", "b", "c", "d", "e", "f"]);
    const list = new PagedList<string>(fetch, 2);
    await tick();
    list.ensure(2, 4);
    await tick();
    list.ensure(4, 6);
    await tick();
    data.items = ["1", "2", "3", "4", "5", "6"];
    fetch.mockClear();
    list.refresh();
    await tick();
    expect(fetch.mock.calls.map((c) => c[0])).toEqual([0, 4]);
    expect(list.get(2)).toBe("c");
    list.ensure(2, 4);
    await tick();
    expect(list.get(2)).toBe("3");
  });

  it("notices when an empty list got items", async () => {
    const { data, fetch } = server([]);
    const list = new PagedList<string>(fetch, 2);
    await tick();
    expect(list.total).toBe(0);
    data.items = ["a"];
    list.refresh();
    await tick();
    expect(list.total).toBe(1);
    expect(list.get(0)).toBe("a");
  });

  it("does not play stale pages", async () => {
    const { data, fetch } = server(["a", "b", "c", "d"]);
    const list = new PagedList<string>(fetch, 2);
    await tick();
    list.ensure(2, 4);
    await tick();
    list.ensure(0, 2);
    data.items = ["1", "2", "3", "4"];
    list.refresh();
    expect(await list.slice(2, 2)).toEqual(["3", "4"]);
  });
});

describe("keptList", () => {
  it("hands out the same list for the same id and refreshes it", async () => {
    const { data, fetch } = server(["a"]);
    const first = keptList<string>("test:same", fetch, 2);
    await tick();
    data.items = ["b"];
    const again = keptList<string>("test:same", fetch, 2);
    expect(again).toBe(first);
    await tick();
    expect(again.get(0)).toBe("b");
  });

  it("starts a new list for another id", () => {
    const { fetch } = server(["a"]);
    expect(keptList<string>("test:one", fetch)).not.toBe(keptList<string>("test:two", fetch));
  });
});
