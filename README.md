# Tahta Kumanda

Pardus (Debian 12 tabanlı) akıllı tahtayı, aynı Wi-Fi'deki telefondan **uygulama kurmadan**
(yalnızca tarayıcıyla) yönetmek için yerel sunucu:

- **Trackpad + klavye**: telefon tarayıcısında açılan sayfa, WebSocket üzerinden tahtaya anlık
  fare/klavye olayı gönderir.
- **Sunum kumandası**: önceki/sonraki slayt, F5, siyah ekran, ses.
- **Ekran yansıtma**: iPhone/iPad için AirPlay (UxPlay), Android için Wi-Fi üzerinden scrcpy.
- **Dosya aktarımı**: telefondan tahtaya fotoğraf/video/PDF/sunum gönderme, tahtada açma,
  tahtadaki dosyaları telefona indirme.
- **Masaüstü paneli**: tahta açılınca adres, PIN, Wi-Fi adı ve QR kodu gösteren, gizlenip
  yeniden açılabilen pencere.

## Mimari ve teknik tercihler

```
 Telefon (Chrome/Safari)                       Pardus akıllı tahta
 ┌──────────────────────┐   HTTP :8000   ┌──────────────────────────────┐
 │ index.html / app.js  │ ─────────────► │ Starlette (uvicorn)          │
 │ trackpad, klavye     │   WebSocket    │  /ws  → uinput sanal fare     │
 │ sunum, dosya, yansıt │ ◄────────────► │         + sanal klavye        │
 └──────────────────────┘                │  /api/cast → adb + scrcpy     │
          │ AirPlay (iOS yerleşik)        │  arka planda UxPlay (AirPlay) │
          └──────────────────────────────►│                              │
                                          └──────────────────────────────┘
```

| Konu | Seçim | Neden |
|---|---|---|
| Sunucu | Python **Starlette + uvicorn**, WebSocket | FastAPI'nin üzerine kurulduğu hafif çatı; Pardus deposunda da var (internetsiz kurulum). |
| Dosya aktarımı | Ham gövdeli **HTTP PUT** akışı | Dosya belleğe alınmadan doğrudan diske yazılır; ilerleme çubuğu, büyük video dosyaları sorunsuz. |
| Masaüstü paneli | **GTK3** (python3-gi) | Pardus'un kendi uygulamaları gibi yerel pencere; X11 ve Wayland'da çalışır. |
| Fare/klavye | **uinput** (python3-evdev) | Çekirdek düzeyinde gerçek USB aygıtı gibi davranır: **X11 ve Wayland**'da, giriş ekranında ve tam ekran uygulamalarda aynı şekilde çalışır. xdotool/pyautogui/pynput yalnızca X11'de güvenilirdir. |
| iPhone yansıtma | **UxPlay** (AirPlay alıcısı) | iOS'ta yerleşik; ek uygulama yok, düşük gecikme, donanımsal çözme. |
| Android yansıtma | **scrcpy + Kablosuz hata ayıklama (ADB)** | Linux'ta kararlı bir Miracast/Chromecast *alıcısı* yok (gnome-network-displays yalnızca *gönderici*). scrcpy H.264 ile ~50-100 ms gecikme verir, tahtadan dokunarak telefonu kontrol bile edebilirsiniz. |
| getDisplayMedia (WebRTC) | **Kullanılmadı** | Android Chrome ve iOS Safari'de ekran paylaşımı API'si yok; ayrıca HTTPS ister. Telefondan tarayıcı ile yansıtma bu nedenle mümkün değil. |

## 1. Kurulum

```bash
# Klasörü tahtaya kopyalayın (ör. ~/tahta-kumanda), sonra tahtadaki kullanıcıyla:
cd ~/tahta-kumanda
chmod +x install.sh
./install.sh            # root DEĞİL; gerekli yerde sudo şifresi sorar
# Ardından oturumu bir kez kapatıp açın (uinput izni için)
```

`install.sh` şunları yapar:

```bash
sudo apt install python3 python3-venv python3-pip python3-evdev \
     python3-starlette python3-uvicorn python3-websockets \
     python3-gi gir1.2-gtk-3.0 qrencode xdg-utils xdg-user-dirs \
     avahi-daemon libnss-mdns curl unzip iproute2 libnotify-bin \
     uxplay scrcpy xdotool gir1.2-ayatanaappindicator3-0.1 \
     gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
     gstreamer1.0-libav gstreamer1.0-gl gstreamer1.0-x gstreamer1.0-vaapi
```

