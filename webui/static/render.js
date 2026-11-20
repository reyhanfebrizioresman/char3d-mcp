import { buildProgress } from "./film.js";
import { run, state, scene } from "./api.js";
import {
  $, $$, action, button, check, confirm, errorHTML, esc, field, head, icon, input,
  screenRoot, seconds, select,
} from "./ui.js";

const isRender = (job) => ["render_video", "render_film"].includes(job.tool)
  && !["quote_required", "consent_required"].includes(job.result?.data?.status);
const active = (job) => !["completed", "failed", "cancelled"].includes(job.status);
const qualityLabels = { draft: "Draft", preview: "Pratinjau", final: "Final" };
const usd = (value) => Number.isFinite(value) ? `$${value.toFixed(4)}` : "—";

export function mount(main) {
  const root = screenRoot(main);
  let quality = "draft", resolution = null, filmName = null, revision = 0, submitting = false;
  root.innerHTML = head("DARI ADEGAN KE FILM", "Saatnya memutar cerita.",
    "Pilih target, kualitas, dan ukuran video.") + `
    <div class="render-layout">
      <section class="panel">
        <div class="panel-head"><h2>${icon("settings")} Pengaturan render</h2></div>
        <div class="panel-body">
          <p id="film-render-scope" class="notice render-field-note" hidden></p>
          <div class="quality-tabs" role="group" aria-label="Kualitas render">
            ${Object.entries(qualityLabels).map(([key, label]) =>
              `<button type="button" data-quality="${key}" class="${key === quality ? "active" : ""}">${label}</button>`).join("")}
          </div>
          <div class="form-grid">
            ${field("Target render", select("video-target", [["local", "Lokal · mesin ini"]]), "span-2")}
            <p id="render-target-note" class="help span-2"></p>
            ${field("Nama video", input("video-name", "film-pertama.mp4", "text", 'maxlength="100"'), "span-2")}
            ${field("Frame awal · opsional", input("video-start", "", "number", 'min="1" step="1" placeholder="Awal adegan"'))}
            ${field("Frame akhir · opsional", input("video-end", "", "number", 'min="1" step="1" placeholder="Akhir adegan"'))}
            <div class="span-2 row between studio-actions">
              ${check("video-vertical", "Vertikal · 9:16", false)}
              ${button("options-refresh", "Hitung estimasi", "refresh", "small subtle")}
            </div>
          </div>
        </div>
        <div class="panel-head"><h2>Pilih resolusi</h2></div>
        <div id="resolution-options"><div class="skeleton"></div></div>
        <div class="render-options-footer">
          <p id="render-note" class="help render-field-note" role="status">Memuat estimasi…</p>
          ${button("start-render", "Render draft", "play", "primary full")}
          <div id="render-error" role="alert"></div>
        </div>
      </section>
      <div class="stack">
        <section class="panel">
          <div class="panel-head"><h2>${icon("render")} Ruang pemutaran</h2><span id="video-state" class="chip">SIAP</span></div>
          <div class="render-cover" id="render-player">${icon("render")}<p>Video hasil render akan tampil di sini.</p></div>
          <div class="panel-body" id="render-progress"><p class="help">Belum ada render aktif.</p></div>
        </section>
        <div id="render-result" class="stack"></div>
      </div>
    </div>`;

  const target = $("#render-error", root);
  const table = $("#resolution-options", root);
  const start = $("#start-render", root);
  const machine = $("#video-target", root);
  const selector = [machine, ...$$("[data-quality]", root), ...[
    "video-name", "video-start", "video-end", "video-vertical", "options-refresh",
  ].map(id => $("#" + id, root))];
  const optionsNote = $("#render-note", root);
  const activeRender = () => state.jobs.find(job => isRender(job) && active(job));

  function updateControls() {
    start.disabled = !resolution || submitting || !!activeRender();
    selector.forEach(el => { el.disabled = submitting; });
    for (const id of ["video-start", "video-end"])
      $("#" + id, root).disabled = submitting || !!filmName;
  }

  function range() {
    if (filmName) return {};
    const first = $("#video-start", root).value, last = $("#video-end", root).value;
    if ([first, last].some(value => value && (!Number.isInteger(Number(value)) || Number(value) < 1)))
      throw new Error("Nomor frame harus berupa bilangan bulat mulai dari 1.");
    if (first && last && Number(last) < Number(first))
      throw new Error("Frame akhir harus sama dengan atau setelah frame awal.");
    return { ...(first ? { frame_start: Number(first) } : {}), ...(last ? { frame_end: Number(last) } : {}) };
  }

  function invalidateOptions(message) {
    revision++;
    resolution = null;
    table.innerHTML = "";
    optionsNote.textContent = message;
    updateControls();
  }

  async function load() {
    invalidateOptions("Menghitung estimasi…");
    target.innerHTML = "";
    const current = revision;
    const info = await scene(true);
    if (revision !== current) return;
    filmName = info.film?.name || null;
    const scope = $("#film-render-scope", root);
    scope.hidden = !filmName;
    scope.textContent = filmName ? `Seluruh film · ${filmName}` : "";
    updateControls();
    const remote = machine.value !== "local";
    const { data: options } = await run(filmName ? "film_render_options" : "render_options", {
      quality, vertical: $("#video-vertical", root).checked, target: machine.value, ...range(),
      ...(filmName ? { name: filmName } : {}),
    });
    if (revision !== current) return;
    state.renderOptions = options;
    table.innerHTML = `<table class="resolution-table"><thead><tr><th>RESOLUSI</th><th>UKURAN</th><th>ESTIMASI</th>
      ${remote ? "<th>BIAYA</th>" : ""}</tr></thead><tbody>${options.options.map(option => {
        const time = remote ? seconds(option.total_s) : option.total_human || option.estimated_human
          || seconds(option.total_s || option.estimated_seconds || option.seconds || option.estimated_s);
        return `<tr><td><label><input type="radio" name="resolution" value="${esc(option.resolution)}"> ${esc(option.resolution)}</label></td>
          <td class="mono">${esc(option.size)}</td><td>${esc(time)}</td>
          ${remote ? `<td class="mono">${usd(option.estimated_cost_usd)}</td>` : ""}</tr>`;
      }).join("")}</tbody></table>`;
    const measurement = options.machine_speed?.measurements
      ? "Berdasarkan render sebelumnya."
      : "Estimasi awal untuk target ini.";
    optionsNote.textContent = `${options.duration_s} dtk · ${options.frames.join("–")} frame. ${measurement}`;
  }

  table.onchange = (event) => {
    if (event.target.name !== "resolution") return;
    resolution = event.target.value;
    $$(".resolution-table tr", root).forEach(row =>
      row.classList.toggle("selected", !!$("input:checked", row)));
    updateControls();
  };

  const reload = () => action(null, async () => {
    try {
      await load();
    } catch (error) {
      optionsNote.textContent = "Estimasi belum tersedia. Coba hitung ulang.";
      throw error;
    }
  }, target);

  for (const btn of $$("[data-quality]", root)) {
    btn.onclick = () => {
      quality = btn.dataset.quality;
      $$("[data-quality]", root).forEach(el => el.classList.toggle("active", el === btn));
      start.innerHTML = icon("play") + `Render ${qualityLabels[quality].toLowerCase()}`;
      reload();
    };
  }
  $("#options-refresh", root).onclick = reload;
  $("#video-vertical", root).onchange = reload;
  machine.onchange = reload;
  for (const id of ["video-start", "video-end"])
    $("#" + id, root).oninput = () => invalidateOptions("Hitung ulang estimasi setelah mengubah rentang.");

  run("remote_targets").then(({ data }) => {
    const label = { ssh: "SSH", runpod: "RunPod", vast: "Vast.ai" };
    machine.append(...(data.targets || []).map(t =>
      new Option(`${t.name} · ${label[t.kind] || t.kind}`, t.name)));
    if (!(data.targets || []).length) $("#render-target-note", root).textContent =
      "Target SSH atau GPU dapat ditambahkan di ~/.config/char3d/targets.json.";
  }).catch(() => {
    $("#render-target-note", root).textContent = "Daftar target jarak jauh gagal dimuat. Render lokal tetap tersedia.";
  });

  start.onclick = async () => {
    if (submitting || !resolution || activeRender()) return;
    submitting = true;
    updateControls();
    target.innerHTML = "";
    try {
      await action(null, async () => {
        const path = $("#video-name", root).value.trim();
        if (!path.toLowerCase().endsWith(".mp4")) throw new Error("Nama video harus berakhiran .mp4.");
        const tool = filmName ? "render_film" : "render_video";
        const args = {
          path, quality, resolution, target: machine.value, wait: false,
          vertical: $("#video-vertical", root).checked, ...range(),
          ...(filmName ? { name: filmName } : {}),
        };
        if (args.target !== "local") {
          const allowed = await confirm("Kirim snapshot ke " + args.target + "?",
            "Snapshot Blender dapat menyertakan tekstur, gambar, audio, font, judul, dan subtitle yang dipakai.",
            "Izinkan pengiriman");
          if (!allowed || !root.isConnected) return;
          args.consent_upload = true;
        }
        const { data } = await run(tool, args);
        if (!root.isConnected) return;
        if (data.status === "consent_required") throw new Error("Target memerlukan izin pengiriman.");
        if (data.status === "quote_required") {
          const accepted = await confirm("Konfirmasi biaya render",
            `<p>${esc(data.target)} · ${esc(data.gpu_type)} · estimasi ${seconds(data.estimated_runtime_s)}</p>
            <p>Estimasi total <strong>${usd(data.estimated_total_usd)}</strong> · ${usd(data.hourly_price_usd)}/jam</p>
            <p>Batas durasi ${esc(data.max_hours)} jam${data.max_budget_usd == null ? "" : ` · batas biaya ${usd(data.max_budget_usd)}`}.</p>
            <p class="help">${esc(data.billing_note)}</p>`, "Setujui biaya & render");
          if (accepted && root.isConnected)
            await run(tool, { ...args, quote_id: data.quote_id, confirm_cost: true });
        }
      }, target);
    } finally {
      submitting = false;
      updateControls();
    }
  };

  function update() {
    updateControls();
    const job = activeRender() || state.jobs.find(isRender);
    if (!job) return;
    const progress = job.progress || job.result?.data || {};
    const complete = job.status === "completed";
    const statuses = { completed: "SELESAI", failed: "GAGAL", queued: "DALAM ANTREAN", cancelled: "DIBATALKAN" };
    $("#video-state", root).textContent = statuses[job.status] || "MERENDER";
    const [done, total] = String(progress.progress || "0/1").split("/").map(Number);
    const percent = complete ? 100 : Math.min(99, Math.round(100 * done / total) || 0);
    const stage = complete ? "Video siap diputar"
      : job.status === "cancelled" ? "Render dibatalkan"
      : job.status === "failed" ? "Render gagal"
      : job.status === "queued" ? `Antrean · posisi ${job.queue_position}`
      : progress.cleanup_pending ? "Membersihkan worker"
      : progress.stage?.startsWith("compose") ? "Menyusun subtitle & grafis"
      : progress.target ? `Memproses di ${progress.target}` : "Merender frame";
    $("#render-progress", root).innerHTML = `
      <div class="row between studio-actions"><strong>${esc(stage)} · ${percent}%</strong><span class="mono muted">${seconds(job.elapsed_s)}</span></div>
      <div class="progress"><i style="width:${percent}%"></i></div>
      <div class="row between studio-actions">
        <span class="help">${progress.progress ? esc(progress.progress) : ""}
          ${progress.eta_s && active(job) ? ` · Sisa sekitar ${seconds(progress.eta_s)}` : ""}
          ${progress.cost_so_far_usd == null ? "" : ` · ${usd(progress.cost_so_far_usd)} terpakai`}
        </span>
        ${active(job) && progress.job_id && !progress.cleanup_pending ? button("cancel-video", "Batalkan", "", "small danger") : ""}
      </div>
      ${progress.scenes ? buildProgress(progress) : ""}
      ${job.error ? errorHTML(job.error) : ""}`;
    const cancel = $("#cancel-video", root);
    if (cancel) cancel.onclick = () => action(cancel, () => run("cancel_render", { job_id: progress.job_id }), target);
    const outputs = $("#render-result", root);
    outputs.hidden = !complete;
    if (!complete) return;
    const file = job.result?.files?.find(url => url.endsWith(".mp4"));
    if (!file) return;
    if ($("video", root)?.getAttribute("src") === file) return;
    $("#render-player", root).innerHTML = `<video controls preload="metadata" src="${esc(file)}"
      ${state.previews[0] ? `poster="${esc(state.previews[0])}"` : ""} aria-label="Video hasil render"></video>`;
    outputs.innerHTML =
      `<a class="button full" href="${esc(file)}?download=1">${icon("download")} Unduh MP4</a>
      ${job.result.files.filter(url => url.endsWith(".srt")).map(url =>
        `<a class="button full" href="${esc(url)}?download=1">Unduh subtitle .srt</a>`).join("")}
      <a class="button full" href="#review" id="render-review">${icon("check")} Review video</a>`;
    $("#render-review", root).onclick = () => {
      const prefix = "/api/files/renders/";
      if (file.startsWith(prefix)) state.reviewVideo = decodeURIComponent(file.slice(prefix.length));
    };
  }

  document.addEventListener("jobs-updated", update);
  update();
  reload();
  return () => document.removeEventListener("jobs-updated", update);
}
