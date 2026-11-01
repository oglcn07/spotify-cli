# Penceresiz Spotify

Oynatıcı: Spotify'ın resmi Soloist uygulaması. Masaüstü Spotify açılmaz.
Eski Spotifyd denemesi ses anahtarı hatası nedeniyle durduruldu.

## İlk bağlantı

1. https://developer.spotify.com/dashboard/soloist adresinde Soloist API
   anahtarını oluştur. Web API client ID'sinden ve `.token-cache` dosyasından farklıdır.
2. `python3 ~/spotify-cli/setup_soloist.py` çalıştırıp anahtarı gizli isteme
   yapıştır. Sohbette paylaşma. Anahtar `~/.config/soloist/soloist.env` içinde tutulur.
3. Telefonundaki Spotify'da, aynı yerel ağdayken cihaz listesinden
   **Cano Terminal** seç. Bu ilk eşleştirme için gerekir; sonraki oturumlar saklanır.
4. `spotify watch` aç. Arama için mevcut Spotipy hesabı bağlantısı kullanılır.

## Kullanım

`spotify play "şarkı sanatçı"`, `spotify pause`, `spotify resume`,
`spotify next`, `spotify prev`, `spotify now`, `spotify volume 50`.
Watch içinde Space, n/p ve / tuşları çalışır. Playlist bilgisi yerel oynatıcıdan gelir.
Terminal en az 90 sütun genişliğindeyse sağda albüm kapağı görünür.
`a` ile 8-bit piksel → 16-bit tarzı detaylı → Glitch → ASCII → 8-bit döngüsünde geçilir.
Glitch, önceki deneysel sürümün bozuk renk efektini korur.
Detaylı mod yarım karakter blokları kullanır; renk sayısı terminal desteğine bağlıdır.
Kapak arka planda
indirilir; görüntü alınamasa da oynatıcı ve kontroller çalışmaya devam eder.
Python bağımlılıkları: `.venv/bin/python -m pip install -r requirements.txt`.

Servis gerektiğinde CLI tarafından başlatılır; oturum açılışında otomatik başlama
etkinleştirilmedi. Elle durdurmak: `systemctl --user stop soloist`.
Durum: `soloist ctl status`. Hata günlüğü: `journalctl --user -u soloist -n 30`.
`watch` ekranından çıkmak müziği durdurmaz.

## Kuyruk, favoriler ve tercihler

- `k`: Soloist kuyruğunu gösterir; tekrar basınca yeniler. Oklarla kaydırılır.
- Arama veya favori listesinde `e`: seçili şarkıyı sıraya ekler. Ana ekranda
  `e`, çalan şarkıyı sıraya ekler. `Enter` seçili şarkıyı hemen çalar.
- `l`: ana ekranda çalanı, listelerde seçileni Spotify beğenilenlerine ekler.
- `f`: Spotify beğenilenlerini açar. Oklarla seç, Enter ile çal;
  `[` / `]` ile önceki / sonraki 20 şarkıya geç.
- `?`: klavye yardımını açar/kapatır. `Esc` ana ekrana döner.
- `+` / `-`: sesi 5 puan değiştirir. `v` kapağı gösterir/gizler.
- `spotify queue`: kuyruğu watch dışında yazdırır.

Favoriler için bir kez `spotify login` çalıştırıp gösterilen bağlantı üzerinden
`user-library-read` ve `user-library-modify` izinlerini ver. Bu işlem watch dışında
yapılır; ek izin verilmeden yerel kuyruk ve oynatma kontrolleri kullanılabilir.
Hesap veya uygulama Spotify Web API erişimini kısıtlıyorsa favori işlemleri hata
bildirir; yerel oynatma çalışmaya devam eder.

Kapak modu, arka plan ve söz paneli görünürlüğü, ses seviyesi
`~/.config/spotify-cli/preferences.json` dosyasında saklanır. Watch yeniden
açıldığında bu tercihler uygulanır; `spotify volume` da kayıtlı sesi günceller.
Kuyruk ekranı açıldığında anlık görüntü alınır; güncellemek için `k` kullan.

Spotify kayıt endpoint'i: https://developer.spotify.com/documentation/web-api/reference/save-library-items

## Güncelleme

Soloist sürümleri derleme tarihinden itibaren 90 gün geçerlidir. Süre dolunca
resmi indirme sayfasından yeni x86_64 Linux paketini indirip
`~/.local/bin/soloist` dosyasını güncelle ve servisi yeniden başlat.

