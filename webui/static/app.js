import { state, request, run, startPolling, poll } from "./api.js";
import {
  icon,
  esc,
  $,
  $$,
  seconds,
  toast,
  button,
  json,
  action,
  errorHTML,
} from "./ui.js";
import * as script from "./script.js";
import * as scene from "./scene.js";
import * as characters from "./characters.js";
import * as render from "./render.js";
import * as gallery from "./gallery.js";
import * as tools from "./tools.js";
const pages = {
  naskah: ["Naskah ke adegan", "script", script],
  adegan: ["Adegan", "scene", scene],
  karakter: ["Karakter", "user", characters],
  render: ["Render", "render", render],
  galeri: ["Galeri output", "gallery", gallery],
  tools: ["Semua tool", "tools", tools],
};
const theme =
  localStorage.getItem("char3d-theme") ||
  (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
function setTheme(value) {
  document.documentElement.dataset.theme = value;
  localStorage.setItem("char3d-theme", value);
  $("#theme-toggle").innerHTML =
    `${icon(value === "dark" ? "moon" : "sun")}<span>${value === "dark" ? "Tema gelap" : "Tema terang"}</span><span>Ganti ↗</span>`;
}
setTheme(theme);
$("#theme-toggle").onclick = () =>
  setTheme(
    document.documentElement.dataset.theme === "dark" ? "light" : "dark",
  );
$("#navigation").innerHTML = Object.entries(pages)
  .map(
    ([id, [label, symbol]]) =>
      `<a class="nav-link" href="#${id}" data-page="${id}">${icon(symbol)}${label}<span class="nav-end">${id === "naskah" ? "✦" : id === "tools" ? "↗" : ""}</span></a>`,
  )
  .join("");
$("#mobile-menu").innerHTML = icon("menu");
const nav = (open) => {
  document.body.classList.toggle("nav-open", open);
  $("#sidebar").inert = matchMedia("(max-width: 680px)").matches && !open;
  $("#sidebar-scrim").hidden = !open;
  $("#mobile-menu").setAttribute("aria-expanded", String(open));
};
matchMedia("(max-width: 680px)").addEventListener("change", () => nav(false));
$("#mobile-menu").onclick = () =>
  nav(!document.body.classList.contains("nav-open"));
$("#sidebar-scrim").onclick = () => nav(false);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    nav(false);
    $("#jobs-panel").hidden = true;
  }
});
let cleanup;
function navigate() {
  const id =
    location.hash.slice(1) in pages ? location.hash.slice(1) : "naskah";
  const [label, , module] = pages[id];
  cleanup?.();
  nav(false);
  $("#current-page").textContent = label;
  document.title = `${label} · char3d Studio`;
  $$("[data-page]").forEach((el) => {
    el.classList.toggle("active", el.dataset.page === id);
    if (el.dataset.page === id) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  try {
    cleanup = module.mount($("#main"));
  } catch (e) {
    $("#main").innerHTML = errorHTML(e);
  }
  window.scrollTo(0, 0);
}
const labels = {
  queued: "Menunggu",
  running: "Memproses",
  rendering: "Merender",
  processing: "AI memproses",
  completed: "Selesai",
  failed: "Gagal",
  cancelled: "Dibatalkan",
};
$("#jobs-toggle").onclick = () => {
  $("#jobs-panel").hidden = !$("#jobs-panel").hidden;
  drawJobs();
};
function drawJobs() {
  const active = state.jobs.filter(
    (j) => !["completed", "failed", "cancelled"].includes(j.status),
  );
  $("#jobs-toggle").innerHTML =
    `${icon("queue")} Antrean <span class="chip">${active.length}</span>`;
  const job = active.find((j) => j.status !== "queued") || active[0];
  if (!$("#engine-state").classList.contains("error")) {
    $("#engine-state").innerHTML =
      `<span class="dot ${job ? "pulse" : ""}"></span><span>${job ? "Engine sibuk" : "Engine terhubung"}</span>`;
  }
  $("#live-status").textContent = job
    ? `${labels[job.status]} · ${job.tool} · ${seconds(job.elapsed_s)}${job.queue_position ? ` · posisi antrean ${job.queue_position}` : ""} · ${active.length} pekerjaan aktif`
    : "Studio siap · Semua perubahan diproses di engine lokal";
  if ($("#jobs-panel").hidden) return;
  const expanded = $$(".job-item details[open]", $("#jobs-panel")).map(
    (el) => el.closest(".job-item").dataset.id,
  );
  $("#jobs-panel").innerHTML =
    `<div class="panel-head"><h2>Antrean studio</h2><button class="icon-button" id="close-jobs" aria-label="Tutup antrean">${icon("close")}</button></div>${
      state.jobs.length
        ? state.jobs
            .slice(0, 30)
            .map(
              (j) =>
                `<article class="job-item" data-id="${j.id}"><div class="row between"><strong>${esc(j.tool)}</strong><span class="chip ${j.status === "completed" ? "green" : j.status === "failed" ? "warm" : ""}">${labels[j.status]}</span></div><small>${seconds(j.elapsed_s)} ${j.queue_position ? `· Antrean #${j.queue_position}` : ""}${j.progress?.progress ? " · " + esc(j.progress.progress) + (j.progress.kind === "film" ? " tahap" : " frame") : ""}</small>${j.error ? `<div class="job-error">${errorHTML(j.error)}</div>` : ""}${j.result ? json(j.result.data) : ""}</article>`,
            )
            .join("")
        : '<div class="empty"><strong>Belum ada pekerjaan</strong><p>Jalankan rencana atau buat karakter untuk memulai.</p></div>'
    }`;
  for (const id of expanded) {
    const details = $(`.job-item[data-id="${id}"] details`, $("#jobs-panel"));
    if (details) details.open = true;
  }
  $("#close-jobs").onclick = () => ($("#jobs-panel").hidden = true);
}
document.addEventListener("jobs-updated", drawJobs);
document.addEventListener("job-submitted", drawJobs);
document.addEventListener("job-finished", (event) => {
  const job = event.detail;
  if (
    [
      "engine_status",
      "scene_info",
      "list_shots",
      "mpfb_assets",
      "render_options",
      "film_render_options",
      "film_info",
      "director_status",
      "list_voices",
    ].includes(job.tool)
  )
    return;
  if (job.tool === "direct_scene") {
    toast(job.status === "completed" ? "Draf sutradara siap ditinjau." : "Draf sutradara gagal. Periksa pesan pada panel.", job.status === "failed" ? "error" : "success");
    return;
  }
  toast(
    `${job.tool} · ${labels[job.status]}`,
    job.status === "failed" ? "error" : "success",
  );
  if (
    (!location.hash || location.hash === "#naskah") &&
    ["script_to_scene", "script_to_film", "render_frames", "render_preview"].includes(job.tool) &&
    job.status === "completed"
  ) {
    script.refreshResult($("#script-result"));
  }
  if (
    job.status === "completed" &&
    ["render_frames", "render_preview"].includes(job.tool) &&
    location.hash === "#adegan"
  )
    scene.refreshPreviews($("#main"));
  if (
    job.status === "completed" &&
    job.tool === "render_views" &&
    location.hash === "#karakter"
  )
    characters.refreshViews($("#main"));
});
let connectionWarned = false;
document.addEventListener("connection-error", () => {
  if (!connectionWarned) {
    connectionWarned = true;
    toast("Koneksi studio terputus. Mencoba menghubungkan kembali…", "error");
  }
  $("#live-status").textContent = "Menghubungkan kembali ke server studio…";
});
async function engineStatus() {
  try {
    const r = await run("engine_status");
    $("#engine-state").classList.remove("error");
    $("#engine-state").innerHTML =
      '<span class="dot"></span><span>Engine terhubung</span>';
    $("#engine-state").title = `Workspace: ${r.data.workspace}`;
  } catch (e) {
    $("#engine-state").classList.add("error");
    $("#engine-state").innerHTML =
      '<span class="dot"></span><span>Engine bermasalah</span>';
    $("#engine-state").title = e.message;
  }
}
try {
  state.tools = (await request("/api/tools")).tools;
  await poll();
  startPolling();
  window.addEventListener("hashchange", navigate);
  navigate();
  engineStatus();
  setInterval(() => {
    if (!state.jobs.some((j) => ["running", "queued"].includes(j.status)))
      engineStatus();
  }, 30000);
} catch (e) {
  $("#main").innerHTML = errorHTML(e);
}
