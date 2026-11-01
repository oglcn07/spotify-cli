#!/usr/bin/env python3
"""Install the CLI in this checkout; Soloist remains an official external download."""

import argparse
from pathlib import Path
import shlex
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
MARKER = '# spotify-cli managed launcher'


def launcher_text(root):
    return (f'#!/bin/sh\n{MARKER}\n'
            f'exec {shlex.quote(str(root / ".venv/bin/python"))} '
            f'{shlex.quote(str(root / "spotify.py"))} "$@"\n')


def install(root, home, skip_deps=False, no_service=False, replace_launcher=False, dry_run=False):
    root, home = Path(root).resolve(), Path(home)
    interpreter = root / '.venv/bin/python'
    launcher = home / '.local/bin/spotify'
    unit = home / '.config/systemd/user/soloist.service'
    if launcher.exists() and not replace_launcher:
        try:
            managed = MARKER in launcher.read_text()
        except (OSError, UnicodeError):
            managed = False
        if not managed:
            raise RuntimeError('Mevcut spotify komutu korunuyor. Bilerek değiştirmek için --replace-launcher kullan.')
    if dry_run:
        print(f'Sanal ortam: {root / ".venv"}')
        print(f'Başlatıcı: {launcher}')
        if not no_service:
            print(f'Servis: {unit} (varsa korunur)')
        return
    if not interpreter.is_file():
        venv.EnvBuilder(with_pip=True).create(root / '.venv')
    if not skip_deps:
        subprocess.run([str(interpreter), '-m', 'pip', 'install', '-r', str(root / 'requirements.txt')], check=True)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(launcher_text(root))
    launcher.chmod(0o755)
    if not no_service:
        if unit.exists():
            print('Mevcut soloist.service korundu.')
        else:
            unit.parent.mkdir(parents=True, exist_ok=True)
            unit.write_text((root / 'packaging/soloist.service').read_text())
            unit.chmod(0o644)
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    print(f'Kuruldu: {launcher}')
    print('PATH içinde ~/.local/bin bulunmalı. Gerekirse: export PATH="$HOME/.local/bin:$PATH"')
    print('Soloist anahtarı: .venv/bin/python setup_soloist.py')
    print('İsteğe bağlı Spotify Web API: spotify configure ardından spotify login')
    print('Bu klasörü taşımadan kullan; taşırsan kurulum betiğini yeniden çalıştır.')


def main():
    parser = argparse.ArgumentParser(description='Spotify CLI kullanıcı kurulumu (sudo kullanma).')
    parser.add_argument('--no-deps', action='store_true', help='Bağımlılık kurulumunu atla (geliştiriciler için).')
    parser.add_argument('--no-service', action='store_true', help='systemd birimini kurma/yükleme.')
    parser.add_argument('--replace-launcher', action='store_true', help='Mevcut spotify komutunu değiştir.')
    parser.add_argument('--dry-run', action='store_true', help='Dosya değiştirmeden hedefleri göster.')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 veya üzeri gerekiyor (Pillow bağımlılığı).')
    if not sys.platform.startswith('linux'):
        parser.error('Bu kurulum betiği Linux içindir.')
    try:
        install(ROOT, Path.home(), args.no_deps, args.no_service, args.replace_launcher, args.dry_run)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Kurulum tamamlanamadı: {error}\n')


if __name__ == '__main__':
    main()
