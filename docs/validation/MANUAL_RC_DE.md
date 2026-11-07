# Windows-RC: manuelle Abnahme (15–20 Minuten)

**Nur ein Testpaket, keine Freigabe zur Veröffentlichung.** Die Entscheidung
trifft der Product Owner. Bekannte Vorschaugrenzen aus PR #316 bleiben offen;
ein bestandener Sichttest macht das strenge Timing-Gate nicht automatisch grün.

Tester/Datum: __________  Build-SHA aus `RC_BUILD.json`: __________
Windows/WebView2/Grafikkarte: __________  Bildschirmauflösung: __________

## Vorbereitung (etwa 2 Minuten)

1. ZIP vollständig in einen neuen, beschreibbaren Ordner entpacken. Den ZIP-Hash
   mit der mitgelieferten `.sha256`-Datei vergleichen. Build und ZIP-Hash im
   englischen Abnahmebericht nachsehen.
2. **`Start-Manual-RC.cmd` doppelklicken**, nicht direkt `orga-drone.exe`.
   Nur dieser Starter verwendet `manual-test-data` neben dem Starter statt
   deiner vorhandenen Bibliothek/Projekte. Beim ersten Start muss diese
   Testbibliothek leer sein. Falls alte eigene Projekte erscheinen: abbrechen.
   Es darf kein Browserfenster als Ersatz für die Desktop-App aufgehen.
3. Zwei originale DJI-Avata-2-MP4s mit sichtbarer Bewegung bereithalten, jeweils
   mindestens 13 Sekunden lang. Für diesen kurzen Test normale Rec.709-Aufnahmen
   verwenden. Bei D-Log M erst die passende technische Konvertierung klären;
   unsere Test-LUTs sind **keine** D-Log-M-Konvertierung.
4. Originale am bisherigen Speicherort lassen. Keine Umbenennen-/Zusammenführen-
   Aktionen verwenden. Import- und Exportwartezeiten bei sehr großen Ordnern
   zählen nicht zur aktiven Testzeit.

**Fehlerbeleg:** Screenshots/kurze Bildschirmaufnahme nur lokal speichern.
Story-Zeit, Aktion, LUT-Namen, erwartetes/tatsächliches Verhalten und
Wiederholbarkeit notieren. Keine privaten Aufnahmen, Menschen, Häuser,
Dateipfade oder genaue Orte in den öffentlichen PR hochladen.

## 1. Originale importieren (2 Minuten)

**Aktionen:** Studio öffnen und über „Neues Projekt“ die neue Story `RC-Abnahme`
anlegen. Dann „Medien hinzufügen“ → „Ordner hinzufügen“; den vorhandenen Ordner
mit den Originalen wählen. Scan abwarten. Zwei Videos A und B in der Bibliothek
öffnen und jeweils zur aktiven Studio-Story hinzufügen.

**Erwartet:** Beide Videos werden erkannt und sind abspielbar. Originaldateien
bleiben am selben Ort; bestehende eigene Projekte sind im isolierten Paket
nicht vorhanden. Keine fehlenden Medien oder Fehlermeldungen.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** Meldung, Scanstatus und Anzahl erkannter Videos notieren;
lokalen Screenshot sowie Log aus `manual-test-data` sichern.

## 2. Normal abspielen und suchen (1–2 Minuten)

**Aktionen:** Noch ohne LUT/Überblendung A und B einzeln auswählen. Jeweils
Play → Pause → Play verwenden. In der Zeitleiste vorwärts und rückwärts klicken.
An drei verschiedenen Stellen pausieren.

**Erwartet:** Bewegungen laufen nachvollziehbar weiter. Das pausierte Bild passt
zur gewählten Stelle; kein dauerhaft altes Bild, schwarzes Aufblitzen,
unerwarteter Helligkeitssprung oder sichtbarer Zeitsprung.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** Clip A/B, ungefähre Story-Zeit und letzte Aktion aufschreiben;
5–10 Sekunden Bildschirmaufnahme vor/nach dem Fehler oder zwei lokale Bilder.

## 3. Einen kreativen LUT anwenden (1–2 Minuten)

**Aktionen:** A auswählen. Im Inspektor „Look & Farben“ → „Kameraprofil & LUTs“
öffnen. Unter „Kreativer Look“ → „Look-Datei hinzufügen“ die mitgelieferte
`TEST-creative-red.cube` wählen, Look-Stärke 100 %. B vorerst ohne LUT lassen.

