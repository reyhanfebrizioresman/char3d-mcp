# char3d — Engine Karakter 3D untuk AI (MCP + Blender)

Engine ini menjalankan Blender di latar belakang dan membuka fungsinya sebagai
"alat" MCP. Claude, Codex, atau klien MCP lain bisa membuat, memeriksa, merender,
dan meng-export aset 3D.

```
Claude / Codex ──MCP──► mcp_server/ ──TCP lokal──► Blender (engine/) ──► .glb .blend .png
```


Gaya `render_style("animated_film")` (`animasi`/`film_animasi`) menyatukan karakter,
alam, dan set dengan empat massa cahaya lembut, bayangan berwarna, tekstur lebih
bersih, kulit hangat dan rim yang jelas. Palet mengikuti cinematic look, termasuk
malam dan kabut. Bisa dipilih lewat `style=` atau header naskah `GAYA: animasi`;
override render bersifat sementara. Wajah dialog/naskah/film kini memakai `face_life` secara
bawaan: ekspresi mikro, kedipan bervariasi, gerak mata, reaksi pendengar, dan napas
halus yang tidak menimpa kurva viseme/tubuh. Gunakan `life=0` untuk menonaktifkannya;
`face_life(..., intensity=1, seed=3)` tersedia untuk adegan manual.

## Status
✅ Fase 1 (fondasi) · ✅ Fase 2 (karakter + rigging) · ✅ Fase 3 (animasi) · ✅ Fase 4 (kamera, cahaya, video) · ✅ Fase 6 (integrasi AI: Hugging Face gratis + fal.ai) · ✅ Manusia realistis (MPFB)

| Alat | Fungsi |
|---|---|
| `engine_status` | Menyalakan Blender bila belum jalan, lalu menampilkan versi dan folder kerja |
| `scene_info` | Daftar objek, ukuran, statistik mesh/armature, animasi |
| `new_scene` | Adegan kosong |
| `add_primitive`, `transform_object`, `delete_objects` | Objek dasar |
| `import_model` | .glb .gltf .fbx .obj .stl .ply .usd .bvh; .vrm dengan add-on opsional |
| `export_asset` | .glb (disarankan, ikut animasi) .gltf .fbx .obj .usd .bvh; Rigify hanya tulang deform; `max_influences=4` membatasi bobot untuk game tanpa mengubah adegan (hasil: `vertices_limited`) |
| `save_project`, `open_project` | File .blend |
| `cinematic_look` | Suasana sinematik prosedural: langit/matahari, haze, berkas cahaya, bloom, grade dan fokus otomatis pada kepala; bisa dibersihkan dengan `clear=True` |
| `render_style` | Preset anime/toon, clay, film, noir, vintage; non-destruktif, tersimpan di .blend; `none` mengembalikan tampilan asli |
| `render_preview`, `render_views` | Render pratinjau (kamera otomatis atau kamera shot), gambarnya dikirim balik ke AI; `engine_name="eevee"` untuk tekstur |
| `create_human` | Karakter manekin prosedural: realistic, heroic, stylized, cartoon, chibi |
| `create_realistic_human`, `mpfb_assets` | Manusia realistis (MakeHuman/MPFB): kulit, rambut, baju, sepatu, janggut, aksesori; kategori pakaian + preset `outfit` dengan `seed`; rig `game_engine`, `mixamo`, `rigify` |
| `upgrade_materials` | Material kulit, mata basah, rambut dan kain yang ditingkatkan; `quality="mpfb"` memulihkan material asli |
| `set_expression`, `list_expressions` | 24 ekspresi wajah (senyum, tawa, sedih, marah, kaget, kedip, dll.) + 52 unit ARKit |
| `auto_expression` | Ekspresi otomatis per kalimat dari makna teks lip sync (id/ms/en): senang, sedih, kaget, marah, takut, berpikir; negasi dan tanda baca, antisipasi, kembali ke ekspresi dasar saat jeda, serta `cues` manual; artikulasi mulut dan kedipan tetap berjalan |
| `lip_sync`, `auto_blink` | Gerak mulut dari teks dan kedipan otomatis |
| `lip_sync_audio`, `transcribe_audio` | Gerak mulut dari rekaman suara (Whisper lokal: waktu tiap kata), audio ikut masuk ke video |
| `lip_sync`, `lip_sync_audio` — `detail="phoneme"` | Lip sync per fonem (default): `language="id"/"ms"/"en"` atau otomatis, durasi relatif di dalam tiap kata, transisi halus, antisipasi bibir bulat o/u/w, penutupan m/b/p dan kontak f/v; `detail="word"` untuk perilaku lama. Pelafalan dan waktu fonem berupa perkiraan aturan, bukan forced alignment akustik |
| `talk_motion` | Gerak kepala (angguk saat penekanan, miring per kalimat), alis, dan lirikan mata saat bicara; menatap kamera |
| `talk_gestures` | Gerak tangan saat bicara: postur bicara + beat, buka telapak, sapuan, menunjuk (lengkap dengan jari); mengikuti penekanan kata, plus gesture sesuai makna kata ("dua" → dua jari, "saya" → tangan di dada, "besar" → tangan melebar, "tidak" → telapak menyapu, ...) atau `cues` manual |
| `set_hand_pose` | Pose jari: rileks, terbuka, kepal, menunjuk, jempol, peace, tiga, empat, OK, dll. (rig MPFB, Mixamo, Rigify) |
| `auto_music`, `add_audio`, `duck_music`, `list_audio`, `remove_audio` | Musik prosedural orisinal yang mengikuti adegan, otomatis turun saat dialog; audio manual `kind="voice"/"music"/"sfx"`, loop dan fade; video bersuara AAC |
| `auto_sfx` | Foley prosedural tersinkron: langkah dari kontak kaki, duduk/berdiri, rustle kain opsional, ambience sesuai set; WAV 48 kHz/16-bit dengan seed dan cache hash, tanpa sampel unduhan |
| `list_voices`, `text_to_speech` | Pilih mesin/suara: Piper offline, Edge online, F5 opsional, Chatterbox online; WAV 48 kHz dengan cache, pitch dan tempo |
| `ai_text_to_speech` | Teks → suara (gratis, Chatterbox di Hugging Face, 23 bahasa) |
| `estimate_landmarks` | Posisi sendi yang akan dipakai rig (tersimpan atau hasil tebakan dari bentuk mesh) |
| `auto_rig_humanoid` | Rig `basic` (21 tulang) atau `rigify` (kontrol FK/IK), plus skinning otomatis |
| `validate_rig`, `list_bones`, `set_pose` | Cek kualitas rig, daftar tulang, pose dan keyframe |
| `list_animations`, `apply_pose` | 12 pose siap pakai (wave, cheer, sit, crouch, fight stance, dll.) |
| `animate` | Klip prosedural dan 46 gerak baru: bahasa tubuh emosi, reaksi, aksi harian, tiga tarian dengan `bpm`, serta fight bergaya; crossfade dan foot IK. Daftar lengkap serta kebutuhan prop/kursi: `list_animations()` |
| `walk_path`, `turn_to` | Jalan/lari melewati target XY dengan lintasan halus, belok maksimal 100°/detik, langkah berputar di sudut tajam, kaki terkunci, lalu berhenti; bisa menghadap titik, objek, atau kamera (`face_end`); mendukung basic/Rigify/MPFB; `avoid="auto"` menghindari perabot dan karakter lain, `ignore` untuk pendekatan kursi |
| `import_mocap`, `retarget_animation` | Mocap .bvh/.fbx/.glb (CMU, Mixamo, dll.) ke rig apa pun, diselaraskan otomatis |
| `lock_feet` | Foot IK: kaki yang menapak dikunci di lantai (tidak selip, tidak tenggelam), tumit → jari berguling alami; otomatis di walk/run/jump dan mocap |
| `secondary_motion` | Ayunan rambut dan hem pakaian baked: `parts=["hair","clothes"]` atau nama objek/aset pakaian. Rok, gaun, ekor jaket/mantel longgar memakai hingga 12 rantai × 4 tulang deform; celana/kaus ketat dilewati dengan alasan. Bobot pinggang lama dibaurkan ke rantai, collider paha/betis + batas jarak tetangga menjaga hem. Jalankan terakhir setelah gerak/duduk/bicara; stiffness/damping/gravity/angin, rerun deterministik, `clear` per rentang, ekspor glTF/FBX. Hasil per pakaian: rantai/tulang, lag tip, clearance kapsul dan waktu bake. Pendekatan rantai elastis, bukan fisika kain per vertex; tanpa tabrakan kursi/prop |
| `add_terrain`, `clear_terrain` | Buat/hapus tangga, ramp, platform, dan satu anak tangga; mesh bertanda walkable. `walk_path` mengikuti tinggi permukaan, menempatkan telapak utuh pada pijakan, dan mengangkat kaki melewati tepi; `lock_feet(terrain=True)` mengikuti tinggi serta kemiringan lokal. Kecepatan dan irama berubah mulus di sepanjang rute: normal di lantai/platform datar, sedikit melambat sesuai kemiringan ramp, langkah jalan pendek dengan irama lebih cepat hanya di tangga. Permintaan lari tetap berlari di bagian datar/ramp dan beralih ke jalan di sekitar tangga (`terrain.gait`: `walk`, `run`, `run/walk`); putaran/langkah penutup memakai irama tersendiri. Tinggi anak tangga disarankan ≤0,20 m, tepi dengan lonjakan >0,25 m dihindari |
| `clear_animation`, `render_frames` | Hapus animasi; render beberapa frame untuk mengecek gerakan |
| `camera_shot`, `list_shots`, `delete_shot` | 23 gerak kamera, 8 ukuran shot, multi-shot otomatis; `avoid_occlusion="auto"` menjaga wajah, headroom, ukuran subjek dan area foreground |
| `set_lighting`, `set_material` | 10 preset cahaya (studio, sunset, neon, horror, dll.) + lantai; `follow="auto"` mengikuti karakter bergerak; material cepat |
| `dialog`, `stage_dialog` | Percakapan 2–4 karakter dalam satu panggilan: posisi saling berhadapan, lip sync per baris (audio/teks), saling menatap, pendengar mengangguk, gestur per pembicara, kamera two-shot lalu single per pembicara |
| `script_to_film`, `film_info`, `open_film_scene`, `film_render_options`, `render_film` | Naskah multiadegan → proyek per adegan + manifest → satu MP4/AAC/SRT; storyboard, kontinuitas tokoh, transisi, kartu judul, cache render dan pembatalan |
| `script_to_scene` | Naskah pendek Indonesia/Inggris atau dict → 1–4 karakter, outfit/jenggot/aksesori katalog, set, aksi jalan/duduk/berdiri/pegang prop, dialog, ekspresi, kamera, subtitle, cahaya serta gerak rambut dan kain longgar. `build=False` hanya membuat rencana tanpa mengubah adegan; hasil berisi frame, shot, warning dan waktu proses |
| `set_environment`, `add_prop`, `clear_environment` | Set prosedural indoor + city_street, park, cafe_terrace, beach; tanah walkable, furnitur/seats, lampu praktis, variant/tema warna dan gambar lokal; bersihkan tanpa menghapus karakter/kamera |
| `set_weather` | clear/rain/snow/fog/wind; partikel deterministik tersimpan di .blend, area kamera, tanah basah, sky/sun, wind untuk rambut/kain |
| `sit_on`, `stand_up` | Duduk pada kursi/sofa/bangku/stool atau permukaan mesh: kontak bokong diukur, kaki IK menapak, arah mengikuti kursi, transisi halus dan pilihan posisi sofa; bisa dilapisi gerak bicara. Berdiri kembali di depan kursi; dudukan statis dan lantai datar |
| `hold_prop`, `release_prop` | Tempel cup/phone/book/mic atau prop lain ke telapak kiri/kanan. `upright=None` otomatis menjaga cup tegak dan mic condong 12° ke telapak/mulut; `True`/`False` mengaktifkan/menonaktifkan koreksi pergelangan, yaw mengikuti tangan. Grip jari bertahan saat gestur ditambahkan; release memulihkan animasi pergelangan/jari di bawahnya. Phone/book tetap mengikuti rotasi tangan. Ekspor glTF menyimpan transform tiap frame; tanpa simulasi jatuh atau solver tabrakan lengan/prop. Pose ekstrem dapat menekuk pergelangan tajam; sesuaikan pose lengan |
| `interact` | Dua karakter bersalaman, berpelukan, tos, fist bump, menyerahkan prop, atau menepuk bahu; pendekatan jalan/putar, IK lengan ke titik kontak bersama, jari dan tatapan pasangan; basic/Rigify/MPFB termasuk beda tinggi |
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

