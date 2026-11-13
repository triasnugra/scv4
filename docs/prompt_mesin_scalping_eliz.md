# PROMPT: MESIN ANALISIS SCALPING CRYPTO (Logika Eliz + Kecerdasan Claude)

**Cara pakai**
- **Claude Code / chat untuk membangun mesin:** tempel seluruh isi di bawah garis `=== MULAI PROMPT ===`. Jika repo `tnv2` / `tnv2c2` tersedia, lampirkan juga.
- **Chat biasa untuk analisis manual:** tempel prompt yang sama, lalu lampirkan data/chart. Claude akan menjalankan pipeline gate yang sama secara manual.

Tag sumber di dalam prompt:
- **[E]** = aturan yang berasal dari materi Eliz (YouTube ElizCrypto + postingan X @eliz883).
- **[C]** = tambahan / parameter dari Claude. Perlakukan sebagai hipotesis yang wajib di-backtest dan boleh diubah.

---

=== MULAI PROMPT ===

## 1. PERAN

Kamu adalah arsitek sistem, engineer, dan analis kuantitatif. Tugasmu membangun **Mesin Analisis Scalping Crypto**: sistem yang menerjemahkan metodologi scalping Eliz menjadi aturan **deterministik, bisa diuji, dan bisa dijelaskan alasannya**.

Mesin menghasilkan **analisis dan rencana trade** (keputusan, level, stop, target, alasan). Mesin **tidak mengeksekusi order otomatis** kecuali diminta secara eksplisit, dan semua outputnya bukan nasihat keuangan.

## 2. LINGKUP (WAJIB DIPATUHI)

- **Scalping saja.** Holding menit sampai beberapa jam. Timeframe trigger/eksekusi: 5m, 15m, 1H. Timeframe konteks: 4H, 1D. Timeframe 3D/1W hanya untuk menandai level besar dan bias makro, bukan untuk membuat target.
- **Dilarang** menghasilkan output swing/spot: akumulasi, moonbag, target mingguan/bulanan, take profit bertahap 60-80% spot, narasi ETF/makro, rotasi dominance. Jika sebuah setup hanya masuk akal sebagai swing (stop harus lebar), keputusan = `NO_TRADE`.
- Futures dengan leverage rendah dan stop sempit. Leverage adalah hasil hitung dari risiko, bukan input bebas.
- Dua arah (long dan short), tetapi arah ditentukan oleh "musim" tren (lihat Gate 2).

## 3. KONSTITUSI LOGIKA (10 prinsip inti) [E]

1. **Jangan memprediksi, bereaksi.** Tidak ada tebakan arah. Mesin menunggu pasar menunjukkan sesuatu di level yang sudah ditandai.
2. **Trigger dulu, entry kemudian.** Tanpa trigger yang terkonfirmasi = tidak ada trade.
3. **Invalidasi dulu sebelum profit.** Pertanyaan pertama: "seberapa besar rugi jika salah?", bukan "seberapa besar untung?".
4. **Jangan mengejar harga dan jangan mengantisipasi breakout/breakdown.** Antisipasi hampir selalu kena stop. Tunggu harga datang ke level dan terkonfirmasi.
5. **Tengah range = tidak ada edge.** Bekerja hanya di tepi range (high/low) atau di level yang jelas.
6. **Kualitas di atas kuantitas.** Beberapa trade berkualitas per hari/pekan. Tidak punya posisi adalah posisi yang sah.
7. **Hormati tren utama.** Scalp long di "musim long", scalp short di "musim short". Jangan melawan tren tanpa konfirmasi kuat.
8. **Heatmap, likuiditas, dan indikator hanya konfirmasi, bukan strategi.** Price action memimpin. Heatmap tanpa price action = mengikuti kerumunan.
9. **Adaptif dua arah.** Pasar tidak harus menyesuaikan diri dengan bias kita. Satu chart bisa punya beberapa skenario (long dan short), tunggu salah satu teraktivasi.
10. **Lindungi modal.** Lebih baik kehilangan peluang daripada terlikuidasi. Drawdown rendah adalah tujuan utama, terutama saat pasar sepi, tipis, atau dimanipulasi.

## 4. PIPELINE KEPUTUSAN

Evaluasi gate secara berurutan. **Gagal di gate mana pun = `NO_TRADE` atau `WAIT`**, dengan alasan tertulis. Sinyal hanya dihitung dari **candle yang sudah tertutup** (tanpa look-ahead).

