import { run, scene, state, upload } from "./api.js";
import { $, action, errorHTML, esc, field, icon, json, select, warnings } from "./ui.js";

export function characterAssets() {
  return `
    <section class="panel" aria-labelledby="character-assets-title">
      <div class="panel-head"><h2 id="character-assets-title">Impor avatar &amp; wajah</h2></div>
      <div class="panel-body stack">
        <form id="vrm-form" class="stack">
          ${field("Avatar VRM", '<input id="vrm-file" type="file" accept=".vrm" required>')}
          <button type="submit" class="button small">${icon("upload")} Impor VRM</button>
          <div id="vrm-result" role="status"></div>
        </form>
        <div class="divider"></div>
        <form id="photo-form" class="stack">
          ${field("Karakter MPFB", select("photo-character", [["", "Belum ada karakter MPFB"]]))}
          ${field("Foto wajah dari depan", '<input id="photo-file" type="file" accept=".png,.jpg,.jpeg" required>')}
          <label class="check"><input type="checkbox" id="photo-consent" required>
            Saya memiliki izin menggunakan wajah pada foto ini</label>
          <p class="help">Foto diproses di workspace studio.</p>
          <button type="submit" class="button primary small" disabled>Terapkan wajah</button>
          <div id="photo-result" role="status"></div>
        </form>
      </div>
    </section>`;
}

export function mountCharacterAssets(root, refreshViews) {
  const photoSelect = $("#photo-character", root);
  const photoSubmit = $("#photo-form button[type=submit]", root);
  const updateCharacters = async (preferred) => {
    const { objects } = await scene(true);
    const selected = preferred || photoSelect.value;
    const bodies = objects.filter(o => o.type === "MESH" && o.source === "mpfb");
    photoSelect.replaceChildren(...(bodies.length
      ? bodies.map(o => new Option(o.name, o.name))
      : [new Option("Belum ada karakter MPFB", "")]));
    if (bodies.some(o => o.name === selected)) photoSelect.value = selected;
    photoSubmit.disabled = !bodies.length;
  };

  async function inspect(names, target) {
    if (!names.length || !root.isConnected) return;
    try {
      const { images } = await run("render_views", { objects: names, size: 320, engine_name: "workbench" });
      state.characterViews = images;
      refreshViews(root);
    } catch (error) {
      target.insertAdjacentHTML("beforeend", errorHTML(new Error("Pratinjau gagal. " + error.message)));
    }
  }

  $("#vrm-form", root).onsubmit = (event) => {
    event.preventDefault();
    const target = $("#vrm-result", root);
    action(event.submitter, async () => {
      const file = $("#vrm-file", root).files[0];
      if (!file || !/\.vrm$/i.test(file.name)) throw new Error("Pilih file dengan ekstensi .vrm.");
      target.textContent = "Mengimpor avatar…";
      const { path } = await upload(file, "models");
      const { data } = await run("import_model", { path });
      state.scene = null;
      const rigs = data.vrm || [];
      target.innerHTML = rigs.map(rig => `<div class="notice"><strong>${esc(rig.armature)}</strong>
        · VRM ${esc(rig.version)} · ${Object.keys(rig.mapped_bones).length} tulang terpetakan</div>`
        + warnings(rig)).join("") + json(data);
      state.character = data;
      await updateCharacters();
      await inspect(rigs.map(rig => rig.armature), target);
    }, target);
  };

  $("#photo-form", root).onsubmit = (event) => {
    event.preventDefault();
    const target = $("#photo-result", root);
    action(event.submitter, async () => {
      const file = $("#photo-file", root).files[0];
      const character = photoSelect.value;
      if (!character || !$("#photo-consent", root).checked) throw new Error("Pilih karakter dan konfirmasi izin foto.");
      if (!file || !/\.(png|jpe?g)$/i.test(file.name)) throw new Error("Gunakan foto JPG, JPEG, atau PNG.");
      target.textContent = "Mencocokkan landmark wajah…";
      const { path } = await upload(file, "images");
      const { data } = await run("face_from_photo", { character, image: path, consent: true });
      state.character = data;
      target.innerHTML = `<div class="notice"><strong>Wajah diterapkan ke ${esc(data.character)}</strong>
        · selisih proyeksi ${esc(data.fit_error_px)} px</div>${json(data)}`;
      await inspect([data.character || character], target);
    }, target);
  };
  action(null, updateCharacters, $("#photo-result", root));
  return updateCharacters;
}