## Suasana sinematik

Tambahkan `SUASANA: senja` (atau `LOOK:` / `MOOD:`) pada naskah, atau panggil
`script_to_scene(naskah, look="golden_hour")`. Tanpa pilihan suasana, hasil dan biaya
render tetap seperti sebelumnya; rencana hanya memberi saran. Picker **Suasana** di
Naskah memilih tampilan saat membangun, sedangkan di Adegan tombol **Terapkan &
pratinjau** langsung membuat pratinjau Eevee.

`cinematic_look("golden_hour")` bekerja pada adegan yang sudah ada. Pilihan lain:
`sunset`, `misty_morning`, `blue_hour`, `night`, `overcast_soft`, `dreamy`, `epic`,
`studio_film`, `none`; alias Indonesia termasuk `senja`, `pagi berkabut`, `malam`,
`mimpi`, dan `epik`. Terapkan setelah set, cahaya, kamera dan cuaca. `intensity=0..1`
mengatur kekuatan, `sun={"elevation":8,"azimuth":220}` mengatur posisi matahari,
`particles="petals"` menambahkan partikel, dan `dof="off"` mematikan DOF otomatis.

Langit, haze dan cahaya dibuat lokal tanpa unduhan. Kamera karakter lama maupun
baru mengikuti kepala dengan DOF sesuai ukuran shot. Efek hanya diterapkan saat
render berwarna; workbench tetap cepat. `clear=True` mengembalikan data asli karena
world, lampu, kamera dan compositor pengguna tidak pernah diubah permanen. Konfigurasi
tersimpan dalam `.blend` dan ikut snapshot video. Grade `render_style` mengambil
prioritas atas grade suasana; bloom/vignette digabung satu kali. Fog cuaca menggantikan
haze agar tidak menumpuk. Lihat [panduan dan biaya CPU](AGENTS.md#cinematic-look).

## Kit alam prosedural

Park dan beach kini memakai vegetasi berdaun, rumput/bunga, air beriak dan latar
berlapis. Preset baru: `blossom_garden`, `pine_forest`, `lakeside`, `riverside`,
`rice_terraces`, `mountain_village`. Naskah menerima `LOKASI: hutan pinus`, `danau`,
`sungai`, `sawah bertingkat`, `desa pegunungan` atau `kebun bunga`.
`set_environment(..., density=1)` mengatur kepadatan (.2–2).

`nature_catalog`, `add_nature` dan `clear_nature` menyediakan 29 generator asli
tanpa unduhan: delapan jenis pohon, semak, padang rumput/bunga, sawah, bukit,
pegunungan, batu, jalan, air, awan, kelopak/daun, burung dan kupu-kupu.
Tersedia juga pagar, lampu, jembatan kayu, gazebo, rumah desa, gubuk sawah, pakis,
batang tumbang sebagai tempat duduk, dan kunang-kunang.
Set mempunyai komposisi khusus: dermaga danau, sungai berkelok dengan jembatan,
sawah berkontur dengan pematang naik, taman berkolam, dan hutan pinus berpakis.
Library murni, parameter dan batasnya: [engine/nature/README.md](engine/nature/README.md).
Gerak tersimpan dalam `.blend`; angin mengikuti cuaca. Periksa Eevee dengan
`golden_hour` atau `misty_morning`; `render_options` melaporkan faktor biaya nature.

Kamera naskah/film kini memakai `camera="directed"` (alias `emosi`/`emotional`):
ukuran shot, gerak dan ritme mengikuti kurva emosi, dengan OTS serta reaksi pendengar
saat suara pembicara tetap berjalan. Hasil memuat alasan setiap shot dan kurva emosi.
Cue `[KAMERA: ...]` tetap diutamakan; `dialog` tetap default `mixed`.
`camera_shot(shot="ots", subject=[tokoh, partner])` membingkai wajah tokoh dengan
belakang kepala dan bahu partner di foreground (sekitar 20–35% lebar frame),
dengan sisi garis dialog tetap konsisten. Hasil melaporkan fraksi foreground;
review memberi warning ringan untuk adegan panjang dengan cakupan statis monoton.
Timing reaksi bersifat heuristik; periksa wajah dan framing.
Dialog meja tanpa blocking khusus menempatkan kedua tamu duduk dan mic di bawah
mulut. Kamera melindungi wajah yang berbicara; caption dan judul otomatis mencari
ruang yang tidak menutupi wajah atau bertabrakan. `review_scene(fix=True)` dapat
memperbaiki kamera terhalang properti serta layout teks lama.

## Suara dialog otomatis

```bash
scripts/install_tts.sh               # Piper + Edge; unduhan Piper ~63 MB + paket
```

`script_to_scene(naskah, language="id", tts_engine="piper")` sekarang membuat
suara dialog otomatis secara **offline**. Gender, usia dan seed memilih variasi
suara per karakter; pilih sendiri lewat bagian **Suara** di UI atau deskripsi
`ANA (perempuan, 28, suara: edge:id-ID-GadisNeural): Halo!`. Dict karakter menerima
`voice`, `pitch` (semiton), dan `rate` (pengali tempo). `build=False` menampilkan
casting tanpa menghasilkan suara atau menghubungi jaringan. `voice=False` mematikan
suara sintetis; `sound` mengatur Foley secara terpisah. `dialog(..., voice=True)`
mengaktifkan fitur yang sama; default `dialog` tetap tanpa TTS.

`list_voices(language="id")` menampilkan status dan perintah instalasi;
`text_to_speech("Halo!", engine="piper")` menghasilkan WAV siap untuk
`lip_sync_audio(..., timing="text", text="Halo!")`. Model disimpan di
`~/.local/share/char3d/tts/` (`CHAR3D_TTS_DIR`), cache di `output/imports/audio/tts/`.
Tool tidak mengunduh model otomatis; saat TTS belum tersedia, adegan tetap dibangun
dengan gerak mulut dan peringatan.

Piper Indonesia hanya memiliki satu speaker (wanita), sehingga suara tokoh dibuat dengan
menggeser nada (PSOLA) dan formant ke nada khas gender/usia: pria dewasa ~125 Hz,
wanita ~215 Hz, anak ~270 Hz. `suara berat`/`suara tinggi` menggeser ±3 semiton. Runtime Piper berlisensi GPL-3.0; repo model berlabel MIT tetapi
tautan dataset pada model card belum jelas, jadi perlakukan model Indonesia sebagai
**penggunaan pribadi**. Edge memakai API Microsoft tidak resmi yang dapat berubah;
**teks dikirim ke Microsoft hanya bila Edge dipilih** (Ardi/Gadis). Chatterbox juga
online, berkuota, dan belum mendukung Indonesia. UI meminta persetujuan sebelum
mengirim teks. F5 tersedia sebagai backend offline opsional.
`scripts/install_tts.sh f5` meminta konfirmasi untuk venv CPU terpisah (~3 GB),
checkpoint 1.348.431.976 byte, vocab paket 11.255 byte dan Vocos 54.365.991 + 461 byte;
manifest ukuran/SHA-256 ada di `scripts/f5_assets.tsv`. Override interpreter:
`CHAR3D_F5_PYTHON=~/.local/share/char3d/f5-venv/bin/python`. Inferensi selalu offline,
memakai worker JSON yang memuat model sekali; `cancel_tts()` menghentikannya.
Kode F5 [MIT](https://github.com/SWivid/F5-TTS/blob/main/LICENSE),
[finetune Indonesia](https://huggingface.co/anantoj/f5-id-v1) Apache-2.0;
[bobot dasar](https://github.com/SWivid/F5-TTS#license) CC-BY-NC → pribadi/nonkomersial.
Suara bawaan `f5:female_adult`, `f5:male_adult`, `f5:elder`, `f5:child` berasal dari
output Piper sintetis (satu speaker dengan variasi pitch; batas penggunaan Piper tetap
berlaku), bukan contoh rekaman paket yang izin suaranya belum jelas. Casting memilih
referensi menurut gender/umur. `list_voices(engine="f5")` menampilkan katalog lokal.

```python
text_to_speech("Selamat pagi!", engine="f5", voice="f5:female_adult")
script_to_scene("MUSIK: haru\nANA (perempuan, 28): Halo!", tts_engine="f5", language="id")
# Gunakan hanya suara sendiri atau suara dengan izin pemiliknya:
text_to_speech("Halo!", engine="f5", voice_reference="audio/saya.wav",
               reference_text="Transkrip persis rekaman saya.")
```

Rekam WAV mono bersih 8–12 detik, satu pembicara, ruangan tenang, tanpa musik,
reverb atau clipping, lalu tuliskan seluruh kata. Referensi juga bisa didaftarkan
melalui JSON `tts/f5/voices/<nama>.json` dengan `voice_reference`, `reference_text`,
`gender`, `age`, `language`. Jangan gunakan suara Edge/Microsoft atau orang tanpa izin.
Worker memakai `HF_HUB_OFFLINE=1`, tidak mengunduh ASR, dan tidak mengimpor torch
ke MCP. Cache mencakup referensi dan pengaturan; timeout `CHAR3D_F5_TIMEOUT=600`,
langkah `CHAR3D_F5_STEPS=8|16|24|32|64` (default 32), thread `CHAR3D_F5_THREADS=2`.
Int8 eksperimental: `CHAR3D_F5_QUANTIZE=1`. F5 CPU jauh lebih lambat dari real time;
Piper tetap default. Pada i5-4460 dengan empat thread, draft 8 langkah membutuhkan
sekitar 40–46 detik untuk 2–3 detik suara; smoke 32 langkah membutuhkan 167,9 detik
untuk 2,19 detik suara mentah (RTF 76,8). Preset child pada 8 langkah memiliki WER
Whisper lebih buruk daripada pembanding Piper; F5 tidak selalu meningkatkan setiap profil.
Demo 10 kalimat × 4 suara dan pembanding Piper, WER Whisper,
F0, durasi, loudness, clipping, waktu dan RTF: `tests/audio2_demos.py` →
`output/voice_demos_f5/`.

`interact(a, b, "handshake")` menyambung setelah animasi kedua rig. Pilih
`hug`, `high_five`, `fist_bump`, `handover`, atau `pat_shoulder`; `start_frame`
menentukan awal, `hold_seconds` durasi kontak, `side="left"` untuk tangan kiri.
`approach=True` memakai jalan/putar dengan penghindaran rintangan statis;
`False` menjaga posisi dan menolak kontak yang tak terjangkau. Untuk menyerahkan
cangkir: `hold_prop(a, cup)` lalu `interact(a, b, "handover", prop=cup)`.
Attachment telapak pindah ke b tanpa mengubah transform dunia prop saat kontak;
animasi lampau tetap tersimpan, termasuk saat ekspor glTF. Hasil berisi frame
approach/reach/contact/release/end, `moved`, `contact_error_m` dan `penetration_m`
pelukan (proxy dada/lengan, bukan jaminan bebas tabrakan mesh/pakaian).
Periksa Eevee dari depan tiga-perempat dan samping. Naskah juga menerima
`[Sari dan Dimas bersalaman]`, `[mereka berpelukan]`, `[Sari tos dengan Dimas]`,
`[Sari memberikan buku kepada Dimas]`, serta padanan Inggris; dict memakai
`{"do":"interact", "who":"Sari", "with":"Dimas", "kind":"handshake"}`.

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
bergerak selama perencanaan; perencana rute tidak memprediksi gerakan karakter lain.

`resolve_collisions()` memperbaiki benturan pada animasi yang sudah dibake: tangan/
lengan, prop yang dipegang, lutut, offset dada kecil, dan garment longgar. Proxy tubuh
mengikuti ukuran mesh; furnitur memakai BVH segitiga. Pass otomatis berjalan setelah
gesture, aksi, interaksi, duduk, dialog dan script (`collisions=False` untuk mematikan).
Root/kaki, wajah, jari dan target kontak dipertahankan. Hasil melaporkan penetrasi
sebelum/sesudah, frame koreksi, konflik yang dilewati dan waktu proses. Gunakan
`report_only=True` untuk mengukur saja. Ini bukan simulasi cloth penuh atau collision
setiap jari/vertex; benturan besar atau kontak terlindungi masih perlu penataan ulang.

## Sutradara AI — dari ide menjadi treatment dan naskah

Di layar **Naskah → Adegan**, tulis ide seperti “dua sahabat bertemu lagi di taman
saat senja setelah 10 tahun, haru” pada panel **Sutradara AI**. Pilih durasi, tokoh,
genre, suasana dan lokasi bila perlu. Hasilnya dua tab: **Prompt sutradara** berisi
treatment visual rinci, dan **Naskah char3d** siap diedit. Klik **Pakai naskah ini**,
**Lihat rencana**, lalu **Bangun adegan**. Tombol **Kembalikan naskah sebelumnya**
memulihkan teks dan pengaturan editor sebelum draf dipakai.

- **Offline · gratis** (default): lokal, templat Indonesia/English, variasi tetap
  untuk seed yang sama. Tidak mengirim ide atau membutuhkan API key.
- **Claude langganan · via Claude Code**: memakai kuota langganan Claude untuk
  penggunaan pribadi. CLI ditemukan dari `CHAR3D_CLAUDE_BIN`, PATH, atau bundel
  Claude Desktop terbaru. Jalankan `claude` sekali lalu login (gunakan path lengkap
  jika tidak ada di PATH). Tidak ada tagihan API per draf dari char3d. CLI dijalankan
  tanpa tools/MCP, tanpa penyimpanan sesi, di folder sementara kosong.
- **Claude API · berbayar**: tambahkan baris berikut ke `~/.config/char3d/env`
  menggunakan editor teks, lalu restart MCP/web UI. Jangan menyimpan key di repo:

  ```dotenv
  ANTHROPIC_API_KEY=isi_key_Anda_di_sini
  ```

  SDK juga mendukung `ANTHROPIC_AUTH_TOKEN` dan profil Anthropic. Default model
  `claude-opus-5-5`; opsi `CHAR3D_DIRECTOR_MODEL` dan `CHAR3D_DIRECTOR_EFFORT=medium`.
  Estimasi memakai tarif Opus 5.5 $4 input/$20 output per juta token (cache tulis
  5 menit $5, baca $0.20), biasanya sekitar $0.05–$0.25 per draf. Output maksimal
  16000 token adalah sekitar $0.32 + input per permintaan; satu perbaikan dapat
  menambah biaya. Pemakaian token dan estimasi aktual tampil bersama hasil.
  Override model tetap memakai estimasi Opus berlabel; tagihan aktual dapat berbeda.
  [Tarif resmi Anthropic](https://platform.claude.com/docs/en/about-claude/pricing).

Kedua pilihan Claude meminta persetujuan sebelum mengirim ide dan opsi ke Anthropic.
**Auto** memilih CLI tersedia, lalu API dikonfigurasi, hanya dengan persetujuan;
selain itu offline. Jika layanan gagal, draf offline disertai peringatan yang jelas,
tanpa berpindah diam-diam ke API berbayar. Tidak ada panggilan online saat memeriksa
status. Model tidak diberi akses file, tools atau engine.

MCP: `director_status()` dan `direct_scene(idea, generator="offline", seed=0)`
menghasilkan `brief`, `treatment`, `script`, `characters`, `plan`, `build_options`, `warnings`.
Keluaran API juga berisi `usage` dan `cost_usd_estimate`; CLI menyebut kuota
langganan. Tidak membangun adegan atau memulai Blender. Semua naskah diperiksa parser;
Claude mendapat maksimal satu perbaikan. Cue shot, musik dan hening dijalankan
oleh naskah; warna kostum dan dressing khusus tetap perlu penataan manual. Durasi perkiraan, pakaian mengikuti aset
terpasang; periksa frame Eevee sebelum render akhir. Agen sebaiknya menulis naskah
sendiri; generator ini terutama untuk UI dan draf cepat.

## Metode penyutradaraan dan review film

`direct_scene` kini menghasilkan `treatment` JSON serta Markdown: tiga pilihan
struktur, logline, pembuka–perubahan–akhir, hook tiga detik, pengulangan detail
pembuka di akhir, shot puncak, alasan tiap shot, beat sheet, cue map musik dan
tabel ambience/Foley/musik. Generator offline tetap deterministik; API/CLI tetap
memerlukan persetujuan dan memakai satu kesempatan perbaikan hasil terstruktur.

Naskah menjalankan `[KAMERA: close-up Ana, push in]`, `[CAMERA: medium two-shot, orbit left]`, `[KAMERA: otomatis]`, `[MUSIK: tegang]`, `[MUSIC: stop]`, dan
`[HENING 1 detik]` / `[SILENCE 1 second]`. Kamera berlaku sampai cue berikutnya;
mood musik pindah pada bar berikutnya. Hening menurunkan musik/ambience 30 dB,
Foley tetap terdengar. Transisi film menerima `J-cut 0.4` / `L-cut 0.4`: handle
memangkas gambar sambil mempertahankan sinkron bibir/audio dan offset subtitle.

Panggil `review_scene()` atau `review_film("Nama")`: urutan penilaian suara,
ritme, kamera, performa, lalu kontinuitas/keterbacaan. Hasil berisi angka bukti,
saran tool, contact sheet berlabel, strip aksi dan laporan Markdown/JSON.
`fix=True` menjalankan tepat satu putaran perbaikan aman lalu memeriksa ulang;
cerita, cast dan suara tidak diganti. `review_video("draft.mp4")` memeriksa hasil
MP4 melalui PyAV tanpa Blender. Default workbench kecil, tanpa ASR;
`asr=True` menambah Whisper lokal dan WER. Skor adalah heuristik, pengukuran
geometri berupa proxy; exposure workbench perlu dicek lagi dengan Eevee/MP4.

`credits()` menulis aset yang benar-benar dirujuk beserta lisensi/catatan asal.
Render otomatis menulis `CREDITS.txt` di samping MP4 (`credits=False` untuk
menonaktifkan); `credits(card=True)` menambah kartu akhir tiga detik. Pengiriman:
MP4, SRT, treatment, CREDITS. Izin model suara dan aset impor tetap mengikuti
sumbernya. Lihat [panduan lengkap](AGENTS.md#directing-method).

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

Outdoor: `LOKASI: jalan` / `jalan kota` / `street`, `taman` / `park`, `kafe` / `cafe`,
`pantai` / `beach`. Header opsional `CUACA: hujan|salju|kabut|berangin|cerah` atau
`WEATHER: rain|snow|fog|wind|clear` menerapkan cuaca setelah kamera/cahaya, sebelum kain.
Set outdoor memakai gradient sky + sun; `set_lighting("noon"|"sunset"|"overcast"|"night")`
mengubah waktu hari dan mempertahankan key/fill karakter tanpa menambah lantai indoor.
Bangku, kursi kafe dan deck chair mendukung `sit_on`; tanah ditag walkable dan
`walk_path` menghindari furnitur. Backdrop ≥30 m, geometri asli prosedural low-poly.
Set memakai anchoring/scale/variant/color_theme yang sama dengan indoor.

`set_weather(kind="rain", intensity=0.5, wind=[1, 0, 0], seed=0)` membuat streak hujan,
meredupkan sky dan membasahi tanah; snow berupa flakes melayang, fog berupa volume
Eevee dengan atenuasi jarak, wind memberi angin saja. Partikel tampil di Eevee/workbench
dan video proses terpisah. Area frustum dekat (24 m) semua kamera shot diperbarui saat
render/save; budget maksimum 2.200 streak / 1.200 flakes, bukan seluruh dunia.
`secondary_motion(wind=None)` memakai wind cuaca (rebake setelah mengubah angin).
`clear` memulihkan roughness/sky dan menghapus data cuaca miliknya; mengganti outdoor
juga membersihkan cuaca. Fog tidak terlihat di workbench; belum ada collision partikel,
akumulasi salju, splash, gelombang dinamis atau simulasi air. Lihat [Weather](AGENTS.md#weather).

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

Teks menghasilkan gerak mulut tanpa suara ucapan; rekaman audio memakai Whisper lokal jika
tersedia dan ikut masuk ke video. MPFB tidak tersedia → manekin ber-rig dengan waktu
kata, subtitle dan gestur, tanpa animasi wajah. Tanpa waktu kata, subtitle dimatikan
dengan warning. Karakter yang diam tetap didukung. Aksi tubuh selesai sebelum baris
berikutnya; cahaya, gerak rambut serta kain longgar dihitung setelah animasi.
Rok/gaun mendapat gerak kain otomatis; baju ketat, rambut pendek dan karakter tanpa
bagian longgar dilewati. Pemilihan outfit belum menyelesaikan clipping baju/rambut/kursi;
periksa pose berjalan dan duduk di Eevee.
`sound=True` (default) menambahkan langkah, duduk/berdiri dan ambience setelah animasi;
gunakan `sound=False` untuk melewatinya. Hasil mencantumkan `sfx.counts` dan strip suara.
Nama karakter dibuat unik; objek lama dipertahankan, set terkelola mengikuti perilaku
`set_environment`. Tidak menyimpan atau merender otomatis. Periksa beberapa shot dengan
`render_frames(camera="scene", engine_name="eevee", size=512)`, lalu simpan dan render
draft. Format lengkap dan resep ada di [Script → scene](AGENTS.md#script--scene).

Gerak baru mencakup emosi (`sad`, `angry`, `nervous`, `happy`), reaksi (`cry`,
`laugh`, `shrug`, `clap`), aksi (`kneel`, `lie_down`, `type`, `drink`, `phone_call`),
tiga `dance_*` dengan `bpm=90`, serta `punch`/`kick`/`block` tanpa gore.
Naskah menerima `[Ana menangis]`, `[Budi minum]`, `[Ana menari]` dan padanan Inggris;
cup/phone/book dipasang lewat sistem pegangan yang sama. `body_language=True`
menambahkan bahasa tubuh emosi di bawah gestur dialog (default naskah: aktif;
`dialog`: nonaktif). Lihat [Animation](AGENTS.md#animation) untuk daftar lengkap.

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


## Film dengan beberapa adegan

`script_to_film` menyimpan tiap adegan sebagai proyek mandiri dan merangkainya menjadi
satu film. Tokoh, rambut, outfit seeded dan casting suara tetap konsisten; perubahan
pakaian berlaku mulai adegan yang memuat arahan tersebut. Naskah lama tetap memakai
`script_to_scene`; naskah dengan header ADEGAN/SCENE diarahkan ke `script_to_film`.

```text
JUDUL: Pertemuan Kembali
ANA (perempuan, 28, rambut bob, kasual)
BUDI (laki-laki, 30, rambut pendek, kasual)
ADEGAN 1: Kafe — pagi
LOKASI: cafe_terrace
SUASANA: pagi berkabut
ANA: Halo, Budi!
BUDI: Selamat pagi.
[TRANSISI: dissolve 0.5 detik]
ADEGAN 2: Taman — sore
LOKASI: taman
SUASANA: senja
CUACA: berangin
KARTU: Sore harinya...
[Ana berganti baju formal]
BUDI: Indah sekali.
ANA: Mari pulang.
[TRANSISI: dip_black 0.5 detik]
ADEGAN 3: Jalan — malam
LOKASI: city_street
SUASANA: malam
ANA: Sampai jumpa!
BUDI: Sampai besok.
```

Periksa storyboard dengan `script_to_film(script, build=False)`, lalu bangun dengan
`script_to_film(script, language="id")`. Proyek berada di
`output/projects/<nama>/scene_01.blend` dan manifest `film.json`, juga tersimpan di
setiap blend. `film_info(nama)` membaca manifest; `open_film_scene(nama, index)`
membuka adegan (index mulai 1). Simpan penyuntingan ke path proyek yang dikembalikan.
`scene_index=N` membangun ulang satu adegan bila sumber adegan lain tetap sama.

Studio Naskah menampilkan kartu lokasi, suasana, cuaca, tokoh, durasi dan transisi,
tombol **Bangun semua adegan**, serta **Bangun ulang** per adegan. Layar Adegan
mempunyai pemilih adegan; tombol Simpan proyek menyimpan ke proyek adegan aktif.
Layar Render menghitung seluruh film dan menampilkan kemajuan tiap adegan; hasil MP4
dapat diputar dan diunduh bersama SRT melalui Galeri.

Mulai dengan `render_film(nama, path="film.mp4", quality="draft")`. Setelah memeriksa
stills Eevee, panggil `film_render_options(nama, quality="final")` dan **pilih sendiri
resolusi** sebelum render pratinjau/final. `render_status(job_id)` dan
`cancel_render(job_id)` berlaku untuk seluruh film. Worker berjalan bergiliran dan
memakai kembali adegan selesai bila hash blend/pengaturan sama. Perubahan file aset
eksternal di tempat yang sama memerlukan `resume=False`.

Dissolve mengurangi durasi film sebesar overlap; dip-to-black/white mempertahankan
cut. Kartu menambah durasi (default dua detik). Audio tiap adegan ikut memudar, dan
subtitle global/SRT mengikuti offset kartu dan overlap. Perubahan outfit ditempatkan
sebelum dialog/aksi adegan; tidak ada animasi berganti baju. Maksimal empat tokoh
global dan 64 adegan, fps seragam. Semua batas motion/cuaca/kamera/TTS tetap berlaku.
Komposisi memakai Blender VSE dan encoder bawaan, tanpa ffmpeg sistem.

Uji unit: `.venv/bin/python tests/test_film.py` → `FILM UNIT OK`. Uji nyata terisolasi:
`CHAR3D_PORT=9996 CHAR3D_WORKSPACE="$PWD/output" .venv/bin/python tests/e2e_smoke.py --film-only`.

## Render di mesin remote / GPU sewaan

Video dan film bisa memakai `target="devodo"` atau nama target sendiri. Default
`target="local"` tetap memakai laptop. Klip film dirender di remote, lalu disusun
di laptop. Tidak ada perubahan Web UI; gunakan tool MCP.

1. Siapkan mesin Linux atau Windows dengan SSH, Python 3.9+, dan Blender dari seri
   major.minor yang sama. Default `blender_version="minor"` menerima 5.2.3 ↔ 5.2.4
   dengan peringatan; `"exact"` mewajibkan patch sama. Seri berbeda ditolak.
   Linux memakai rsync; Windows memakai SCP/SFTP tanpa rsync. GPU perlu driver
   grafis serta CUDA/OptiX/HIP sesuai perangkat.
   `scripts/install_remote_worker.sh --help` menjelaskan verifikasi/instalasi arsip resmi.
   Worker tidak perlu MPFB, repo char3d, atau paket pip tambahan.
2. Buat `~/.config/char3d/targets.json`, misalnya:

   ```json
   {"devodo":{"kind":"ssh","host":"devodo","jump_host":"reyhan",
     "remote_dir":"/opt/char3d/remote","blender":"/opt/char3d/blender-5.2.4-linux-x64/blender",
     "device":"cpu","max_parallel":1,"max_hours":4}}
   ```

   Uji `ssh -F ~/.ssh/config -o BatchMode=yes devodo` sendiri. SSH menggunakan
   kunci/agent dan known_hosts milik pemilik; char3d tidak menerima kata sandi.
3. Untuk menyewa GPU, **pemilik membuat dan mendanai akun RunPod/Vast.ai sendiri**.
   Simpan `RUNPOD_API_KEY=...` atau `VAST_API_KEY=...` di `~/.config/char3d/env`,
   lalu `chmod 600 ~/.config/char3d/env`. Jangan simpan kunci API di repo/targets.
   Tambahkan target `kind="runpod"` atau `"vast"` dengan `gpu_type`, `image` milik
   Anda yang sudah berisi Blender, `public_key` (path kunci SSH **publik**),
   `blender`, `device`, `max_hourly_usd`, `max_budget_usd` dan `max_hours`.
   Contoh lengkap ada di [AGENTS.md](AGENTS.md#remote-rendering).
4. Panggil `remote_targets()`, lalu `render_options(quality="final", target="devodo")`.
   Pilih resolusi dari waktu/biayanya. Untuk mengukur mesin SSH, gunakan
   `calibrate=True, consent_upload=True`; film memakai `film_render_options`.
5. Mulai `render_video(..., target="NAMA", consent_upload=True)` atau `render_film`.
   Consent berarti scene, tekstur/gambar, font, suara/WAV dan overlay diunggah.
   Pada target berbayar, panggilan pertama hanya mengembalikan **quote**. Periksa
   GPU, harga per jam, estimasi total dan batas biaya/waktu; ulangi argumen yang sama
   dengan `quote_id="...", confirm_cost=True` setelah menyetujuinya. Quote berlaku
   sepuluh menit, sekali pakai; perubahan pengaturan memerlukan quote baru.
6. Pantau `render_status(job_id)`. `cancel_render(job_id)` atau `stop_target("NAMA")`
   membatalkan pekerjaan dan mengakhiri instance char3d. Hasil MP4 diverifikasi dengan
   PyAV; SRT/CREDITS tetap berdampingan dengan video. Uji SSH tanpa biaya sewa:
   `.venv/bin/python tests/remote_ssh_smoke.py devodo`.

Instance berbayar dihapus setelah selesai/gagal/batal atau batas terlampaui. Supervisor
tetap berjalan jika MCP ditutup dan mencoba ulang cleanup bila API gagal. **Laptop
pengendali harus tetap hidup/online**; batas invoice saat laptop mati atau API provider
putus tidak dapat dijamin. Pasang batas saldo/alert di akun provider juga. Estimasi
bukan tagihan; pajak/pembulatan/penyimpanan bisa berbeda. Cache blob privat di remote
tetap tersimpan dengan batas ukuran; scene sementara dibersihkan setelah pengiriman.
Cache simulasi eksternal, linked library, volume dan UDIM/sequence perlu dikonversi
sebelum dikirim. Tidak ada dukungan Kaggle/Colab atau akal-akalan free tier.

### PC Windows milik sendiri

Aktifkan **OpenSSH Server** dan layanan `sshd` di PC. Untuk akun anggota Administrators,
public key laptop yang **disetujui pemilik** masuk ke
`C:\ProgramData\ssh\administrators_authorized_keys`. Jangan kirim private key.
Di PowerShell Administrator, setelah menambahkan key tanpa BOM:

```powershell
$keyFile = "$env:ProgramData\ssh\administrators_authorized_keys"
icacls.exe $keyFile /inheritance:r
icacls.exe $keyFile /grant:r '*S-1-5-32-544:F' '*S-1-5-18:F'
New-Item -ItemType Directory -Force 'D:\char3d\remote'
```

Periksa ACL lama agar tidak ada grant pengguna lain; batasi folder worker juga.
Pertahankan akses melalui VPN/jump host. Contoh target di `targets.json`:

```json
{"pc":{"kind":"ssh","os":"windows","shell":"cmd",
  "host":"10.8.0.8","jump_host":"reyhan","user":"reyhan febrizio r",
  "remote_dir":"D:\\char3d\\remote",
  "python":"C:\\Users\\Reyhan Febrizio R\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
  "blender":"C:\\Users\\Reyhan Febrizio R\\AppData\\Local\\Programs\\Blender\\blender-5.2.3-windows-x64\\blender.exe",
  "blender_version":"minor","device":"cuda","vram_gb":4,"max_parallel":1}}
```

Path/nama login berspasi didukung. Shell cmd.exe maupun PowerShell 5.1 menggunakan
command PowerShell terenkode UTF-16LE; tidak perlu mengubah DefaultShell. `os` boleh
dihilangkan untuk deteksi otomatis. Verifikasi fingerprint host di kedua mesin
sebelum mengisi known_hosts; contoh lengkap, fingerprint PC yang diberikan pemilik,
instalasi OpenSSH dan penambahan key ada di [panduan Windows](AGENTS.md#target-ssh-windows-penyiapan-oleh-pemilik-pc).

Eevee memakai GPU; Cycles memakai `cuda` atau `optix`. Nama GPU/VRAM dilaporkan,
dengan peringatan dan saran menurunkan resolusi bila estimasi scene melebihi 4 GB.
Estimasi memori bukan pengukuran pasti. Ukur kecepatan dengan
`render_options(target="pc", quality="preview", calibrate=True, consent_upload=True)`.
Blender sudah membawa encoder MP4, jadi FFmpeg eksternal tidak wajib.
Setelah key diotorisasi, jalankan `.venv/bin/python tests/remote_ssh_smoke.py pc`.
Render biasa memakai `render_video(..., target="pc", consent_upload=True)`; progress,
cancel, reattach dan film sama seperti target Linux.

## Web UI — studio lokal

Gunakan char3d langsung dari browser, tanpa build frontend atau Node saat runtime:

```bash
./run_webui.sh
# http://127.0.0.1:8765
./run_webui.sh --port 8781
```

`CHAR3D_WEBUI_PORT` mengubah port UI; `CHAR3D_PORT` dan `CHAR3D_WORKSPACE`
memilih engine/workspace yang sama dengan MCP. Launcher membaca env opsional
`~/.config/char3d/env` (atau `CHAR3D_ENV_FILE`) dan memakai `.venv`.
Starlette dan uvicorn sudah tersedia melalui dependensi MCP.

Enam layar: **Naskah ke adegan** (rencana sebelum build), **Adegan** (objek, shot,
frame, simpan/buka proyek), **Karakter** (katalog MPFB atau manekin), **Render**
(draft, pilihan resolusi dan estimasi, progres/ETA/batal), **Galeri output**
(gambar, MP4, GLB interaktif, unduhan), serta **Semua tool** (formulir otomatis
dari skema MCP dan unggahan audio/gambar/model). Label berbahasa Indonesia,
tema gelap/terang, dan tata letak mobile tersedia. Hasil pekerjaan muncul otomatis;
Anda dapat berpindah layar selama engine bekerja. Teks naskah menghasilkan gerak
mulut; suara ucapan membutuhkan rekaman atau generasi suara yang dikonfirmasi.

UI hanya mendengarkan `127.0.0.1`. Host/origin asing ditolak, file dibatasi ke
workspace setelah resolusi symlink, dan unggahan maksimal 100 MB masuk ke
`imports/`. Tool `run_blender_python` tidak tersedia. Generasi AI meminta konfirmasi
sebelum mengirim prompt/gambar/audio ke fal.ai atau Hugging Face. Tidak ada CDN,
telemetri, atau permintaan font eksternal. Jangan menaruh UI ini di reverse proxy
publik; UI dirancang untuk pemakaian lokal oleh pemilik komputer.

Antrean menyimpan 100 hasil terakhir di memori server; restart UI menghapus riwayat,
sementara file hasil dan proyek tetap ada. Simpan proyek `.blend` sebelum menutup
studio. Viewer GLB lokal mendukung aset standar; kompresi Draco/Meshopt/KTX2 belum
didukung. File glTF terpisah memerlukan resource pendamping yang dapat diakses;
gunakan GLB untuk impor/ekspor satu file.

Verifikasi pada port engine terpisah (jangan gunakan 9876):

```bash
CHAR3D_PORT=9981 CHAR3D_WORKSPACE="$PWD/output" .venv/bin/python tests/webui_smoke.py
.venv/bin/python tests/test_webui.py
# Dengan UI berjalan di 8781:
.venv/bin/python tests/webui_e2e.py
```

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

## Karakter anime, VRM, dan wajah dari foto

Model OpenSeeFace lokal memakai `~/.local/share/char3d/face` (override
`CHAR3D_FACE_MODEL_DIR`, fallback workspace `models/face`). Checksum ada di
`scripts/toon_assets.tsv`; tool tidak mengunduh model. Hasil `face_from_photo`
memuat `traits`, skor geometri `likeness_score`, dan resep JSON `look` yang bisa
dipakai ulang lewat `create_realistic_human(..., look=resep)` atau karakter dict
script. Skor bukan verifikasi identitas; satu foto tidak menentukan modifier 3D
secara unik. Gaya rambut/kacamata/janggut memakai pilihan katalog yang diberikan
atau dipertahankan, bukan ditebak oleh model landmark. Tekstur resep tetap di
workspace `imports/face_looks/`.

`create_realistic_human(..., style="anime"|"cartoon"|"chibi")` membuat proporsi
MPFB 6,75 / 4,75 / 2,8 kepala, tetap dengan rig, baju/rambut, blink, viseme dan ekspor
GLB. Default `realistic` tetap sama. Deskriptor `anime`, `kartun`, `chibi` berlaku
per karakter; `GAYA: anime` juga menjadi default tubuh, kecuali karakter bertanda
`realistis`. Hasil menyarankan `render_style("anime")` tanpa memaksanya.
Mata dan iris diperbesar, bentuk wajah/hidung disederhanakan, serta anggota tubuh
cartoon/chibi diperpendek; tinggi chibi memakai 82% hasil MPFB. Garis kelopak
mengikuti morph native; alis sederhana dan alpha rambut yang tegas mengurangi grain. `tests/toon_polish.py` membuat
perbandingan tampilan serta pengukuran kelopak dan bibir.

Impor `.vrm` memerlukan VRM Add-on for Blender (`scripts/install_vrm.sh`). Model
VRM memiliki lisensi sendiri yang wajib dipatuhi pengguna. `face_from_photo`
memerlukan `consent=True` untuk wajah sendiri/orang yang memberi izin, foto
frontal lokal di `imports/`, dan dua model ONNX OpenSeeFace BSD-2-Clause
(`scripts/install_face_landmarks.sh`). Foto tidak diunggah. Tekstur foto default
aktif untuk realistis, nonaktif untuk gaya kartun. Installer meminta konfirmasi,
memeriksa SHA-256/ukuran yang sudah dicatat di TSV, dan menyediakan `--dry-run`. Tidak ada unduhan otomatis atau perubahan virtualenv.
Lihat panduan [AGENTS.md](AGENTS.md) untuk privasi, instalasi, dan batas fitting.

## Manusia realistis (MPFB)

Material `enhanced` kini menjadi default: tekstur kulit tetap dipakai, dengan
scatter hangat yang mengikuti warna kulit, roughness lokal, detail pori halus,
normalisasi kulit terang agar tidak putih kapur, iris cokelat alami dengan
catchlight khusus mata, variasi rambut dan sheen kain. Gunakan `materials="mpfb"`
saat membuat karakter untuk shader bawaan, atau
`upgrade_materials("Maya_rig", quality="mpfb")` untuk memulihkannya persis.
`skin_detail` / `hair_detail` bernilai 0..2; `skin_tone=None` mengukur tekstur,
atau pilih `light` / `medium` / `dark` untuk menyesuaikan scatter tanpa mengganti
warna tekstur. Material tersimpan dalam `.blend` dan snapshot video. glTF tetap
membawa tekstur warna/alpha/normal dan roughness dasar; hasil ekspor melaporkan
detail prosedural yang hilang. Estimasi render menghitung faktor material
tersendiri (maksimal 1.15×; draft 1×).
Koreksi potret tidak ditumpuk penuh dengan key sinematik yang sudah diredupkan;
preset lampu dan exposure global tetap. Bukti pengukuran dan sheet revisi ada di
`output/material_review_v2/` dan `output/skin_result.md`.

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

## Musik latar otomatis

`auto_music(..., backend="auto")` memakai GeneralUser GS jika bank dan renderer
tersedia, lalu otomatis memilih synth numpy bila tidak ada. `backend="soundfont"`
mewajibkan bank; `backend="synth"` memakai versi lama. Instal eksplisit dengan
`scripts/install_soundfont.sh` (konfirmasi, atau `--yes`): tinysoundfont 0.3.7 tanpa
PyAudio, SF2 v2.0.3 32.319.396 byte dan lisensi dengan checksum di
`scripts/soundfonts.tsv`. `CHAR3D_SOUNDFONT` mengganti path; lisensi bank mengizinkan
pembuatan musik pribadi/komersial. Tidak ada unduhan saat render. Blender memakai
subproses Python kompatibel (`CHAR3D_MUSIC_PYTHON`, default `.venv/bin/python`).

Aransemen GM mencakup piano/e-piano, gitar nylon/steel, strings, woodwinds, brass,
choir/pad, harp, mallet, bass dan drum kanal 10. Inversi dengan voice leading, bass
approach, counter-melody di B, fill sebelum pergantian bagian/cut, velocity serta
CC7/CC11 membentuk intro → A → B → outro. Nusantara menggunakan figur orisinal
bersahutan dengan vibraphone, marimba, glock/celesta, tubular bells, steel drums,
kalimba/koto, taiko/timpani dan orchestral hit. Tangga nada pelog/slendro hanya
pendekatan subset equal temperament; bukan rekonstruksi laras, repertoar atau ansambel
tradisional. Metrik spektrum soundfont dan synth dilaporkan terpisah.

`auto_music(mood="auto", seed=17)` membuat musik orisinal secara offline dengan
soundfont lokal atau numpy, lalu menurunkannya 12 dB saat dialog. Tidak memakai layanan AI.
Pilih ceria, hangat, sedih/haru, romantis, tegang, misterius, epik, tenang, lucu,
nostalgia, dreamy, atau nusantara (pentatonik temperamen sama, bell/metallophone
dan gong; bukan tiruan karya atau tuning daerah tertentu).
Mode auto membaca emosi dialog, suasana sinematik, cuaca dan lokasi. Aksen kecil
mengikuti cut/judul, dinamika mengikuti emosi, dan akhir mendapat kadens.

Naskah menerima `MUSIK: hangat` / `MUSIC: sad`, atau `MUSIK: tanpa`.
`script_to_scene` dan `script_to_film` memakai `music="auto"` secara default;
`music=None` menonaktifkan musik, terpisah dari `sound=False` untuk Foley.
`build=False` melaporkan mood/tempo/key tanpa membuat WAV.
Film memakai skor berkelanjutan melewati kartu dan cut: mood yang sama meneruskan
komposisi; mood berbeda memakai crossfade. Preview tiap adegan tetap bersuara.

Parameter opsional: `duration` (detik, default rentang adegan, maksimum 600),
`tempo` (40..180 BPM), `key="D minor"`, `intensity=0.6`, `volume=0.35`,
`sections=[{"frame":49,"intensity":0.8}]`, `fade_in=1`, `fade_out=2`.
WAV stereo 48 kHz/16-bit disimpan berdasarkan hash konten di
`output/imports/audio/music/generated/`, sekitar −16 LUFS dan puncak ≤−1 dBFS
sebelum volume/fade/ducking. Pengukur K-weighted/true-peak berupa pendekatan.
Panggilan ulang mengganti musik milik generator saja; `clear=True` menghapusnya.
Musik manual tetap ada. Simpan ulang setelah perubahan timeline/emosi/kamera.
Ini pengiring berbasis aturan dengan sintesis ringan; hasil perlu didengarkan.
Demo semua mood: `tests/test_music.py --demos` → `output/music_demos/metrics.json`.
`--demos --soundfont` → `output/music_demos_sf/` (12 mood × 30 detik, metrik dan waktu render).
Setiap mood/seed memilih dari semua 12 key, dengan register, ritme bass/drum dan
orkestrasi berbeda. PolyBLEP 2×, FM 4× dan resonator pluck modal menjaga harmonik
serta air alami; guard antialias tidak memotong semua treble. Metrik spektrum memakai
20 detik pertama WAV mono-sum dengan Hann FFT: <120 Hz, >2/4/8/16 kHz dan centroid.

## Suara dan lip sync dari audio

`auto_sfx(characters=["Maya_rig"], seed=7)` dijalankan setelah `walk_path`, `animate`,
mocap dan aksi duduk/berdiri. Default `kinds=["footsteps", "sit", "ambience"]`; sit
mencakup berdiri, dan `"cloth"` menambah rustle gerak. `surface="auto"` membaca tanah
di bawah kaki (tag `char3d_surface`/`c3d_surface`, nama material/objek, lalu preset set).
Pilihan eksplisit: wood, concrete/tile, carpet, grass, gravel, sand. Langkah memakai
heel transient, resonansi badan, toe/scuff dan variasi per langkah; sofa lebih lembut.
Ambience set mencakup office, studio, classroom, living_room serta city_street, park,
cafe_terrace dan beach jika preset tersebut tersedia. Bed berulang mulus pada sekitar
-30 dBFS RMS sebelum fade dan pengali `volume`.

WAV asli 48 kHz mono 16-bit disimpan di `output/imports/sfx/generated/` dengan hash
konten; seed yang sama memakai file yang sama. Hasil memberi kontak `touchdowns`,
`counts`, frame/path/hash/surface tiap strip. Panggilan ulang mengganti sfx miliknya
dalam `frame_start`/`frame_end`; `clear=True` hanya menghapus sfx otomatis (semua kind
jika `kinds` tidak diisi). Suara voice/music/sfx manual tetap ada, dan sfx tidak memicu
`duck_music`. Tidak mengubah animasi atau panjang adegan. Kontak awal kaki yang sudah
menapak tidak berbunyi. Deteksi mocap/hip-drop bersifat heuristik; jongkok dapat terbaca
sebagai duduk. Belum ada simulasi akustik/sepatu, occlusion audio atau tanah bergerak.
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

### Mode bebas: bespoke worlds

Describe a place with `direct_world` or author a safe JSON recipe from
`world_schema()`. Compose nature, original creatures, floating islands, lanterns
and generic architecture with saved motion, cinematic looks and walkable staging.
Validate without Blender using `compose_world(..., build=False)`, build/inspect,
then `save_world("name")` and use `DUNIA: name` in a script. Studio's **Dunia** page
provides generation, JSON editing, inline validation and Eevee preview. No
AI-authored Python runs; schemas and hard budgets bound every build.
Heroes include a round coiling serpent, articulated whale fins/tail, stratified
floating gardens, seamless cloud billows and layered mountain heightfields.
Saved medium/close camera hints support depth of field and dressed backgrounds.
See [world recipe guide](engine/world/README.md) for catalog, consent, limits and tests.