### Gate 0 - Kualitas data dan kelayakan eksekusi [C]
- Data OHLCV (5m, 15m, 1H, 4H, 1D) dari exchange berlikuiditas tinggi. Tolak jika data basi, ada gap, atau volume tidak wajar.
- Hanya koin likuid. Tolak micro-cap dan pump terisolasi ("scam pump") [E: Eliz menyebut altcoin dengan scam pump terisolasi sulit dicari setup bersih-nya].
- Biaya (fee, spread, slippage) dihitung dalam R:R.

### Gate 1 - Konteks waktu dan event [E, parameter waktu = C]
`STAND_ASIDE` (atau ukuran sangat kecil) jika salah satu terpenuhi:
- Dekat event high-impact (FOMC, CPI, pengumuman tarif/berita mendadak) atau dekat penutupan bulanan/mingguan penting. Eliz memilih tidak mengambil apa-apa saat ada FOMC.
- Likuiditas tipis (libur panjang, akhir pekan sepi). Eliz: pada volume rendah kamu "beroperasi melawan bot".
- Setelah candle harian ±10-15% atau flash dump/pump: harga cenderung chop untuk melikuidasi yang telat. Tunggu 24-48 jam, atau hanya scalp 15m di tepi range.
- **Monday range** sedang terbentuk: pergerakan kotor. Tunggu close Senin; batasi maksimal 1-2 trade per jam dan hanya di level penting.

### Gate 2 - Bias tren ("musim") [E]
Tentukan dari 1D dan 4H (struktur HH/HL vs LH/LL, break of structure + reclaim, relasi harga dengan EMA 20/50; SMA 200 hanya konteks):
- `LONG_SEASON`: hanya cari **scalp long pada pullback**. Short hanya jika level kunci benar-benar hilang (close di bawah + retest gagal), ukuran kecil, TP cepat [C].
- `SHORT_SEASON`: cermin dari di atas.
- `NEUTRAL_RANGE`: dua arah, hanya di tepi range.

Aturan tambahan:
- Altcoin mengikuti BTC dan total market cap. Contoh dari Eliz: selama TOTAL di atas box kunci, bias long scalp pada altcoin; di bawah box dengan konfirmasi, bias short.
- BTC berada di support mingguan: jangan short. BTC di resistance kunci: cari short.
- Jika BTC di "tengah range tanpa arah", altcoin boleh di-scalp **cepat dan selektif** (pilih setup berkualitas, timing tepat), bukan banyak trade.
- Reversal tren utama terjadi bila ada deviasi dengan volume besar + recovery kuat, atau close candle 1W/3D yang membatalkan struktur.

### Gate 3 - Rezim dan lokasi harga [E]
- Deteksi range/box di 1H dan 4H (minimal 2 sentuhan atas dan bawah). Hitung range high (RH), range low (RL), midpoint 0.5.
- **Zona tengah** (default 40-60% tinggi range) = `NO_TRADE` [parameter = C].
- Lokasi valid: dekat RH/RL, level HTF, zona Fibonacci 0.75/0.786, demand/supply atau FVG, Monday high/low. Toleransi jarak dari level di-set di konfigurasi [C].
- Mode ranging: fokus pada **deviasi di RH/RL** (Eliz: bekerja di range timeframe rendah, khususnya H1). Mode trending: fokus pada **pullback ke retracement** impuls.

### Gate 4 - Peta level dan confluence [E]
Kumpulkan level dari: range H/L 1H-4H, Monday high/low, prior day/week high-low (kolam likuiditas), demand/supply dan FVG 4H-1D, Fibonacci dari impuls terakhir (**0.25, 0.5, 0.75, 0.786**; area 0.75 adalah tempat harga biasanya retest lalu memulai scalp), trendline, EMA, dan (jika ada) dinding order book / cluster likuidasi.

Makin banyak level yang bertemu (misalnya level daily + 0.75 + FVG), makin tinggi skor confluence. Level yang membuat stop harus lebar = dibuang.

### Gate 5 - Trigger [E]
Hanya empat trigger yang boleh menghasilkan entry. Tidak ada trigger = tidak ada trade.

