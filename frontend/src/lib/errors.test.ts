import { afterEach, describe, expect, it } from "vitest";
import { ruleFieldLabels, uiMessage } from "./errors";
import { i18n } from "./i18n.svelte";

describe("uiMessage", () => {
  afterEach(() => {
    i18n.lang = "de";
  });
  it("translates rule editor messages and shows the field label", () => {
    ruleFieldLabels.genre = "Genre";
    expect(uiMessage("genre: a value is required")).toBe("Genre: Bitte einen Wert angeben.");
  });
  it("fills in numbers", () => {
    expect(uiMessage("password must be 8-256 characters")).toBe("Das Passwort muss 8 bis 256 Zeichen lang sein.");
  });
  it("speaks English when the UI does", () => {
    i18n.lang = "en";
    expect(uiMessage("password must be 8-256 characters")).toBe("The password must be 8 to 256 characters long.");
  });
  it("passes unknown messages through", () => {
    expect(uiMessage("something new")).toBe("something new");
  });
});
