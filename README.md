# 🤖 Jarvis Bot — Personal AI & Music Discord Bot

Jarvis adalah Discord bot serbaguna berbasis Python yang menggunakan library `discord.py` (v2.x). Bot ini dirancang untuk berfungsi sebagai asisten pribadi yang pintar (didukung oleh AI dari Groq/Custom API), pemutar musik berkualitas tinggi (mendukung YouTube, Spotify, dan SoundCloud), sistem moderasi server yang andal, serta utilitas lengkap untuk server Discord Anda.

Bot ini menyajikan antarmuka menu bantuan interaktif menggunakan komponen Discord UI (Select Menus) yang modern dan intuitif.

---

## 🚀 Fitur Utama

### 🤖 1. AI & Asisten Pintar

- **Chat AI (`!j ask`)**: Mengobrol dengan Jarvis secara langsung. Menggunakan API Groq (default) dengan fallback model cerdas (seperti Llama 3.3, Llama 3.1, Gemma 2).
- **Pencarian Web (`!j search`)**: Cari informasi terkini dari web dengan rangkuman pintar.
- **Ringkas PDF (`!j summarize`)**: Unggah file PDF atau masukkan tautannya, dan Jarvis akan mengekstrak serta merangkum isinya menggunakan `pypdf` dan LLM.
- **Pembuat Gambar AI (`!j image`)**: Hasilkan gambar unik dari deskripsi teks (prompt) menggunakan Custom Image API.
- **Asisten Harian**:
  - `!j remind`: Pengingat terjadwal yang akan mengirim pesan DM saat waktu habis.
  - `!j timer`: Penghitung waktu mundur dengan notifikasi mention.
  - `!j weather`: Mengecek perkiraan cuaca kota di seluruh dunia melalui integrasi `wttr.in`.
  - `!j calc`: Kalkulator matematika instan yang aman.

### 🎵 2. Musik & Audio

- **Multi-Platform**: Mendukung pemutaran dari YouTube (video & playlist), Spotify (track & playlist), SoundCloud, atau pencarian langsung berdasarkan judul lagu.
- **Kontrol Playback**: Dukungan perintah standar seperti `join`, `play`, `pause`, `resume`, `skip`, `stop`, dan `volume`.
- **Manajemen Antrian**: Lihat daftar antrian (`queue`), riwayat lagu (`ph`/`playinghistory`), hapus lagu tertentu dari antrian (`remove`), dan bersihkan antrian (`clearqueue`).
- **Windows Opus Support**: Dilengkapi dengan Opus audio encoder library bawaan (`lib/libopus.dll`) agar voice client langsung berjalan tanpa kendala pada Windows host.

### ⚙️ 3. Moderasi Server

Kelola kenyamanan server dengan perintah moderasi terintegrasi:

- **Disiplin Member**: `kick`, `ban`, `unban`, `timeout`, `untimeout`, `mute`, dan `unmute`.
- **Sistem Peringatan (Warn)**: Memberikan peringatan (`warn`), melacak daftar pelanggaran (`warnings`), dan menghapus warning (`clearwarns`).
- **Manajemen Channel**: Pembersihan pesan massal (`purge`/`clear`), pembatasan laju chat (`slowmode`), serta penguncian channel (`lock`/`unlock`).

### 🛠️ 4. Utilitas & Sistem Info

- **Statistik Bot**: Mengecek ping/latensi (`ping`), uptime bot (`uptime`), dan statistik internal (`stats`).
- **Informasi Detail**: Info server (`serverinfo`), profil member (`userinfo`), detail bot (`info`), dan tautan undang bot (`invite`).
- **Monitor Host (`!j sysinfo`)**: Melacak statistik performa server host secara real-time (penggunaan CPU, RAM, Disk, informasi OS, dan versi Python).

---

## 📦 Persyaratan Sistem

Sebelum menjalankan bot, pastikan sistem Anda telah memenuhi persyaratan berikut:

1.  **Python 3.8 atau lebih tinggi**
2.  **FFmpeg**: Diperlukan oleh `discord.py[voice]` dan `yt-dlp` untuk memproses audio.
    - **Windows**: Unduh FFmpeg, ekstrak, dan tambahkan folder `bin` ke System PATH Anda.
    - **Linux (Ubuntu/Debian)**: Jalankan `sudo apt update && sudo apt install ffmpeg`
    - **macOS**: Jalankan `brew install ffmpeg`
3.  **Opus Library**:
    - Untuk **Windows**, file `libopus.dll` sudah disertakan di folder `lib/`.
    - Untuk **Linux/macOS**, pastikan package `libopus` terpasang di sistem jika bot mengalami kendala suara.

---

## 🛠️ Instalasi & Setup

Ikuti langkah-langkah di bawah ini untuk memasang dan menjalankan Jarvis Bot secara lokal:

### 1. Clone Repositori

