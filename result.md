# char3d Web UI — hasil implementasi

Studio lokal berbahasa Indonesia dengan enam layar: Naskah ke adegan, Adegan,
Karakter, Render, Galeri output, dan Semua tool. Tema gelap/terang, navigasi mobile,
dialog aksesibel, notifikasi, antrean, waktu proses, dan pembaruan hasil otomatis
tersedia. Formulir lanjutan mencakup seluruh 89 tool yang diizinkan dari skema MCP.

Server memakai Starlette + uvicorn dan memanggil `mcp.list_tools()` /
`mcp.call_tool()` dari paket yang sudah ada. Perintah berjalan berurutan;
render video dan job AI dipantau sampai selesai. Frontend memakai ES modules
tanpa build. Viewer GLB memakai three.js r160 yang disimpan lokal beserta lisensi MIT.
Tidak ada dependensi Python baru, CDN, atau kebutuhan Node saat menjalankan aplikasi.
`engine/`, `providers/`, dan `requirements.txt` tidak diubah.

## Menjalankan

```bash
./run_webui.sh
# Buka http://127.0.0.1:8765
./run_webui.sh --port 8781
```

`CHAR3D_WEBUI_PORT` memilih port UI; `CHAR3D_PORT` dan `CHAR3D_WORKSPACE` memilih
engine/workspace. Launcher memakai `.venv` dan env opsional yang sama dengan MCP.
Simpan proyek dari layar Adegan; ekspor GLB melalui `export_asset` di Semua tool.

Host/origin asing ditolak, `run_blender_python` diblokir termasuk ketika diaktifkan
di MCP, dan generasi AI membutuhkan konfirmasi pengiriman data ke pihak ketiga.
File diperiksa setelah resolusi symlink dan harus berada di workspace. Unggahan
audio/gambar/model dibatasi 100 MB ke `imports/`. Nilai FAL_KEY/HF_TOKEN disamarkan
pada hasil dan error. Aplikasi hanya mendengarkan loopback.

## File

- `webui/__init__.py`, `webui/__main__.py`: paket dan CLI.
- `webui/app.py`: endpoint tool/skema, job, galeri, file, unggahan, dan static assets.
- `webui/jobs.py`: antrean tunggal, normalisasi konten MCP, pemantauan render/AI.
- `webui/security.py`: origin/host, confinement workspace, dan redaksi rahasia.
- `webui/static/index.html`, `favicon.svg`, `tokens.css`, `studio.css`: shell dan sistem desain.
- `webui/static/app.js`, `api.js`, `ui.js`, `icons.js`, `schema.js`: navigasi, state, polling, komponen, formulir skema.
- `webui/static/script.js`, `scene.js`, `characters.js`, `render.js`, `gallery.js`, `tools.js`: enam layar.
- `webui/static/viewer.js`, `vendor/README.txt`, `vendor/three/{three.module.js,GLTFLoader.js,OrbitControls.js,BufferGeometryUtils.js,LICENSE}`: viewer offline.
- `run_webui.sh`: launcher executable.
- `tests/webui_smoke.py`, `test_webui.py`, `webui_e2e.py`, `webui_browser.cjs`: smoke keamanan/engine, unit antrean, alur nyata, dan QA browser.
- `README.md`, `AGENTS.md`: panduan penggunaan dan agen.
- `result.md`: laporan ini. Pesan commit disalin ke `output/COMMIT_MSG.txt`.

## Verifikasi

Semua pengujian engine menggunakan **9981**, workspace di worktree ini, dan UI
**8781**. Port 9876 tidak digunakan. Sandbox hanya mengizinkan baca pada instalasi
MPFB; untuk pengujian realistis, resource Blender disalin ke direktori uji yang dapat
ditulis dan dipilih dengan `BLENDER_USER_RESOURCES`. Kode engine tetap utuh.

```text
WEBUI SMOKE OK
tests/test_webui.py: Ran 5 tests — OK
tests/test_phonemes.py: Ran 6 tests — OK
python -m py_compile webui/*.py tests/*webui*.py — PASS
node --check webui/static/*.js — PASS (setiap modul)
git diff --check — PASS
```

Ruff tidak terpasang; pemeriksaan sintaks memakai `py_compile` sesuai brief.
Log tersedia di `output/webui_smoke.log`, `test_webui.log`, `test_phonemes.log`,
`webui_e2e_final.log`, dan `webui_browser.log`.

Alur nyata memakai naskah dua karakter Indonesia di taman: parse-only, build,
frame kamera Workbench dan Eevee, simpan proyek, ekspor GLB, pilihan resolusi,
dan render draft 480p sepanjang 12 frame. Hasil utama:

- `output/projects/webui-sebuah-awal.blend`
- `output/exports/webui-karakter.glb`
- `output/renders/webui-sebuah-awal-draft.mp4` dan `.srt`
- `output/webui_e2e.json`: hasil terstruktur setiap tahap.

