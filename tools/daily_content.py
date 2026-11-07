#!/usr/bin/env python3
"""
Holt den Tagesinhalt (Ayet, Hadis, Dua) von der Diyanet Awqat Salah API
und legt ihn als daily.json ab. Die Namaz-Vakti-App liest diese Datei.
Zugangsdaten kommen ausschliesslich aus den Repository-Secrets.
"""
import datetime as dt
import json
import os
import re
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


QURAN_API = "https://api.alquran.cloud/v1/ayah/{ref}/editions/quran-uthmani,de.bubenheim,en.hilali"
VERSE_EDITIONS = {
    "quran-uthmani": ("ar", "Mushaf (Uthmani)"),
    "de.bubenheim": ("de", "Bubenheim & Elyas, König-Fahd-Komplex"),
    "en.hilali": ("en", "Hilali & Khan, King Fahd Complex"),
}
DEEPL_TARGETS = {"de": "DE", "en": "EN-GB", "ar": "AR"}


def get_json(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verse_refs(source: str) -> list[str]:
    """'(Ra'd, 13/26)' -> ['13:26'], '24/52-53' -> ['24:52', '24:53']"""
    m = re.search(r"(\d{1,3})\s*/\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?", source or "")
    if not m:
        return []
    sura, first = int(m[1]), int(m[2])
    last = int(m[3]) if m[3] else first
    if not (1 <= sura <= 114) or last < first or last - first > 10:
        return []
    return [f"{sura}:{a}" for a in range(first, last + 1)]


def verse_translations(source: str) -> dict:
    """Anerkannte Uebersetzungen statt Maschinenuebersetzung fuer Koranverse."""
    refs = verse_refs(source)
    if not refs:
        print(f"Keine Versangabe erkannt in: {source!r}")
        return {}
    parts: dict[str, list[str]] = {}
    for ref in refs:
        try:
            data = get_json(QURAN_API.format(ref=ref)).get("data") or []
        except Exception as err:  # noqa: BLE001
            print(f"Koran-API nicht erreichbar fuer {ref}: {err}")
            return {}
        for item in data:
            ident = (item.get("edition") or {}).get("identifier")
            if ident in VERSE_EDITIONS:
                parts.setdefault(ident, []).append((item.get("text") or "").strip())
    out = {}
    for ident, texts in parts.items():
        lang, credit = VERSE_EDITIONS[ident]
        if len(texts) == len(refs):
            out[lang] = {"verse": " ".join(texts), "verseCredit": credit}
    print(f"Versuebersetzungen fuer {', '.join(refs)}: {sorted(out)}")
    return out


def deepl(texts: list[str], target: str, key: str) -> list[str] | None:
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    body = json.dumps({"text": texts, "source_lang": "TR", "target_lang": target}).encode()
    try:
        result = get_json(
            f"https://{host}/v2/translate",
            headers={"Authorization": f"DeepL-Auth-Key {key}", "Content-Type": "application/json"},
            data=body,
        )
        return [t.get("text", "") for t in result.get("translations", [])]
    except Exception as err:  # noqa: BLE001
        print(f"DeepL-Fehler ({target}): {err}")
        return None


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

    # Uebersetzungen: Verse aus anerkannten Koranuebersetzungen, Hadis und Dua per DeepL
    translations = {lang: {} for lang in DEEPL_TARGETS}
    for lang, values in verse_translations(content["verseSource"]).items():
        translations.setdefault(lang, {}).update(values)
    key = os.environ.get("DEEPL_API_KEY", "").strip()
    texts = [content["hadith"], content["pray"]]
    if key and any(texts):
        for lang, target in DEEPL_TARGETS.items():
            out = deepl([t or " " for t in texts], target, key)
            if out and len(out) == 2:
                translations[lang].update({"hadith": out[0].strip(), "pray": out[1].strip(), "machine": True})
        print("DeepL-Uebersetzungen erstellt.")
    elif not key:
        print("Kein DEEPL_API_KEY hinterlegt, Hadis und Dua bleiben auf Tuerkisch.")
    content["translations"] = {k: v for k, v in translations.items() if v}
    text = json.dumps(content, ensure_ascii=False, indent=1)
    (ROOT / "daily.json").write_text(text + "\n", "utf-8")
    (ROOT / "archive").mkdir(exist_ok=True)
    (ROOT / "archive" / f"{today}.json").write_text(text + "\n", "utf-8")
    print(f"Tagesinhalt für {today} gespeichert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
