import { screenRoot } from "./ui.js";
import { run, state, scene } from "./api.js";
import { characterAssets, mountCharacterAssets } from "./character-assets.js";
import {
  icon,
  esc,
  $,
  $$,
  head,
  field,
  select,
  input,
  check,
  button,
  action,
  filmstrip,
  json,
  warnings,
  bindRanges,
  toast,
} from "./ui.js";
const slider = (id, label, value, min = 0, max = 1, step = 0.05) =>
  field(
    `${label} <output for="${id}">${value}</output>`,
    input(id, value, "range", `min="${min}" max="${max}" step="${step}"`),
  );
export function mount(root) {
  root = screenRoot(root);
  let mode = "realistic";
  root.innerHTML =
    head(
      "PEMERAN UNTUK CERITA ANDA",
      "Kenalkan, karakter berikutnya.",
      "Bentuk penampilan, pilih pakaian, lalu periksa dari setiap sisi.",
      `<span class="chip green">MPFB · Aset CC0</span>`,
    ) +
    `<div class="character-layout"><section class="panel"><div class="panel-head"><h2>${icon("user")} Pembuat karakter</h2><span class="mono muted">CASTING</span></div><div class="panel-body"><div class="quality-tabs"><button type="button" data-mode="realistic" class="active">Manusia realistis</button><button type="button" data-mode="mannequin">Manekin</button></div><div id="asset-notice" class="help" style="margin-bottom:18px">Membaca katalog aset lokal…</div><form id="character-form"><div class="form-grid">${field("Nama karakter", input("char-name", "Maya", "text", 'required maxlength="60"'), "span-2")}<div id="realistic-fields" class="span-2"><div class="form-grid">${slider("char-gender", "Feminin → maskulin", 0)}${slider("char-age", "Usia (tahun)", 28, 1, 90, 1)}${slider("char-height", "Tinggi relatif", 0.5)}${slider("char-weight", "Berat relatif", 0.5)}${slider("char-muscle", "Otot", 0.4)}${slider("char-proportions", "Proporsi", 0.5)}${field("Rambut", select("char-hair", [["", "Tanpa rambut"]]))}${field("Kulit", select("char-skin", [["auto", "Otomatis sesuai karakter"]]))}${field(
      "Preset pakaian",
      select("char-outfit", [
        ["casual", "Kasual"],
        ["formal", "Formal"],
        ["sport", "Olahraga"],
        ["summer", "Musim panas"],
        ["winter", "Musim dingin"],
      ]),
    )}${field("Jenggot / kumis", select("char-beard", [["", "Tanpa jenggot"]]))}${field("Gaya karakter", select("char-style", [
      ["realistic", "Realistis"], ["anime", "Anime"], ["cartoon", "Kartun"], ["chibi", "Chibi"],
    ]))}${field("Rig", select("char-rig", ["game_engine", "rigify", "mixamo", "default", "cmu_mb"]))}${field("Seed pakaian", input("char-seed", 0, "number", 'min="0" step="1"'))}<details class="span-2"><summary>Warisan etnis · bobot campuran</summary><div class="form-grid">${slider("race-asian", "Asia", 1)}${slider("race-african", "Afrika", 0)}${slider("race-caucasian", "Kaukasia", 0)}</div></details><div class="span-2">${check("explicit-clothes", "Pilih pakaian dari katalog", false)}<div id="clothes-list" class="catalog-clothes" style="margin-top:10px" hidden></div></div></div></div><div id="mannequin-fields" class="span-2" hidden><div class="form-grid">${field("Gaya proporsi", select("man-style", ["stylized", "realistic", "heroic", "cartoon", "chibi"]))}${field(
      "Gender",
      select("man-gender", [
        ["neutral", "Netral"],
        ["female", "Perempuan"],
        ["male", "Laki-laki"],
      ]),
    )}${field("Tinggi (meter)", input("man-height", 1.75, "number", 'min="0.3" max="3" step="0.05"'))}${slider("man-build", "Bentuk tubuh", 1, 0.7, 1.4, 0.05)}</div><p class="help" style="margin-top:14px">Manekin halus untuk blockout. Belum memiliki wajah, rambut, pakaian, atau jari.</p></div></div><div class="divider"></div><button class="button primary full" type="submit">${icon("plus")} Buat karakter</button><p class="help" style="text-align:center;margin-top:10px" id="character-tool">create_realistic_human · sudah termasuk rig</p></form></div></section><div class="stack"><section class="panel"><div class="panel-head"><h2>Pratinjau karakter</h2><span class="chip warm">MODEL SHEET</span></div><div class="character-stage" id="character-stage"><span class="stage-label">MODEL SHEET · −Y FRONT</span>${state.characterViews[0] ? `<img src="${esc(state.characterViews[0])}" alt="Karakter terbaru">` : `<div class="empty"><div class="silhouette" aria-hidden="true"></div><strong>Wajah baru untuk dunia Anda.</strong><p>Karakter akan tampil di sini, lengkap dengan tampilan depan, samping, dan belakang.</p></div>`}</div><div id="character-views">${state.characterViews.length ? filmstrip(state.characterViews, ["Depan", "Kanan", "Belakang", "Tiga perempat"]) : ""}</div></section>${characterAssets()}<div id="character-result">${state.character ? json(state.character) : ""}</div><div class="script-hint">${icon("eye")}<div><h3>Periksa sebelum beraksi.</h3><p>Eevee menampilkan kulit dan material. Periksa pakaian dari setiap sisi; pose ekstrem dapat menyebabkan clipping. Rig MPFB siap dipakai tanpa auto-rig ulang.</p></div></div></div></div>`;
  bindRanges(root);
  const updateCharacters = mountCharacterAssets(root, refreshViews);
  const toggle = (value) => {
    mode = value;
    $$("[data-mode]", root).forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === mode),
    );
    $("#realistic-fields", root).hidden = mode !== "realistic";
    $("#mannequin-fields", root).hidden = mode !== "mannequin";
    $("#character-tool", root).textContent =
      mode === "realistic"
        ? "create_realistic_human · sudah termasuk rig"
        : "create_human · manekin A-pose";
  };
  $$("[data-mode]", root).forEach(
    (btn) => (btn.onclick = () => toggle(btn.dataset.mode)),
  );
  $("#explicit-clothes", root).onchange = (e) => {
    $("#clothes-list", root).hidden = !e.target.checked;
    $("#char-outfit", root).disabled = e.target.checked;
  };
  const catalog = (assets) => {
    state.assets = assets;
    $("#asset-notice", root).innerHTML =
      `<span class="chip green">${icon("check")} Katalog siap</span> <span class="help">${Object.keys(assets.packs || {}).length} paket lokal · siap digunakan</span>`;
    for (const [id, key, initial] of [
      ["char-hair", "hair", [["", "Tanpa rambut"]]],
      ["char-skin", "skins", [["auto", "Otomatis sesuai karakter"]]],
      ["char-beard", "beards", [["", "Tanpa jenggot"]]],
    ]) {
      const el = $(`#${id}`, root);
      const list = assets.assets?.[key] || [];
      el.innerHTML = select(
        id,
        [...initial, ...list],
        id === "char-hair" && list.includes("bob01") ? "bob01" : initial[0][0],
      ).replace(/^<select[^>]*>|<\/select>$/g, "");
    }
    $("#clothes-list", root).innerHTML =
      Object.entries(assets.clothing_categories || {})
        .map(
          ([group, names]) =>
            `<details><summary>${esc(group)} · ${names.length}</summary>${names.map((name, i) => `<label class="check"><input type="checkbox" name="clothing" value="${esc(name)}">${esc(assets.clothing_metadata?.[name]?.name || name)}</label>`).join("")}</details>`,
        )
        .join("") || '<p class="help">Belum ada pakaian terpasang.</p>';
  };
  if (state.assets) catalog(state.assets);
  else
    run("mpfb_assets")
      .then((r) => catalog(r.data))
      .catch(() => {
        $("#asset-notice", root).innerHTML =
          '<div class="notice">MPFB belum tersedia. Jalankan <code>scripts/install_mpfb.sh</code>, lalu restart engine. Manekin tetap dapat digunakan.</div>';
        toggle("mannequin");
      });
  $("#character-form", root).onsubmit = (event) => {
    event.preventDefault();
    const target = $("#character-result", root);
    action(
      $("button[type=submit]", event.target),
      async () => {
        let args = { name: $("#char-name", root).value.trim() };
        if (mode === "realistic") {
          for (const key of [
            "gender",
            "age",
            "height",
            "weight",
            "muscle",
            "proportions",
            "seed",
          ])
            args[key] = Number($(`#char-${key}`, root).value);
          for (const key of ["hair", "skin", "outfit", "rig", "beard", "style"])
            args[key] = $(`#char-${key}`, root).value || null;
          args.race = Object.fromEntries(
            ["asian", "african", "caucasian"].map((k) => [
              k,
              Number($(`#race-${k}`, root).value),
            ]),
          );
          if (!Object.values(args.race).some((x) => x > 0))
            throw new Error("Pilih setidaknya satu bobot etnis.");
          if ($("#explicit-clothes", root).checked)
            args.clothes = $$("input[name=clothing]:checked", root).map(
              (el) => el.value,
            );
        } else {
          args = {
            ...args,
            style: $("#man-style", root).value,
            gender: $("#man-gender", root).value,
            height: Number($("#man-height", root).value),
            build: Number($("#man-build", root).value),
            arm_angle: 35,
          };
        }
        const realistic = mode === "realistic";
        await scene(true);
        const r = await run(
          realistic ? "create_realistic_human" : "create_human",
          args,
        );
        state.character = r.data;
        state.scene = null;
        target.innerHTML = warnings(r.data) + json(r.data);
        if (realistic) await updateCharacters(r.data.body || r.data.name);
        toast("Karakter dibuat. Memeriksa keempat sisi…");
        const subject = r.data.armature || r.data.name;
        const preview = await run("render_views", {
          objects: [subject],
          size: 320,
          engine_name: realistic ? "eevee" : "workbench",
        });
        state.characterViews = preview.images;
        if (!$("#character-stage", root)) return;
        $("#character-stage", root).innerHTML =
          `<span class="stage-label">${esc(subject)} · ${esc(r.data.height_m || args.height || "")} m</span><img src="${esc(preview.images[0])}" alt="Tampak depan karakter ${esc(args.name)}">`;
        $("#character-views", root).innerHTML = filmstrip(preview.images, [
          "Depan",
          "Kanan",
          "Belakang",
          "Tiga perempat",
        ]);
      },
      target,
    );
  };
}
export function refreshViews(root) {
  const stage = $("#character-stage", root);
  if (!stage || !state.characterViews.length) return;
  stage.innerHTML = `<img src="${esc(state.characterViews[0])}" alt="Pratinjau karakter terbaru">`;
  $("#character-views", root).innerHTML = filmstrip(state.characterViews, [
    "Depan",
    "Kanan",
    "Belakang",
    "Tiga perempat",
  ]);
  if (state.character)
    $("#character-result", root).innerHTML =
      warnings(state.character) + json(state.character);
}
