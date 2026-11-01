# Spotify CLI 🎵

Linux terminalinden Spotify kontrolü: masaüstü Spotify penceresini açmadan müzik çal, albüm ve sanatçı ara, koleksiyonlarda gezin, kuyruğunu ve favorilerini yönet.

Oynatma için Spotify’ın resmî **Soloist** uygulamasını, arama ve kitaplık işlemleri için **Spotify Web API / Spotipy** kullanır. Bu proje bağımsız bir terminal istemcisidir; Spotify’ın resmî istemcisi değildir.

## Neler var?

- **İki görünüm:** önde bilgi kutuları ve kare kapak arka planı olan Adalar; ayrı kapak paneli olan Klasik.
- Şarkı, albüm, sanatçı ve playlist araması; sayfalama ve koleksiyon içinde gezinme.
- Yerel oynatma kontrolleri, konuma gitme, ses, shuffle ve repeat komutları.
- Kuyruğu görüntüleme, parça ekleme ve Spotify beğenilenleri.
- Yerel sabitlenen koleksiyonlar ve kalıcı görünüm ayarları.
- 8-bit, 16-bit tarzı, Glitch ve ASCII kapak çizimleri.
- Bulunabilirse çevrimiçi sözler; yerel `.lrc` dosyasıyla satır takibi.
- Soloist gerektiğinde başlatılır; Watch’tan çıkmak müziği durdurmaz.

## Gereksinimler

| Gereksinim | Açıklama |
| --- | --- |
| Linux | `systemd --user` oturumu; mevcut uygulama Linux içindir |
| Python **3.11+** | `venv` ve `pip` ile; Pillow bu alt sürüm sınırını gerektirir |
| Ses | Çalışan PipeWire veya PulseAudio |
| Terminal | UTF-8; 256 renk önerilir; rahat kullanım için en az 100×30 |
| Spotify | Soloist API anahtarı oluşturabilen **Premium** hesap |
| Soloist | Kendi mimarine uygun resmî Linux derlemesi |
| Web API Client ID | **İsteğe bağlı:** arama, koleksiyon tarama ve favoriler için kendi uygulaman |