**Erwartet:** A bekommt sichtbar den warmen Test-Look; B behält seinen normalen
Look. Kein schwarzes/leeres Bild, keine Fehlermeldung. Die Originaldatei bleibt
unverändert. Der starke Test-Look ist beabsichtigt, kein Qualitätslook.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** LUT-Name, Stärke und Meldung/angezeigten Vorschauhinweis notieren;
lokales Bild vor/nach Anwendung aufnehmen.

## 4. Pausierte und laufende Vorschau vergleichen (1 Minute)

**Aktionen:** Mit A dreimal Play → Pause → Play durchführen, auch nach einem
Sprung in der Zeitleiste. Bewegung und Farbe direkt vor/nach Pause vergleichen.

**Erwartet:** Der Look bleibt erkennbar derselbe. Kein auffälliger Farbwechsel,
Helligkeitsblitz oder lange stehenbleibendes altes Bild. Falls ein Hinweis auf
eine eingeschränkte Vorschau erscheint, dessen Wortlaut notieren und die
Abweichung bewerten; nicht stillschweigend als PASS werten.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** Aufnahme des Pause/Play-Wechsels mit Story-Zeit, LUT und Hinweis;
Farbe/Helligkeit und Bewegung getrennt beschreiben.

## 5. Video-zu-Video-Überblendung anlegen (2 Minuten)

**Aktionen:** Bei beiden Clips im Abschnitts-Inspektor „Quelle von“ auf `10,0`
und „Quelle bis“ auf `13,0` setzen (falls das Feld einen Punkt erwartet: `10.0`
und `13.0`). Wiederholung 1, Geschwindigkeit normal lassen. A vor B anordnen.
Den Übergang zwischen A und B anklicken; „Übergang“ → „Überblenden“,
„Übergangsdauer“ `1,0` Sekunde wählen. Zunächst den kreativen LUT von A wieder
auf „Keine“ setzen: damit wird die Kontrolle **ohne LUT** getestet.

**Erwartet:** Story etwa 5 Sekunden lang. Die Überlappung liegt bei Story
2–3 Sekunden. Zwei bewegte Bilder überlagern sich, ohne unerwartetes Schwarz.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** Lokales Bild der beiden Clips, Übergangseinstellung und Dauer;
angezeigte Story-Gesamtdauer notieren.

## 6. Kontinuierlich durch die Überlappung spielen (1 Minute)

**Aktionen:** Bei etwa Story 1,3 Sekunden starten und bis mindestens 3,3 Sekunden
laufen lassen. Fünfmal wiederholen. Auf das ausblendende und das einblendende
Bild getrennt achten, besonders auf bewegte Kanten/Bäume.

**Erwartet:** Beide Bilder bewegen sich während der Überblendung weiter.
Kein deutlich stehendes Bild, schwarzer Blitz, kurzer Helligkeitssprung oder
sichtbarer Sprung beim Eintritt/Austritt. Die Messabweichungen aus #316 sind
bekannt; hier zählt zusätzlich, was du tatsächlich siehst.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** Wiederholung x/5 und Story-Zeit; kurze lokale Aufnahme mit etwas
Vorlauf/Nachlauf. Falls Aufnahmeprogramme das Verhalten ändern, auch ohne
Aufnahme wiederholen und das ausdrücklich notieren.

## 7. Direkt in der Überlappung starten (1 Minute)

**Aktionen:** Pausieren. Etwa ein Viertel in die markierte Überlappung klicken
(Story 2,25 Sekunden). Von dort Play starten; bis hinter 3 Sekunden laufen
lassen. Dreimal wiederholen.

**Erwartet:** Das aktuelle Mischbild geht nachvollziehbar in Bewegung über.
Kein altes Startbild, schwarzer Blitz oder deutliches Nachspringen einer Ebene.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** Startposition, Verzögerung/Zeitsprung und Wiederholung x/3
notieren; lokale Aufnahme vom pausierten Bild bis nach der Überlappung.

## 8. Bei 25 / 50 / 75 % pausiert suchen (2 Minuten)

