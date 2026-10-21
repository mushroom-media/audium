// The API speaks English (it is also used by scripts and other clients); the UI shows German.
// Unknown messages pass through unchanged, so a new server message is never swallowed.

type Rule = [RegExp, string | ((m: RegExpMatchArray) => string)];

const RULES: Rule[] = [
  // rule editor: "<Feld>: …" (field labels are German already)
  [/^(.+): a value is required$/, (m) => `${m[1]}: Bitte einen Wert angeben.`],
  [/^(.+): a number is required$/, (m) => `${m[1]}: Bitte eine Zahl angeben.`],
  [/^(.+): 'between' needs two values$/, (m) => `${m[1]}: „zwischen“ braucht zwei Werte.`],
  [/^(.+): value must be between 0 and 1$/, (m) => `${m[1]}: Der Wert muss zwischen 0 und 1 liegen.`],
  [/^(.+): value must be one of (.+)$/, (m) => `${m[1]}: erlaubt sind ${m[2]}.`],
  [/^(.+): operator must be one of (.+)$/, (m) => `${m[1]}: Diese Bedingung passt nicht zum Feld.`],
  [/^a rule needs at least one condition$/, "Die Regel braucht mindestens eine Bedingung."],
  [/^at most (\d+) conditions$/, (m) => `Höchstens ${m[1]} Bedingungen.`],
  [/^unknown field/, "Unbekanntes Feld in der Regel."],
  [/^only smart playlists have a rule$/, "Nur Smart-Playlists haben eine Regel."],
  [/^smart playlists fill themselves/, "Smart-Playlists füllen sich selbst – ändere stattdessen die Regel."],
  // playlists
  [/^name must not be empty$/, "Bitte einen Namen angeben."],
  [/^a playlist can hold at most (\d+) tracks$/, (m) => `Eine Playlist kann höchstens ${Number(m[1]).toLocaleString("de-DE")} Titel enthalten.`],
  [/^at most (\d+) tracks per request$/, (m) => `Höchstens ${Number(m[1]).toLocaleString("de-DE")} Titel auf einmal.`],
  [/^none of the tracks exist$/, "Diese Titel gibt es nicht mehr."],
  [/^the playlist was changed meanwhile$/, "Die Playlist wurde inzwischen geändert – bitte neu laden."],
  [/^the owner already has full access$/, "Der Besitzer hat schon vollen Zugriff."],
  [/^only the owner can do this$/, "Das darf nur der Besitzer der Playlist."],
  [/^playlist not found$/, "Diese Playlist gibt es nicht (mehr) oder sie ist nicht für dich freigegeben."],
  [/^user not found$/, "Diesen Nutzer gibt es nicht."],
  // library and admin
  [/^overlaps with existing library folder (.+)$/, (m) => `Überschneidet sich mit dem Bibliotheksordner ${m[1]}.`],
  [/^path must be inside (.+)$/, (m) => `Der Ordner muss innerhalb von ${m[1]} liegen.`],
  [/^path is not a directory$/, "Das ist kein Ordner."],
  [/^folder is not readable by the container user$/, "Der Container darf diesen Ordner nicht lesen (Dateirechte prüfen)."],
  [/^rel_path must be a sub-folder/, "Bitte einen Unterordner des Bibliotheksordners angeben."],
  [/^already excluded$/, "Dieser Ordner ist schon ausgeschlossen."],
  [/^username already taken$/, "Der Benutzername ist vergeben."],
  [/^username must be/, "Benutzername: 2–32 Zeichen, nur Buchstaben, Ziffern, . _ -"],
  [/^password must be (\d+)-(\d+) characters$/, (m) => `Das Passwort muss ${m[1]} bis ${m[2]} Zeichen lang sein.`],
  [/^at least one active admin is required$/, "Es muss mindestens ein aktiver Admin bleiben."],
  [/^you cannot change your own role$/, "Die eigene Rolle kannst du nicht ändern."],
  [/^you cannot disable your own account$/, "Das eigene Konto kannst du nicht sperren."],
  [/^current password is wrong$/, "Das aktuelle Passwort stimmt nicht."],
  [/^invalid setup token$/, "Der Setup-Token stimmt nicht."],
  [/^setup is already complete$/, "Die Einrichtung ist schon abgeschlossen."],
  [/^invite is invalid or expired$/, "Diese Einladung ist ungültig oder abgelaufen."],
  [/^admin only$/, "Nur für Admins."],
  [/^(album|artist|track|auto-playlist|job|library folder|folder|item) not found$/, "Nicht gefunden."],
  [/^file not available$/, "Die Datei ist gerade nicht erreichbar."],
];

export function germanMessage(message: string): string {
  for (const [re, out] of RULES) {
    const m = message.match(re);
    if (m) return typeof out === "string" ? out : out(m);
  }
  return message;
}
