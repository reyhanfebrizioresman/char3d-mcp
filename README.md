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
| `export_asset` | .glb (disarankan, ikut animasi) .gltf .fbx .obj .usd .bvh; untuk Rigify hanya tulang deform yang ikut |
| `save_project`, `open_project` | File .blend |
| `render_preview`, `render_views` | Render pratinjau (kamera otomatis atau kamera shot), gambarnya dikirim balik ke AI |
| `create_human` | Karakter manekin prosedural: realistic, heroic, stylized, cartoon, chibi |
| `create_realistic_human`, `mpfb_assets` | Manusia realistis (MakeHuman/MPFB): kulit, mata, alis, rambut, baju; sudah di-rig dengan bobot buatan tangan |
| `estimate_landmarks` | Posisi sendi yang akan dipakai rig (tersimpan atau hasil tebakan dari bentuk mesh) |
| `auto_rig_humanoid` | Rig `basic` (21 tulang) atau `rigify` (kontrol FK/IK), plus skinning otomatis |
| `validate_rig`, `list_bones`, `set_pose` | Cek kualitas rig, daftar tulang, pose dan keyframe |
| `list_animations`, `apply_pose` | 12 pose siap pakai (wave, cheer, sit, crouch, fight stance, dll.) |
| `animate` | Klip prosedural: idle, walk, run, wave, cheer, jump, nod, head_shake (bisa disambung) |
| `import_mocap`, `retarget_animation` | Mocap .bvh/.fbx/.glb (CMU, Mixamo, dll.) ke rig apa pun, diselaraskan otomatis |
| `clear_animation`, `render_frames` | Hapus animasi; render beberapa frame untuk mengecek gerakan |
| `camera_shot`, `list_shots`, `delete_shot` | 23 gerak kamera (dolly, orbit, crane, crash zoom, dolly zoom, tracking, drone reveal, dll.), 8 ukuran shot, multi-shot otomatis |
| `set_lighting`, `set_material` | 10 preset cahaya (studio, sunset, neon, horror, dll.) + lantai; material cepat |
| `render_video`, `render_status`, `cancel_render` | Render MP4 (H.264) di proses latar belakang: draft, preview, final, cycles |
| `set_timeline` | Rentang frame dan fps |
| `prepare_model` | Merapikan model dari luar: gabung mesh, kurangi poligon, skala tinggi, berdiri di lantai |
| `ai_text_to_3d`, `ai_image_to_3d` | Teks/gambar → model 3D → otomatis diimpor, dirapikan, dan di-rig (gratis lewat Hugging Face, atau berbayar lewat fal.ai) |
| `ai_image_to_video`, `ai_text_to_video` | Gambar/render → video AI ala Higgsfield (gratis lewat Hugging Face, atau berbayar lewat fal.ai) |
| `ai_status`, `ai_job_status`, `ai_cancel_job` | Status konfigurasi dan job AI |
| `run_blender_python` | Hanya aktif jika `CHAR3D_ALLOW_PYTHON=1` |

Konvensi pose dan resep alur kerja untuk AI ada di [AGENTS.md](AGENTS.md).

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
Isinya: 23 kulit, 10 rambut, 12 alis, 4 bulu mata, 2 mata, dan 20 baju/sepatu/topi.
Lisensi: kode MPFB GPL-3.0 (tidak disalin ke repo ini, hanya dipanggil saat runtime);
aset MakeHuman CC0, jadi karakter hasilnya bebas dipakai, termasuk untuk komersial.

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