- `/dev/uinput` için udev kuralı + `uinput` modülünü açılışta yükleme, kullanıcıyı `input` grubuna ekleme
- Google'dan güncel **adb** (platform-tools) indirme (kablosuz eşleştirme için adb 30+ gerekir; depodaki eski olabilir)
- `.venv` sanal ortamı (`--system-site-packages`) ve `requirements.txt`
- avahi-daemon'u açma; ufw etkinse portları açma (8000/tcp, 7000,7001,7100/tcp, 6000,6001,7011/udp, 5353/udp)
- Oturum açılınca **Tahta Kumanda panelini** otomatik açma (`~/.config/autostart`) ve uygulama menüsüne
  **"Tahta Kumanda"** kısayolu ekleme; kurulum bitince paneli hemen açar

## 2. Dosya yapısı

```
tahta-kumanda/
├── install.sh            # tek seferlik kurulum
├── panel.sh              # masaüstü panelini açar (otomatik başlatma bunu çağırır)
├── start.sh              # yalnızca sunucuyu başlatır (panel bunu kullanır)
├── bilgi.sh              # tahtada adres + PIN'i tam ekran gösterir
├── ayarlar.env.ornek     # ayarlar şablonu (kurulumda ayarlar.env'e kopyalanır)
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py           # Starlette: sayfalar, API, WebSocket, PIN koruması
│   ├── files.py          # dosya aktarımı (yükleme, listeleme, açma, indirme)
│   ├── netinfo.py        # IP adresi ve Wi-Fi adı
│   ├── panel.py          # GTK3 masaüstü paneli
│   ├── panel_core.py     # panelin arayüzden bağımsız kısmı
│   ├── input_device.py   # uinput sanal fare/klavye
│   ├── keymap.py         # Türkçe Q / US karakter→tuş eşlemeleri
│   └── casting.py        # UxPlay (AirPlay) ve adb+scrcpy (Android) yönetimi
├── static/
│   ├── index.html        # telefon arayüzü
│   ├── style.css
│   └── app.js            # trackpad (touchstart/move/end), klavye, dosyalar, paneller
└── tools/platform-tools/ # install.sh indirir (adb)
```

## 3. Kullanım

1. Tahta açılınca **Tahta Kumanda paneli** açılır: adres (ör. `192.168.1.50:8000`), **PIN**,
   bağlı **Wi-Fi adı** ve QR kod görünür. Panel sunucuyu kendisi başlatır.
   - **Gizle** düğmesi (ya da pencereyi kapatmak) paneli gizler; sunucu çalışmaya devam eder.
   - Tekrar göstermek için: uygulama menüsünden **"Tahta Kumanda"**, sistem tepsisindeki simge
     ya da telefonda **Ayarlar → Bağlantı panelini tahtada göster**.
   - **Tam ekran göster**: bilgiyi tüm sınıfın göreceği büyüklükte açar.
   - **Yeni PIN**: PIN'i değiştirir, bağlı telefonların bağlantısını keser.
