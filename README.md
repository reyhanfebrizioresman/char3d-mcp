# char3d — Engine Karakter 3D untuk AI (MCP + Blender)

Engine ini menjalankan Blender di latar belakang dan membuka fungsinya sebagai
"alat" MCP. Claude, Codex, atau klien MCP lain bisa membuat, memeriksa, merender,
dan meng-export aset 3D.

```
Claude / Codex ──MCP──► mcp_server/ ──TCP lokal──► Blender (engine/) ──► .glb .blend .png
```

## Status
✅ Fase 1 (fondasi) · ✅ Fase 2 (karakter + rigging) · ✅ Fase 3 (animasi) · ✅ Fase 4 (kamera, cahaya, video) · ✅ Fase 6 (integrasi AI: Hugging Face gratis + fal.ai) · ✅ Manusia realistis (MPFB)

| Alat | Fungsi |
|---|---|
| `engine_status` | Menyalakan Blender bila belum jalan, lalu menampilkan versi dan folder kerja |
| `scene_info` | Daftar objek, ukuran, statistik mesh/armature, animasi |
| `new_scene` | Adegan kosong |
| `add_primitive`, `transform_object`, `delete_objects` | Objek dasar |
| `import_model` | .glb .gltf .fbx .obj .stl .ply .usd .bvh |
| `export_asset` | .glb (disarankan, ikut animasi) .gltf .fbx .obj .usd .bvh; Rigify hanya tulang deform; `max_influences=4` membatasi bobot untuk game tanpa mengubah adegan (hasil: `vertices_limited`) |
| `save_project`, `open_project` | File .blend |
| `render_style` | Preset anime/toon, clay, film, noir, vintage; non-destruktif, tersimpan di .blend; `none` mengembalikan tampilan asli |
| `render_preview`, `render_views` | Render pratinjau (kamera otomatis atau kamera shot), gambarnya dikirim balik ke AI; `engine_name="eevee"` untuk tekstur |
| `create_human` | Karakter manekin prosedural: realistic, heroic, stylized, cartoon, chibi |
| `create_realistic_human`, `mpfb_assets` | Manusia realistis (MakeHuman/MPFB): kulit, rambut, baju, sepatu, janggut, aksesori; kategori pakaian + preset `outfit` dengan `seed`; rig `game_engine`, `mixamo`, `rigify` |
| `set_expression`, `list_expressions` | 24 ekspresi wajah (senyum, tawa, sedih, marah, kaget, kedip, dll.) + 52 unit ARKit |
| `auto_expression` | Ekspresi otomatis per kalimat dari makna teks lip sync (id/ms/en): senang, sedih, kaget, marah, takut, berpikir; negasi dan tanda baca, antisipasi, kembali ke ekspresi dasar saat jeda, serta `cues` manual; artikulasi mulut dan kedipan tetap berjalan |
| `lip_sync`, `auto_blink` | Gerak mulut dari teks dan kedipan otomatis |
| `lip_sync_audio`, `transcribe_audio` | Gerak mulut dari rekaman suara (Whisper lokal: waktu tiap kata), audio ikut masuk ke video |
| `lip_sync`, `lip_sync_audio` — `detail="phoneme"` | Lip sync per fonem (default): `language="id"/"ms"/"en"` atau otomatis, durasi relatif di dalam tiap kata, transisi halus, antisipasi bibir bulat o/u/w, penutupan m/b/p dan kontak f/v; `detail="word"` untuk perilaku lama. Pelafalan dan waktu fonem berupa perkiraan aturan, bukan forced alignment akustik |
| `talk_motion` | Gerak kepala (angguk saat penekanan, miring per kalimat), alis, dan lirikan mata saat bicara; menatap kamera |
| `talk_gestures` | Gerak tangan saat bicara: postur bicara + beat, buka telapak, sapuan, menunjuk (lengkap dengan jari); mengikuti penekanan kata, plus gesture sesuai makna kata ("dua" → dua jari, "saya" → tangan di dada, "besar" → tangan melebar, "tidak" → telapak menyapu, ...) atau `cues` manual |
| `set_hand_pose` | Pose jari: rileks, terbuka, kepal, menunjuk, jempol, peace, tiga, empat, OK, dll. (rig MPFB, Mixamo, Rigify) |
| `add_audio`, `duck_music`, `list_audio`, `remove_audio` | Suara `kind="voice"/"music"/"sfx"`; musik `loop=True` sampai akhir adegan + `fade_in`/`fade_out` (detik); `duck_music(amount_db=-12)` menurunkan musik saat dialog; video otomatis bersuara AAC |
| `ai_text_to_speech` | Teks → suara (gratis, Chatterbox di Hugging Face, 23 bahasa) |
| `estimate_landmarks` | Posisi sendi yang akan dipakai rig (tersimpan atau hasil tebakan dari bentuk mesh) |
| `auto_rig_humanoid` | Rig `basic` (21 tulang) atau `rigify` (kontrol FK/IK), plus skinning otomatis |
| `validate_rig`, `list_bones`, `set_pose` | Cek kualitas rig, daftar tulang, pose dan keyframe |
| `list_animations`, `apply_pose` | 12 pose siap pakai (wave, cheer, sit, crouch, fight stance, dll.) |
| `animate` | Klip prosedural: idle, walk, run, wave, cheer, jump, nod, head_shake; disambung dengan crossfade otomatis (transisi halus, kaki tetap menapak) |
| `walk_path`, `turn_to` | Jalan/lari melewati target XY dengan lintasan halus, belok maksimal 100°/detik, langkah berputar di sudut tajam, kaki terkunci, lalu berhenti; bisa menghadap titik, objek, atau kamera (`face_end`); mendukung basic/Rigify/MPFB; `avoid="auto"` menghindari perabot dan karakter lain, `ignore` untuk pendekatan kursi |
| `import_mocap`, `retarget_animation` | Mocap .bvh/.fbx/.glb (CMU, Mixamo, dll.) ke rig apa pun, diselaraskan otomatis |
| `lock_feet` | Foot IK: kaki yang menapak dikunci di lantai (tidak selip, tidak tenggelam), tumit → jari berguling alami; otomatis di walk/run/jump dan mocap |
| `secondary_motion` | Ayunan rambut dan hem pakaian baked: `parts=["hair","clothes"]` atau nama objek/aset pakaian. Rok, gaun, ekor jaket/mantel longgar memakai hingga 12 rantai × 4 tulang deform; celana/kaus ketat dilewati dengan alasan. Bobot pinggang lama dibaurkan ke rantai, collider paha/betis + batas jarak tetangga menjaga hem. Jalankan terakhir setelah gerak/duduk/bicara; stiffness/damping/gravity/angin, rerun deterministik, `clear` per rentang, ekspor glTF/FBX. Hasil per pakaian: rantai/tulang, lag tip, clearance kapsul dan waktu bake. Pendekatan rantai elastis, bukan fisika kain per vertex; tanpa tabrakan kursi/prop |
| `add_terrain`, `clear_terrain` | Buat/hapus tangga, ramp, platform, dan satu anak tangga; mesh bertanda walkable. `walk_path` mengikuti tinggi permukaan, menempatkan telapak utuh pada pijakan, dan mengangkat kaki melewati tepi; `lock_feet(terrain=True)` mengikuti tinggi serta kemiringan lokal. Kecepatan dan irama berubah mulus di sepanjang rute: normal di lantai/platform datar, sedikit melambat sesuai kemiringan ramp, langkah jalan pendek dengan irama lebih cepat hanya di tangga. Permintaan lari tetap berlari di bagian datar/ramp dan beralih ke jalan di sekitar tangga (`terrain.gait`: `walk`, `run`, `run/walk`); putaran/langkah penutup memakai irama tersendiri. Tinggi anak tangga disarankan ≤0,20 m, tepi dengan lonjakan >0,25 m dihindari |
| `clear_animation`, `render_frames` | Hapus animasi; render beberapa frame untuk mengecek gerakan |
| `camera_shot`, `list_shots`, `delete_shot` | 23 gerak kamera, 8 ukuran shot, multi-shot otomatis; `avoid_occlusion="auto"` menjaga wajah, headroom, ukuran subjek dan area foreground |
| `set_lighting`, `set_material` | 10 preset cahaya (studio, sunset, neon, horror, dll.) + lantai; `follow="auto"` mengikuti karakter bergerak; material cepat |
| `dialog`, `stage_dialog` | Percakapan 2–4 karakter dalam satu panggilan: posisi saling berhadapan, lip sync per baris (audio/teks), saling menatap, pendengar mengangguk, gestur per pembicara, kamera two-shot lalu single per pembicara |
| `script_to_scene` | Naskah pendek Indonesia/Inggris atau dict → 1–4 karakter, outfit/jenggot/aksesori katalog, set, aksi jalan/duduk/berdiri/pegang prop, dialog, ekspresi, kamera, subtitle, cahaya serta gerak rambut dan kain longgar. `build=False` hanya membuat rencana tanpa mengubah adegan; hasil berisi frame, shot, warning dan waktu proses |
| `set_environment`, `add_prop`, `clear_environment` | Set prosedural: podcast_studio, classroom, office, stage, living_room, news_desk; furnitur, bangku, stool, cup, phone, book, handheld_microphone + lampu praktis dalam koleksi char3d_env, variant/tema warna dan gambar lokal pada layar/papan; bersihkan tanpa menghapus karakter/kamera |
| `sit_on`, `stand_up` | Duduk pada kursi/sofa/bangku/stool atau permukaan mesh: kontak bokong diukur, kaki IK menapak, arah mengikuti kursi, transisi halus dan pilihan posisi sofa; bisa dilapisi gerak bicara. Berdiri kembali di depan kursi; dudukan statis dan lantai datar |
| `hold_prop`, `release_prop` | Tempel cup/phone/book/mic atau prop lain ke telapak kiri/kanan. `upright=None` otomatis menjaga cup tegak dan mic condong 12° ke telapak/mulut; `True`/`False` mengaktifkan/menonaktifkan koreksi pergelangan, yaw mengikuti tangan. Grip jari bertahan saat gestur ditambahkan; release memulihkan animasi pergelangan/jari di bawahnya. Phone/book tetap mengikuti rotasi tangan. Ekspor glTF menyimpan transform tiap frame; tanpa simulasi jatuh atau solver tabrakan lengan/prop. Pose ekstrem dapat menekuk pergelangan tajam; sesuaikan pose lengan |
| `add_subtitles`, `remove_subtitles` | Subtitle otomatis dari waktu kata lip sync (atau teks/audio): gaya tiktok (kata aktif menyala + pop-in), karaoke, classic; dibakar ke video + file .srt |
| `add_transition`, `add_title`, `list_graphics`, `remove_graphics` | Grafis timeline: crossfade antar-shot (frame tambahan kamera keluar), fade in/out, dip hitam/putih; kartu judul dan lower third nama + peran dengan bar transparan, animasi slide/fade; digabung dengan subtitle tanpa mengubah durasi/audio |
| `render_options`, `render_video`, `render_status`, `cancel_render` | Render MP4 (H.264) di proses latar belakang: draft, preview, final, cycles; pilih resolusi 480p–4K (atau vertikal) dengan estimasi waktu render yang dikalibrasi per mesin (belajar dari render sebelumnya, atau `calibrate=True` untuk frame uji) |
| `set_timeline` | Rentang frame dan fps |
| `prepare_model` | Merapikan model dari luar: gabung mesh, kurangi poligon, skala tinggi, berdiri di lantai |
| `ai_text_to_3d`, `ai_image_to_3d` | Teks/gambar → model 3D → otomatis diimpor, dirapikan, dan di-rig (gratis lewat Hugging Face, atau berbayar lewat fal.ai) |
| `ai_image_to_video`, `ai_text_to_video` | Gambar/render → video AI ala Higgsfield (gratis lewat Hugging Face, atau berbayar lewat fal.ai) |
| `ai_status`, `ai_job_status`, `ai_cancel_job` | Status konfigurasi dan job AI |
| `run_blender_python` | Hanya aktif jika `CHAR3D_ALLOW_PYTHON=1` |

