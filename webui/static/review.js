import { run, request, scene, state } from "./api.js";
import {
  $, $$, action, button, check, confirm, esc, field, head, icon, json, screenRoot, select,
} from "./ui.js";

const categories = {
  sound: "Audio", rhythm: "Ritme", camera: "Kamera", performance: "Performa",
  continuity: "Kontinuitas", readability: "Keterbacaan",
};
const severity = {
  error: ["Masalah", "error", 0], warn: ["Peringatan", "warm", 1], info: ["Catatan", "", 2],
};

function reportFile(result, path) {
  return path && result.files.find(url => {
    const prefix = "/api/files/";
    if (!url.startsWith(prefix)) return false;
    const relative = decodeURIComponent(url.slice(prefix.length));
    return path === relative || path.endsWith("/" + relative);
  });
}

function renderReport(target, result) {
  const report = result.data;
  const sheet = reportFile(result, report.contact_sheet);
  const file = reportFile(result, report.report_md);
  const issues = [...(report.issues || [])].sort((a, b) =>
    (severity[a.severity]?.[2] ?? 3) - (severity[b.severity]?.[2] ?? 3));
  const fixed = report.fixed || [];
  target.innerHTML = `
    <section class="panel" aria-labelledby="review-score-title">
      <div class="panel-head">
        <h2 id="review-score-title">Ringkasan</h2>
        ${file ? `<a class="button small subtle" href="${esc(file)}?download=1">${icon("download")} Unduh laporan</a>` : ""}
      </div>
      <div class="panel-body review-summary">
        <div class="review-score"><strong>${esc(report.score)}</strong><span> / 100</span>
          ${report.before ? `<small>Skor awal ${esc(report.before.score)}</small>` : ""}
        </div>
        <dl class="review-metrics">${Object.entries(report.scores || {}).map(([key, value]) =>
          `<div><dt>${esc(categories[key] || key)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>
        ${report.audio ? `<p class="help">${esc(report.audio.lufs)} LUFS · ${esc(report.audio.true_peak_dbfs)}
          dBTP · ${esc(report.audio.clipped_samples)} sampel clipping</p>` : ""}
        ${report.scenes?.length ? `<details><summary>Skor per adegan</summary>
          <ul class="feature-list">${report.scenes.map(item =>
            `<li>${esc(item.index)}. ${esc(item.name)} · ${esc(item.score)}/100</li>`).join("")}</ul>
          </details>` : ""}
        ${report.fix_rounds ? `<details><summary>Koreksi diterapkan · ${fixed.filter(f => f.status === "applied").length}</summary>
          <ul class="feature-list">${fixed.length ? fixed.map(f =>
            `<li>${f.scene == null ? "" : `Adegan ${esc(f.scene)} · `}${esc(f.tool)}
              ${f.status === "applied" ? "· diterapkan" : `· ${esc(f.reason || f.status)}`}</li>`).join("")
            : "<li>Tidak ada koreksi otomatis pada hasil ini.</li>"}</ul>
          </details>` : ""}
        ${report.limits?.length ? `<details><summary>Batas pengukuran</summary><ul class="feature-list">
          ${report.limits.map(limit => `<li>${esc(limit)}</li>`).join("")}</ul></details>` : ""}
      </div>
    </section>
    ${sheet ? `<section class="panel">
      <div class="panel-head"><h2>Cuplikan frame</h2><a class="button small subtle" href="${esc(sheet)}?download=1">Unduh PNG</a></div>
      <a class="review-sheet" href="${esc(sheet)}" target="_blank" rel="noopener">
        <img src="${esc(sheet)}" alt="Lembar cuplikan frame dan label Review">
      </a>
    </section>` : ""}
    <section class="panel" aria-labelledby="review-issues-title">
      <div class="panel-head"><h2 id="review-issues-title">Temuan</h2><span class="chip">${issues.length}</span></div>
      ${issues.length ? `<ul class="review-issues">${issues.map(item => {
        const [label, tone] = severity[item.severity] || [item.severity, ""];
        const where = [
          item.scene == null ? "" : `Adegan ${item.scene}`, item.shot, item.character,
          item.frame == null ? "" : `Frame ${item.frame}`,
          item.time == null ? "" : `${item.time} dtk`,
        ].filter(Boolean).map(esc).join(" · ");
        return `<li>
          <div class="row studio-actions"><span class="chip ${tone}">${esc(label)}</span>
            <strong>${esc(categories[item.category] || item.category)}</strong>
            ${item.auto_fixable ? '<span class="help">Bisa dikoreksi</span>' : ""}
          </div>
          <p>${esc(item.message)}</p>
          ${where ? `<p class="help">${where}</p>` : ""}
          ${report.kind === "scene" && Number.isInteger(item.frame) ?
            `<a class="button small subtle" href="#adegan" data-review-frame="${item.frame}">Periksa frame ${item.frame}</a>` : ""}
          ${Object.keys(item.evidence || {}).length || item.fix?.length ?
            `<details><summary>Bukti &amp; saran</summary><pre>${esc(JSON.stringify(
              { bukti: item.evidence, saran: item.fix }, null, 2))}</pre></details>` : ""}
        </li>`;
      }).join("")}</ul>` : '<p class="panel-body help">Tidak ada temuan pada pemeriksaan ini.</p>'}
    </section>`;
  for (const link of $$("[data-review-frame]", target))
    link.onclick = () => { state.reviewFrame = Number(link.dataset.reviewFrame); };
}

export function mount(main) {
  const root = screenRoot(main);
  let filmName = null, busy = false, scopeChanged = false;
  const preferredVideo = state.reviewVideo;
  state.reviewVideo = null;
  root.innerHTML = head("", "Review",
    "Periksa audio, kamera, dan kontinuitas sebelum membagikan hasil.") + `
    <div class="review-layout">
      <section class="panel" aria-labelledby="review-settings-title">
        <div class="panel-head"><h2 id="review-settings-title">Pengaturan pemeriksaan</h2></div>
        <form id="review-form" class="panel-body stack">
          ${field("Yang diperiksa", '<select id="review-scope"><option value="scene">Adegan aktif</option><option value="film" disabled>Film aktif · versi tersimpan</option><option value="video">Video MP4</option></select>')}
          <div id="review-video-fields" hidden>
            ${field("Video di galeri", select("review-video", [["", "Memuat video…"]]))}
            <a class="help" href="#render">Buka Render</a>
          </div>
          <div class="stack" id="review-scene-fields">
            ${field("Kedalaman", select("review-level", [["quick", "Cepat"], ["standard", "Standar"], ["full", "Lengkap"]], "quick"))}
            ${check("review-sheet", "Buat lembar cuplikan frame")}
            <p id="review-scope-note" class="help"></p>
          </div>
          <button class="button primary full" type="submit">${icon("eye")} Jalankan Review</button>
          ${button("review-fix", "Jalankan dengan koreksi", "check", "small")}
          <div id="review-status" class="help" role="status"></div>
          <div id="review-error" role="alert"></div>
        </form>
      </section>
      <div id="review-report" class="stack">
        <div class="panel panel-body"><p class="help">Belum ada hasil pemeriksaan.</p></div>
      </div>
    </div>`;
  const form = $("#review-form", root), menu = $("#review-scope", root);
  const video = $("#review-video", root), fixButton = $("#review-fix", root);
  const status = $("#review-status", root), error = $("#review-error", root);
  const target = $("#review-report", root);
  function updateControls() {
    const rendered = menu.value === "video";
    $("#review-scene-fields", root).hidden = rendered;
    $("#review-video-fields", root).hidden = !rendered;
    fixButton.hidden = rendered;
    for (const control of [menu, video, $("#review-level", root), $("#review-sheet", root), fixButton])
      control.disabled = busy;
    form.querySelector("button[type=submit]").disabled = busy || (rendered && !video.value);
    $("#review-scope-note", root).textContent = menu.value === "film"
      ? `Memeriksa versi tersimpan · ${filmName || ""}`
      : "Memeriksa kondisi adegan saat ini.";
  }
  menu.onchange = () => { scopeChanged = true; updateControls(); };
  video.onchange = updateControls;

  scene(true).then(info => {
    filmName = info.film?.name || null;
    menu.querySelector('[value="film"]').disabled = !filmName;
    if (!busy && !scopeChanged && filmName && !preferredVideo) menu.value = "film";
    updateControls();
  }).catch(error => {
    if (!busy && menu.value === "scene") status.textContent = error.message;
  });
  request("/api/gallery").then(({ files }) => {
    const entries = files.filter(f => f.extension === ".mp4" && f.path.startsWith("renders/"));
    video.replaceChildren(...(entries.length ? [new Option("Pilih MP4…", ""), ...entries.map(
      f => new Option(f.path.slice("renders/".length), f.path.slice("renders/".length)))]
      : [new Option("Belum ada video di galeri", "")]));
    if (preferredVideo && !busy && !scopeChanged && entries.some(f => f.path === "renders/" + preferredVideo)) {
      video.value = preferredVideo;
      menu.value = "video";
    }
    updateControls();
  }).catch(error => {
    video.replaceChildren(new Option("Daftar video gagal dimuat", ""));
    if (menu.value === "video") status.textContent = error.message;
  });

  async function inspect(fix) {
    if (busy) return;
    const scope = menu.value;
    if (scope === "video" && !video.value) return;
    busy = true;
    scopeChanged = true;
    updateControls();
    try {
      await action(null, async () => {
        if (fix && !await confirm("Jalankan satu putaran koreksi?",
          scope === "film"
            ? "Koreksi otomatis diterapkan dan disimpan ke file adegan film."
            : "Koreksi otomatis diterapkan ke adegan aktif.",
          "Jalankan dengan koreksi")) return;
        error.innerHTML = "";
        status.textContent = "Memeriksa hasil…";
        const args = scope === "video" ? { path: video.value } : {
          level: $("#review-level", root).value, fix, sheet: $("#review-sheet", root).checked,
          ...(scope === "film" ? { name: filmName } : {}),
        };
        const result = await run("review_" + scope, args, {
          onUpdate: (job) => {
            if (job.status === "queued") status.textContent = "Menunggu giliran…";
            if (job.status === "running") status.textContent = "Memeriksa hasil…";
          },
        });
        renderReport(target, result);
        status.textContent = "Review selesai.";
        if (fix) state.scene = state.shots = null;
      }, error);
    } finally {
      if (error.textContent) status.textContent = "";
      busy = false;
      updateControls();
    }
  }
  form.onsubmit = (event) => { event.preventDefault(); inspect(false); };
  fixButton.onclick = () => inspect(true);
  updateControls();
}
