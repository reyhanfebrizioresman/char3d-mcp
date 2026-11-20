import { run } from "./api.js";
import { $, esc, field, select, input, button, action, confirm, toast, json } from "./ui.js";

export function otsForm() {
  return `
    <details class="panel-body shot-tools">
      <summary>Tambah shot dari balik bahu (OTS)</summary>
      <form id="ots-form" class="form-grid">
        ${field("Subjek yang terlihat", select("ots-subject", []))}
        ${field("Bahu di latar depan", select("ots-foreground", []))}
        ${field("Frame awal", input("ots-start", "", "number", 'min="0" step="1" required'))}
        ${field("Frame akhir", input("ots-end", "", "number", 'min="0" step="1" required'))}
        <button class="button span-2" type="submit" disabled>Tambah shot</button>
      </form>
      <div id="ots-result" role="status"></div>
    </details>`;
}

export function collisionPanel() {
  return `
    <section class="panel" aria-labelledby="collision-title">
      <div class="panel-head"><h2 id="collision-title">Collision karakter</h2></div>
      <form id="collision-form" class="panel-body stack">
        <div class="form-grid">
          ${field("Karakter", select("collision-character", [["", "Semua karakter terlihat"]]))}
          ${field("Bagian", select("collision-part", [
            ["all", "Semua bagian"], ["arms", "Lengan"], ["props", "Properti di tangan"],
            ["legs", "Kaki"], ["torso", "Torso"], ["clothes", "Pakaian"],
          ]))}
          ${field("Frame awal · opsional", input("collision-start", "", "number", 'min="0" step="1"'))}
          ${field("Frame akhir · opsional", input("collision-end", "", "number", 'min="0" step="1"'))}
        </div>
        <div class="row studio-actions">
          <button id="collision-check" class="button primary small" type="submit" disabled>Ukur penetrasi</button>
          ${button("collision-repair", "Terapkan koreksi", "", "small")}
        </div>
        <div id="collision-result" role="status"></div>
      </form>
    </section>`;
}

export function mountSceneTools(root, refresh) {
  const ots = $("#ots-form", root);
  const collision = $("#collision-form", root);
  const list = (id) => $("#" + id, root);
  const checkButton = list("collision-check");
  const repairButton = list("collision-repair");
  let rigs = [], busy = false;

  function refreshControls(info) {
    rigs = info.objects.filter(o => o.type === "ARMATURE" && o.visible !== false);
    const choices = rigs.map(o => [o.name, o.name]);
    for (const [id, options] of [
      ["ots-subject", choices], ["ots-foreground", choices],
      ["collision-character", [["", "Semua karakter terlihat"], ...choices]],
    ]) {
      const menu = list(id);
      const previous = menu.value;
      menu.replaceChildren(...options.map(([value, label]) => new Option(label, value)));
      if (options.some(([value]) => value === previous)) menu.value = previous;
      else if (id === "ots-foreground" && choices.length > 1) menu.selectedIndex = 1;
    }
    if (!list("ots-start").value) list("ots-start").value = info.frame_range[0];
    if (!list("ots-end").value) list("ots-end").value = info.frame_range[1];
    for (const [index, field] of ["collision-start", "collision-end"].entries())
      list(field).placeholder = String(info.frame_range[index]);
    ots.querySelector("button").disabled = rigs.length < 2;
    checkButton.disabled = repairButton.disabled = !rigs.length || busy;
  }

  ots.onsubmit = (event) => {
    event.preventDefault();
    const result = list("ots-result");
    action(ots.querySelector("button"), async () => {
      const subject = list("ots-subject").value, foreground = list("ots-foreground").value;
      const start_frame = Number(list("ots-start").value), end_frame = Number(list("ots-end").value);
      if (!subject || !foreground || subject === foreground) throw new Error("Pilih dua rig berbeda.");
      if (end_frame < start_frame) throw new Error("Frame akhir harus sama dengan atau setelah frame awal.");
      const { data } = await run("camera_shot", { shot: "over_shoulder", subject: [subject],
        foreground, start_frame, end_frame });
      result.innerHTML = `<p class="help">${esc(data.camera)} · frame ${start_frame}–${end_frame}</p>` +
        (data.occlusion?.warning ? `<p class="notice">${esc(data.occlusion.warning)}</p>` : "");
      await refresh();
      toast("Shot OTS ditambahkan.");
    }, result);
  };

  async function measure(reportOnly) {
    if (busy || !rigs.length || !collision.reportValidity()) return;
    busy = checkButton.disabled = repairButton.disabled = true;
    const result = list("collision-result");
    try {
      await action(null, async () => {
        const character = list("collision-character").value;
        const frameStart = list("collision-start").value, frameEnd = list("collision-end").value;
        const args = { report_only: reportOnly, parts: list("collision-part").value };
        if (character) args.characters = [character];
        if (frameStart) args.frame_start = Number(frameStart);
        if (frameEnd) args.frame_end = Number(frameEnd);
        if (frameStart && frameEnd && args.frame_end < args.frame_start)
          throw new Error("Frame akhir harus sama dengan atau setelah frame awal.");
        if (!reportOnly && !await confirm("Terapkan koreksi collision?",
          "Koreksi mengubah keyframe pada rig dan rentang yang dipilih.", "Terapkan koreksi")) return;
        result.textContent = reportOnly ? "Mengukur collision…" : "Menerapkan koreksi…";
        const { data } = await run("resolve_collisions", args);
        const cm = value => `${(Number(value) * 100).toLocaleString("id-ID", { maximumFractionDigits: 2 })} cm`;
        const skips = Object.entries(data.characters || {}).flatMap(([name, rig]) =>
          (rig.skipped || []).map(item => `<li>${esc(name)} · ${esc(item.part)} · ${item.count} frame<br><span class="muted">${esc(item.reason)}</span></li>`));
        result.innerHTML = `<div class="notice">Frame ${data.frames.join("–")} · penetrasi maksimum
          <strong>${cm(data.max_penetration_before_m)}${reportOnly ? "" : ` → ${cm(data.max_penetration_after_m)}`}</strong>
          ${reportOnly ? "" : ` · ${data.frames_corrected} frame dikoreksi`}</div>
          ${skips.length ? `<details><summary>Konflik yang dilewati</summary><ul class="feature-list">${skips.join("")}</ul></details>` : ""}
          ${json(data)}`;
        if (!reportOnly) await refresh();
      }, result);
    } finally {
      busy = false;
      checkButton.disabled = repairButton.disabled = !rigs.length;
    }
  }
  collision.onsubmit = (event) => { event.preventDefault(); measure(true); };
  repairButton.disabled = true;
  repairButton.onclick = () => measure(false);
  return refreshControls;
}
