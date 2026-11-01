# Katkı rehberi

Hata bildirimi veya pull request açabilirsin. Python 3.11+ kullan; dört boşluk,
`snake_case` adlandırma ve Türkçe terminal mesajları mevcut kodla uyumlu olsun.

## Yerel geliştirme

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -v
```

Çevrimdışı testlerde Spotify, subprocess ve zamanı mock'la. Curses çizimini UI
thread'inde tut; API/görsel indirmelerini işçiye bırak. Normal renk modlarında
`color_pair` kimlikleri 256'dan küçük kalmalı. Canlı test yaptıysan hangi
komutları denediğini ve oynatmayı değiştirip değiştirmediğini PR'da yaz.

## Hata bildirirken

İşletim sistemi, Python sürümü, terminal boyutu, komut ve beklenen/gerçek davranış
yeterlidir. Token, Soloist anahtarı, `soloist.env`, hesap oturumu veya temizlenmemiş
günlük paylaşma.

## Değişiklik önerirken

Somut davranış değişikliğini, ilgili komutları ve test sonucunu belirt. Mevcut iki
tasarımı, komut takma adlarını ve Unicode arama davranışını koru. Yeni ağ kaynağını
çalıştığını doğrulamadan varsayılan kaynak yapma.