Konvensi pose dan resep alur kerja untuk AI ada di [AGENTS.md](AGENTS.md).

Panggil `set_lighting` setelah animasi tubuh (`walk_path`, `animate`, `sit_on`), lalu
ulangi jika geraknya berubah. `follow="auto"` mengikuti perpindahan horizontal di atas
0,43 x tinggi berdiri (~0,75 m untuk manusia); `True` mengikuti setiap perpindahan,
`False` mempertahankan lampu statis. Lampu SUN tetap statis. Hasil menyertakan `follow`,
`travel_m`, dan `keys` (jumlah sampel posisi).

`walk_path(..., avoid="auto", ignore=None)` memotret mesh terlihat pada frame awal:
perabot, properti, dan karakter lain menjadi rintangan statis. A* delapan arah memakai
sel 5 cm dan radius tubuh dari bahu/pinggul ditambah jarak aman 5 cm. Jalur kosong
mempertahankan key animasi persis; `avoid=False` memakai perilaku lama, `True` juga
mengaktifkan pemeriksaan. `turn_to` menerima opsi yang sama dan menolak putaran
jika radius tubuh awal terhalang, tanpa memindahkan karakter.

Tanah, permukaan walkable, bagian karakter sendiri, properti yang sedang dipegang,
dan geometri di luar irisan tinggi lokal 0,05–1,7 m dikecualikan. Tepi terrain dengan
beda tinggi >0,25 m menghalangi jalur. `ignore=[root_kursi]` mengabaikan objek beserta
turunannya untuk mendekat sebelum `sit_on`; gunakan nama root hasil `add_prop`.
Target di dalam rintangan dipindah ke sel kosong terdekat dengan `warnings`.
Posisi awal yang hanya masuk margin jarak aman (misalnya berdiri di belakang meja) melangkah
keluar dulu ke sel kosong terdekat (≤0,6 m, dengan warning); posisi awal yang lebih dalam
atau target tak terjangkau menghasilkan error sebelum baking.
Pencarian dibatasi 3–10 m di luar rute dan satu juta sel; pecah rute yang sangat luas.

