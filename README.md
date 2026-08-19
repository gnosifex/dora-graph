# dora-graph

**English summary.** An animated map of the EU DORA regulation (Regulation (EU) 2022/2554) and the documents around it: the regulation and its articles, the delegated and implementing acts, supervisory guidelines, ESA Q&As, preparatory final reports, German supervisory circulars and the referenced standards. Nodes are coloured by how binding a source is, sized by how long the document is, and appear along the real timeline — so the picture builds itself from 2006 to today. This repository holds the generator code, the graph metadata with links to the publishers' originals, and the built page. It mirrors no legal text. Unofficial, not legal advice, not affiliated with the ESAs, BaFin or the EU.

**Live:** https://gnosifex.github.io/dora-graph/

---

## Was das ist

Die DORA-Regulatorik ist kein Dokument, sondern ein Geflecht: Die Verordnung verweist auf sich selbst und auf fremdes Recht, zwölf delegierte und Durchführungsverordnungen konkretisieren einzelne Artikel, Leitlinien und Q&As legen aus, Final Reports gehen den Rechtsakten voraus, nationale Rundschreiben und externe Standards hängen daran. Diese Seite zeigt das Geflecht als Graph und spielt seine Entstehung als Zeitraffer ab.

## Wie das Bild zu lesen ist

- **Kreise sind Rechtsakte.** Die Artikel, Anhänge und Paragrafen eines Akts liegen in seinem Kreis. Die Kreise stehen nebeneinander, nicht ineinander — Beziehungen zwischen Akten laufen ausschließlich über Kanten.
- **Farbe ist Verbindlichkeit,** nicht Wichtigkeit: Tiefrot bindendes Recht, darüber die Skala bis Blau für laufende Aufsichtskommunikation, Violett die Standards außerhalb der Rangordnung. Die Skala folgt der Quellenhierarchie des zugrunde liegenden Korpus.
- **Größe ist Textumfang** — aber nur bei eigenständigen Dokumenten. Einzelne Artikel, Q&As und Aufsichtsseiten sind einheitlich klein, damit die Ebene der Einzelnormen nicht mit der Ebene der Dokumente konkurriert.
- **Gestrichelte Ränder markieren Schätzungen:** Das Dokument liegt nicht vollständig im Korpus, sein Umfang ist hochgerechnet (Referenzakte) oder aus der Seitenzahl geschätzt (Standards).
- **Rote Strichlinien sind Verdrängung:** lang gestrichelt vollständig aufgehoben, fein gepunktet teilweise überholt — der sichtbarste Effekt von DORA auf die vorherige Aufsichtspraxis.
- **Der Zeitpunkt ist die Erstfassung des Instruments,** nicht die gespiegelte Novelle. Bestand vor 2006 ist ab dem ersten Frame sichtbar; beim Erscheinen von DORA im Dezember 2022 rückt er nach außen.

Ein Klick auf eine Legendenzeile hebt die Knoten dieses Rangs hervor.

![Legende der Verbindlichkeitsränge: Rang 1 tiefrot bis Rang 7 blau, Standards violett, Erwägungsgründe grau](docs/legende.png)

## Was hier liegt — und was nicht

Dieses Repository enthält **keinen gespiegelten Rechtstext**. `data/graph.json` führt je Knoten nur Titel, Datum, Rang, Umfangskennzahl und die **Quell-URL beim Herausgeber**; die Volltexte bleiben dort, wo sie hingehören — bei EUR-Lex, den ESAs und der BaFin. `LINKS.md` ist derselbe Bestand als durchsuchbare Liste.

Die Metadaten stammen aus einem privaten Korpus-Spiegel (Projekt `ask-dora`), der die Quellen deterministisch bei ihren Herausgebern abruft. Dieses Repo ist dessen Schaufenster, nicht seine Kopie.

## Erzeugungskette

```
Korpus  --build_vault.py-->  Obsidian-Vault  --export_graph.py-->  data/graph.json
                                                                        |
                                                    build_site.py       |  make_links.py
                                                            v           v
                                                    docs/index.html   LINKS.md
```

Nur die letzten beiden Schritte lassen sich mit dem Inhalt dieses Repos nachvollziehen — sie brauchen ausschließlich `data/graph.json`:

```bash
python3 generator/build_site.py && python3 generator/check_site.py
```

`build_vault.py` und `export_graph.py` sind der Vollständigkeit halber enthalten; sie setzen den Korpus-Spiegel voraus. Alle Skripte laufen mit der Python-Standardbibliothek, ohne Abhängigkeiten und ohne Netz.

## Annahmen und Grenzen

Der Graph ist eine Darstellung, kein Nachschlagewerk — mehrere Kanten und Werte sind bewusst gesetzt, weil die Daten sie nicht hergeben:

- **Kuratierte Kanten.** Dass ein Final Report seinen RTS vorbereitet, dass MaRisk und BAIT das KWG konkretisieren und EBA-Leitlinien umsetzen, dass DORA sie verdrängt: Nichts davon steht als maschinenlesbare Beziehung in den Quellen. Diese Kanten sind aus den Dokumenttiteln und dem Aufhebungsstand kuratiert und im Generator als Konstanten sichtbar.
- **Datumsannahmen.** Maßstab ist die Reihenfolge, nicht das exakte Datum. Wo eine Erstfassung nicht datiert vorliegt, steht eine plausible Näherung; die ISO-27000-Familie ist über ihre BS-7799-Vorläufer datiert.
- **Umfangsschätzungen.** Teilweise gespiegelte Akte sind über den mittleren Umfang ihrer gespiegelten Einheiten hochgerechnet, Standards über ihre Seitenzahl geschätzt. Beide tragen den gestrichelten Rand.
- **Der Korpus ist ein Ausschnitt.** Was nicht gespiegelt ist, fehlt im Bild — Vollständigkeit ist weder erreicht noch behauptet.

## Haftungsausschluss

Inoffizielles Hobbyprojekt. **Keine Rechtsberatung.** Keine Verbindung zu den Europäischen Aufsichtsbehörden, zur BaFin, zur Deutschen Bundesbank, zur EZB oder zur EU. Keine Gewähr für Richtigkeit, Vollständigkeit oder Aktualität; maßgeblich ist allein die jeweilige Fassung beim Herausgeber, auf die jeder Knoten verlinkt. Die Titel der Dokumente sind als Fundstellenangaben zitiert; die Rechte an den Dokumenten selbst liegen bei den jeweiligen Herausgebern.

## Lizenz

Code unter der MIT-Lizenz (siehe `LICENSE`). `data/graph.json` und `LINKS.md` enthalten Fundstellenangaben — Titel, Daten, Verweise und Links —, also Fakten über öffentlich publizierte Dokumente, keine Inhalte daraus.
