import { esc, field, select, input, check, $, $$ } from "./ui.js";
const labels = {
  name: "Nama",
  path: "Path file",
  character: "Karakter",
  characters: "Karakter",
  armature: "Armature",
  objects: "Objek",
  frame: "Frame",
  frame_start: "Frame awal",
  frame_end: "Frame akhir",
  start_frame: "Frame awal",
  end_frame: "Frame akhir",
  quality: "Kualitas",
  resolution: "Resolusi",
  width: "Lebar",
  height: "Tinggi",
  size: "Ukuran",
  text: "Teks",
  language: "Bahasa",
  seed: "Seed",
  camera: "Kamera",
  view: "Sudut pandang",
  engine_name: "Engine render",
  strength: "Kekuatan",
  expression: "Ekspresi",
  audio: "Audio",
  image: "Gambar",
  prompt: "Prompt",
  provider: "Penyedia",
  build: "Bangun adegan",
  fps: "Frame per detik",
  style: "Gaya",
  location: "Lokasi",
  rotation_deg: "Rotasi",
  scale: "Skala",
  rig: "Jenis rig",
  clothes: "Pakaian",
  hair: "Rambut",
  skin: "Kulit",
  subtitles: "Subtitle",
  sound: "Suara",
  script: "Naskah",
  wait: "Tunggu hasil",
  all: "Semua",
  clear: "Bersihkan",
  keyframe: "Simpan keyframe",
  transparent: "Transparan",
  vertical: "Vertikal",
  face: "Wajah",
  approach: "Dekati pasangan",
  loop: "Ulangi",
  calibrate: "Ukur kecepatan mesin",
  deform_only: "Hanya tulang deform",
};
function shape(schema) {
  return schema.anyOf?.find((s) => s.type !== "null") || schema;
}
function kind(schema) {
  const s = shape(schema);
  if (schema.anyOf?.filter((s) => s.type !== "null").length > 1) return "json";
  return ["object", "array"].includes(s.type) ? "json" : s.type;
}
export function schemaForm(schema) {
  const required = schema.required || [];
  return `<div class="form-grid">${Object.entries(schema.properties || {})
    .map(([key, raw]) => {
      const s = shape(raw),
        type = kind(raw),
        id = `arg-${key}`,
        label = `${esc(labels[key] || key.replaceAll("_", " "))}${required.includes(key) ? " *" : ""} <span class="schema-name">${esc(key)}</span>`;
      let control;
      if (s.enum)
        control = select(
          id,
          [
            ...(!required.includes(key) && raw.default == null
              ? [["", "Otomatis / default"]]
              : []),
            ...s.enum,
          ],
          raw.default ?? "",
        );
      else if (type === "boolean" && raw.anyOf?.some((s) => s.type === "null"))
        control = select(
          id,
          [
            ["", "Otomatis / default"],
            ["true", "Ya"],
            ["false", "Tidak"],
          ],
          raw.default == null ? "" : String(raw.default),
        );
      else if (type === "boolean")
        return `<div class="field">${check(id, label, raw.default === true)}</div>`;
      else if (type === "json")
        control = `<textarea class="schema-json" id="${id}" ${required.includes(key) ? "required" : ""} spellcheck="false" placeholder="${esc(s.type === "array" ? "[]" : s.type === "object" ? "{}" : "JSON atau teks")}" data-json ${raw.anyOf?.some((s) => s.type === "string") ? "data-allow-text" : ""}>${raw.default != null ? esc(JSON.stringify(raw.default, null, 2)) : ""}</textarea>`;
      else
        control = input(
          id,
          raw.default ?? "",
          type === "number" || type === "integer" ? "number" : "text",
          `${type === "integer" ? 'step="1"' : type === "number" ? 'step="any"' : ""} ${required.includes(key) ? "required" : ""}`,
        );
      return field(label, control, type === "json" ? "span-2" : "");
    })
    .join("")}</div>`;
}
export function readSchema(schema, root) {
  const result = {};
  for (const [key, raw] of Object.entries(schema.properties || {})) {
    const el = $(`#arg-${key}`, root);
    const type = kind(raw);
    let value = el.type === "checkbox" ? el.checked : el.value;
    if (value === "" && !(schema.required || []).includes(key)) continue;
    if (type === "boolean" && el.type !== "checkbox") value = value === "true";
    if (type === "json") {
      try {
        value = JSON.parse(value);
      } catch {
        if (raw.anyOf?.some((s) => s.type === "string")) value = el.value;
        else throw new Error(`${key}: JSON tidak valid`);
      }
    } else if (type === "number" || type === "integer") {
      if (value === "") throw new Error(`${key}: angka diperlukan`);
      value = Number(value);
      if (
        !Number.isFinite(value) ||
        (type === "integer" && !Number.isInteger(value))
      )
        throw new Error(`${key}: angka tidak valid`);
    }
    result[key] = value;
  }
  return result;
}
export function validateJSON(root) {
  $$("[data-json]", root).forEach((el) =>
    el.addEventListener("input", () => {
      if (!el.value) {
        el.setCustomValidity("");
        return;
      }
      try {
        JSON.parse(el.value);
        el.setCustomValidity("");
      } catch {
        el.setCustomValidity(
          el.hasAttribute("data-allow-text") ? "" : "JSON tidak valid",
        );
      }
    }),
  );
}
