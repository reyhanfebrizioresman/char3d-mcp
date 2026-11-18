import { esc } from "./ui.js";

export const LOOKS = [
  ["none", "Tanpa suasana", "Cahaya adegan asli", "#616b70,#a4a9a2,#d4d1be"],
  ["golden_hour", "Jam emas", "Hangat · bayangan panjang", "#285b6a,#e7a063,#fff0bc"],
  ["sunset", "Senja", "Merah muda · rim hangat", "#53487d,#ca7292,#ffbd83"],
  ["misty_morning", "Pagi berkabut", "Sejuk · kabut rendah", "#8eafbb,#cad5ce,#f5e9d1"],
  ["blue_hour", "Jam biru", "Biru dalam · lampu hangat", "#172c58,#517296,#efb87c"],
  ["night", "Malam", "Cahaya bulan · pijar lampu", "#080f24,#233b66,#bb8955"],
  ["overcast_soft", "Mendung lembut", "Teduh · warna alami", "#7c9096,#b2bebc,#e0dbcf"],
  ["dreamy", "Mimpi", "Pastel · debu melayang", "#8e98bc,#e7b6ca,#fff0d5"],
  ["epic", "Epik", "Kontras · berkas cahaya", "#182d40,#696d70,#e5b66f"],
  ["studio_film", "Film studio", "Lembut · pijar praktikal", "#243d42,#957866,#e3bf97"],
];

export const lookLabel = (preset) => LOOKS.find((look) => look[0] === preset)?.[1] || preset;

export function lookPicker(id, follow = false, selected = follow ? "" : "none") {
  const values = follow ? [["", "Ikuti naskah", "Pakai SUASANA: bila tersedia", "#454b43,#898b74,#c5b99d"], ...LOOKS] : LOOKS;
  return `<div class="look-picker" id="${id}" data-value="${esc(selected)}"><div class="look-grid" role="radiogroup" aria-label="Suasana">${values.map(([key, title, description, colors]) => `<label class="look-choice" title="${esc(description)}"><input type="radio" name="${id}-choice" value="${key}" ${key === selected ? "checked" : ""}><span class="look-swatch" style="--look-colors:${colors}" aria-hidden="true"><i></i></span><span class="look-name">${esc(title)}</span></label>`).join("")}</div><p class="help look-description" aria-live="polite">${esc(values.find((l) => l[0] === selected)?.[2] || "")}</p></div>`;
}

export function mountLookPicker(root, id, onChange = () => {}) {
  const el = root.querySelector(`#${id}`);
  el.addEventListener("change", (event) => {
    el.dataset.value = event.target.value;
    const look = LOOKS.find((l) => l[0] === event.target.value);
    el.querySelector(".look-description").textContent = look?.[2] || "Pakai SUASANA: bila tersedia";
    onChange(event.target.value);
  });
  return el;
}
