#Push:
Status prüfen (Optional): Schau nach, was sich geändert hat.
-> git status

Änderungen vormerken: Füge alle geänderten Dateien dem nächsten „Paket“ hinzu.
-> git add .

Commit erstellen: Schnüre das Paket und beschrifte es.
-> git commit -m "Beschreibe hier kurz deine Änderung"

Hochladen: Schicke die Änderungen zu GitHub.
-> git push origin main


#Pull:
Normaler Pull mit sofortiger Änderung
-> git pull origin main

Wenn du nur wissen willst, ob es Updates gibt, ohne sie sofort zu installieren
-> git fetch

Änderungen verwerfen: Hast du dich auf dem Server total vertippt und willst den Zustand von GitHub wiederherstellen?
-> git reset --hard origin/main