import { run, state } from "./api.js";
import { $, errorHTML, esc, field, icon, select } from "./ui.js";

export const walkPressPanel = () => `
  <section class="panel" aria-labelledby="walk-press-title">
    <div class="panel-head"><h2 id="walk-press-title">${icon("play")} Jalan lalu tekan tombol</h2></div>
    <form id="walk-press-form" class="preview-controls walk-press-controls">
      ${field("Karakter", select("walk-press-character", []))}
      ${field("Tutup tombol", select("walk-press-button", []))}
      <button class="button primary" type="submit" disabled>${icon("eye")} Pratinjau aksi</button>
    </form>
    <div class="walk-press-feedback">
      <p id="walk-press-status" class="help" role="status"></p>
      <div id="walk-press-error"></div>
    </div>
    <div id="walk-press-player" class="walk-press-player"></div>
  </section>`;

export function mountWalkPress(root) {
  const form = $("#walk-press-form", root);
  const character = $("#walk-press-character", form);
  const button = $("#walk-press-button", form);
  const submit = $("button[type=submit]", form);
  const status = $("#walk-press-status", root);
  const error = $("#walk-press-error", root);
  const player = $("#walk-press-player", root);
  let busy = false;

  function controls() {
    character.disabled = busy || !character.options.length;
    button.disabled = busy || !button.options.length;
    submit.disabled = busy || !character.value || !button.value;
  }

  function show(saved) {
    player.innerHTML = saved
      ? `<video controls playsinline preload="metadata" src="${esc(saved.url)}" aria-label="Pratinjau jalan dan tekan tombol"></video>`
      : "";
  }

  function selected() {
    const saved = state.walkPressPreview;
    return saved?.character === character.value && saved?.button === button.value ? saved : null;
  }

  function changed() {
    error.innerHTML = "";
    show(selected());
    status.textContent = "";
    controls();
  }
  character.onchange = button.onchange = changed;

  form.onsubmit = async (event) => {
    event.preventDefault();
    if (submit.disabled) return;
    const selection = { character: character.value, button: button.value };
    busy = true;
    controls();
    error.innerHTML = "";
    show(null);
    status.textContent = "Menyiapkan lintasan dan pijakan…";
    try {
      const result = await run("preview_walk_press", selection, {
        onUpdate(job) {
          if (!form.isConnected) return;
          if (job.status === "queued") status.textContent = "Menunggu giliran…";
          if (job.status === "running") status.textContent = "Menyiapkan lintasan dan pijakan…";
          if (job.status === "rendering") {
            const progress = job.progress?.progress;
            status.textContent = progress ? `Merender pratinjau ${progress} frame…` : "Merender pratinjau…";
          }
        },
      });
      const url = result.files.find((file) => file.toLowerCase().endsWith(".mp4"));
      if (!url) throw new Error("Video pratinjau belum tersedia. Coba jalankan lagi.");
      state.walkPressPreview = { ...selection, url };
      if (form.isConnected) {
        show(state.walkPressPreview);
        status.textContent = "Pratinjau siap diputar.";
      }
    } catch (failure) {
      if (form.isConnected) {
        status.textContent = "";
        error.innerHTML = errorHTML(failure);
      }
    } finally {
      busy = false;
      controls();
    }
  };

  return (info) => {
    const objects = new Map(info.objects.map((object) => [object.name, object]));
    const rigs = info.objects.filter((object) => object.type === "ARMATURE" && object.visible);
    function bound(object) {
      if (object.modifiers?.some((m) => m.startsWith("ARMATURE:"))) return true;
      for (let parent = objects.get(object.parent); parent; parent = objects.get(parent.parent)) {
        if (parent.type === "ARMATURE") return true;
      }
      return false;
    }
    const preferred = /(?:button|tombol|switch|saklar)/i;
    const caps = info.objects.filter((object) => object.type === "MESH" && object.visible && !bound(object))
      .sort((a, b) => Number(preferred.test(b.name)) - Number(preferred.test(a.name)) || a.name.localeCompare(b.name));
    updateOptions(character, rigs, character.value || state.walkPressPreview?.character);
    updateOptions(button, caps, button.value || state.walkPressPreview?.button);
    controls();
    if (busy) return;
    show(selected());
    status.textContent = !rigs.length ? "Tambahkan karakter yang sudah memiliki rig."
      : !caps.length ? "Tambahkan mesh terpisah untuk tutup tombol." : "";
  };
}

function updateOptions(control, objects, selectedName) {
  control.innerHTML = objects.map(({ name }) => `<option value="${esc(name)}">${esc(name)}</option>`).join("");
  if (objects.some(({ name }) => name === selectedName)) control.value = selectedName;
}
