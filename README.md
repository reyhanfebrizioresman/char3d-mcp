# char3d — Engine Karakter 3D untuk AI (MCP + Blender)

Engine ini menjalankan Blender di latar belakang dan membuka fungsinya sebagai
"alat" MCP. Claude, Codex, atau klien MCP lain bisa membuat, memeriksa, merender,
dan meng-export aset 3D.

```
Claude / Codex ──MCP──► mcp_server/ ──TCP lokal──► Blender (engine/) ──► .glb .blend .png
```

## Status
✅ Fase 1 (fondasi) · ✅ Fase 2 (karakter + rigging) · ✅ Fase 3 (animasi)

| Alat | Fungsi |
|---|---|
| `engine_status` | Menyalakan Blender bila belum jalan, lalu menampilkan versi dan folder kerja |
| `scene_info` | Daftar objek, ukuran, statistik mesh/armature, animasi |
| `new_scene` | Adegan kosong |
| `add_primitive`, `transform_object`, `delete_objects` | Objek dasar |
| `import_model` | .glb .gltf .fbx .obj .stl .ply .usd .bvh |
| `export_asset` | .glb (disarankan, ikut animasi) .gltf .fbx .obj .usd .bvh; untuk Rigify hanya tulang deform yang ikut |
| `save_project`, `open_project` | File .blend |
| `render_preview`, `render_views` | Render pratinjau, gambarnya dikirim balik ke AI |
| `create_human` | Karakter manekin prosedural: realistic, heroic, stylized, cartoon, chibi |
| `estimate_landmarks` | Posisi sendi yang akan dipakai rig (tersimpan atau hasil tebakan dari bentuk mesh) |
| `auto_rig_humanoid` | Rig `basic` (21 tulang) atau `rigify` (kontrol FK/IK), plus skinning otomatis |
| `validate_rig`, `list_bones`, `set_pose` | Cek kualitas rig, daftar tulang, pose dan keyframe |
| `list_animations`, `apply_pose` | 12 pose siap pakai (wave, cheer, sit, crouch, fight stance, dll.) |
| `animate` | Klip prosedural: idle, walk, run, wave, cheer, jump, nod, head_shake (bisa disambung) |
| `import_mocap`, `retarget_animation` | Mocap .bvh/.fbx/.glb (CMU, Mixamo, dll.) ke rig apa pun, diselaraskan otomatis |
| `clear_animation`, `render_frames` | Hapus animasi; render beberapa frame untuk mengecek gerakan |
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

## Pengaturan (variabel lingkungan)
| Variabel | Default | Arti |
|---|---|---|
| `CHAR3D_BLENDER` | `~/.local/opt/blender/blender` | Lokasi Blender |
| `CHAR3D_PORT` | `9876` | Port lokal engine (dipakai bersama Claude dan Codex) |
| `CHAR3D_WORKSPACE` | `./output` | Folder hasil (renders, exports, projects, imports) |
| `CHAR3D_ALLOW_PYTHON` | (mati) | `1` = AI boleh menjalankan Python bebas di Blender |

## Catatan
- Komputer tanpa GPU: render Workbench ±1 detik, Eevee ±10 detik per gambar
  (512 px). Cycles lambat, jadi gunakan hanya untuk hasil final.
- Konvensi: satuan meter, sumbu Z ke atas, karakter menghadap -Y.