```bash
git clone <repository-url>
cd jarvis
```

### 2. Instal Dependensi

Pasang semua pustaka yang diperlukan menggunakan `pip`:

```bash
pip install -r requirements.txt
```

_(Opsional)_ Jika Anda ingin menggunakan fitur ringkasan dokumen PDF (`!j summarize`), pasang pustaka `pypdf`:

```bash
pip install pypdf
```

### 3. Konfigurasi Environment File

Buat file bernama `.env` di direktori utama proyek (sejajar dengan `jarvis.py`) dan ikuti format berikut:

```env
# Token Bot Discord (Wajib)
DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN_HERE

# API Key untuk Fitur AI (Wajib jika ingin menggunakan fitur chat/search/pdf)
GROQ_API_KEY=YOUR_GROQ_API_KEY_HERE

# Custom AI API (Opsional, jika ingin merutekan chat ke API Anda sendiri)
JARVIS_API_URL=
JARVIS_API_SECRET=

# Custom Image API (Opsional, untuk fitur !j image)
CUSTOM_IMAGE_API_URL=
CUSTOM_IMAGE_API_KEY=

# Kustomisasi Model Groq (Opsional)
GROQ_MODEL_1=llama-3.3-70b-versatile
GROQ_MODEL_LABEL_1=Llama 3.3 70B
GROQ_MODEL_2=llama-3.1-8b-instant
GROQ_MODEL_LABEL_2=Llama 3.1 8B
GROQ_MODEL_3=gemma2-9b-it
GROQ_MODEL_LABEL_3=Gemma 2 9B
```

