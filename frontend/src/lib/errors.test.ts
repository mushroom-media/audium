import { describe, expect, it } from "vitest";
import { germanMessage } from "./errors";

describe("germanMessage", () => {
  it("translates rule editor messages and keeps the field label", () => {
    expect(germanMessage("Genre: a value is required")).toBe("Genre: Bitte einen Wert angeben.");
  });
  it("fills in numbers", () => {
    expect(germanMessage("password must be 8-256 characters")).toBe("Das Passwort muss 8 bis 256 Zeichen lang sein.");
  });
  it("passes unknown messages through", () => {
    expect(germanMessage("something new")).toBe("something new");
  });
});
