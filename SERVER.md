# 🐧 Linux-Server Deployment

Anleitung, um den TikTok Live Recorder auf einem Linux-Server (Debian/Ubuntu)
als Hintergrunddienst laufen zu lassen.

## 1. System-Voraussetzungen

```bash
# Python und Tools
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg git

# (streamlink wird gleich im venv installiert — schlechter über apt, da oft veraltet)
```

## 2. Benutzer & Verzeichnisse

```bash
# Eigenen Benutzer für den Dienst anlegen (sicherer als root)
sudo useradd -m -s /bin/bash tiktok

# Projekt-Verzeichnis
sudo mkdir -p /opt/tiktok_recorder
sudo chown tiktok:tiktok /opt/tiktok_recorder
```

## 3. Code hochladen

Entweder per `scp` / `rsync` von deinem lokalen Rechner:

```bash
rsync -av --exclude='__pycache__' tiktok_recorder_project/ \
  user@server:/opt/tiktok_recorder/
```

Oder per Git, falls du das Projekt in ein Repo gepackt hast:

```bash
sudo -u tiktok git clone <repo-url> /opt/tiktok_recorder
```

## 4. Python-Umgebung einrichten

```bash
sudo -u tiktok bash << 'EOF'
cd /opt/tiktok_recorder
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install streamlink
EOF
```

## 5. Erster Test (manuell)

```bash
sudo -u tiktok bash
cd /opt/tiktok_recorder
source venv/bin/activate

TTR_HOST=0.0.0.0 TTR_OPEN=0 \
TTR_AUTH_USER=admin TTR_AUTH_PASS=DEIN_PASSWORT \
python main.py
```

Im Browser unter `http://<server-ip>:8765` öffnen — Login-Dialog erscheint.
Mit `Strg+C` beenden, dann den `exit`-Befehl im Terminal.

## 6. Als systemd-Dienst einrichten

```bash
# Service-Datei kopieren und Pfade/Passwort anpassen
sudo cp /opt/tiktok_recorder/tiktok_recorder.service /etc/systemd/system/
sudo nano /etc/systemd/system/tiktok_recorder.service
#  → User=, WorkingDirectory=, ExecStart=, TTR_AUTH_PASS=  prüfen!

sudo systemctl daemon-reload
sudo systemctl enable tiktok_recorder
sudo systemctl start tiktok_recorder

# Status prüfen
sudo systemctl status tiktok_recorder

# Live-Log
sudo journalctl -u tiktok_recorder -f
```

## 7. Firewall öffnen

Wenn der Server `ufw` nutzt:

```bash
sudo ufw allow 8765/tcp
```

Bei einem Cloud-Anbieter (Hetzner, DigitalOcean, AWS): zusätzlich die
Cloud-Firewall im Web-Panel öffnen.

## 8. (Empfohlen) Reverse-Proxy mit HTTPS

Direkt-Zugriff auf Port 8765 funktioniert, ist aber **unverschlüsselt** —
Basic-Auth schützt dann nur unzureichend. Besser: nginx + Let's Encrypt davorschalten.

### nginx-Beispiel

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/tiktok_recorder`:

```nginx
server {
    listen 80;
    server_name recorder.example.com;

    # Große Video-Downloads erlauben
    client_max_body_size 0;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Für Range-Requests beim Video-Streaming
        proxy_buffering off;
        proxy_request_buffering off;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/tiktok_recorder /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS-Zertifikat holen
sudo certbot --nginx -d recorder.example.com
```

Danach **wieder zurück auf localhost-Bind** in der Service-Datei:

```ini
Environment="TTR_HOST=127.0.0.1"
```

Und die Firewall für 8765 wieder schließen — nur 80/443 müssen offen sein.

```bash
sudo systemctl restart tiktok_recorder
sudo ufw delete allow 8765/tcp
sudo ufw allow 'Nginx Full'
```

## 9. Speicherplatz im Auge behalten

Live-Aufnahmen werden schnell groß (1080p ≈ 1–2 GB pro Stunde). Sinnvoll:

```bash
# Speichernutzung prüfen
du -sh /home/tiktok/TikTokRecordings/*

# Alte Aufnahmen automatisch löschen (z.B. älter als 30 Tage)
# als Cronjob für den tiktok-User:
sudo -u tiktok crontab -e
# eintragen:
# 0 3 * * * find /home/tiktok/TikTokRecordings -name "*.mp4" -mtime +30 -delete
```

## 10. Updates einspielen

```bash
sudo systemctl stop tiktok_recorder
sudo -u tiktok bash -c "
  cd /opt/tiktok_recorder
  # Neue Dateien hochladen / git pull
  source venv/bin/activate
  pip install -r requirements.txt --upgrade
  pip install -U streamlink
"
sudo systemctl start tiktok_recorder
```

## Troubleshooting

| Problem | Lösung |
|---|---|
| Dienst startet nicht | `sudo journalctl -u tiktok_recorder -n 50` für Fehler |
| `streamlink: not found` im Log | venv-Pfad in `ExecStart` prüfen, oder `/opt/tiktok_recorder/venv/bin` zum PATH der Service-Unit hinzufügen |
| Port 8765 nicht erreichbar | UFW + Cloud-Firewall prüfen, `ss -tlnp \| grep 8765` zeigt, ob der Server lauscht |
| 502 Bad Gateway über nginx | Service läuft nicht oder bind ist falsch (`127.0.0.1` für nginx-Setup) |
| Sehr hohe CPU-Last | Mehrere parallele Aufnahmen mit 1080p — eventuell auf 720p heruntersetzen in `recorder.py` |