Hasil menambah `avoided`, `detours`, `path_points` (termasuk awal), `body_radius_m`,
`clearance_m`, `planning_seconds`, dan `warnings`. Clearance mengukur jarak minimum
root yang disampel ke footprint mentah/tepi terrain; null jika tidak ada rintangan
atau `avoid=False`. Footprint convex tiap mesh bersifat konservatif. Rintangan tidak
bergerak selama perencanaan; tidak ada collision solver khusus tangan/kaki/anggota
tubuh atau prediksi gerakan karakter lain.

## Dari naskah menjadi adegan

```python
script_to_scene(script="""JUDUL: Pagi di Studio
LOKASI: office
ANA (perempuan, 28, rambut bob): Selamat pagi!
BUDI (laki-laki, 35, kasual): Terima kasih, Ana.
[Budi duduk di kursi]
ANA: Apa kabar hari ini?
""", language="id", seed=0)
```

Gunakan `build=False` untuk memeriksa rencana terlebih dahulu. `TITLE/LOCATION`,
`[Budi walks to 1, -1]`, `[Ana holds a cup]`, `[Ana looks at Budi]`, serta
`[pause 1 second]` juga didukung. Format dict memberi kontrol atas karakter
(`id`, `gender`, `age`, `hair`, `clothes`, `outfit`, `beard`, `accessories`, `race`) dan beat (`say`/`text`/`audio`/`emotion`,
atau `do`/`who` dengan `walk`, `sit`, `stand`, `hold`, `gesture`, `pose`, `look`, `pause`).
Kata deskripsi/arah panggung yang tidak dikenali dilaporkan sebagai warning.