Soloist gereksinimleri ve güncel indirmeler: [resmî başlangıç rehberi](https://developer.spotify.com/documentation/soloist/tutorials/getting-started), [indirmeler](https://developer.spotify.com/documentation/soloist/reference/downloads-and-updates).

## Kurulum

### 1. Sistem paketleri

Ubuntu/Debian örneği:

```bash
sudo apt update
sudo apt install git curl python3 python3-venv python3-pip
python3 --version
```

Python sürümünün **3.11 veya daha yeni** olduğundan emin ol. Daha eski dağıtımlarda uygun Python sürümünü ayrıca kurmalısın. Ses sisteminin ve kullanıcı systemd oturumunun çalışır durumda olması gerekir. Diğer dağıtımlarda eşdeğer paketleri kullan.

### 2. Soloist’i resmî kaynaktan indir

Önce mimarini kontrol et:

```bash
uname -m
```

Aşağıdaki örnek **x86_64 Linux** içindir. ARM için [resmî indirme sayfasından](https://developer.spotify.com/documentation/soloist/reference/downloads-and-updates) uygun arşivi seç.

```bash
soloist_tmp=$(mktemp -d)
curl --fail --location \
  https://soloist-builds.spotifycdn.com/soloist_release_x86_64.tar.gz \
  --output "$soloist_tmp/soloist.tar.gz"
tar -xzf "$soloist_tmp/soloist.tar.gz" -C "$soloist_tmp"
mkdir -p "$HOME/.local/bin"
install -m 755 "$soloist_tmp/soloist" "$HOME/.local/bin/soloist"
"$HOME/.local/bin/soloist" --version
```

İndirme/açma işlemi hata verirse devam etme. Geçici dizini işin bitince kaldırabilirsin. Soloist arşivleri ve çalıştırılabilir dosyaları bu depoda dağıtılmaz; her kullanıcı resmî kaynaktan indirir. Derleme süresi dolarsa aynı sayfadan güncelle.

### 3. Projeyi indir ve kur

```bash
git clone https://github.com/oglcn07/spotify-cli.git
cd spotify-cli
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
```

Betik bu klasörde `.venv` oluşturur, `requirements.txt` bağımlılıklarını yükler, `~/.local/bin/spotify` başlatıcısını ve kullanıcı servisini hazırlar. **`sudo python3 install.py` kullanma.**

- Mevcut `spotify` komutunun üzerine otomatik yazmaz. Bilerek değiştirmek istersen `python3 install.py --replace-launcher` kullan.
- Mevcut `soloist.service` dosyasını korur; yalnız yeni kurulumda örnek servisi oluşturur.
- Kurulum servisi otomatik etkinleştirmez veya müziği başlatmaz.
- Proje klasörü kurulumdan sonra yerinde kalmalı. Taşırsan kurulum betiğini yeniden çalıştır.
- `~/.local/bin` kalıcı PATH’inde yoksa kullandığın kabuğun başlangıç dosyasına ekle.

### 4. Kendi Soloist anahtarını kaydet ve cihazı eşleştir

[Spotify Soloist anahtar sayfasından](https://developer.spotify.com/dashboard/soloist) **kendi hesabına ait** anahtarı oluştur. Ardından proje klasöründe:

```bash
.venv/bin/python setup_soloist.py
```

Anahtar gizli istemde alınır ve `~/.config/soloist/soloist.env` dosyasına yalnız sahibinin okuyabileceği şekilde yazılır. Servis başlatılır/yeniden başlatılır.

Telefonundaki Spotify uygulamasında, aynı yerel ağdayken cihaz listesinden **Cano Terminal** seç. İlk eşleştirme tamamlandıktan sonra:

```bash
spotify watch
```

Bu aşamada yerel oynatma, ses ve kuyruk kontrolleri kullanılabilir. Arama ve favoriler için aşağıdaki adımı da tamamla.

### 5. Spotify Web API’yi bağla (isteğe bağlı)

Soloist anahtarı ile Web API **Client ID farklı şeylerdir**. Bu depo sahibinin hesabı veya anahtarı indirenlere verilmez; herkes kendi uygulamasını kullanır.

1. [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) üzerinden kendi Web API uygulamanı oluştur.
2. Uygulamanın Redirect URI alanına tam olarak **`http://127.0.0.1:8888/callback`** ekle.
3. Client ID’yi al. **Client Secret gerekmiyor:** PKCE kullanıyoruz.
4. Terminalde:

```bash
spotify configure
spotify login
```

`configure` Client ID’yi yerel olarak kaydeder. `login` sırasında Spotipy’nin gösterdiği yetkilendirme bağlantısını tarayıcıda açıp yönergeleri tamamla. Callback için `8888` portu kullanılabilir olmalı. SSH/uzak makinede loopback callback için tünel veya aynı makinede tarayıcı gerekebilir.

Alternatif olarak `SPOTIFY_CLIENT_ID` ortam değişkeni verilebilir. [.env.example](.env.example) yalnız örnektir; otomatik yüklenmez.

Web API erişimi Spotify’ın uygulama modu, hesap, izin ve kota kurallarına bağlıdır. Kendi Client ID’sini kullanmak tüm endpoint’lere erişimi garanti etmez. Arama veya favoriler reddedilse bile Soloist yerel kontrolleri kullanılabilir.

## Kullanım

```bash
spotify watch
spotify play "Arctic Monkeys 505"
spotify play --album "Arctic Monkeys AM"
spotify play --playlist "playlist adı" --shuffle
spotify pause
spotify resume
spotify next
spotify prev
spotify now
spotify volume 50
spotify seek 2:15
spotify shuffle on
spotify repeat track
spotify queue
spotify pins
```

## Watch kısayolları

| Tuş | İşlem |
| --- | --- |
| `Space` | Oynat / duraklat |
| `n` / `p` | Sonraki / önceki parça |
| `←` / `→` | 5 saniye sar |
| `Shift+←` / `Shift+→` | Terminal destekliyorsa 30 saniye sar |
| `g` | Saniye veya `2:15` gibi belirli bir konuma git |
| `+` / `-` | Sesi 5 puan değiştir |
| `z` / `r` | Shuffle / repeat |
| `/`, sonra `Tab` | Ara; şarkı / albüm / sanatçı / playlist türünü değiştir |
| `↑` / `↓` | Listede seç |
| `Enter` | Seçili parçayı/koleksiyonu çal |
| `o` | Seçili koleksiyonun içine gir |
| `[` / `]` | Önceki / sonraki sayfa |
| `Esc` | Önceki liste / aramadan çık |
| `k` | Kuyruğu aç / yenile |
| `e` | Seçili veya çalan şarkıyı kuyruğa ekle |
| `f` / `l` | Beğenilenleri aç / şarkıyı beğen |
| `b` / `B` | Koleksiyon sabitle-kaldır / sabitlenenleri aç |
| `t` | Adalar ↔ Klasik görünüm |
| `a` / `v` | Kapak çizim modu / kapağı aç-kapat |
| `s` | Sağdaki söz panelini aç-kapat |
| `PgUp` / `PgDn` | Düz sözleri kaydır |
| `,` | Parlaklık ve kutu genişlikleri |
| `?` | Kaydırılabilir yardım |
| `q` / `Ctrl+C` | Çık; müzik devam eder |

`q` arama yazarken normal harftir; aramadan `Esc` ile çıkabilirsin.

## Şarkı sözleri

Çevrimiçi kaynaklar LRCLIB ve lyrics.ovh’dir. Parça başlığı, sanatçı ve gerekirse albüm/süre bu servislere gönderilir. Musixmatch yalnız kendi `MUSIXMATCH_API_KEY` değişkenini tanımlarsan isteğe bağlı denenir; ücretsiz anahtar veya zamanlı erişim vaat edilmez.

**Otomatik zamanlama garanti değildir.** Servis çalışmayabilir veya yalnız düz metin döndürebilir. Panelde `Zamanlama yok` yazıyorsa mevcut veride satır zamanları yoktur; aktif satır takibi yapılamaz. Türkçe kapsamı da kaynağa göre değişir.

Elinde doğru kayda ait UTF-8 zamanlı söz dosyası varsa, ilgili şarkı çalarken:

```bash
spotify lyrics import ~/Downloads/505.lrc
spotify lyrics path
```

Watch’ta `s` ile paneli kapatıp yeniden aç. Yerel LRC önceliklidir; aktif satır kalın gösterilir ve otomatik kayar. Dosyalar kendiliğinden indirilmez veya otomatik zamanlanmaz.

## Ayarlar ve yerel dosyalar

| Konum | İçerik |
| --- | --- |
| `~/.config/spotify-cli/oauth.json` | Kendi Web API Client ID’n |
| `~/.config/spotify-cli/token-*.json` | OAuth erişim/yenileme token’ları; özel dosyalar |
| `~/.config/spotify-cli/preferences.json` | Görünüm, ses ve panel tercihleri |
| `~/.config/spotify-cli/pins.json` | Yerel sabitlenen koleksiyonlar |
| `~/.config/spotify-cli/lyrics/` | İçe aktarılan LRC dosyaları |
| `~/.config/soloist/soloist.env` | Soloist API anahtarı; özel dosya |
| `~/.local/share/soloist/` | Soloist eşleşme ve oturum verileri |
| `~/.config/systemd/user/soloist.service` | Kullanıcı servisi |

Anahtar, token ve oturum dosyalarını paylaşma. `.gitignore`, yerel sanal ortamı, eski yedekleri, token dosyalarını ve Soloist arşivlerini Git’ten dışlar.

## Sorun giderme

**`spotify: command not found`**

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**Soloist başlamıyor / ses yok**

```bash
systemctl --user status soloist.service
journalctl --user -u soloist.service -n 30
"$HOME/.local/bin/soloist" --version
```

Anahtarın kaydedildiğini, resmî derlemenin güncel olduğunu, ses oturumunu ve Spotify Connect eşleşmesini kontrol et. Günlük paylaşmadan önce anahtar ve oturum bilgilerini temizle.

**Playlist içeriği 403 veriyor**: Spotify bu koleksiyonun Web API üzerinden listelenmesini reddediyor olabilir. Arama sonucunu oynatmak ile içeriğini listelemek farklı işlemlerdir.

**Shuffle/repeat değişmiyor**: Mevcut oynatma bağlamı komutu kısıtlıyor olabilir. Uygulama gerçek durumu kontrol eder ve uygulanmayan komutu başarı gibi göstermez.

**Sözler gelmiyor / zamanlama yok**: Söz kaynağının erişimi ve verisiyle ilgilidir; ücretsiz senkron söz garantisi yoktur. Yerel LRC kullanılabilir.

**Kapak/söz paneli görünmüyor**: `v` / `s` tuşlarını ve terminal boyutunu kontrol et. Söz paneli en az 76 sütun ve 18 satır ister; tüm alanlar için daha geniş terminal kullan.

Servisi elle durdurmak:

```bash
systemctl --user stop soloist.service
```

## Güncelleme

Proje klasöründe:

```bash
git pull --ff-only
python3 install.py
```

Soloist ayrı güncellenir: resmî arşivden yeni çalıştırılabilir dosyayı indir, `~/.local/bin/soloist` dosyasını değiştir ve kullanıcı servisini yeniden başlat. Bu depo Soloist’i yeniden dağıtmaz.

## Geliştirme ve testler

```bash
.venv/bin/python -m unittest discover -v
.venv/bin/python -m py_compile spotify.py setup_soloist.py install.py
```

Çevrimdışı testler Spotify’a bağlanmaz ve oynatmayı değiştirmez. GitHub Actions, Python 3.11 / 3.12 / 3.13 üzerinde aynı testleri çalıştıracak şekilde yapılandırılmıştır. Canlı oynatma ve API davranışı hesap, Soloist sürümü ve Spotify izinlerine bağlıdır.

Daha fazla teknik not: [HEADLESS.md](HEADLESS.md). Katkı rehberi: [CONTRIBUTING.md](CONTRIBUTING.md).

## Lisans

Bu projenin kaynak kodu [MIT](LICENSE) lisanslıdır. Soloist, Spotify ve kullanılan üçüncü taraf bileşenlerin kendi lisans ve kullanım koşulları geçerlidir; Soloist ikili dosyası bu lisansla dağıtılmaz.