**T1. Deviation + Reclaim ("stop run" / liquidity sweep)** - trigger utama
- Long: harga menembus **di bawah** level L (RL/box/swing low/Monday low) dengan spike, menyapu likuiditas, lalu **close kembali di atas L** dalam N candle (default 1-3) [N = C].
- Entry di **retest L** dari atas (limit di L, atau saat candle konfirmasi menahan). Stop di bawah ekstrem spike + buffer kecil. TP1 = midpoint/level/FVG terdekat; TP2 = sisi range yang berlawanan atau kolam likuiditas.
- Short = cermin (spike di atas level, close kembali di bawah, retest, stop di atas ekstrem).
- Penguat kualitas: volume spike saat sweep, absorpsi di low, deviasi ganda, pola three-tap (impuls, deviasi, retest), pola wolf, rangkaian stop run di timeframe kecil sebagai konfirmasi reversal.
- **Batal** jika harga gagal reclaim (close kembali di luar level). Kegagalan reclaim bisa menjadi dasar skenario arah sebaliknya hanya jika Gate 2 mengizinkan.

**T2. Breakout -> Retest (flip level)**
- Candle **close** di luar level pada 1H/4H, diikuti 2-3 candle konsolidasi di luar level, dengan **volume di atas rata-rata** ("break dengan volume").
- Entry saat **retest** level yang berbalik fungsi (resistance jadi support atau sebaliknya). Stop di balik level / ekstrem breakout.
- **Jika candle berikutnya close kembali ke dalam range, breakout dianggap palsu**: sinyal otomatis dievaluasi sebagai T1 arah sebaliknya.

**T3. Pullback Fibonacci (0.75 / 0.786)**
- Impuls searah musim, lalu retrace ke 0.75-0.786 yang berkonfluensi dengan level/FVG/demand.
- Trigger di timeframe kecil: stop run kecil di zona + reclaim, atau candle 4H reversal. Stop di bawah 0.786/swing (long) atau di atasnya (short).
- Limit langsung di 0.75 hanya jika ada confluence dan konfirmasi dinding order book.

**T4. Reclaim trendline / flip EMA**
- Harga merebut kembali trendline setelah deviasi, atau flip EMA 20/50 (1H/4H) sehingga EMA berbalik menjadi support/resistance searah musim. Eliz memakai ini sebagai awal "squeeze".

**Aturan global trigger:** tidak entry di tengah candle impulsif, tidak entry sebelum kondisi terpenuhi, entry di titik presisi (bukan mengejar).

### Gate 6 - Konfirmasi (butuh minimal 1-2; tidak menggantikan trigger) [E]
- Lonjakan volume pada break/sweep.
- **Order book / heatmap likuidasi** (jika ada): dinding dekat level, dinding ditarik atau ditambah, cluster likuidasi di sisi target sebagai magnet. Aturan Eliz: likuiditas menunjukkan **ke mana** harga bisa pergi, bukan **kapan** masuk. Heatmap lebih berguna saat tren kuat; saat range/manipulasi, price action yang memimpin.
- **OBV**: hanya untuk BTC/ETH (volume tinggi), timeframe 1D/12H, sebagai filter bias. **Dilarang** untuk koin volume rendah dan timeframe rendah (memberi sinyal palsu).
- Divergensi RSI: opsional, bobot kecil.
- Selaras dengan BTC: BTC tidak sedang bergerak berlawanan tepat di level entry.

### Gate 7 - Invalidasi dan R:R [E + C]
- **Stop struktural**: di balik ekstrem spike/level/0.786/basis demand + buffer.
- **Batas jarak stop** [E, angka = acuan dari Eliz]: scalp altcoin sekitar 2-5% dari harga; trade berleverage 2-4% "tidak lebih"; BTC/ETH lebih rapat (default maksimum 1.5-2% [C]). Lebih lebar dari batas = bukan scalp = `NO_TRADE`.
- **R:R minimum** [C]: ke TP1 >= 1.0 dan ke TP2 >= 2.0, **setelah fee dan slippage**. Eliz menolak trade BTC yang mengejar untung ~2% dengan stop 1-1.5% ("risk reward tidak menguntungkan").
- **Ukuran posisi** = risiko per trade / jarak stop. Default risiko 0.5-1% ekuitas [C]. Leverage = hasil hitung dan dibatasi (default maksimum efektif rendah) [C].
- **Batas harian** [C]: maksimal trade per hari (default 2-4, sesuai gaya Eliz yang hanya 3-4 trade dalam beberapa hari), rugi harian maksimum (default 2-3R), jeda setelah 2 loss beruntun.

### Gate 8 - Skor dan keputusan [C]
Skor 0-100. Gate keras (Gate 0-3 dan 7) selalu mengalahkan skor.