**Aktionen:** Pausieren; die Zeitleiste bei Bedarf vergrößern. Nacheinander auf
ein Viertel, die Mitte und drei Viertel der Überlappungsbreite klicken:
ungefähr Story 2,25 / 2,50 / 2,75 Sekunden. Jede Position zweimal aufsuchen,
jeweils etwa eine Sekunde warten. Danach von der Mitte kurz Play → Pause.

**Erwartet:** Der Mischanteil verändert sich passend von A zu B. Kein halb so
helles Bild durch eine fehlende Ebene, kein leeres Bild oder dauerhaft alter
Frame. Die Maus kann Zeiten auf Pixel/Video-Frames runden; tatsächlich
angezeigte Zeiten notieren, nicht Millisekunden-Genauigkeit behaupten.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** Zwei lokale Bilder derselben Position direkt nach dem Sprung
und nach einer Sekunde; Fortschritt 25/50/75 %, angezeigte Zeit und LUT-Zustand.

## 9. Mit LUTs wiederholen (2–3 Minuten)

**Aktionen:** Erst A und B mit `TEST-creative-red.cube` bei 100 % versehen.
Schritte 6–8 kurz wiederholen. Dann nur bei B `TEST-creative-blue.cube` wählen,
A bleibt rot. Wieder dreimal kontinuierlich durchspielen, dreimal direkt
in der Überlappung starten und alle drei Pausenpositionen prüfen.

**Erwartet:** Beide Looks sind unterscheidbar und gehen entsprechend dem
Mischanteil ineinander über. Kein zusätzlicher Blitz, Stillstand oder Zeitsprung.
Der beabsichtigte allmähliche Farbwechsel ist kein Fehler; ein abrupter Blitz
oder plötzlich fehlender Look ist einer.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** Gleiches/verschiedenes LUT-Paar, Stärke, Position und letzter
Schritt; lokale Vergleichsaufnahme auch ohne LUT versuchen. Nicht aus einem
Fehler ohne LUT automatisch auf einen LUT-Fehler schließen.

## 10. MP4 exportieren und ansehen (3 Minuten)

**Aktionen:** Die Story mit den unterschiedlichen LUTs über „Export“ als MP4,
1080p, Qualität „Standard“ in eine **neue Datei im entpackten Testordner**
exportieren, z. B. `RC-Abnahme.mp4`. Keine vorhandene Datei überschreiben.
Im normalen Videoplayer öffnen. Überblendung bei 2–3 Sekunden mehrfach ansehen;
Mischbilder bei etwa 2,25 / 2,50 / 2,75 Sekunden mit Studio vergleichen.
Studio schließen und über den Starter erneut öffnen; Test-Story wiederfinden.

**Erwartet:** Export endet erfolgreich, Video etwa 5 Sekunden lang. Keine
schwarzen Frames, eingefrorene Bilder oder Übergangssprünge im MP4. Farbe und
Mischanteile entsprechen erkennbar der Story. Kleine Unterschiede durch
Kompression/Frame-Raster getrennt von deutlichen Fehlern beschreiben. Die
Test-Story bleibt nach Neustart erhalten; eigene produktive Projekte unberührt.

Ergebnis: [ ] PASS  [ ] FAIL  [ ] NOT TESTED

**Bei Fehler:** Exportmeldung/Einstellungen, MP4-Zeit, Studio-Zeit und lokales
Bildpaar notieren. **Vorschaufehler** und **Fehler auch im Export** getrennt
markieren; MP4 und Logs nur lokal zur Prüfung bereithalten.

## Entscheidung des Product Owners

- [ ] Alle Schritte durchgeführt; auffällige Vorschaugrenzen dokumentiert.
- [ ] Originale unverändert und keine vorhandenen Projekte verändert.
- [ ] Bekannte Timing-/Farb-Gates und nicht getestete Release-Gates im Bericht gelesen.

Entscheidung: [ ] GO  [ ] CONDITIONAL GO  [ ] NO-GO

Akzeptierte Einschränkungen / Bedingungen / Blocker: ____________________

Name/Datum: ____________________  Lokale Belege: ____________________

Ein Haken hier veröffentlicht nichts. Vor einer später ausdrücklich
beauftragten Veröffentlichung bleiben u. a. der Mark-of-the-Web-Test mit
Windows-Explorer-Entpacken und die nativen Dialogprüfungen aus
`packaging/README.md` verpflichtend. Ein NOT TESTED ist kein PASS.
