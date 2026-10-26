import { describe, expect, it } from "vitest";
import { normalizeServer } from "./api";

describe("normalizeServer", () => {
  it("adds the scheme people leave out, http only for local addresses", () => {
    expect(normalizeServer("192.168.1.5:8091")).toBe("http://192.168.1.5:8091");
    expect(normalizeServer("localhost:8091/")).toBe("http://localhost:8091");
    expect(normalizeServer("music.example.org")).toBe("https://music.example.org");
    expect(normalizeServer(" https://music.example.org/audium// ")).toBe("https://music.example.org/audium");
    expect(normalizeServer("http://nas:8091")).toBe("http://nas:8091");
  });
});
