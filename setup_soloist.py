"""Store a Soloist API key locally without exposing it in chat or shell history."""

import getpass
import os
from pathlib import Path
import subprocess


def main():
    print("Anahtar: https://developer.spotify.com/dashboard/soloist")
    key = getpass.getpass("Soloist API anahtarını yapıştır (gizli): ").strip()
    if not key or any(not (c.isascii() and (c.isalnum() or c in "_-./=")) for c in key):
        raise SystemExit("Geçersiz anahtar biçimi; hiçbir şey kaydedilmedi.")
    directory = Path.home() / ".config/soloist"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "soloist.env"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(f"SOLOIST_API_KEY={key}\n")
    subprocess.run(["systemctl", "--user", "restart", "soloist.service"], check=True)
    print("Anahtar kaydedildi; Soloist başlatıldı.")
    print("Spotify telefon uygulamasında cihazlardan Cano Terminal seç (tek sefer).")
    print("Ardından: spotify watch")


if __name__ == "__main__":
    main()
