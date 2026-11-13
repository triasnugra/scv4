# Mesin Analisis Scalping Crypto

Mesin analisis **scalping saja** (bukan swing) berbasis logika Eliz (YouTube ElizCrypto + X @eliz883) ditambah lapisan
kecerdasan Claude (skor, R:R bersih biaya, ukuran posisi, pelacak hasil, backtest). Berjalan otomatis di
**GitHub Actions** dan dipublikasikan sebagai dashboard di **GitHub Pages**.

> Alat bantu analisis, bukan nasihat keuangan dan bukan jaminan profit. Parameter bertanda **[C]** di `config.yaml`
> adalah hipotesis yang HARUS di-backtest sebelum dipercaya. Default-nya analisis/paper trading, tanpa auto-eksekusi.

## Cara pasang (5 langkah)

1. **Buat repo baru** di GitHub (mis. `scalp-engine`). Pakai repo khusus: jika kamu menaruhnya di repo situs yang sudah
   punya halaman lain (mis. `username.github.io`), deploy Pages via Actions akan **menggantikan seluruh isi situs**.
2. **Upload semua isi folder ini** ke branch `main` (termasuk folder `.github/`, yang tersembunyi di sebagian file manager).
3. Buka **Settings -> Pages -> Build and deployment -> Source: GitHub Actions**.
4. Buka tab **Actions**, aktifkan workflow bila diminta, pilih **Scalp Analysis and Deploy -> Run workflow**.
   (Opsi `demo` memakai data sintetis untuk menguji tampilan tanpa jaringan.)
5. Dashboard muncul di `https://<username>.github.io/<nama-repo>/` setelah workflow hijau. Selanjutnya berjalan tiap 15 menit.

## Cara kerja

```
GitHub Actions (cron */15)
  -> ambil data OHLCV (5m/15m/1h/4h/1d, candle tertutup saja) dari provider fallback
  -> pipeline Gate 0-9 per simbol (BTC dulu sebagai konteks musim altcoin)
  -> catat sinyal LONG/SHORT_SCALP ke history.json dan lacak hasilnya (R) dengan candle 5m
  -> tulis site/index.html + data.json + history.json
  -> deploy ke GitHub Pages
```

`history.json` dibawa antar-run dengan mengunduh versi dari Pages sebelumnya (tidak ada commit berulang ke repo).

### Pipeline keputusan

| Gate | Isi |
|---|---|
| G0 | Kualitas data, candle basi, likuiditas koin |
| G1 | Event/waktu: jendela stand-aside manual, post-shock 24-48 jam, Monday range, likuiditas tipis |
| G2 | "Musim" tren: LONG_SEASON / SHORT_SEASON / NEUTRAL_RANGE (struktur HH/HL, EMA 20/50, 1D + 4H) |
| G3 | Range H1 (RH/RL), zona tengah = no-man's land |
| G4 | Peta level + confluence (range edge, Monday H/L, prev day/week, FVG, Fibonacci 0.25/0.5/0.75/0.786, EMA, pivot HTF) |
| G5 | Trigger: **T1** deviation+reclaim, **T2** breakout-retest, **T3** pullback fib 0.75/0.786, **T4** reclaim trendline / flip EMA |
| G6 | Konfirmasi: volume, wick, dinding order book, OBV (hanya BTC/ETH), divergensi RSI, keselarasan BTC |
| G7 | Stop struktural, batas jarak stop, R:R bersih fee+slippage, batas harian, ukuran posisi |
| G8 | Skor 0-100 (>=75 TRADE, >=66 WAIT) |
| G9 | Rencana manajemen: TP1 parsial, stop ke break-even, stop cadangan, time stop |

Long dan short dijamin simetris: logika ditulis untuk sisi long, sisi short dijalankan pada harga yang dicerminkan.

## Konfigurasi

Semua parameter ada di `config.yaml` (komentar `[E]` = dari materi Eliz, `[C]` = tambahan Claude). Yang paling sering diubah:

```yaml
symbols: [BTC, ETH, SOL, PEPE]
account: { equity_usd: 1000, risk_pct: 0.75, max_leverage_effective: 10 }
gate1_context:
  stand_aside_windows:                 # isi manual saat ada FOMC/CPI dsb. (waktu UTC)
    - { start: "2026-12-17 18:00", end: "2026-12-17 22:00", label: "FOMC" }
scoring: { trade_threshold: 75, wait_threshold: 66 }
```

## Jalankan lokal

```bash
pip install -r requirements.txt
python -m pytest -q                                   # tes
python -m scalp.main analyze --out site --demo        # demo offline
python -m scalp.main analyze --out site               # live
python -m scalp.main backtest --symbol BTC --days 30 --step 2 --json out/bt.json
```

Backtest juga bisa dijalankan dari tab Actions (**Backtest (manual)**); hasilnya diunggah sebagai artifact.

## Batasan yang perlu kamu tahu

- **Jadwal GitHub Actions best-effort**: bisa tertunda beberapa menit dan tidak cocok untuk eksekusi latensi rendah.
  Cocok untuk snapshot/alert per 15 menit. Di repo publik, workflow terjadwal dinonaktifkan GitHub setelah 60 hari tanpa
  aktivitas repo; aktifkan lagi dari tab Actions bila itu terjadi.
- **Provider data**: urutan fallback `binance_vision -> okx -> bybit` (satu provider dipakai untuk semua timeframe satu simbol).
  Sebagian exchange memblokir IP wilayah tertentu (HTTP 403/451); bila semua gagal, simbol ditandai G0 FAIL dan workflow
  gagal hanya jika SEMUA simbol gagal. Ubah urutan di `data.providers`. Nama simbol berbeda per exchange diatur di `symbol_overrides`.
- **Heatmap likuidasi tidak termasuk** (butuh API berbayar). Dinding order book dipakai sebagai konfirmasi opsional;
  bila tidak tersedia, mesin berjalan tanpa itu.
- **Backtest tanpa order book/heatmap** dan mengasumsikan entry terisi di harga entry; bila stop dan target tersentuh
  dalam candle yang sama, dianggap stop dulu (konservatif).
- **Belum terbukti punya edge.** Pada uji internal dengan data acak (random walk), mesin tetap mengeluarkan sebagian
  kecil sinyal; itu wajar untuk baseline tanpa edge dan artinya hasil live/backtest nyata yang menentukan, bukan skor.
  Kalibrasi bobot, ambang, dan batas stop lewat backtest walk-forward pada data nyata.
- Tes unit memakai data sintetis dan mock jaringan; **panggilan API exchange nyata belum diuji dari lingkungan pembuatan**.
  Jalankan workflow sekali secara manual dan cek log bila ada provider yang gagal.

## Struktur repo

```
.github/workflows/analyze.yml    cron + test + deploy Pages
.github/workflows/backtest.yml   backtest manual
config.yaml                      semua parameter
scalp/                           data, structure, levels, triggers, confirm, risk, engine, tracker, backtest, report, main
scalp/web/index.template.html    dashboard statis
tests/                           tes unit (data sintetis + mock)
```
