import { switcher } from "./film.js";
import { otsForm, collisionPanel, mountSceneTools } from "./scene-tools.js";
import { lookPicker, mountLookPicker } from "./looks.js";
import { walkPressPanel, mountWalkPress } from "./walk-press.js";
import { screenRoot } from "./ui.js";
import { run, state, scene, request } from "./api.js";
import {
  icon,
  esc,
  $,
  $$,
  head,
  field,
  select,
  input,
  button,
  empty,
  action,
  filmstrip,
  json,
  confirm,
  modal,
  closeModal,
  toast,
} from "./ui.js";
export function mount(root) {
  root = screenRoot(root);
  const initialFrame = state.reviewFrame ?? 1;
  state.reviewFrame = null;
  root.innerHTML =
    head(
      "ATUR SETIAP SUDUT",
      "Di balik layar.",
      "Periksa dunia Anda, satu objek dan satu frame pada satu waktu.",
      `<div class="row">${button("scene-refresh", "Sinkronkan", "refresh", "subtle small")}${button("scene-save", "Simpan proyek", "save", "small")}<a class="button small" href="#review">${icon("check")} Review</a></div>`,
    ) +
    `<section id="film-switcher" class="panel film-switcher" aria-label="Adegan film"></section><div class="scene-layout"><div class="stack"><section class="panel"><div class="panel-head"><h2>Objek adegan</h2><span id="object-count" class="chip">—</span></div><div style="padding:13px"><label class="search">${icon("search")}${input("object-search", "", "search", 'placeholder="Cari objek…" aria-label="Cari objek"')}</label></div><div class="object-list" id="object-list" tabindex="0" aria-label="Daftar objek adegan"><div class="skeleton"></div></div></section><div class="row">${button("scene-open", "Buka proyek", "folder", "small subtle")}${button("scene-new", "Adegan baru", "plus", "small subtle")}</div><div class="help">Z ke atas · satuan meter<br>Karakter menghadap −Y (depan).</div></div><div class="stack"><section class="panel"><div class="panel-head"><h2>${icon("camera")} Monitor adegan</h2><span id="scene-meta" class="mono muted">SCENE VIEW</span></div><div class="viewport" id="scene-viewport">${state.previews[0] ? `<img src="${esc(state.previews[0])}" alt="Pratinjau adegan terbaru">` : empty("camera", "Temukan sudut terbaik.", "Pilih frame dan kamera, lalu buat pratinjau untuk memeriksa komposisi.")}</div><form id="preview-form" class="preview-controls">${field("Frame · pisahkan koma", input("preview-frames", initialFrame, "text", 'required pattern="[0-9, ]+"'))}${field(
      "Kamera / sudut",
      select("preview-camera", [
        ["scene", "Kamera adegan"],
        ["three_quarter", "Tiga perempat"],
        ["front", "Depan"],
        ["right", "Kanan"],
        ["back", "Belakang"],
        ["top", "Atas"],
      ]),
    )}${field(
      "Engine",
      select("preview-engine", [
        ["workbench", "Workbench · cepat"],
        ["eevee", "Eevee · material"],
      ]),
    )}${field(
      "Ukuran",
      select(
        "preview-size",
        [
          ["256", "256 px"],
          ["512", "512 px"],
        ],
        "512",
      ),
    )}<button class="button primary" type="submit">${icon("eye")} Pratinjau</button></form><div id="scene-filmstrip">${state.previews.length ? filmstrip(state.previews) : ""}</div><div id="scene-error"></div></section>${walkPressPanel()}<section class="panel" aria-label="Suasana adegan"><div class="panel-head"><h2>${icon("light")} Suasana</h2><span class="chip">SINEMATIK</span></div><div class="scene-look-body">${lookPicker("scene-look", false, state.scene?.cinematic_look?.preset || "none")}<div class="row look-actions"><span class="help">Periksa warna, cahaya, dan fokus.</span>${button("apply-look", "Terapkan & pratinjau", "eye", "primary small")}</div></div></section><section class="panel"><div class="panel-head"><h2>${icon("render")} Linimasa shot</h2></div>${otsForm()}<div id="shot-list"><div class="skeleton"></div></div></section>${collisionPanel()}</div></div>`;
  const target = $("#scene-error", root);
  let lookRevision = 0;
  const looks = mountLookPicker(root, "scene-look", () => lookRevision++);
  $("#apply-look", root).onclick = () => action($("#apply-look", root), async () => {
    const info = await scene(true);
    await run("cinematic_look", { preset: looks.dataset.value });
    const frame = Number($("#preview-frames", root).value.split(",")[0]) || 1;
    const rigs = info.objects.filter((object) => object.type === "ARMATURE").map((object) => object.name);
    const result = await run("render_frames", { frames: [frame], camera: info.active_camera ? "scene" : "auto",
      ...(info.active_camera || !rigs.length ? {} : { objects: rigs }), size: 512, engine_name: "eevee" });
    state.previews = result.images;
    refreshPreviews(root);
    $("#preview-engine", root).value = "eevee";
    await scene(true);
    toast("Suasana diterapkan.");
  }, target);
  const refresh = async () => {
    const revision = lookRevision;
    const info = await scene(true);
    showObjects(root, info);
    refreshTools(info);
    refreshWalkPress(info);
    await switcher(root, refresh);
    const currentLook = info.cinematic_look?.preset || "none";
    if (revision === lookRevision) {
      looks.dataset.value = currentLook;
      const radio = looks.querySelector(`input[value="${currentLook}"]`);
      if (radio) { radio.checked = true; radio.dispatchEvent(new Event("change", { bubbles: true })); }
    }
    const shots = await run("list_shots");
    state.shots = shots.data;
    showShots(root, shots.data);
  };
  const refreshTools = mountSceneTools(root, refresh);
  const refreshWalkPress = mountWalkPress(root);
  if (state.scene) {
    showObjects(root, state.scene);
    refreshTools(state.scene);
    refreshWalkPress(state.scene);
  }
  if (state.shots) showShots(root, state.shots);
  action(null, refresh, target);
  $("#scene-refresh", root).onclick = () =>
    action($("#scene-refresh", root), refresh, target);
  $("#object-search", root).oninput = () => showObjects(root, state.scene);
  $("#preview-form", root).onsubmit = (event) => {
    event.preventDefault();
    const btn = $("button[type=submit]", event.target);
    action(
      btn,
      async () => {
        const frames = $("#preview-frames", root)
          .value.split(",")
          .map((x) => Number(x.trim()));
        if (
          !frames.length ||
          frames.some((x) => !Number.isInteger(x) || x < 0) ||
          frames.length > 12
        )
          throw new Error("Pilih 1–12 nomor frame yang valid.");
        const camera = $("#preview-camera", root).value;
        const result = await run("render_frames", {
          frames,
          camera: camera === "scene" ? "scene" : "auto",
          view: camera === "scene" ? "three_quarter" : camera,
          size: Number($("#preview-size", root).value),
          engine_name: $("#preview-engine", root).value,
        });
        state.previews = result.images;
        $("#scene-viewport", root).innerHTML = result.images[0]
          ? `<img src="${esc(result.images[0])}" alt="Frame ${frames[0]} dari adegan">`
          : empty(
              "image",
              "Tidak ada gambar",
              "Lihat detail hasil di antrean.",
            );
        $("#scene-filmstrip", root).innerHTML = filmstrip(
          result.images,
          frames.map((f) => `Frame ${f} · ${camera}`),
        );
        target.innerHTML = "";
      },
      target,
    );
  };
  $("#scene-save", root).onclick = () => {
    if (state.scene?.film && state.film) {
      const entry = state.film.scenes[state.scene.film.index - 1];
      action($("#scene-save", root), async () => {
        await run("save_project", { path: entry.project });
        toast("Adegan film tersimpan.");
      }, target);
      return;
    }
    modal(
      "Simpan proyek",
      `<form id="save-form"><div class="modal-body">${field("Nama proyek (.blend)", input("project-name", "adegan.blend", "text", 'required pattern="[^/\\\\]+[.]blend"'))}<p class="help" style="margin-top:12px">Proyek disimpan ke workspace/projects/.</p></div><div class="modal-actions"><button class="button primary" type="submit">${icon("save")} Simpan proyek</button></div></form>`,
    );
    $("#save-form").onsubmit = (event) => {
      event.preventDefault();
      action(
        $("button[type=submit]", event.target),
        async () => {
          await run("save_project", { path: $("#project-name").value });
          closeModal();
          toast("Proyek tersimpan.");
        },
        target,
      );
    };
  };
  $("#scene-open", root).onclick = () =>
    action(
      $("#scene-open", root),
      async () => {
        const files = (await request("/api/gallery")).files.filter(
          (f) => f.extension === ".blend",
        );
        modal(
          "Buka proyek",
          `<div class="modal-body">${files.length ? files.map((f) => `<button class="button full open-file" data-path="${esc(f.path)}" style="margin-bottom:8px">${icon("folder")}${esc(f.name)}</button>`).join("") : empty("folder", "Belum ada proyek", "Simpan adegan terlebih dahulu.")}</div>`,
        );
        $$(".open-file").forEach(
          (btn) =>
            (btn.onclick = async () => {
              const path = btn.dataset.path;
              closeModal();
              if (
                await confirm(
                  "Ganti adegan saat ini?",
                  "Perubahan yang belum disimpan akan hilang.",
                  "Buka proyek",
                  true,
                )
              )
                action(
                  null,
                  async () => {
                    await run("open_project", {
                      path: path.replace(/^projects\//, ""),
                    });
                    state.previews = [];
                    await refresh();
                    toast("Proyek dibuka.");
                  },
                  target,
                );
            }),
        );
      },
      target,
    );
  $("#scene-new", root).onclick = async () => {
    if (
      await confirm(
        "Mulai adegan baru?",
        "Semua objek di adegan saat ini akan dihapus. Perubahan yang belum disimpan akan hilang.",
        "Buat adegan baru",
        true,
      )
    )
      action(
        $("#scene-new", root),
        async () => {
          await scene(true);
          await run("new_scene");
          state.previews = [];
          state.build = null;
          $("#scene-viewport", root).innerHTML = empty(
            "scene",
            "Panggung baru, cerita baru.",
            "Buat karakter atau mulai dengan naskah.",
          );
          $("#scene-filmstrip", root).innerHTML = "";
          await refresh();
        },
        target,
      );
  };
}
export function refreshPreviews(root) {
  const viewport = $("#scene-viewport", root);
  if (!viewport || !state.previews.length) return;
  viewport.innerHTML = `<img src="${esc(state.previews[0])}" alt="Pratinjau adegan terbaru">`;
  $("#scene-filmstrip", root).innerHTML = filmstrip(state.previews);
}
function showObjects(root, info) {
  if (!info || !$("#object-search", root)) return;
  const query = $("#object-search", root).value.toLowerCase();
  const groups = {
    ARMATURE: ["Karakter & rig", "user"],
    MESH: ["Properti & mesh", "scene"],
    CAMERA: ["Kamera", "camera"],
    LIGHT: ["Pencahayaan", "light"],
    OTHER: ["Lainnya", "folder"],
  };
  $("#object-count", root).textContent = info.objects.length;
  $("#scene-meta", root).textContent =
    `${info.frame_range.join("–")} f · ${info.fps} FPS`;
  let html = "";
  for (const [type, [label, symbol]] of Object.entries(groups)) {
    const items = info.objects.filter(
      (o) =>
        (type === "OTHER"
          ? !["ARMATURE", "MESH", "CAMERA", "LIGHT"].includes(o.type)
          : o.type === type) && o.name.toLowerCase().includes(query),
    );
    if (items.length)
      html +=
        `<div class="object-group">${label} · ${items.length}</div>` +
        items
          .map(
            (o) =>
              `<div class="object-item">${icon(symbol)}<span>${esc(o.name)}</span><small>${o.armature?.bones ? o.armature.bones + " b" : o.mesh?.vertices ? o.mesh.vertices + " v" : ""}</small></div>`,
          )
          .join("");
  }
  $("#object-list", root).innerHTML =
    html ||
    empty(
      "scene",
      "Belum ada objek",
      "Buat karakter atau bangun adegan dari naskah.",
    );
}
function showShots(root, data) {
  if (!$("#shot-list", root)) return;
  const shots = data?.shots || [];
  const roles = { establish: "Pembuka", reaction: "Reaksi pendengar", OTS: "Dari balik bahu", speaker: "Pembicara" };
  $("#shot-list", root).innerHTML = shots.length
    ? `<div class="shot-track">${shots.map(s => {
      const [first, last] = s.frames;
      const role = roles[s.reason?.role] || (s.info?.shot === "over_shoulder" ? roles.OTS : "");
      const emotion = s.reason?.emotion;
      return `<button type="button" class="shot-block" data-shot-frame="${esc(first)}">
        ${esc(s.marker || s.camera || "Shot")}
        <small>${esc(first)}–${esc(last)} f${role ? ` · ${esc(role)}` : ""}${emotion ? ` · ${esc(emotion)}` : ""}</small>
      </button>`;
    }).join("")}</div>${json(data)}`
    : empty(
        "render",
        "Linimasa masih kosong.",
        "Kamera dari naskah atau camera_shot akan muncul di sini.",
      );
  for (const btn of $$("[data-shot-frame]", root)) {
    btn.onclick = () => {
      const frame = $("#preview-frames", root);
      frame.value = btn.dataset.shotFrame;
      $("#preview-camera", root).value = "scene";
      frame.focus();
    };
  }
}
