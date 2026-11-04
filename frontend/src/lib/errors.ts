// The API speaks English (it is also used by scripts and other clients); the UI shows its messages
// in the UI language, with the German text as the key like everywhere else (i18n.svelte.ts).
// Unknown messages pass through unchanged, so a new server message is never swallowed.

import { num, t } from "./i18n.svelte";

type Rule = [RegExp, (m: RegExpMatchArray) => string];

/** Rule field name -> its label in the UI language; the rule editor fills it from /rules/fields. */
export const ruleFieldLabels: Record<string, string> = {};
const label = (name: string) => ruleFieldLabels[name] ?? name;

const RULES: Rule[] = [
  // rule editor: "<field name>: …"
  [/^(.+): a value is required$/, (m) => t("{field}: Bitte einen Wert angeben.", { field: label(m[1]) })],
  [/^(.+): a number is required$/, (m) => t("{field}: Bitte eine Zahl angeben.", { field: label(m[1]) })],
  [/^(.+): 'between' needs two values$/, (m) => t("{field}: „zwischen“ braucht zwei Werte.", { field: label(m[1]) })],
  [/^(.+): value must be between 0 and 1$/, (m) => t("{field}: Der Wert muss zwischen 0 und 1 liegen.", { field: label(m[1]) })],
  [/^(.+): value must be one of (.+)$/, (m) => t("{field}: erlaubt sind {values}.", { field: label(m[1]), values: m[2] })],
  [/^(.+): operator must be one of (.+)$/, (m) => t("{field}: Diese Bedingung passt nicht zum Feld.", { field: label(m[1]) })],
  [/^a rule needs at least one condition$/, () => t("Die Regel braucht mindestens eine Bedingung.")],
  [/^at most (\d+) conditions$/, (m) => t("Höchstens {n} Bedingungen.", { n: Number(m[1]) })],
  [/^unknown field/, () => t("Unbekanntes Feld in der Regel.")],
  [/^only smart playlists have a rule$/, () => t("Nur Smart-Playlists haben eine Regel.")],
  [/^smart playlists fill themselves/, () => t("Smart-Playlists füllen sich selbst – ändere stattdessen die Regel.")],
  // playlists
  [/^name must not be empty$/, () => t("Bitte einen Namen angeben.")],
  [/^a playlist can hold at most (\d+) tracks$/, (m) => t("Eine Playlist kann höchstens {n} Titel enthalten.", { n: Number(m[1]) })],
  [/^at most (\d+) tracks per request$/, (m) => t("Höchstens {n} Titel auf einmal.", { n: Number(m[1]) })],
  [/^none of the tracks exist$/, () => t("Diese Titel gibt es nicht mehr.")],
  [/^the playlist was changed meanwhile$/, () => t("Die Playlist wurde inzwischen geändert – bitte neu laden.")],
  [/^the owner already has full access$/, () => t("Der Besitzer hat schon vollen Zugriff.")],
  [/^only the owner can do this$/, () => t("Das darf nur der Besitzer der Playlist.")],
  [/^playlist not found$/, () => t("Diese Playlist gibt es nicht (mehr) oder sie ist nicht für dich freigegeben.")],
  [/^user not found$/, () => t("Diesen Nutzer gibt es nicht.")],
  // library and admin
  [/^overlaps with existing library folder (.+)$/, (m) => t("Überschneidet sich mit dem Bibliotheksordner {path}.", { path: m[1] })],
  [/^path must be inside (.+)$/, (m) => t("Der Ordner muss innerhalb von {path} liegen.", { path: m[1] })],
  [/^path is not a directory$/, () => t("Das ist kein Ordner.")],
  [/^folder is not readable by the container user$/, () => t("Der Container darf diesen Ordner nicht lesen (Dateirechte prüfen).")],
  [/^rel_path must be a sub-folder/, () => t("Bitte einen Unterordner des Bibliotheksordners angeben.")],
  [/^already excluded$/, () => t("Dieser Ordner ist schon ausgeschlossen.")],
  [/^username already taken$/, () => t("Der Benutzername ist vergeben.")],
  [/^username must be/, () => t("Benutzername: 2–32 Zeichen, nur Buchstaben, Ziffern, . _ -")],
  [/^password must be (\d+)-(\d+) characters$/, (m) => t("Das Passwort muss {min} bis {max} Zeichen lang sein.", { min: m[1], max: m[2] })],
  [/^at least one active admin is required$/, () => t("Es muss mindestens ein aktiver Admin bleiben.")],
  [/^you cannot change your own role$/, () => t("Die eigene Rolle kannst du nicht ändern.")],
  [/^you cannot disable your own account$/, () => t("Das eigene Konto kannst du nicht sperren.")],
  [/^current password is wrong$/, () => t("Das aktuelle Passwort stimmt nicht.")],
  [/^the password is wrong$/, () => t("Das Passwort stimmt nicht.")],
  [/^the time for the setup has run out$/, () => t("Die Zeit für die Einrichtung ist abgelaufen. Starte den Container neu, dann hast du wieder 30 Minuten.")],
  [/^the admin password needs at least (\d+) characters$/, (m) => t("Das Admin-Passwort braucht mindestens {n} Zeichen.", { n: num(Number(m[1])) })],
  [/^setup is already complete$/, () => t("Die Einrichtung ist schon abgeschlossen.")],
  [/^this server is not set up yet$/, () => t("Dieser Server ist noch nicht eingerichtet. Öffne ihn zuerst im Browser.")],
  [/^invite is invalid or expired$/, () => t("Diese Einladung ist ungültig oder abgelaufen.")],
  [/^admin only$/, () => t("Nur für Admins.")],
  [/^(album|artist|track|auto-playlist|job|library folder|folder|item) not found$/, () => t("Nicht gefunden.")],
  [/^file not available$/, () => t("Die Datei ist gerade nicht erreichbar.")],
];

export function uiMessage(message: string): string {
  for (const [re, out] of RULES) {
    const m = message.match(re);
    if (m) return out(m);
  }
  return message;
}