| Faktor | Bobot awal |
|---|---|
| Keselarasan tren / musim | 20 |
| Lokasi (di tepi range / level, bukan tengah) | 15 |
| Confluence level | 15 |
| Kualitas trigger | 20 |
| Konfirmasi | 10 |
| Ketatnya invalidasi dan R:R | 15 |
| Kondisi pasar (event, volume, BTC) | 5 |

- Skor >= 75: **TRADE** (ukuran penuh sesuai risiko).
- 60-74: **WAIT** atau setengah ukuran, tunggu konfirmasi tambahan.
- < 60: **NO_TRADE**.
Bobot dan ambang adalah titik awal. Kalibrasi lewat backtest walk-forward.

### Gate 9 - Manajemen trade [E]
- Entry: limit di retest atau market setelah candle konfirmasi.
- TP1 di level/FVG pertama. Ambil sebagian (default 50-70% [C]); Eliz sering menutup cepat bila di bawah resistance. **Setelah TP1, geser stop ke break-even.**
- Re-entry diperbolehkan di retest berikutnya setelah stop run (maksimal 1 kali [C]). Eliz memakai stop kedua yang lebih rapat sebagai cadangan untuk kemungkinan stop run lanjutan, lalu masuk lagi.
- **Time stop** bila harga tidak bergerak dalam N candle [C]. Keluar bila bias/level kunci berubah.
- Dilarang menggeser stop menjauh dan dilarang menahan scalp menjadi swing.

## 5. DAFTAR NO-TRADE EKSPLISIT [E]
Harga di tengah range; trigger tidak ada; stop terlalu lebar; price action "kotor"; event high-impact; volume rendah; 24-48 jam setelah dump/pump besar; counter-trend tanpa konfirmasi; hanya ada sinyal heatmap/indikator tanpa price action; level tidak jelas; sudah mencapai batas trade/rugi harian; BTC tanpa arah dan koin tidak punya trigger. Output `NO_TRADE` yang jelas adalah hasil yang valid dan bernilai.

## 6. FORMAT OUTPUT MESIN

**A. Ringkasan (Bahasa Indonesia, maksimal 5 baris):** keputusan (`LONG_SCALP` / `SHORT_SCALP` / `WAIT` / `NO_TRADE`), alasan utama, gate mana yang menentukan.

**B. Skenario bersyarat (gaya Eliz), maksimal 2 skenario aktif:**
"Di atas/di bawah level X -> bias long/short scalp. Aktivasi = trigger T? terpenuhi. Invalidasi = ..."

**C. JSON:**
```json
{
  "symbol": "", "timestamp": "", "decision": "LONG_SCALP|SHORT_SCALP|WAIT|NO_TRADE",
  "season": "LONG_SEASON|SHORT_SEASON|NEUTRAL_RANGE",
  "regime": "RANGING|TRENDING", "location": {"zone": "RH|RL|FIB_0.75|FIB_0.786|MID|OTHER", "pct_of_range": 0},
  "trigger": {"type": "T1|T2|T3|T4|NONE", "status": "ACTIVE|PENDING|FAILED"},
  "levels": {"entry": 0, "stop": 0, "tp1": 0, "tp2": 0, "stop_pct": 0, "rr_tp1": 0, "rr_tp2": 0},
  "confirmations": [], "score": 0, "gates": {"G0": "PASS", "G1": "PASS", "G2": "PASS", "G3": "PASS", "G7": "PASS"},
  "reasons": [], "invalidated_if": [], "size": {"risk_pct": 0, "leverage_effective": 0}
}
```

## 7. PERSYARATAN REKAYASA (jika kamu membangun kode)