2. Telefon tahtayla **aynı Wi-Fi**'de olsun; tarayıcıda adresi açıp PIN'i girin (telefon hatırlar).
3. Trackpad hareketleri:
   - Tek parmak: imleç · Dokun: sol tık · İki kez dokun ve sürükle: tut-sürükle
   - İki parmak kaydır: kaydırma · İki parmakla dokun: sağ tık · Üç parmak: orta tık
   - Sağ kenardaki şerit: tek parmakla kaydırma
   - Alttaki **Sol/Sağ** düğmeleri basılı tutulabilir (bir parmak düğmede, diğeri trackpad'de = sürükleme)
4. **Klavye**: telefon klavyesi açılır, yazdıklarınız harf harf tahtaya gider (otomatik düzeltme
   dahil). Üstteki çubukta Esc, Tab, oklar, Kopyala/Yapıştır, Alt+Tab vb. var.
   Uyarı: tahtadaki klavye düzeni `ayarlar.env`'deki `TAHTA_KLAVYE` ile aynı olmalı (varsayılan `tr`).

5. **Dosyalar**: *Telefondan tahtaya gönder* ile bir veya birden çok dosya seçin; ilerleme çubuğu
   görünür. Dosyalar tahtada **Masaüstü/Telefondan Gelenler** klasörüne kaydedilir.
   *Gelince tahtada otomatik aç* işaretliyse dosya gelir gelmez tahtada açılır. Listedeki
   **Aç** dosyayı tahtada açar, **İndir** telefona indirir, **Sil** iki dokunuşla siler.
   Tahtada bu klasöre koyduğunuz dosyalar da telefondan indirilebilir.
   Tek dosya için üst sınır varsayılan 4 GB'dır (`TAHTA_DOSYA_LIMIT_MB`).

Telefonda sayfayı "Ana ekrana ekle" ile kısayol yaparsanız uygulama gibi tam ekran açılır.

## 4. Ekran yansıtma nasıl çalışır?

### iPhone / iPad (AirPlay – önerilen, sıfır kurulum)
UxPlay sunucuyla birlikte arka planda sürekli dinler (çökerse kendiliğinden yeniden başlar).
Telefonda: **Denetim Merkezi → Ekran Yansıtma → "Akıllı Tahta"**. Görüntü tahtada tam ekran açılır;
ses de tahtadan çıkar. Durdurmak için aynı menüden "Yansıtmayı Durdur".

### Android (scrcpy, Wi-Fi ADB)
Telefon başına **bir kez** eşleştirme:
1. Ayarlar → Telefon hakkında → *Yapım numarası*'na 7 kez dokunun.
2. Geliştirici seçenekleri → **Kablosuz hata ayıklama**'yı açın.
3. Ekranı bölün (Chrome + Ayarlar yan yana) — uygulama değiştirince kod penceresi kapanır.
4. "Eşleştirme kodu ile cihaz eşleştir" → çıkan **port** ve **6 haneli kodu** web arayüzündeki
   *Ekranımı Yansıt → Android → 1. Adım*'a yazıp **Eşleştir**.

Sonraki kullanımlarda: Kablosuz hata ayıklama açıkken **Yansıtmayı Başlat**. Sunucu, isteğin
geldiği IP'den telefonu tanır, portu mDNS ile otomatik bulur (`adb mdns services`), `adb connect`
yapar ve scrcpy'yi tahtada tam ekran açar. Bulamazsa Kablosuz hata ayıklama ekranındaki
"IP adresi ve bağlantı noktası" satırındaki portu elle yazın.

## 5. Elle başlatma / durdurma / loglar

```bash
./panel.sh                       # paneli aç / gizlenmiş paneli göster
./start.sh                       # yalnızca sunucu, ön planda, loglar terminalde
./start.sh --arka-plan           # arka planda
pkill -f 'python[0-9.]* -m uvicorn app\.main:app'   # durdur (UxPlay ve scrcpy de kapanır)
tail -f ~/.cache/tahta-kumanda/sunucu.log   # ayrıca uxplay.log, scrcpy.log
cat ~/.config/tahta-kumanda/pin  # geçerli PIN (silerseniz yenisi üretilir)
```

## 6. Sorun giderme

| Belirti | Çözüm |
|---|---|
| Arayüzde "fare/klavye hazır değil: /dev/uinput açılamadı" | Oturumu kapatıp açın; olmazsa `ls -l /dev/uinput` (grup `input` olmalı), `sudo modprobe uinput`. |
| Telefondan sayfa açılmıyor | Aynı ağda mısınız? Okul ağı "istemci yalıtımı (AP isolation)" uyguluyorsa cihazlar birbirini göremez: BT birimine sorun ya da tahtadan/telefondan hotspot kullanın. |
| iPhone listede "Akıllı Tahta"yı görmüyor | `systemctl status avahi-daemon`; ağ mDNS'i engelliyor olabilir (AP isolation). `~/.cache/tahta-kumanda/uxplay.log`'a bakın. |
| AirPlay görüntüsü siyah/donuk | `ayarlar.env` içinde `TAHTA_UXPLAY_ARGS=-vs ximagesink` veya `-avdec` deneyin. |
| Türkçe karakterler yanlış çıkıyor | Tahtadaki düzen ile `TAHTA_KLAVYE` aynı olmalı (`tr` ya da `us`). |
| Panel açılmıyor | Terminalde `./panel.sh` çalıştırıp hatayı görün; `sudo apt install python3-gi gir1.2-gtk-3.0`. |
| Panelde QR kod yok | `sudo apt install qrencode` |
| Tepside simge yok | GNOME'da "AppIndicator" eklentisi kapalı olabilir; panel yine menüden açılır. |
| Dosya gönderilmiyor | Telefonda hata mesajına bakın (yer yok / çok büyük). Klasör: `ayarlar.env` → `TAHTA_DOSYA_KLASORU`. |
| Android "Bağlanılamadı" | Eşleştirme yapıldı mı, Kablosuz hata ayıklama açık mı? Wi-Fi değişince Android bu ayarı kapatır. |

## Güvenlik

Aynı Wi-Fi'deki herkes adresi görebileceği için arayüz **PIN** ister (5 hatalı denemede 1 dakika
engel). Bilgi sayfası (`/bilgi`) yalnızca tahtanın kendisinden açılabilir. Trafik yerel ağda
şifresiz HTTP'dir; PIN'i değiştirmek için paneldeki **Yeni PIN** düğmesini kullanın. Dosyalar yalnızca
belirlenen klasöre yazılır ve oradan okunur; dosya adlarıyla klasör dışına çıkılamaz.

---

© 2026 [Hasan Özdemir](https://github.com/develophasan). Tüm hakları saklıdır.