Resmi rehber: https://developer.spotify.com/documentation/soloist/tutorials/getting-started
İndirmeler: https://developer.spotify.com/documentation/soloist/reference/downloads-and-updates

API anahtarını, `.token-cache` dosyasını ve `~/.local/share/soloist` içindeki
oturum verilerini sürüm kontrolüne ekleme.

## Şarkı sözleri

`spotify watch`, kapağı karartılmış ve büyütülmüş arka plan olarak gösterir.
Bilgiler ve listeler öndeki kutularda, sözler sağdaki ayrı kutuda yer alır.
`s` söz panelini gizler/gösterir; tam ekrana geçmez. Söz paneli için en az
76 sütun ve 18 satır gerekir. Görünürlük tercihi sonraki açılışta hatırlanır. Zamanlı sözlerde çalan satır
vurgulanır ve otomatik takip edilir. Düz sözleri `PgUp` / `PgDn` ile kaydır.

Kaynak: [LRCLIB](https://lrclib.net/docs); ulaşılamazsa veya söz bulunamazsa
[lyrics.ovh](https://github.com/NTag/lyrics.ovh) üzerinden düz söz denenir.
Panelde kullanılan kaynağın adı gösterilir. Başlık, sanatçı, albüm ve süre
LRCLIB'e; yedek aramada sanatçı ve başlık lyrics.ovh'ye gönderilir.
Spotify oturum bilgileri gönderilmez. Ek paket veya
API anahtarı gerekmez. Sözler ayrı bir işçide yüklenir; bu oturumda son 32
parça bellekte tutulur. Her parçada söz veya zamanlama bulunmayabilir.
Bağlantı hataları önbelleğe alınmaz; aynı parça için en az 30 saniye sonra
otomatik yeniden denenir. Servisin `Retry-After` süresi varsa ona uyulur.
İki kaynakta da bulunamayan sözler için denemeler en az 5 dakika arayla yapılır.
`s` ile söz panelini yeniden açmak da denemeyi tetikler; servis bekleme süresi korunur.

Söz alınamazsa panel her kaynağın hata kodunu ayrı gösterir ve yeniden deneme
süresini sayar. lyrics.ovh tam sanatçı listesiyle sonuç bulamazsa (404),
yalnız ilk sanatçıyla bir kez daha dener; servis hatalarında bu ek istek yapılmaz.

### Musixmatch (isteğe bağlı)

Resmî [Musixmatch geliştirici hesabından](https://developer.musixmatch.com/)
API anahtarı al. Planın `matcher.subtitle.get` erişimini desteklemesi zamanlı
söz için gereklidir; anahtar tek başına zamanlı söz yetkisini garanti etmez.
[Resmî API koleksiyonu](https://www.postman.com/musixmatch-dev/musixmatch-apis/overview).

Bash terminalinde anahtarı ekrana veya komut geçmişine yazmadan bu oturum için tanımla:

```bash
read -rsp 'Musixmatch API anahtarı: ' MUSIXMATCH_API_KEY
printf '\n'
export MUSIXMATCH_API_KEY
spotify watch
```

Anahtar sohbete, kaynak koda veya preferences.json içine yazılmaz; yalnız bu
terminalden başlatılan uygulamanın ortamında tutulur. Terminali kapatınca kaybolur.
Kaldırmak için `unset MUSIXMATCH_API_KEY` kullan.

Anahtar tanımlıysa, LRCLIB zamanlı söz veremediğinde Musixmatch denenir.
Başlık, sanatçı ve süre resmî `api.musixmatch.com` servisine gönderilir.
Önce `matcher.subtitle.get` LRC çıktısı istenir; söz bulunamazsa veya zamanlı
söz yetkisi yoksa `matcher.lyrics.get` ile düz söz denenir. Sonrasında mevcut
lyrics.ovh yedeği kullanılabilir. API'nin restricted işaretlediği içerik gösterilmez.
API anahtarı/plan hatası terminale anahtar veya istek URL'si yazılmadan bildirilir.

Panelde `Canlı` varsa aktif satır kalın ve ters renkli görünür; otomatik kayar.
`Zamanlama yok` düz metnin geldiğini belirtir, tahmini zamanlama yapılmaz.
Anahtar alındıktan sonra doğrulama parçaları: Sertab Erener — Aşk,
Yung Ouzo — en baba rüzgarda yanar ateş (GODBLESS), Arctic Monkeys — 505.
Bu parçaların Musixmatch kapsamı henüz canlı doğrulanmadı.

Ek çevrimdışı kontroller:
`.venv/bin/python -m unittest -v test_watch test_lyrics test_musixmatch`

### Ücretsiz, yerel zamanlı söz dosyaları

Anahtarsız alternatifler bu ortamda canlı denendi: NetEase `-462`, lrcmux `403`,
Megalobiz `410` döndürdü. Bu kaynaklar çalışan birer yedek olarak eklenmedi.

Elindeki UTF-8 `.lrc` dosyasını kullanmak için ilgili parçayı çalarken:

```bash
spotify lyrics import ~/Downloads/505.lrc
```

Dosya doğrulanır ve `~/.config/spotify-cli/lyrics/` altına atomik olarak kopyalanır.
Başlık, sanatçı ve albüm eşleştirilir; konser/stüdyo albümleri ayrı tutulur.
Bu işlem oynatmayı değiştirmez ve hiçbir söz servisine istek göndermez.
Yalnız düz metin olan, zaman damgası içermeyen veya 1 MiB'den büyük dosyalar reddedilir;
hatalı dosya mevcut geçerli söz dosyasının üzerine yazılmaz.

Çalan parçanın beklenen dosya yolunu görmek için `spotify lyrics path` kullan.
Watch'ta `s` ile söz panelini yeniden aç veya watch'ı yeniden başlat.
Yerel LRC varsa internet kaynaklarından önce kullanılır; ekranda `Yerel LRC · Canlı`
yazar. Aktif satır kalın ve ters renkli gösterilir, otomatik kayar; duraklatma ve
parçada başka zamana geçme takip edilir. Saniyenin kesirleri de hesaba katılır.
Yerel dosya yoksa mevcut internet kaynakları denenmeye devam eder.

LRC dosyası satır başına gerçek zamanları içermelidir. Biçim örneği (şarkı sözü değildir):

```text
[00:10.50] İlk örnek satır
[00:14.20] İkinci örnek satır
```

Dosya indirilmez veya kendiliğinden zamanlanmaz; doğru kayda ait zamanlı söz dosyasını
sen sağlamalısın. Dosyayı düzenledikten sonra `s` ile yeniden açarak tekrar yükle.

Kontroller:
`.venv/bin/python -m unittest -v test_watch test_lyrics test_musixmatch test_local_lyrics`

Düz söz bulunması zamanlı söz aramasını durdurmaz: sözler ekranda kalırken
LRCLIB en az 30 saniye arayla yeniden denenir (servis bekleme süresi korunur).
Zamanlı sürüm bulunursa aktif parça otomatik olarak ona geçer. LRCLIB erişilemiyorsa
ve yerel LRC yoksa düz sözlerde aktif satır takibi yapılamaz.

## Watch araması ve arka plan

- `/`: Arama kutusunu aç. Yazarken `Tab` ile Şarkı → Albüm → Sanatçı → Playlist
  türleri arasında geç. `Enter` arar; `Esc` vazgeçer.
- Sonuçlarda oklarla seç, `Enter` ile seçilen Spotify URI'sini Soloist'e gönder.
  Albüm/sanatçı/playlist sonuçları koleksiyon URI'siyle açılır.
- Sayfa başına en fazla 10 sonuç gelir. `[` / `]` önceki/sonraki sayfadır.
- `e` ve `l` yalnız şarkı sonuçlarında sıraya ekler/beğenir; koleksiyonları
  bu işlemlere göndermez.
- `v`: Büyük kapak arka planını göster/gizle. `a`: 8-bit, 16-bit, Glitch, ASCII.
  Görsel kırpılmadan, kullanılabilir alana sığan en büyük kare olarak ortalanır;
  üst kenarı ve alt bilgi satırlarını aşmaz. Öndeki kutular opaktır.
- `s`: Sağ söz panelini aç/kapat. Gizliyken yeni söz isteği gönderilmez;
  açarken yerel dosyalar yeniden kontrol edilir.

Yeni düzen kontrolleri:
`.venv/bin/python -m unittest -v test_watch test_watch_ui test_lyrics test_musixmatch test_local_lyrics`

Canlı doğrulamada dört arama türü de Spotify'dan sonuç döndürdü. Yeni koleksiyon
seçimlerinin gerçek oynatmayı başlatması canlı denenmedi; URI gönderimi çevrimdışı
kontrol edildi.

### İki tasarım

`t` ile **Adalar** ve **Klasik** tasarımlar arasında geçilir. Seçim
`preferences.json` içindeki `design` alanına kaydedilir ve yeniden açılışta korunur.
Adalar tasarımı: kare kapak arka planda, metinler öndeki kutularda.
Klasik tasarım: bilgiler solda, kapak ayrı orta/sağ panelde, sözler en sağda;
arka plan ve kutu çizimi yoktur. Alan yetmezse kapak paneli gizlenir.
İki tasarımda da `s` sözleri, `v` kapağı açar/kapatır; arama türleri ve
sayfalama aynıdır. `a` kapak çizim modunu değiştirir.

## Koleksiyon tarayıcısı, oynatma ve hızlı erişim

Watch içinde yeni kontroller:

| Tuş | İşlem |
| --- | --- |
| `o` | Seçilen albüm/playlist içindeki şarkıları veya sanatçının albümlerini aç |
| `Esc` | Koleksiyonda önceki listeye ve seçime dön |
| `[` / `]` | Koleksiyonlarda önceki/sonraki 10 öğe |
| `Enter` | Seçili şarkıyı veya koleksiyonu çal |
| `←` / `→` | 5 saniye geri/ileri sar |
| `Shift+←` / `Shift+→` | Terminal bu tuşları iletiyorsa 30 saniye sar |
| `g` | Saniye veya `dakika:saniye` girerek belirli konuma git |
| `z` | Karışık çalmayı değiştir |
| `r` | Tekrarı kapalı → koleksiyon → tek şarkı şeklinde değiştir |
| `b` | Seçilen koleksiyonu sabitle veya sabitlemeyi kaldır |
| `B` | Yerel sabitlenenler listesini aç |
| `,` | Görünüm ayarlarını aç; ↑/↓ ile seç, ←/→ ile değiştir |

Koleksiyon içerikleri API işçisinde yüklenir. Playlist içerikleri için güncel
`playlists/{id}/items` endpoint'i kullanılır; eski/yenilenmiş yanıt biçimlerindeki
`track` ve `item` alanları okunabilir. Yerel parçalar, podcast bölümleri ve boş
öğeler gösterilmez. API bir playlist'i okumaya izin vermiyorsa (403), mevcut liste
korunur ve hata gösterilir. Koleksiyon çalma ile içeriğini API'den listeleme ayrı
izin ve hizmet kısıtlamalarına tabidir. `o` ek kitaplık yetkisi istemez.

Sarma ve oynatma modları WatchAPI işçisinde yerel Soloist kontrolünden gönderilir;
terminal çizimi beklemez. Shuffle/repeat komutlarından sonra gerçek oynatma durumu
kontrol edilir. Spotify komutu mevcut bağlamda reddederse başarılı mesajı verilmez.
Şarkı bilgisinin altındaki modlar oynatıcıdan okunur, varsayılmaz.

Komut satırında da kullanılabilir:

```bash
spotify seek 2:15
spotify shuffle on
spotify repeat track
spotify pins
spotify pin spotify:album:ALBUM_ID Kısa Ad
spotify unpin spotify:album:ALBUM_ID
```

`spotify shuffle` ve `spotify repeat`, argümansız çalıştırıldığında Watch'taki gibi
mevcut modu değiştirir. Sabitlenenler `~/.config/spotify-cli/pins.json` içinde
saklanır; Spotify beğenilenlerini değiştirmez. Aynı URI'yi yeni adla `pin` etmek
kısa adını günceller. En fazla 100 albüm/sanatçı/playlist sabitlenebilir.

Görünüm ayarları parlaklık (%15–85), bilgi kutusu genişliği (32–68 sütun) ve söz
kutusu genişliğini (24–64 sütun) kaydeder. Gerçek çizim terminale sığacak şekilde
sınırlanır. Kare kapak geometrisi ve söz paneli açılırken sabit bilgi kutusu
korunur. `?` yardımı artık ↑/↓ veya PgUp/PgDn ile kaydırılabilir.

Doğrulama: Albümün 10+2 parçalık iki sayfası ve sanatçının iki albüm sayfası canlı
okundu. Örnek herkese açık playlist içeriği Spotify tarafından 403 ile reddedildi.
Sarma bağlı Soloist üzerinde doğrulandı. Mevcut tek-parça bağlamında shuffle/repeat
uygulanmadı; Spotify API denemesi de `Restriction violated` döndürdü. Önceki
shuffle/repeat ayarları geri yüklendi. Bu bağlam sınırı kodda başarı gibi gösterilmez.

Tam çevrimdışı kontroller:
`.venv/bin/python -m unittest -v test_watch test_watch_ui test_lyrics test_musixmatch test_local_lyrics test_features`