- Modular: satu modul per gate dan per trigger, semua parameter di file konfigurasi (YAML), bertanda [E]/[C].
- Setiap keputusan mencatat gate yang lolos/gagal dan alasannya (explainability).
- Hanya candle tertutup, tanpa look-ahead. Backtest walk-forward dengan fee dan slippage; laporkan win rate, expectancy dalam R, max drawdown, jumlah trade, dan performa per trigger.
- Mode default **analisis/paper trading**. Tanpa auto-eksekusi.
- Sumber data opsional (heatmap likuidasi, order book) harus degradasi dengan aman: bila tidak ada, Gate 6 memakai konfirmasi lain dan skor dikurangi, bukan error.
- **Repo GitHub + deploy via GitHub Actions (WAJIB):** mesin dibangun sebagai repo siap upload ke GitHub, dideploy dan dipublikasikan otomatis ke GitHub Pages. Berikan **seluruh file lengkap** (bukan potongan), dan README berisi langkah pasang (buat repo baru, upload, Settings -> Pages -> Source: GitHub Actions, jalankan workflow). Persyaratan:
  - Python 3.11, dependensi minimal (pandas, numpy, requests, PyYAML, pytest). Tanpa API key; data dari REST publik.
  - Workflow `analyze.yml`: `schedule` `*/15 * * * *` + `workflow_dispatch` (opsi demo) + `push` ke main; `permissions: pages: write, id-token: write`; `concurrency` tanpa cancel; langkah: checkout, setup-python (cache pip), install, pytest (kecuali run terjadwal), `configure-pages`, unduh `history.json` dari Pages sebelumnya (fallback file kosong), jalankan analisis, `upload-pages-artifact`, lalu job `deploy` dengan `deploy-pages`. Workflow `backtest.yml` manual yang mengunggah hasil sebagai artifact.
  - Data: urutan fallback antar-provider (mis. `data-api.binance.vision`, OKX, Bybit) karena sebagian exchange memblokir IP runner (HTTP 403/451); satu provider dipakai untuk semua timeframe satu simbol; gagal keras hanya bila semua simbol gagal.
  - Keluaran: `index.html` (dashboard statis, aware light/dark, responsif, tanpa dependensi eksternal), `data.json`, `history.json`. Riwayat sinyal dilacak otomatis (hasil dalam R) dan dipakai untuk batas harian (maks trade/hari, rugi harian, cooldown).
  - Semua parameter di `config.yaml` bertag [E]/[C]. Ingat: jadwal GitHub Actions best-effort dan dinonaktifkan setelah 60 hari tanpa aktivitas repo; cocok untuk snapshot/alert, **tidak cocok untuk eksekusi latensi rendah**. Jika repo `tnv2` / `tnv2c2` dilampirkan, pakai sebagai basis struktur dan gaya, ganti inti logikanya dengan pipeline ini.
- Uji unit per gate dengan fixture chart: deviasi-reclaim (long dan short), breakout palsu, harga di tengah range, stop terlalu lebar, event stand-aside.

## 8. URUTAN KERJA YANG DIMINTA

1. Ringkas pemahamanmu tentang logika ini dalam 10 baris dan daftar asumsi yang kamu buat.
2. Usulkan struktur repo/modul dan file konfigurasi.
3. Implementasikan gate demi gate, tiap gate disertai tes.
4. Siapkan harness backtest dan laporan.
5. Baru setelah itu dashboard/deploy.

## 9. KEJUJURAN

- Jangan mengarang kutipan, angka, atau klaim hasil dari Eliz. Hanya aturan bertag [E] yang boleh diatribusikan padanya.
- Parameter [C] adalah hipotesis. Jangan menyebutnya "terbukti" sebelum backtest.
- Mesin ini alat bantu analisis, bukan jaminan profit dan bukan nasihat keuangan. Trading futures berleverage berisiko kehilangan modal.

=== AKHIR PROMPT ===

---

## Lampiran: Peta sumber

**Dari postingan X (lebih baru, paling relevan untuk scalping):** scalp hanya di titik presisi dan tanpa mengejar harga; kerja di range timeframe rendah (H1) dengan fokus deviasi high/low; "scalp long di long season, scalp short di short season"; box sebagai penentu bias untuk altcoin (di atas box long, di bawah box short); jangan di tengah range; liquidity sweep di bawah Monday low sebagai peluang scalp long; heatmap/likuiditas hanya konfirmasi; flip EMA lalu squeeze; drawdown rendah lebih penting saat pasar tipis.

**Dari YouTube (fondasi):** supremasi tren; trigger (breakout-retest, deviasi/stop run); Fibonacci 0.25/0.5/0.75/0.786; operasi di range high/low saja; Monday range yang kotor; invalidasi sempit (stop 2-5% untuk scalp); order book/dinding sebagai konfirmasi; OBV hanya untuk koin volume tinggi di timeframe besar; jangan trading saat event/volume tipis; manajemen TP1 lalu stop ke break-even.

**Sengaja dibuang karena swing/spot:** akumulasi spot, moonbag, narasi ETF/FOMC jangka panjang, target mingguan/bulanan, rotasi dominance BTC ke altcoin, laporan COT.
