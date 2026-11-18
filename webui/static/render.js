import { buildProgress } from "./film.js";
import { screenRoot } from "./ui.js";
import { run, state, scene } from "./api.js";
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
  seconds,
  json,
  toast,
  errorHTML,
} from "./ui.js";
const active = (job) =>
  !["completed", "failed", "cancelled"].includes(job.status);
export function mount(root) {
  root = screenRoot(root);
  let quality = "draft",
    resolution = null,
    options = null, filmName = state.film?.name || null;
  root.innerHTML =
    head(
      "DARI ADEGAN KE FILM",
      "Saatnya memutar cerita.",
      "Periksa draft, pilih resolusi, lalu biarkan studio menyelesaikannya.",
      `<span class="chip">${icon("render")} H.264 · MP4</span>`,
    ) +
    `<div class="render-layout"><section class="panel"><div class="panel-head"><h2>${icon("settings")} Pengaturan render</h2><span class="mono muted">OUTPUT</span></div><div class="panel-body"><div id="film-render-scope" class="notice" style="margin-bottom:16px" hidden></div><div class="quality-tabs" role="group" aria-label="Kualitas render"><button data-quality="draft" class="active">Draft</button><button data-quality="preview">Pratinjau</button><button data-quality="final">Final</button></div><div class="form-grid">${field("Nama video", input("video-name", "film-pertama.mp4", "text", 'maxlength="100"'), "span-2")}${field("Frame awal · opsional", input("video-start", "", "number", 'min="1" step="1" placeholder="Awal adegan"'))}${field("Frame akhir · opsional", input("video-end", "", "number", 'min="1" step="1" placeholder="Akhir adegan"'))}<div class="span-2 row between">${check("video-vertical", "Vertikal · 9:16", false)}${button("options-refresh", "Hitung estimasi", "refresh", "small subtle")}</div></div></div><div class="panel-head"><h2>Pilih resolusi</h2><span class="help">Estimasi waktu mesin ini</span></div><div id="resolution-options"><div class="skeleton"></div></div><div class="render-options-footer"><p id="render-note" class="help" style="margin-bottom:17px">Pilih ukuran output sebelum mulai.</p>${button("start-render", "Render draft", "play", "primary full")}<div id="render-error" style="margin-top:12px"></div></div></section><div class="stack"><section class="panel"><div class="panel-head"><h2>${icon("render")} Ruang pemutaran</h2><span id="video-state" class="chip">SIAP SAAT ANDA SIAP</span></div><div class="render-cover" id="render-player">${icon("render")}<p>Film Anda akan diputar di sini.</p><span class="mono muted">LIGHTS. CAMERA. CREATE.</span></div><div class="panel-body" id="render-progress"><div class="row between"><strong style="font-size:12px">Belum ada render aktif</strong><span class="mono muted">00:00</span></div><div class="progress"><i></i></div><p class="help">Anda bisa berpindah layar selama render berjalan.</p></div></section><div class="render-advice">${icon("bulb")}<div><strong>Mulai dari draft yang ringan.</strong><p>Workbench memeriksa gerak dan kamera dengan cepat. Pratinjau dan final menggunakan Eevee untuk material dan pencahayaan.</p></div></div><div class="notice" style="font-size:11px">Pilih sendiri resolusi sebelum render. Estimasi akan semakin akurat setelah mesin menyelesaikan render pertama.</div><div id="render-result"></div></div></div>`;
  const target = $("#render-error", root);
  const range = () => {
    if (filmName) return {};
    const a = $("#video-start", root).value,
      b = $("#video-end", root).value;
    const args = {};
    if (a) args.frame_start = Number(a);
    if (b) args.frame_end = Number(b);
    if (a && b && Number(b) < Number(a))
      throw new Error("Frame akhir harus setelah frame awal.");
    return args;
  };
  const load = async () => {
    resolution = null;
    $("#start-render", root).disabled = true;
    const info = await scene(true);
    filmName = info.film?.name || null;
    const scope = $("#film-render-scope", root);
    scope.hidden = !filmName;
    scope.textContent = filmName ? `Seluruh film · ${filmName}` : "";
    for (const id of ["video-start", "video-end"]) $(`#${id}`, root).disabled = !!filmName;
    const result = await run(filmName ? "film_render_options" : "render_options", {
      ...(filmName ? {name:filmName} : {}),
      quality,
      vertical: $("#video-vertical", root).checked,
      ...range(),
    });
    options = result.data;
    state.renderOptions = options;
    $("#resolution-options", root).innerHTML =
      `<table class="resolution-table"><thead><tr><th>RESOLUSI</th><th>UKURAN</th><th>ESTIMASI</th></tr></thead><tbody>${(options.options || []).map((o) => `<tr><td><label><input type="radio" name="resolution" value="${esc(o.resolution)}"> ${esc(o.resolution)}</label></td><td class="mono">${esc(o.size)}</td><td>${esc(o.total_human || o.estimated_human || seconds(o.total_s || o.estimated_seconds || o.seconds || o.estimated_s))}</td></tr>`).join("")}</tbody></table>`;
    $("#render-note", root).textContent =
      `${options.duration_s} dtk · ${options.frames.join("–")} frame. ${options.machine_speed?.measurements ? "Estimasi dipelajari dari mesin ini." : "Belum dikalibrasi; estimasi awal CPU."}`;
    $$("input[name=resolution]", root).forEach(
      (el) =>
        (el.onchange = () => {
          resolution = el.value;
          $$(".resolution-table tr", root).forEach((row) =>
            row.classList.toggle("selected", !!$("input:checked", row)),
          );
          $("#start-render", root).disabled = state.jobs.some(
            (j) => ["render_video", "render_film"].includes(j.tool) && active(j),
          );
        }),
    );
  };
  $$("[data-quality]", root).forEach(
    (btn) =>
      (btn.onclick = () => {
        quality = btn.dataset.quality;
        $$("[data-quality]", root).forEach((el) =>
          el.classList.toggle("active", el === btn),
        );
        $("#start-render", root).innerHTML =
          icon("play") +
          (quality === "draft"
            ? "Render draft"
            : quality === "preview"
              ? "Render pratinjau"
              : "Render final");
        action(null, load, target);
      }),
  );
  $("#options-refresh", root).onclick = () =>
    action($("#options-refresh", root), load, target);
  $("#video-vertical", root).onchange = () => action(null, load, target);
  for (const id of ["video-start", "video-end"])
    $(`#${id}`, root).onchange = () => {
      resolution = null;
      $("#start-render", root).disabled = true;
      $("#render-note", root).textContent =
        "Rentang berubah. Hitung estimasi kembali, lalu pilih resolusi.";
    };
  $("#start-render", root).onclick = () =>
    action(
      $("#start-render", root),
      async () => {
        if (!resolution)
          throw new Error("Pilih resolusi output terlebih dahulu.");
        const path = $("#video-name", root).value.trim();
        if (!path.toLowerCase().endsWith(".mp4"))
          throw new Error("Nama video harus berakhiran .mp4");
        const parameters = {
          path,
          quality,
          resolution,
          vertical: $("#video-vertical", root).checked,
          ...range(),
          wait: false,
        };
        await scene(true);
        target.innerHTML = "";
        const r = await run(filmName ? "render_film" : "render_video", { ...parameters, ...(filmName ? {name:filmName} : {}) });
        const result = $("#render-result", root);
        if (result) result.innerHTML = json(r.data);
        toast("Video selesai dirender.");
      },
      target,
    );
  const update = () => {
    const job = state.jobs.find((j) => ["render_video", "render_film"].includes(j.tool));
    if (!job) return;
    const p = job.progress || job.result?.data || {};
    let done = 0,
      total = 1;
    if (typeof p.progress === "string")
      [done, total] = p.progress.split("/").map(Number);
    const complete = job.status === "completed";
    const percent = complete
      ? 100
      : Math.min(99, Math.round((done / total) * 100) || 0);
    $("#video-state", root).textContent = complete
      ? "SELESAI"
      : job.status === "failed"
        ? "GAGAL"
        : job.status === "queued"
          ? "DALAM ANTREAN"
          : "MERENDER";
    $("#render-progress", root).innerHTML =
      `<div class="row between"><strong style="font-size:12px">${complete ? "Film siap diputar" : job.status === "queued" ? `Antrean · posisi ${job.queue_position}` : job.status === "failed" ? "Render gagal" : p.stage?.startsWith("compose") ? "Menyusun subtitle & grafis" : "Merender frame"} · ${percent}%</strong><span class="mono muted">${seconds(job.elapsed_s)}</span></div><div class="progress"><i style="width:${percent}%"></i></div><div class="row between"><span class="help">${p.progress ? esc(p.progress) + (p.kind === "film" ? " tahap · " : " frame · ") : ""}${complete ? "Tersimpan di galeri" : p.eta_s ? `Sisa sekitar ${seconds(p.eta_s)}` : "Menyiapkan estimasi…"}</span>${active(job) && p.job_id ? button("cancel-video", "Batalkan", "", "small danger") : ""}</div>${p.scenes ? buildProgress(p) : ""}${job.error ? errorHTML(job.error) : ""}`;
    if ($("#cancel-video", root))
      $("#cancel-video", root).onclick = () =>
        action(
          $("#cancel-video", root),
          () => run("cancel_render", { job_id: p.job_id }),
          target,
        );
    if (complete) {
      const file = job.result?.files?.find((f) => f.endsWith(".mp4"));
      if (file && !$("video", root))
        $("#render-player", root).innerHTML =
          `<video controls preload="metadata" src="${esc(file)}" ${state.previews[0] ? `poster="${esc(state.previews[0])}"` : ""} aria-label="Video hasil render"></video>`;
      if (file)
        $("#render-result", root).innerHTML =
          `<a class="button full" href="${esc(file)}?download=1">${icon("download")} Unduh MP4</a>${job.result.files
            .filter((f) => f.endsWith(".srt"))
            .map(
              (f) =>
                `<a class="button full" href="${esc(f)}?download=1" style="margin-top:8px">Unduh subtitle .srt</a>`,
            )
            .join("")}`;
    }
    if (active(job)) $("#start-render", root).disabled = true;
    else if (resolution) $("#start-render", root).disabled = false;
  };
  document.addEventListener("jobs-updated", update);
  update();
  action(null, load, target);
  return () => document.removeEventListener("jobs-updated", update);
}