Deskripsi outfit: `kasual/casual`, `formal/jas/resmi/elegant`, `olahraga/sport`,
`musim panas/summer`, `musim dingin/winter/jaket/coat`; `gaun/dress/rok/skirt` memilih
summer untuk perempuan. `jenggot/brewok/beard/kumis/moustache` memilih rambut wajah,
`kacamata/glasses` dan `topi/hat` memilih aksesori terpasang. Kata `suit` tetap memilih
setelan sistem. Dalam dict, gunakan `outfit="summer"` (juga casual/formal/sport/winter),
`beard=True` atau nama katalog, dan `accessories=["glasses", "hat"]`.
Outfit dipilih dengan seed per karakter (`seed + indeks * 101`); `clothes` eksplisit
(termasuk `[]`) mengesampingkan preset. Nama hair/clothes paket diterima; parse-only
menandainya unverified dan build memeriksa katalog terpasang. Nama paket dalam teks
disimpan di `assets` sampai jenisnya diketahui. Paket tidak tersedia → warning dan
outfit memakai setelan sistem; aksesori/jenggot yang tidak tersedia dilewati.

Teks menghasilkan gerak mulut tanpa suara; rekaman audio memakai Whisper lokal jika
tersedia dan ikut masuk ke video. MPFB tidak tersedia → manekin ber-rig dengan waktu
kata, subtitle dan gestur, tanpa animasi wajah. Tanpa waktu kata, subtitle dimatikan
dengan warning. Karakter yang diam tetap didukung. Aksi tubuh selesai sebelum baris
berikutnya; cahaya, gerak rambut serta kain longgar dihitung setelah animasi.
Rok/gaun mendapat gerak kain otomatis; baju ketat, rambut pendek dan karakter tanpa
bagian longgar dilewati. Pemilihan outfit belum menyelesaikan clipping baju/rambut/kursi;
periksa pose berjalan dan duduk di Eevee.
Nama karakter dibuat unik; objek lama dipertahankan, set terkelola mengikuti perilaku
`set_environment`. Tidak menyimpan atau merender otomatis. Periksa beberapa shot dengan
`render_frames(camera="scene", engine_name="eevee", size=512)`, lalu simpan dan render
draft. Format lengkap dan resep ada di [Script → scene](AGENTS.md#script--scene).

`camera_shot(..., avoid_occlusion="auto")` memeriksa wajah/mata pada awal, tengah,
akhir dan kira-kira setiap 0,5 detik dengan raycast mesh yang sudah dievaluasi.
Jika terhalang atau foreground terlalu penuh, kamera mencoba pedestal naik, sudut
±10–30°, lalu mendekat melewati penghalang. Setiap kandidat menyelesaikan aim dan
lensa agar proyeksi mata/puncak kepala/dada mengikuti desain awal: toleransi posisi
4% frame, ukuran subjek ±15%. Mata dari bounds karakter duduk yang terlalu tinggi
diarahkan ke garis 1/3 frame tanpa mengubah skala desain. Wajah harus terhalang
≤5%, mata close-up bebas, dan foreground ≤25% untuk close-up/medium (≤35% shot
lebih lebar), diukur dengan ray grid 24×14 sampai kedalaman mata subjek.
Gaze dialog mengikuti posisi kepala aktual sesudah jalan/duduk/berputar; target jauh
di samping juga memutar dada sedikit. Single dibuat sesudah gaze, mengikuti arah
wajah dan garis antar kepala saat itu agar eyeline konsisten di setiap cut.
Kursi generik yang menyembunyikan karakter di belakang lawan bicara atau membelakangi
percakapan diganti guest chair pada lantai kosong dengan jalur pendekatan yang bisa
dicapai; hasil tercatat di `warnings` dan `plan.guest_chairs`. Nama kursi eksplisit
tetap dihormati. Kamera dialog/`script_to_scene` tetap di sisi garis dialog saat itu;
kandidat di dalam mesh atau menembus dinding ditolak. Jika gagal, coba satu ukuran
lebih lebar; jika tetap gagal, kamera asli dipertahankan dengan `warning`.
Shot frontal bebas penghalang mempertahankan key kamera persis; `False` memakai framing
lama, `True` sama dengan `"auto"`. Single dialog juga memeriksa komposisi saat
wajah sudah bebas agar mata tetap di bagian sepertiga atas.
Wajah yang berpaling >75° juga memicu koreksi atau warning; `face_angle_before`
dan `face_angle` melaporkan sudut terburuk dalam derajat. Shot frontal bebas
penghalang mempertahankan key persis. Hasil `occlusion` memuat `before`/`after`,
`adjusted`, `sample_frames`, `seconds`,
`frame_coverage_before`/`frame_coverage_after`, `face_screen` (posisi mata 0..1 dari
kiri atas per sampel), `subject_scale` (rasio tinggi kepala–dada terhadap desain),
dan `shot_size` terpilih (juga di hasil utama). Bagian karakter sendiri, prop yang
dipegang, ground dan objek tersembunyi diabaikan. Landmark dan grid bersifat
perkiraan; objek tipis, gerakan di antara sampel, rambut sendiri dan animasi yang
diubah sesudahnya tetap perlu diperiksa dengan render Eevee.
Lihat [Shots](AGENTS.md#film-cameras-lighting-video).

## Kebutuhan
- Blender 5.2 LTS. Secara default dicari di `~/.local/opt/blender/blender`,
  bisa juga diatur lewat `CHAR3D_BLENDER`.
- Python 3.10+

## Instalasi
```bash
python3 -m venv .venv
```
```bash
.venv/bin/pip install -r requirements.txt
```
```bash
chmod +x run_mcp.sh
```

## Tes
```bash
.venv/bin/python tests/e2e_smoke.py
```
Tambahkan `CHAR3D_MPFB_PACK_VISUALS=1` untuk lembar Eevee front/¾ dari empat outfit
paket tambahan. Cek katalog, bobot, deformasi dan jalur tekstur selalu berjalan;
paket opsional yang belum terpasang dilewati dengan pesan.
Tambahkan `CHAR3D_ENV_VISUALS=1` untuk merender keenam set dengan karakter MPFB di Eevee;
tes standar merender kantor dan contoh gambar layar agar lebih cepat.

GitHub Actions (`.github/workflows/ci.yml`) menjalankan pemeriksaan tanpa Blender di setiap
push/PR: lint `ruff --select F`, compile semua modul, larangan `import bpy` di `mcp_server/`,
impor server MCP, dan `tests/test_phonemes.py`. Tes E2E Blender tetap dijalankan lokal.

## Menyambungkan ke AI
Ganti `/PATH/KE/char3d` dengan lokasi folder ini.

**Claude Code**
```bash
claude mcp add --scope user char3d -- /PATH/KE/char3d/run_mcp.sh
```

**Codex**
```bash
codex mcp add char3d -- /PATH/KE/char3d/run_mcp.sh
```

**Claude Desktop**: tambahkan ke `claude_desktop_config.json`:
```json
{ "mcpServers": { "char3d": { "command": "/PATH/KE/char3d/run_mcp.sh" } } }
```

## Manusia realistis (MPFB)
`create_realistic_human` memakai [MPFB](https://extensions.blender.org/add-ons/mpfb/) dan
paket aset sistem MakeHuman (CC0). Keduanya dipasang di Blender portable milik char3d,
jadi `~/.config/blender` tidak tersentuh. Instalasi (±327 MB, checksum diverifikasi):
```bash
scripts/install_mpfb.sh
```
Isinya: 23 kulit, 10 rambut, 12 alis, 4 bulu mata, 2 mata, gigi, lidah, 20 baju/sepatu/topi,
plus paket wajah `faceunits01` (52 blendshape ARKit) dan `visemes01` (22 bentuk mulut),
semuanya CC0.

Paket CC0 tambahan (opsional, sesudah instalasi dasar):
```bash
scripts/install_mpfb_packs.sh                  # semua 12 paket
scripts/install_mpfb_packs.sh shirts01 pants01 # atau pilih paket
```
Default: `shirts01 pants01 skirts01 dress01 suits01 hats01 glasses01 bodyparts05
hair01 shoes01 skins01 skins02`. Ukuran unduhan terkompresi: pakaian sekitar 176 MB,
`hair01` 217 MB, `shoes01` 79 MB, kulit (`skins01` + `skins02`) 172 MB, janggut 6 MB.
Skrip mencetak ukuran sebelum mengunduh, memakai cache `~/.local/opt/dl/mpfb/`
(`MPFB_DOWNLOAD_DIR` untuk menggantinya), mengecek SHA256 tercatat (peringatan bila
berubah), memvalidasi ZIP dengan MPFB, mengekstrak dan memperbarui daftar aset.
`CHAR3D_BLENDER` memilih executable; `MPFB_USER_DATA` dapat memilih direktori data
MPFB terpisah. Restart engine sesudah memasang paket.

`mpfb_assets()` menampilkan seluruh nama di `assets`, anggota paket di `packs`, serta
`clothing_categories` dan `clothing_metadata` (kategori, gender, nama, tags, z_depth).
Ada top/bottom/dress/suit/shoes/hat/glasses/beard/moustache; topi dan kacamata masuk
parameter `clothes`. `hair`, `skin`, `eyebrows`, `eyelashes` menerima semua nama yang
terpasang. `skin="auto"` tetap memilih kulit sesuai umur/gender/etnis.
Contoh:
```python
create_realistic_human("Rina", gender=0, hair="toigo_inverted_bob",
                      outfit="summer", seed=7)
create_realistic_human("Dani", gender=1, beard="wdg_scruffy_beard",
                      clothes=["namuhekam_male_polo_shirt", "cortu_cargo_pants",
                               "toigo_ankle_boots_male", "jujube_newsboy_cap",
                               "spamrakuen_sagerfrogs_glasses_01"])
```
Preset: `casual`, `formal`, `sport`, `summer`, `winter` (dengan topi). Pilihan diambil
dari aset terpasang dan menghindari gender yang berlawanan bila namanya/tags menyatakan
male/female; aset tanpa penanda dianggap unisex. Catalog/gender/seed yang sama memberi
pakaian yang sama. `clothes` eksplisit, termasuk `[]`, menggantikan preset; janggut
tetap ditambahkan. Hasil `warnings` memberitahu kategori yang tidak tersedia atau
pakaian bertumpuk (misalnya dua atasan atau setelan + atasan), tanpa menggagalkan
kombinasi eksplisit. Fitting, bobot tulang dan body hiding memakai mekanisme MPFB;
vertex pakaian/rambut yang tidak mendapat bobot diisi dari tetangga berbobot terdekat
tanpa mengubah bobot lain (`weights_repaired` melaporkan jumlah per mesh).
Tidak ada simulasi kain. Topi/rambut dan rok/pose ekstrem masih bisa berpotongan:
periksa `render_views(..., engine_name="eevee")` sebelum ekspor.

Lisensi: kode MPFB GPL-3.0 (tidak disalin ke repo ini, hanya dipanggil saat runtime);
aset MakeHuman CC0, jadi karakter hasilnya bebas dipakai, termasuk untuk komersial.

## Suara dan lip sync dari audio
- **Whisper** (faster-whisper, MIT) berjalan lokal di CPU dan mendeteksi waktu setiap kata
  dalam rekaman. Modelnya (`tiny`, ±75 MB) diunduh sekali saat pertama dipakai. Model yang
  lebih akurat bisa dipilih dengan `CHAR3D_WHISPER_MODEL=base` (±145 MB) atau `small`.
- Tanpa Whisper, lip sync tetap jalan memakai analisis suara (energi + spektrum), dan
  hasilnya lebih rapi kalau teks ucapannya diberikan.
- `ai_text_to_speech` memakai Space gratis Chatterbox Multilingual (23 bahasa, **belum ada
  bahasa Indonesia**; yang paling dekat `ms`/Melayu). Kuota GPU anonim harian kecil;
  `HF_TOKEN` gratis menaikkannya. Fitur tiru suara (`voice_reference`) hanya boleh untuk
  suara sendiri atau suara yang sudah mendapat izin.

## AI providers
Alat `ai_*` bisa memakai dua provider (parameter `provider`):

| Provider | Biaya | Kelebihan | Kekurangan |
|---|---|---|---|
| `hf` — Hugging Face Spaces | **Gratis**, tanpa key | Langsung jalan | Antrean, kuota GPU harian, Space bisa offline, video pendek |
| `fal` — fal.ai | Berbayar per pemakaian | Cepat, stabil, model video lebih kuat | Perlu `FAL_KEY` |

`auto` (default) memakai fal kalau `FAL_KEY` ada, kalau tidak memakai Hugging Face gratis.

### Gratis: Hugging Face Spaces
Tidak perlu apa-apa. Supaya kuota GPU gratis lebih besar, buat akun Hugging Face gratis,
buat token "Read", lalu simpan di file rahasia yang sama (lihat langkah fal di bawah)
sebagai baris `HF_TOKEN=isi_token_anda`.

| Tugas | Resep default | Pilihan lain (`model=`) |
|---|---|---|
| teks → gambar | `flux-schnell` (FLUX.1-schnell) | — |
| gambar → 3D | `hunyuan3d` (Hunyuan3D-2, tanpa tekstur) | `hunyuan3d-textured`, `trellis`, `stable-fast-3d` |
| gambar → video | `ltx` (LTX-Video, maks 8 detik) | `wan` (Wan 2.2, maks 5 detik) |
| teks → video | `ltx` | — |

### Berbayar: fal.ai

1. Buat API key di dashboard fal.ai.
2. Simpan key di file **di luar repo** (dibaca otomatis oleh `run_mcp.sh`, berlaku untuk
   Claude dan Codex):
   ```bash
   mkdir -p ~/.config/char3d && touch ~/.config/char3d/env && chmod 600 ~/.config/char3d/env
   ```
   Lalu isi file itu dengan satu baris `FAL_KEY=isi_key_anda` memakai editor teks.
3. Restart Claude Desktop atau buka sesi Codex baru, lalu minta AI menjalankan `ai_status`.

Model default (bisa diganti per panggilan dengan `model=`, atau secara global lewat
variabel lingkungan `CHAR3D_MODEL_TEXT_TO_IMAGE`, `CHAR3D_MODEL_IMAGE_TO_3D`,
`CHAR3D_MODEL_IMAGE_TO_VIDEO`, `CHAR3D_MODEL_TEXT_TO_VIDEO`):

| Tugas | Model default |
|---|---|
| teks → gambar konsep | `fal-ai/flux/schnell` |
| gambar → 3D | `fal-ai/hunyuan3d/v2` |
| gambar → video | `fal-ai/kling-video/v2.1/standard/image-to-video` |
| teks → video | `fal-ai/kling-video/v2.1/standard/text-to-video` |

Nama model dan format inputnya bisa berubah di fal.ai. Kalau ada error 404/422,
cek halaman model di fal.ai lalu kirim `model=` dan `extra_input=` yang sesuai.

Uji alur AI tanpa key dan tanpa internet (memakai server fal.ai tiruan lokal):
```bash
.venv/bin/python tests/e2e_ai_mock.py
```

## Pengaturan (variabel lingkungan)
| Variabel | Default | Arti |
|---|---|---|
| `CHAR3D_BLENDER` | `~/.local/opt/blender/blender` | Lokasi Blender |
| `CHAR3D_PORT` | `9876` | Port lokal engine (dipakai bersama Claude dan Codex) |
| `CHAR3D_WORKSPACE` | `./output` | Folder hasil (renders, exports, projects, imports) |
| `CHAR3D_ALLOW_PYTHON` | (mati) | `1` = AI boleh menjalankan Python bebas di Blender |
| `FAL_KEY` | (kosong) | API key fal.ai untuk alat `ai_*` (simpan di `~/.config/char3d/env`) |
| `CHAR3D_ENV_FILE` | `~/.config/char3d/env` | File rahasia yang dibaca `run_mcp.sh` |

## Catatan
- Komputer tanpa GPU: render Workbench ±1 detik, Eevee ±10 detik per gambar
  (512 px). Cycles lambat, jadi gunakan hanya untuk hasil final.
- Konvensi: satuan meter, sumbu Z ke atas, karakter menghadap -Y.

### Render styles

`render_style("anime")` memberi cel shading dengan warna/tekstur asli dan outline
siluet tipis. Kulit, mata dan alpha rambut tetap terbaca. `outline=False` mematikan
outline. `clay` memakai clay matte seragam; `film` memakai AgX, glow ringan, vignette
dan grain; `noir` hitam putih kontras; `vintage` hangat dan pudar.

```python
render_style("film", strength=0.8, grade={"teal_orange": True, "exposure": 0.2}, letterbox=True)
render_frames([1], camera="scene", engine_name="eevee", size=512)
render_style("none")
```

`grade` mendukung exposure (-8..8 stop), contrast/saturation (0..3; netral 1),
temperature/tint (-1..1; netral 0). `letterbox=True` = 2.39:1, atau rasio 1..4.
Konfigurasi bertahan lewat save/open dan render video terpisah. Material, modifier,
world dan pengaturan view asli dipulihkan sesudah render, termasuk saat gagal.
Draft/workbench tetap seperti sebelumnya; judul/subtitle digambar sesudah grade.
`render_options` menyertakan faktor biaya style dalam estimasi. Outline hanya untuk
mesh opaque; alpha hair cards dan fitur mata dilewati. Shader kustom tanpa Principled
tetap memakai shading aslinya. Cycles memakai Toon BSDF, sehingga ramp berbeda dari Eevee.


Uji CPU Eevee 540p dengan karakter MPFB: anime + outline ≈ 1.20× waktu normal;
clay/film/noir/vintage 0.84–0.96× pada adegan uji. Estimasi tetap konservatif dan
belajar dari kecepatan mesin. Detail angka dan batas outline ada di AGENTS.md.

## Lisensi
MIT — lihat [LICENSE](LICENSE). Aset MPFB/MakeHuman berlisensi CC0; gambar, audio, dan
model milik pengguna tetap mengikuti lisensinya masing-masing.
