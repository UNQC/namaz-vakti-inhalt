#!/usr/bin/env python3
"""
Holt den Tagesinhalt (Ayet, Hadis, Dua) von der Diyanet Awqat Salah API
und legt ihn als daily.json ab. Die Namaz-Vakti-App liest diese Datei.
Zugangsdaten kommen ausschliesslich aus den Repository-Secrets.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "https://awqatsalah.diyanet.gov.tr"
ROOT = Path(__file__).resolve().parent.parent
UA = "NamazVakti-Content/1.0 (private app project)"


def camel(value):
    if isinstance(value, dict):
        return {(k[:1].lower() + k[1:]): camel(v) for k, v in value.items()}
    if isinstance(value, list):
        return [camel(v) for v in value]
    return value


def send(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for wait in (0, 15, 60):
        if wait:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return camel(json.loads(resp.read().decode("utf-8")))
        except urllib.error.HTTPError:
            raise
        except Exception as err:  # noqa: BLE001
            print(f"Netzwerkfehler: {type(err).__name__}")
    raise SystemExit("Diyanet nicht erreichbar")


def main() -> int:
    email, password = os.environ.get("DIYANET_EMAIL"), os.environ.get("DIYANET_PASSWORD")
    if not email or not password:
        raise SystemExit("DIYANET_EMAIL und DIYANET_PASSWORD fehlen.")
    try:
        auth = send("POST", "/Auth/Login", {"email": email, "password": password})
    except urllib.error.HTTPError as err:
        if err.code not in (404, 405):
            raise SystemExit(f"Login fehlgeschlagen (HTTP {err.code})")
        auth = send("POST", "/api/Auth/Login", {"email": email, "password": password})
    token = (auth.get("data") or {}).get("accessToken")
    if not token:
        raise SystemExit(f"Login fehlgeschlagen: {auth.get('message')}")

    result = send("GET", "/api/DailyContent", token=token)
    data = result.get("data") or {}
    today = dt.datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat()
    content = {
        "date": today,
        "dayOfYear": data.get("dayOfYear"),
        "verse": data.get("verse") or "",
        "verseSource": data.get("verseSource") or "",
        "hadith": data.get("hadith") or "",
        "hadithSource": data.get("hadithSource") or "",
        "pray": data.get("pray") or "",
        "praySource": data.get("praySource") or "",
        "source": "T.C. Diyanet İşleri Başkanlığı",
    }
    if not (content["verse"] or content["hadith"] or content["pray"]):
        raise SystemExit(f"Kein Inhalt erhalten: {result.get('message')}")
    text = json.dumps(content, ensure_ascii=False, indent=1)
    (ROOT / "daily.json").write_text(text + "\n", "utf-8")
    (ROOT / "archive").mkdir(exist_ok=True)
    (ROOT / "archive" / f"{today}.json").write_text(text + "\n", "utf-8")
    print(f"Tagesinhalt für {today} gespeichert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
