import { needsSpeechConsent, authorizeSpeech } from "./voices.js";
import { screenRoot } from "./ui.js";
import { run, state, scene, upload } from "./api.js";
import {
  icon,
  esc,
  $,
  $$,
  head,
  input,
  select,
  field,
  button,
  empty,
  action,
  json,
  filmstrip,
  confirm,
  seconds,
  toast,
  check,
} from "./ui.js";
import { schemaForm, readSchema, validateJSON } from "./schema.js";
const groups = {
  Adegan: [
    "engine_status",
    "scene_info",
    "new_scene",
    "add_primitive",
    "transform_object",
    "delete_objects",
    "engine_shutdown",
  ],
  File: [
    "import_model",
    "export_asset",
    "save_project",
    "open_project",
    "prepare_model",
  ],
  "Pratinjau & gaya": [
    "render_style",
    "render_preview",
    "render_views",
    "render_frames",
  ],
  "Karakter & rig": [
    "mpfb_assets",
    "create_realistic_human",
    "create_human",
    "estimate_landmarks",
    "auto_rig_humanoid",
    "validate_rig",
    "list_bones",
    "set_pose",
    "set_hand_pose",
  ],
  Wajah: [
    "list_expressions",
    "set_expression",
    "auto_expression",
    "lip_sync",
    "auto_blink",
  ],
  "Audio & suara": [
    "add_audio",
    "auto_sfx",
    "duck_music",
    "list_audio",
    "remove_audio",
    "transcribe_audio",
    "lip_sync_audio",
    "list_voices",
    "text_to_speech",
    "talk_motion",
    "talk_gestures",
  ],
  "Dialog & naskah": ["dialog", "stage_dialog", "script_to_scene"],
  Animasi: [
    "list_animations",
    "apply_pose",
    "animate",
    "walk_path",
    "turn_to",
    "import_mocap",
    "retarget_animation",
    "lock_feet",
    "secondary_motion",
    "clear_animation",
  ],
  Film: [
    "list_camera_moves",
    "camera_shot",
    "list_shots",
    "delete_shot",
    "set_timeline",
    "list_lighting_presets",
    "set_lighting",
    "set_material",
    "add_subtitles",
    "remove_subtitles",
    "add_transition",
    "add_title",
    "list_graphics",
    "remove_graphics",
    "render_options",
    "render_video",
    "render_status",
    "cancel_render",
  ],
  "Set, properti & cuaca": [
    "set_environment",
    "add_prop",
    "clear_environment",
    "sit_on",
    "stand_up",
    "hold_prop",
    "release_prop",
    "interact",
    "set_weather",
    "add_terrain",
    "clear_terrain",
  ],
  "AI eksternal": [
    "ai_status",
    "ai_text_to_3d",
    "ai_image_to_3d",
    "ai_image_to_video",
    "ai_text_to_video",
    "ai_job_status",
    "ai_cancel_job",
    "ai_text_to_speech",
  ],
};
const generators = new Set([
  "ai_text_to_3d",
  "ai_image_to_3d",
  "ai_image_to_video",
  "ai_text_to_video",
  "ai_text_to_speech",
]);
export function mount(root) {
  root = screenRoot(root);
  let current =
    state.tools.find((t) => t.name === localStorage.getItem("char3d-tool")) ||
    state.tools.find((t) => t.name === "scene_info");
  root.innerHTML =
    head(
      "KENDALI LEBIH JAUH",
      "Seluruh studio. Semua kemungkinan.",
      "Akses langsung lapisan MCP, dengan formulir dari skema tool yang sama.",
      `<span class="chip">${state.tools.length} tool tersedia</span>`,
    ) +
    `<div class="tools-layout"><div><section class="panel"><div style="padding:14px;border-bottom:1px solid var(--line)"><label class="search">${icon("search")}${input("tool-search", "", "search", 'placeholder="Cari tool…" aria-label="Cari tool"')}</label></div><div id="tool-list" class="tool-list"></div></section><section class="panel upload-bar"><h3>${icon("upload")} Impor file lokal</h3><p class="help">Audio, gambar, dan model · maks. 100 MB. Disimpan di imports/.</p>${field(
      "Jenis file",
      select("upload-kind", [
        ["audio", "Audio"],
        ["images", "Gambar"],
        ["models", "Model 3D"],
      ]),
    )}<label class="field" style="margin-top:12px"><span>Pilih file</span><input type="file" id="upload-file" accept=".wav,.mp3,.flac,.ogg,.m4a"></label><div id="upload-result" class="upload-result" style="margin-top:10px"></div></section></div><section class="panel"><div id="tool-content"></div></section></div>`;
  const list = $("#tool-list", root),
    target = $("#tool-content", root);
  const drawList = () => {
    const query = $("#tool-search", root).value.toLowerCase();
    let html = "";
    const used = new Set();
    for (const [category, names] of Object.entries(groups)) {
      const tools = state.tools.filter(
        (t) =>
          names.includes(t.name) &&
          (t.name + " " + t.description).toLowerCase().includes(query),
      );
      if (!tools.length) continue;
      html +=
        `<div class="tool-category">${category}</div>` +
        tools
          .map((t) => {
            used.add(t.name);
            return `<button class="tool-option ${current?.name === t.name ? "active" : ""}" data-tool="${esc(t.name)}">${esc(t.name)}<span>${generators.has(t.name) ? "↗" : "›"}</span></button>`;
          })
          .join("");
    }
    for (const t of state.tools.filter(
      (t) =>
        !Object.values(groups).flat().includes(t.name) &&
        (t.name + " " + t.description).toLowerCase().includes(query),
    ))
      html += `<button class="tool-option" data-tool="${esc(t.name)}">${esc(t.name)}</button>`;
    list.innerHTML =
      html || empty("search", "Tidak ditemukan", "Coba kata kunci lain.");
    $$("[data-tool]", list).forEach(
      (btn) =>
        (btn.onclick = () => {
          current = state.tools.find((t) => t.name === btn.dataset.tool);
          localStorage.setItem("char3d-tool", current.name);
          drawList();
          drawForm();
        }),
    );
  };
  const drawForm = () => {
    if (!current) {
      target.innerHTML = empty(
        "tools",
        "Tool belum tersedia",
        "Segarkan halaman untuk mencoba lagi.",
      );
      return;
    }
    const tool = current;
    target.innerHTML = `<div class="panel-head"><h2 class="mono">${esc(tool.name)}</h2><span class="chip ${generators.has(tool.name) ? "warm" : ""}">${generators.has(tool.name) ? "EKSTERNAL" : "MCP TOOL"}</span></div><div class="panel-body"><p class="tool-description">${esc(tool.description)}</p>${generators.has(tool.name) ? '<p class="tool-warning">↗ Prompt, gambar, atau audio dikirim ke pihak ketiga. Konfirmasi akan diminta sebelum menjalankan.</p>' : ""}<form id="tool-form">${schemaForm(tool.inputSchema)}<div class="divider"></div><button type="submit" class="button primary">${icon("play")} Jalankan tool</button><span id="tool-elapsed" class="help" style="margin-left:10px"></span></form><div id="tool-result" style="margin-top:22px"></div></div>`;
    validateJSON(target);
    $("#tool-form", target).onsubmit = (e) => {
      e.preventDefault();
      const out = $("#tool-result", target);
      action(
        $("button[type=submit]", e.target),
        async () => {
          const args = readSchema(tool.inputSchema, target);
          if (
            tool.name === "render_video" &&
            args.quality !== "draft" &&
            !args.resolution &&
            !(args.width && args.height)
          )
            throw new Error(
              "Pilih resolusi terlebih dahulu melalui render_options atau layar Render.",
            );
          let confirmed = false;
          if (needsSpeechConsent(tool.name, args)) {
            confirmed = await authorizeSpeech(tool.name, args);
            if (!confirmed) return;
          }
          if (generators.has(tool.name)) {
            confirmed = await confirm(
              "Kirim ke layanan AI eksternal?",
              `Tool <code>${esc(tool.name)}</code> mengirim prompt, gambar, dan/atau audio yang dipilih ke <strong>fal.ai atau Hugging Face</strong>. Penyedia dapat menyimpan data; fal.ai berbayar. Lanjutkan hanya untuk data yang Anda izinkan dibagikan.`,
              "Setuju & kirim",
            );
            if (!confirmed) return;
          }
          if (
            [
              "new_scene",
              "open_project",
              "engine_shutdown",
              "delete_objects",
              "clear_environment",
              "clear_terrain",
            ].includes(tool.name) &&
            !(await confirm(
              "Lanjutkan perubahan adegan?",
              `<code>${esc(tool.name)}</code> dapat menghapus atau mengganti pekerjaan saat ini. Simpan proyek jika diperlukan.`,
              "Lanjutkan",
              true,
            ))
          )
            return;
          await scene(true);
          const result = await run(tool.name, args, {
            confirmExternal: confirmed,
            onUpdate: (job) => {
              const el = $("#tool-elapsed", target);
              if (el)
                el.textContent =
                  (job.status === "queued"
                    ? `Antrean #${job.queue_position} · `
                    : "") + seconds(job.elapsed_s);
            },
          });
          state.scene = null;
          out.innerHTML =
            filmstrip(result.images) +
            result.files
              .filter((f) => f.endsWith(".mp4"))
              .map(
                (f) =>
                  `<video style="width:100%;margin-top:12px" controls src="${esc(f)}"></video>`,
              )
              .join("") +
            json(result.data);
          const details = $("details", out);
          if (details) details.open = true;
          toast(`${tool.name} selesai.`);
        },
        out,
      );
    };
  };
  $("#tool-search", root).oninput = drawList;
  $("#upload-kind", root).onchange = (e) => {
    $("#upload-file", root).accept = {
      audio: ".wav,.mp3,.flac,.ogg,.m4a",
      images: ".png,.jpg,.jpeg,.webp",
      models: ".glb,.gltf,.fbx,.obj,.stl,.ply,.usd,.usdz,.bvh,.bin",
    }[e.target.value];
  };
  $("#upload-file", root).onchange = (e) =>
    action(
      null,
      async () => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 100 * 1024 * 1024)
          throw new Error("Batas unggahan 100 MB");
        const out = $("#upload-result", root);
        out.textContent = "Mengunggah…";
        const uploaded = await upload(file, $("#upload-kind", root).value);
        out.innerHTML = `Siap digunakan sebagai path:<br><code>${esc(uploaded.path)}</code><br><span class="help">Salin path ini ke parameter audio / image / path.</span>`;
      },
      $("#upload-result", root),
    );
  drawList();
  drawForm();
}
