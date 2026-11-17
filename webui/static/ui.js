import { icon } from "./icons.js";
export { icon };
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [
  ...root.querySelectorAll(selector),
];
// Async work keeps its own detached screen alive while navigation mounts another.
export function screenRoot(main) {
  const screen = document.createElement("div");
  main.replaceChildren(screen);
  return screen;
}
export const seconds = (value) => {
  const n = Math.max(0, Math.round(Number(value) || 0));
  return n < 60
    ? `${n} dtk`
    : n < 3600
      ? `${Math.floor(n / 60)} m ${n % 60} dtk`
      : `${Math.floor(n / 3600)} j ${Math.round((n % 3600) / 60)} m`;
};
export const bytes = (value) =>
  value < 1024 * 1024
    ? `${Math.round(value / 1024)} KB`
    : `${(value / 1024 / 1024).toFixed(1)} MB`;
export const field = (label, control, extra = "") =>
  `<label class="field ${extra}"><span>${label}</span>${control}</label>`;
export const select = (id, options, value = "") =>
  `<select id="${id}" name="${id}">${options
    .map((o) => {
      const [v, l] = Array.isArray(o) ? o : [o, o];
      return `<option value="${esc(v)}" ${String(v) === String(value) ? "selected" : ""}>${esc(l)}</option>`;
    })
    .join("")}</select>`;
export const input = (id, value = "", type = "text", attrs = "") =>
  `<input id="${id}" name="${id}" type="${type}" value="${esc(value)}" ${attrs}>`;
export const check = (id, label, on = true) =>
  `<label class="check"><input type="checkbox" id="${id}" ${on ? "checked" : ""}>${label}</label>`;
export const button = (id, label, symbol = "", cls = "") =>
  `<button class="button ${cls}" id="${id}" type="button">${symbol ? icon(symbol) : ""}${label}</button>`;
export const empty = (symbol, title, copy) =>
  `<div class="empty">${icon(symbol)}<strong>${title}</strong><p>${copy}</p></div>`;
export const head = (eyebrow, title, copy, action = "") =>
  `<div class="page-head"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${copy}</p></div>${action}</div>`;
export const json = (data) =>
  `<details><summary>Detail hasil · JSON</summary><pre>${esc(JSON.stringify(data, null, 2))}</pre></details>`;
export const warnings = (data) =>
  (data?.warnings || [])
    .map(
      (w) =>
        `<div class="notice">${esc(typeof w === "string" ? w : JSON.stringify(w))}</div>`,
    )
    .join("");
export function errorHTML(error) {
  const [message, ...tail] = String(error?.message || error).split("\n");
  return `<div class="notice error"><strong>${esc(message)}</strong>${tail.length ? `<details><summary>Detail teknis / traceback</summary><pre>${esc(tail.join("\n"))}</pre></details>` : ""}</div>`;
}
export function toast(message, type = "success") {
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.innerHTML = `${icon(type === "error" ? "bulb" : "check")}<span>${esc(message)}</span><button class="icon-button" aria-label="Tutup notifikasi">${icon("close")}</button>`;
  node.querySelector("button").onclick = () => node.remove();
  $("#toasts").append(node);
  setTimeout(() => node.remove(), 6500);
}
export async function action(button, callback, target = null) {
  if (button?.disabled) return;
  if (button) button.disabled = true;
  try {
    return await callback();
  } catch (e) {
    toast(String(e.message).split("\n")[0], "error");
    if (target) target.innerHTML = errorHTML(e);
  } finally {
    if (button) button.disabled = false;
  }
}
let onClose = null;
export function closeModal() {
  clearModal();
  $("#modal").close();
}
function clearModal() {
  const cleanup = onClose;
  onClose = null;
  cleanup?.();
  $("#modal-content").innerHTML = "";
  $("#modal").className = "";
}
$("#modal").addEventListener("close", () => {
  if (!$("#modal").open) clearModal();
});
export function modal(
  title,
  body,
  actions = "",
  cleanup = null,
  media = false,
) {
  if ($("#modal").open) closeModal();
  onClose = cleanup;
  $("#modal").classList.toggle("media-modal", media);
  $("#modal-content").innerHTML =
    `<div class="modal-head"><h2>${esc(title)}</h2><button class="icon-button modal-close" aria-label="Tutup dialog">${icon("close")}</button></div>${body}${actions}`;
  $(".modal-close").onclick = closeModal;
  $("#modal").showModal();
}
export function confirm(title, copy, yes = "Lanjutkan", danger = false) {
  return new Promise((resolve) => {
    modal(
      title,
      `<div class="modal-body">${copy}</div>`,
      `<div class="modal-actions">${button("confirm-no", "Batal", "", "subtle")}${button("confirm-yes", yes, "", danger ? "danger" : "primary")}</div>`,
      () => resolve(false),
    );
    $("#confirm-no").onclick = closeModal;
    $("#confirm-yes").onclick = () => {
      resolve(true);
      closeModal();
    };
  });
}
export async function lightbox(url, name = "Pratinjau") {
  modal(
    name,
    `<div class="media-content"><img src="${esc(url)}" alt="${esc(name)}"></div>`,
    "",
    null,
    true,
  );
}
export function filmstrip(images, labels = []) {
  return `<div class="filmstrip">${images.map((url, i) => `<button type="button" data-image="${esc(url)}" data-label="${esc(labels[i] || `Pratinjau ${i + 1}`)}"><img src="${esc(url)}" alt="${esc(labels[i] || `Pratinjau ${i + 1}`)}"><span>${esc(labels[i] || `Pratinjau ${i + 1}`)} ${icon("external")}</span></button>`).join("")}</div>`;
}
document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-image]");
  if (el) lightbox(el.dataset.image, el.dataset.label);
});
export function bindRanges(root = document) {
  $$("input[type=range]", root).forEach((el) => {
    const out = $(`output[for="${el.id}"]`, root);
    const update = () => {
      if (out) out.textContent = el.value;
    };
    el.addEventListener("input", update);
    update();
  });
}
