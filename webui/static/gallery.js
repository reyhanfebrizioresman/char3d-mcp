import { screenRoot } from "./ui.js";
import { state, request, run } from "./api.js";
import {
  icon,
  esc,
  $,
  $$,
  head,
  input,
  button,
  empty,
  action,
  bytes,
  modal,
  lightbox,
  json,
  toast,
} from "./ui.js";
export function mount(root) {
  root = screenRoot(root);
  let filter = "all";
  root.innerHTML =
    head(
      "SEMUA HASIL, SATU TEMPAT",
      "Arsip dunia yang Anda ciptakan.",
      "Pratinjau, putar, dan unduh hasil dari workspace lokal.",
      button("gallery-refresh", "Segarkan", "refresh", "small subtle"),
    ) +
    `<div class="toolbar"><label class="search">${icon("search")}${input("gallery-search", "", "search", 'placeholder="Cari hasil kreasi…" aria-label="Cari hasil kreasi"')}</label><div class="filter-tabs" aria-label="Filter galeri"><button data-filter="all" class="active">Semua</button><button data-filter="image">Gambar</button><button data-filter="video">Video</button><button data-filter="model">3D</button><button data-filter="project">Proyek</button></div></div><div class="section-label"><span id="gallery-count">Memuat hasil…</span><span class="mono">WORKSPACE / OUTPUT</span></div><div id="gallery-content"><div class="skeleton" style="height:260px"></div></div>`;
  const content = $("#gallery-content", root);
  const type = (file) =>
    [".png", ".jpg", ".jpeg", ".webp"].includes(file.extension)
      ? "image"
      : file.extension === ".mp4"
        ? "video"
        : [".glb", ".gltf"].includes(file.extension)
          ? "model"
          : "project";
  const draw = () => {
    const query = $("#gallery-search", root).value.toLowerCase();
    const list = state.gallery.filter(
      (f) =>
        (filter === "all" || type(f) === filter) &&
        f.name.toLowerCase().includes(query),
    );
    $("#gallery-count", root).textContent = `${list.length} hasil kreasi`;
    content.innerHTML = list.length
      ? `<div class="gallery-grid">${list
          .map((file) => {
            const t = type(file);
            return `<article class="asset-card"><button class="asset-thumb" data-file="${esc(file.path)}" aria-label="Buka ${esc(file.name)}">${t === "image" ? `<img loading="lazy" src="${esc(file.url)}" alt="${esc(file.name)}">` : t === "video" ? `<video preload="metadata" muted src="${esc(file.url)}#t=0.1" aria-label="Cuplikan ${esc(file.name)}"></video>` : icon(t === "model" ? "scene" : file.extension === ".blend" ? "folder" : "script")}<span class="asset-type">${esc(file.extension.slice(1).toUpperCase())}</span></button><div class="asset-body"><h3 title="${esc(file.name)}">${esc(file.name)}</h3><div class="asset-meta"><span>${new Date(file.modified * 1000).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" })}</span><span>${bytes(file.size)}</span></div><div class="asset-actions"><span>${esc(file.folder)}/</span><a href="${esc(file.url)}?download=1" download>${icon("download")} Unduh</a></div></div></article>`;
          })
          .join("")}</div>`
      : empty(
          "gallery",
          "Ruang untuk karya berikutnya.",
          "Render frame, ekspor karakter, atau simpan proyek. Hasilnya akan terkumpul di sini.",
        );
    $$("[data-file]", root).forEach(
      (el) =>
        (el.onclick = () =>
          open(
            state.gallery.find((f) => f.path === el.dataset.file),
            type,
          )),
    );
  };
  const load = async () => {
    state.gallery = (await request("/api/gallery")).files;
    draw();
  };
  $("#gallery-search", root).oninput = draw;
  $$("[data-filter]", root).forEach(
    (btn) =>
      (btn.onclick = () => {
        filter = btn.dataset.filter;
        $$("[data-filter]", root).forEach((el) =>
          el.classList.toggle("active", el === btn),
        );
        draw();
      }),
  );
  $("#gallery-refresh", root).onclick = () =>
    action($("#gallery-refresh", root), load, content);
  const signature = (jobs) =>
    jobs
      .filter((j) => j.status === "completed" && j.result?.files?.length)
      .map((j) => j.id)
      .join(",");
  let previous = signature(state.jobs);
  const update = (event) => {
    const next = signature(event.detail.jobs || []);
    if (next !== previous) {
      previous = next;
      load().catch(() => {});
    }
  };
  document.addEventListener("jobs-updated", update);
  action(null, load, content);
  return () => document.removeEventListener("jobs-updated", update);
}
async function open(file, type) {
  const t = type(file);
  if (t === "image") return lightbox(file.url, file.name);
  if (t === "video") {
    const srt = state.gallery.find(
      (f) => f.path === file.path.replace(/\.mp4$/, ".srt"),
    );
    modal(
      file.name,
      `<div class="media-content"><video controls autoplay src="${esc(file.url)}" aria-label="${esc(file.name)}"></video></div><div class="modal-actions"><a class="button" href="${esc(file.url)}?download=1">${icon("download")} Unduh MP4</a>${srt ? `<a class="button" href="${esc(srt.url)}?download=1">Subtitle .srt</a>` : ""}</div>`,
      "",
      null,
      true,
    );
    return;
  }
  if (t === "model") {
    let dispose = () => {};
    modal(
      file.name,
      '<div class="media-content"><div class="model-viewport" id="model-viewport"><span class="model-message">Menyiapkan model 3D lokal…</span></div><p class="help" style="margin-top:10px">Seret untuk memutar · scroll / cubit untuk zoom · klik kanan untuk menggeser.</p></div>',
      "",
      () => dispose(),
      true,
    );
    try {
      const viewer = await import("./viewer.js");
      if (!$("#model-viewport")) return;
      dispose = await viewer.show($("#model-viewport"), file.url);
    } catch (e) {
      if ($(".model-message"))
        $(".model-message").textContent =
          `Pratinjau 3D gagal: ${e.message}. Anda tetap dapat mengunduh model.`;
    }
    return;
  }
  modal(
    file.name,
    `<div class="modal-body"><p>${esc(file.path)}</p><p class="help">${bytes(file.size)} · ${file.extension === ".blend" ? "Buka melalui Adegan → Buka proyek untuk melanjutkan penyuntingan." : "Unduh file untuk membukanya dengan aplikasi yang sesuai."}</p><a class="button" style="margin-top:18px" href="${esc(file.url)}?download=1">${icon("download")} Unduh file</a></div>`,
  );
}