Empat sisi karakter juga diperiksa dengan Eevee. QA Chromium memeriksa seluruh
formulir tool, validasi JSON, boolean nullable, konfirmasi AI tanpa mengirim data,
navigasi ketika job berjalan, GLB bertekstur, dan pemutaran MP4.

## Screenshot final

Semua ada di `output/webui_screens/`. Desktop 1440 × 1000; mobile 390 × 844;
capture halaman penuh sehingga tinggi file dapat lebih besar.

| Layar | Desktop gelap | Desktop terang | Mobile gelap | Mobile terang |
|---|---|---|---|---|
| Naskah | `desktop-dark-naskah.png` | `desktop-light-naskah.png` | `mobile-dark-naskah.png` | `mobile-light-naskah.png` |
| Adegan | `desktop-dark-adegan.png` | `desktop-light-adegan.png` | `mobile-dark-adegan.png` | `mobile-light-adegan.png` |
| Karakter | `desktop-dark-karakter.png` | `desktop-light-karakter.png` | `mobile-dark-karakter.png` | `mobile-light-karakter.png` |
| Render | `desktop-dark-render.png` | `desktop-light-render.png` | `mobile-dark-render.png` | `mobile-light-render.png` |
| Galeri | `desktop-dark-galeri.png` | `desktop-light-galeri.png` | `mobile-dark-galeri.png` | `mobile-light-galeri.png` |
| Semua tool | `desktop-dark-tools.png` | `desktop-light-tools.png` | `mobile-dark-tools.png` | `mobile-light-tools.png` |

Tambahan: `desktop-dark-glb-viewer.png` dan lembar kontak `contact-dark.png`,
`contact-light.png`, `contact-mobile.png`. Temuan aksesibilitas tersimpan di
`output/webui_accessibility.json`.

QA browser membutuhkan Playwright dan opsional axe hanya pada lingkungan pengujian:

```bash
PLAYWRIGHT_MODULE=/path/to/playwright-core \
AXE_MODULE=/path/to/@axe-core/playwright node tests/webui_browser.cjs
```

```text
WEBUI E2E OK
CHARACTER VIEWS OK — four Eevee views at 320px
WEBUI BROWSER OK — 24 screen captures, no overflow, no external requests,
no JS errors, WCAG A/AA checks passed
```

Pemeriksaan axe pada keempat kombinasi tema/ukuran layar menghasilkan nol temuan
(`webui_accessibility.json` berisi `[]`). Screenshot final diperiksa secara visual;
kontras tema terang, radio resolusi, editor mobile, pemuatan galeri, dan framing
viewer GLB dirapikan berdasarkan temuan tersebut. Layanan uji ditutup setelah QA.

## Batasan dan lanjutan

- Riwayat antrean berada di memori (100 hasil terakhir); restart server menghapus
  riwayat, sementara file dan proyek tersimpan tetap tersedia di galeri.
- Progres per tahap `script_to_scene` belum disediakan tool asli; UI menampilkan
  status antrean dan waktu berjalan. Render video memiliki progres frame dan ETA.
- Teks naskah menggerakkan mulut tanpa suara ucapan. Gunakan audio asli atau
  generasi suara yang dikonfirmasi untuk dialog bersuara.
- Viewer mendukung GLB standar; decoder Draco/Meshopt/KTX2 belum disertakan.
  Gunakan GLB untuk aset dengan tekstur yang tertanam. Viewer membuka pose tersimpan
  dengan orbit/zoom; pemutar klip animasi GLB belum disediakan.
- Kualitas deformasi, clipping pakaian, dan komposisi kamera mengikuti engine.
  UI memudahkan pemeriksaan frame dan empat sisi, tanpa mengubah perilaku engine.
  Ekspor MPFB dapat menyertakan helper mesh dan material yang berbeda dari Eevee;
  viewer menampilkan isi GLB yang diekspor, termasuk helper tersebut.
- UI dirancang untuk pemilik komputer lokal; tidak menyediakan autentikasi atau
  hosting publik. Tidak ada panggilan generasi AI eksternal selama pengujian.

Perubahan dicommit pada `codex/web-ui` tanpa push atau merge. Screenshot,
render, log, dan salinan pesan commit berada di `output/` yang diabaikan Git.

Index worktree asli dipasang hanya-baca oleh sandbox, sedangkan penyimpanan objek
dan ref branch dapat ditulis. Commit memakai index terpisah
`output/webui_git_index` dan memperbarui hanya ref `codex/web-ui`. Setelah keluar
dari sandbox, jalankan `git reset --mixed HEAD` dari worktree ini untuk menyamakan
index aslinya dengan commit; perintah ini mempertahankan isi file kerja. Sementara
itu, `GIT_INDEX_FILE="$PWD/output/webui_git_index" git status` menunjukkan status
terhadap index yang dipakai untuk commit. Symlink `.venv` bawaan tidak dicommit.
