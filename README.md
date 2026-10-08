# Tahta Kumanda

Pardus (Debian 12 tabanlı) akıllı tahtayı, aynı Wi-Fi'deki telefondan **uygulama kurmadan**
(yalnızca tarayıcıyla) yönetmek için yerel sunucu:

- **Trackpad + klavye**: telefon tarayıcısında açılan sayfa, WebSocket üzerinden tahtaya anlık
  fare/klavye olayı gönderir.
- **Sunum kumandası**: önceki/sonraki slayt, F5, siyah ekran, ses.
- **Ekran yansıtma**: iPhone/iPad için AirPlay (UxPlay), Android için Wi-Fi üzerinden scrcpy.

## Mimari ve teknik tercihler

```
 Telefon (Chrome/Safari)                       Pardus akıllı tahta
 ┌──────────────────────┐   HTTP :8000   ┌──────────────────────────────┐
 │ index.html / app.js  │ ─────────────► │ FastAPI (uvicorn)            │
 │ trackpad, klavye     │   WebSocket    │  /ws  → uinput sanal fare     │
 │ sunum, yansıt        │ ◄────────────► │         + sanal klavye        │
 └──────────────────────┘                │  /api/cast → adb + scrcpy     │
          │ AirPlay (iOS yerleşik)        │  arka planda UxPlay (AirPlay) │
          └──────────────────────────────►│                              │
                                          └──────────────────────────────┘
```

| Konu | Seçim | Neden |
|---|---|---|
| Sunucu | Python **FastAPI + uvicorn**, WebSocket | Hafif, asenkron; Pardus deposunda da var (internetsiz kurulum). |
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
     python3-fastapi python3-uvicorn python3-websockets \
     avahi-daemon libnss-mdns curl unzip iproute2 libnotify-bin \
     uxplay scrcpy xdotool \
     gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
     gstreamer1.0-libav gstreamer1.0-gl gstreamer1.0-x gstreamer1.0-vaapi
```

- `/dev/uinput` için udev kuralı + `uinput` modülünü açılışta yükleme, kullanıcıyı `input` grubuna ekleme
- Google'dan güncel **adb** (platform-tools) indirme (kablosuz eşleştirme için adb 30+ gerekir; depodaki eski olabilir)
- `.venv` sanal ortamı (`--system-site-packages`) ve `requirements.txt`
- avahi-daemon'u açma; ufw etkinse portları açma (8000/tcp, 7000,7001,7100/tcp, 6000,6001,7011/udp, 5353/udp)
- Oturum açılınca otomatik başlatma (`~/.config/autostart`) ve menüde **"Tahta Kumanda Bilgi"** kısayolu

## 2. Dosya yapısı

```
tahta-kumanda/
├── install.sh            # tek seferlik kurulum
├── start.sh              # sunucuyu başlatır (otomatik başlatma da bunu çağırır)
├── bilgi.sh              # tahtada adres + PIN'i büyük gösterir
├── ayarlar.env.ornek     # ayarlar şablonu (kurulumda ayarlar.env'e kopyalanır)
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI: sayfalar, API, WebSocket, PIN koruması
│   ├── input_device.py   # uinput sanal fare/klavye
│   ├── keymap.py         # Türkçe Q / US karakter→tuş eşlemeleri
│   └── casting.py        # UxPlay (AirPlay) ve adb+scrcpy (Android) yönetimi
├── static/
│   ├── index.html        # telefon arayüzü
│   ├── style.css
│   └── app.js            # trackpad (touchstart/move/end), klavye, paneller
└── tools/platform-tools/ # install.sh indirir (adb)
```

## 3. Kullanım

1. Tahta açılınca sunucu kendiliğinden başlar ve köşede bildirim çıkar:
   `Telefondan şu adrese girin: http://192.168.1.50:8000  PIN: 1234`
   (Bildirimi kaçırdıysanız menüden **Tahta Kumanda Bilgi**.)
2. Telefon tahtayla **aynı Wi-Fi**'de olsun; tarayıcıda adresi açıp PIN'i girin (telefon hatırlar).
3. Trackpad hareketleri:
   - Tek parmak: imleç · Dokun: sol tık · İki kez dokun ve sürükle: tut-sürükle
   - İki parmak kaydır: kaydırma · İki parmakla dokun: sağ tık · Üç parmak: orta tık
   - Sağ kenardaki şerit: tek parmakla kaydırma
   - Alttaki **Sol/Sağ** düğmeleri basılı tutulabilir (bir parmak düğmede, diğeri trackpad'de = sürükleme)
4. **Klavye**: telefon klavyesi açılır, yazdıklarınız harf harf tahtaya gider (otomatik düzeltme
   dahil). Üstteki çubukta Esc, Tab, oklar, Kopyala/Yapıştır, Alt+Tab vb. var.
   Uyarı: tahtadaki klavye düzeni `ayarlar.env`'deki `TAHTA_KLAVYE` ile aynı olmalı (varsayılan `tr`).

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
./start.sh                       # ön planda, loglar terminalde
./start.sh --arka-plan           # arka planda
pkill -f "uvicorn app.main"      # durdur (UxPlay ve scrcpy de kapanır)
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
| Android "Bağlanılamadı" | Eşleştirme yapıldı mı, Kablosuz hata ayıklama açık mı? Wi-Fi değişince Android bu ayarı kapatır. |

## Güvenlik

Aynı Wi-Fi'deki herkes adresi görebileceği için arayüz **PIN** ister (5 hatalı denemede 1 dakika
engel). Bilgi sayfası (`/bilgi`) yalnızca tahtanın kendisinden açılabilir. Trafik yerel ağda
şifresiz HTTP'dir; PIN'i ders aralarında değiştirmek için `~/.config/tahta-kumanda/pin` dosyasını
silip sunucuyu yeniden başlatın.