> [!IMPORTANT]
> Pastikan Anda telah mengaktifkan **Message Content Intent** di halaman [Discord Developer Portal](https://discord.com/developers/applications) pada menu **Bot** aplikasi Anda agar bot dapat membaca dan merespons perintah teks.

### 4. Jalankan Bot

Jalankan file utama bot menggunakan Python:

```bash
python jarvis.py
```

---

## 🕹️ Daftar Perintah (Commands)

Prefix perintah bot adalah `!jarvis` atau `!j` (contoh: `!j play` atau `!jarvis play`).
Jika Anda mengetik `!jarvis` atau `!j` tanpa argumen tambahan, Jarvis akan menampilkan **Menu Bantuan Interaktif** berbasis embed.

### 🎵 Musik

| Perintah         | Alias | Deskripsi                                                    | Contoh Penggunaan           |
| :--------------- | :---- | :----------------------------------------------------------- | :-------------------------- |
| `join`           | -     | Menyuruh bot masuk ke Voice Channel Anda.                    | `!j join`                   |
| `play`           | -     | Memutar lagu/playlist dari YouTube/Spotify/SoundCloud.       | `!j play rewrite the stars` |
| `pause`          | -     | Menjeda pemutaran musik saat ini.                            | `!j pause`                  |
| `resume`         | -     | Melanjutkan pemutaran musik yang dijeda.                     | `!j resume`                 |
| `skip`           | -     | Melewati lagu yang sedang diputar.                           | `!j skip`                   |
| `stop`           | -     | Menghentikan musik dan mengeluarkan bot dari Voice Channel.  | `!j stop`                   |
| `queue`          | -     | Menampilkan daftar antrian lagu saat ini.                    | `!j queue`                  |
| `nowplaying`     | `np`  | Menampilkan detail lagu yang sedang diputar.                 | `!j np`                     |
| `playinghistory` | `ph`  | Menampilkan riwayat lagu yang telah diputar sebelumnya.      | `!j ph`                     |
| `volume`         | -     | Mengatur volume suara bot (skala 0 - 100).                   | `!j volume 75`              |
| `clearqueue`     | `cq`  | Menghapus semua lagu yang ada dalam antrian.                 | `!j cq`                     |
| `remove`         | -     | Menghapus lagu tertentu dari antrian berdasarkan nomor urut. | `!j remove 3`               |

### 🤖 AI & Asisten

| Perintah    | Alias            | Deskripsi                                                       | Contoh Penggunaan                       |
| :---------- | :--------------- | :-------------------------------------------------------------- | :-------------------------------------- |
| `ask`       | `chat`, `ai`     | Mengajukan pertanyaan ke Jarvis AI.                             | `!j ask buatkan resep nasi goreng`      |
| `clearchat` | -                | Menghapus memori riwayat chat Anda dengan bot.                  | `!j clearchat`                          |
| `search`    | `web`, `cari`    | Mencari jawaban langsung dari web.                              | `!j search harga saham Apple hari ini`  |
| `image`     | `img`, `gambar`  | Membuat gambar AI berdasarkan deskripsi teks.                   | `!j image kucing memakai helm astronot` |
| `summarize` | `sum`, `ringkas` | Merangkum isi file PDF (wajib lampirkan file atau isi URL PDF). | `!j summarize` _(sambil attach PDF)_    |
| `remind`    | -                | Menyetel pengingat waktu (`s`/`m`/`h`/`d`).                     | `!j remind 2h rapat kerja`              |
| `timer`     | -                | Memulai timer countdown (`s`/`m`/`h`).                          | `!j timer 10m`                          |
| `weather`   | -                | Menampilkan info cuaca kota tujuan saat ini.                    | `!j weather Jakarta`                    |
| `calc`      | -                | Menghitung operasi matematika dasar.                            | `!j calc (25 * 4) / 10`                 |
| `sysinfo`   | -                | Menampilkan status hardware server host.                        | `!j sysinfo`                            |
| `model`     | `models`         | Melihat daftar model AI Groq yang dikonfigurasi.                | `!j model`                              |

### ⚙️ Moderasi

| Perintah     | Alias      | Deskripsi                                                    | Contoh Penggunaan                |
| :----------- | :--------- | :----------------------------------------------------------- | :------------------------------- |
| `kick`       | -          | Mengeluarkan member dari server.                             | `!j kick @user spam iklan`       |
| `ban`        | -          | Memblokir member secara permanen dari server.                | `!j ban @user pelanggaran berat` |
| `unban`      | -          | Membuka blokir member server.                                | `!j unban Username#1234`         |
| `timeout`    | -          | Membisukan member untuk durasi tertentu (menit).             | `!j timeout @user 15 toxic`      |
| `untimeout`  | -          | Menghapus status timeout dari member.                        | `!j untimeout @user`             |
| `purge`      | `clear`    | Menghapus sejumlah pesan di channel chat.                    | `!j clear 20`                    |
| `warn`       | -          | Memberikan poin peringatan (warning) ke member.              | `!j warn @user melanggar aturan` |
| `warnings`   | `warnlist` | Menampilkan seluruh riwayat warning seorang member.          | `!j warnings @user`              |
| `clearwarns` | -          | Menghapus seluruh riwayat warning seorang member.            | `!j clearwarns @user`            |
| `slowmode`   | -          | Mengatur jeda kirim pesan di channel saat ini (detik).       | `!j slowmode 5`                  |
| `lock`       | -          | Mengunci channel agar member biasa tidak bisa mengirim chat. | `!j lock`                        |
| `unlock`     | -          | Membuka kembali channel yang terkunci.                       | `!j unlock`                      |
| `mute`       | -          | Memberikan role Muted atau membisukan member di channel.     | `!j mute @user`                  |
| `unmute`     | -          | Mengembalikan hak berbicara member.                          | `!j unmute @user`                |

### 🛠️ Utilitas

| Perintah     | Alias           | Deskripsi                                                     | Contoh Penggunaan   |
| :----------- | :-------------- | :------------------------------------------------------------ | :------------------ |
| `ping`       | -               | Menampilkan latensi koneksi bot ke server Discord.            | `!j ping`           |
| `uptime`     | -               | Melihat berapa lama bot telah online sejak dinyalakan.        | `!j uptime`         |
| `stats`      | -               | Menampilkan statistik jumlah server, user, dan pemakaian RAM. | `!j stats`          |
| `info`       | -               | Menampilkan informasi pengembang dan deskripsi bot.           | `!j info`           |
| `invite`     | -               | Mendapatkan link untuk mengundang Jarvis ke server lain.      | `!j invite`         |
| `userinfo`   | `user`, `whois` | Menampilkan informasi lengkap profil member.                  | `!j userinfo @user` |
| `serverinfo` | `server`        | Menampilkan informasi lengkap server/guild Discord.           | `!j serverinfo`     |
| `cogs`       | -               | Menampilkan daftar modul cogs bot yang sedang aktif.          | `!j cogs`           |

---

## 📁 Struktur Proyek

```text
jarvis/
├── cogs/                 # Folder modul/cogs bot
│   ├── ai.py             # Fitur integrasi AI (Groq, Image, PDF)
│   ├── assistant.py      # Fitur pengingat, cuaca, kalkulator, sysinfo
│   ├── moderation.py     # Fitur moderasi server (kick, ban, purge, dll)
│   ├── music.py          # Fitur pemutaran musik & audio
│   └── utility.py        # Fitur utilitas & info bot
├── lib/                  # Folder library eksternal
│   └── libopus.dll       # Audio library Opus (khusus Windows host)
├── jarvis.py             # File utama / Entry point bot
├── requirements.txt      # Daftar dependensi Python
├── .gitignore            # Konfigurasi file yang diabaikan Git
└── .env                  # Konfigurasi kredensial / API Key (lokal)
```

---

## 🛡️ Lisensi & Kontribusi

Proyek ini dibuat untuk tujuan suka-suka. Kontribusi, perbaikan bug, atau penambahan fitur sangat dipersilakan! Silakan ajukan Pull Request (PR) atau laporkan masalah Anda melalui fitur Issues.
