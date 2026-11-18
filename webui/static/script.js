import { lookPicker, mountLookPicker, lookLabel } from "./looks.js";
import { screenRoot } from "./ui.js";
import { mountVoices, needsSpeechConsent, authorizeSpeech } from "./voices.js";
import { run, state, scene } from "./api.js";
import { panel as directorPanel, mountDirector } from "./director.js";
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
  json,
  warnings,
  errorHTML,
  action,
  filmstrip,
  seconds,
  toast,
} from "./ui.js";
export const TEMPLATE = `JUDUL: Sebuah Awal
LOKASI: park

ANA (perempuan, 28, rambut bob):
Halo, Budi! Siap untuk ide baru?

BUDI (laki-laki, 30, rambut pendek):
Tentu. Mari kita mulai!

[Ana melambai]`;
// Speech belongs on the same line as its speaker in char3d's text grammar.
const example = TEMPLATE.replace(/:\n(?=[^\n\[])/g, ": ");
const locations = [
  ["", "Ikuti naskah"],
  ["podcast_studio", "Studio podcast"],
  ["office", "Kantor"],
  ["classroom", "Ruang kelas"],
  ["stage", "Panggung"],
  ["living_room", "Ruang keluarga"],
  ["news_desk", "Studio berita"],
  ["city_street", "Jalan kota"],
  ["park", "Taman"],
  ["cafe_terrace", "Teras kafe"],
  ["beach", "Pantai"],
];
export function mount(root) {
  root = screenRoot(root);
  root.innerHTML =
    head(
      "DARI IMAJINASI KE LAYAR",
      "Setiap adegan dimulai dari cerita.",
      "Tulis percakapan. Atur suasana. Hidupkan dunia Anda.",
      `<span class="chip">${icon("script")} Naskah → Adegan</span>`,
    ) +
    directorPanel() + `
 <div class="step-line" id="script-steps"><span class="step active" data-step="1"><b>01</b> Tulis cerita <span class="step-arrow">→</span></span><span class="step" data-step="2"><b>02</b> Periksa rencana <span class="step-arrow">→</span></span><span class="step" data-step="3"><b>03</b> Hidupkan adegan</span></div>
 <div class="script-layout"><div><section class="panel"><div class="editor-bar"><div class="editor-tab">${icon("script")} naskah.char3d <span class="dot"></span></div>${button("example", "Pakai contoh", "", "small subtle")}</div><div class="script-editor"><div class="line-numbers" aria-hidden="true">01<br>02<br>03<br>04<br>05<br>06<br>07<br>08<br>09<br>10</div><textarea id="script-text" class="screenplay" aria-label="Editor naskah" spellcheck="false" wrap="soft"></textarea></div><div class="editor-footer"><span>BAHASA NASKAH · INDONESIA / ENGLISH</span><span id="script-count"></span></div><div class="editor-actions"><span class="help">Periksa rencana sebelum<br>membangun adegan Anda.</span><div class="row">${button("plan", "Lihat rencana", "eye", "subtle")}${button("build", "Bangun adegan", "spark", "primary")}</div></div></section>
 <section class="panel voice-section" id="script-voices" aria-label="Suara dialog"></section>
 <div class="script-hint">${icon("bulb")}<div><h3>Sutradara ada di tangan Anda.</h3><p>Tulis <code>[Budi duduk di kursi]</code> untuk aksi, atau <code>[Ana melambai]</code> untuk gestur. Deklarasikan karakter dengan <code>NAMA (deskripsi): dialog</code>.</p><details><summary>Panduan format naskah</summary><p><code>JUDUL:</code> memberi nama adegan. <code>LOKASI: park</code> memilih set. <code>CUACA: hujan</code> menambah cuaca. <code>SUASANA: senja</code> memilih tampilan sinematik. Satu dialog per baris; maksimal 4 karakter. Suara otomatis memakai Piper offline. Pilih mesin dan suara tiap karakter di bagian Suara. Gunakan <code>suara: edge:id-ID-GadisNeural</code> atau <code>suara berat</code> di deskripsi karakter; layanan online meminta persetujuan.</p></details></div></div></div>
 <aside class="panel script-settings"><div class="panel-head"><h2>${icon("settings")} Pengaturan adegan</h2><span class="mono muted">SCENE</span></div><div class="settings-body"><div class="form-grid">
 ${field(
   "Bahasa",
   select(
     "script-language",
     [
       ["id", "Indonesia"],
       ["en", "English"],
       ["ms", "Melayu"],
       ["auto", "Otomatis"],
     ],
     "id",
   ),
 )}
 ${field("Lokasi", select("script-location", locations))}
 ${field(
   "Pencahayaan",
   select("script-lighting", [
     ["studio", "Studio lembut"],
     ["sunset", "Senja hangat"],
     ["noon", "Siang hari"],
     ["overcast", "Mendung"],
     ["night", "Malam"],
     ["neon", "Neon"],
     ["horror", "Dramatis"],
   ]),
 )}
 ${field(
   "Cuaca",
   select("script-weather", [
     ["", "Ikuti naskah"],
     ["clear", "Cerah"],
     ["rain", "Hujan"],
     ["snow", "Salju"],
     ["fog", "Kabut"],
     ["wind", "Berangin"],
   ]),
 )}
 ${field(
   "Kamera",
   select("script-camera", [
     ["mixed", "Campuran · sinematik"],
     ["singles", "Per pembicara"],
     ["two_shot", "Dua karakter"],
     ["none", "Atur sendiri"],
   ]),
   "span-2",
 )}
 ${field("Seed variasi", input("script-seed", 0, "number", 'min="0" step="1"'), "span-2")}
 <div class="span-2 look-field"><label class="field-label">Suasana</label>${lookPicker("script-look", true, localStorage.getItem("char3d-script-look") || "")}</div>
 </div><div class="divider"></div><div class="row between">${check("script-subtitles", "Subtitle", true)}${check("script-sound", "Efek suara", true)}</div></div><div class="settings-footer">${icon("shield")} Piper lokal · suara online dengan persetujuan</div></aside></div>
 <section class="result-section"><div class="section-label"><h2>Ruang pratinjau</h2><span id="script-stage">IDE → RENCANA → ADEGAN</span></div><div id="script-result"></div></section>`;
  const looks = mountLookPicker(root, "script-look", (value) => localStorage.setItem("char3d-script-look", value));
  const editor = $("#script-text", root);
  const numbers = $(".line-numbers", root);
  editor.value = localStorage.getItem("char3d-script") || example;
  // Soft-wrapped editor: a hidden mirror measures each logical line so its
  // number stays aligned with the first visual row of that line.
  const mirror = document.createElement("div");
  mirror.className = "screenplay-mirror";
  mirror.setAttribute("aria-hidden", "true");
  editor.parentElement.appendChild(mirror);
  const syncScroll = () => {
    if (numbers.firstElementChild)
      numbers.firstElementChild.style.transform = `translateY(${-editor.scrollTop}px)`;
  };
  const renumber = () => {
    const cs = getComputedStyle(editor);
    Object.assign(mirror.style, {
      font: cs.font,
      letterSpacing: cs.letterSpacing,
      tabSize: cs.tabSize,
      paddingLeft: cs.paddingLeft,
      paddingRight: cs.paddingRight,
      width: editor.clientWidth + "px",
    });
    const rows = editor.value.split("\n");
    mirror.replaceChildren(
      ...rows.map((text) => {
        const row = document.createElement("div");
        row.textContent = text || " ";
        return row;
      }),
    );
    const lineHeight = parseFloat(cs.lineHeight) || 26;
    const heights = [...mirror.children].map((row) => row.offsetHeight || lineHeight);
    numbers.innerHTML = `<div>${Array.from(
      { length: Math.max(10, rows.length) },
      (_, i) =>
        `<span style="display:block;height:${heights[i] ?? lineHeight}px">${String(i + 1).padStart(2, "0")}</span>`,
    ).join("")}</div>`;
    syncScroll();
  };
  const update = () => {
    $("#script-count", root).textContent =
      `${editor.value.length} karakter · tersimpan di browser`;
    localStorage.setItem("char3d-script", editor.value);
    renumber();
  };
  editor.addEventListener("scroll", syncScroll);
  const resize = new ResizeObserver(() => {
    numbers.style.height = editor.clientHeight + "px";
    renumber();
  });
  resize.observe(editor);
  editor.addEventListener("input", update);
  update();
  $("#example", root).onclick = () => {
    editor.value = example;
    update();
  };
  const target = $("#script-result", root);
  setStep(root, state.latestScript ? (state.latestScript.built ? 3 : 2) : 1);
  if (state.latestScript)
    showResult(target, state.latestScript.data, state.latestScript.built);
  else
    target.innerHTML = `<div class="panel result-idle"><div><span class="eyebrow">DUNIA ANDA, SEBENTAR LAGI</span><h3 style="margin-top:9px">Sebuah cerita, banyak kemungkinan.</h3><p>Karakter, alur, dan shot Anda akan muncul di sini setelah rencana siap.</p></div><div class="storyboard" aria-hidden="true"><div class="story-frame"><i class="frame-corner"></i></div><div class="story-frame"><i class="frame-corner"></i></div><div class="story-frame"><i class="frame-corner"></i></div></div></div>`;
  const args = (build) => {
    let script = editor.value.trim();
    if (!script) throw new Error("Tulis naskah terlebih dahulu.");
    const weather = $("#script-weather", root).value;
    if (weather) {
      script = script.replace(/^(CUACA|WEATHER):.*$/gim, "");
      script = `CUACA: ${weather}\n${script}`;
    }
    return {
      script,
      build,
      language: $("#script-language", root).value,
      environment: $("#script-location", root).value || null,
      lighting: $("#script-lighting", root).value,
      look: looks.dataset.value || null,
      camera: $("#script-camera", root).value,
      seed: Number($("#script-seed", root).value),
      subtitles: $("#script-subtitles", root).checked,
      sound: $("#script-sound", root).checked,
      ...voiceControls.parameters(),
    };
  };
  const voiceControls = mountVoices($("#script-voices", root), () => args(false));
  const resetDraft = () => {
    state.latestScript = null;
    state.plan = null;
    setStep(root, 1);
    target.innerHTML = '<div class="notice">Naskah berubah. Klik <strong>Lihat rencana</strong> untuk memeriksa sebelum membangun.</div>';
  };
  const settingIds = ["script-language", "script-location", "script-lighting", "script-weather", "script-camera", "script-seed"];
  const disposeDirector = mountDirector(root, (draft) => {
    if (editor.value === draft.script) return;
    const previous = { script: editor.value, look: looks.dataset.value,
      settings: Object.fromEntries(settingIds.map(id => [id, $(`#${id}`, root).value])),
      voices: JSON.parse(JSON.stringify(state.voiceSettings?.overrides || {})) };
    localStorage.setItem("char3d-director-previous", JSON.stringify(previous));
    editor.value = draft.script;
    $("#script-language", root).value = draft.build_options.language;
    $("#script-location", root).value = "";
    $("#script-weather", root).value = "";
    $("#script-lighting", root).value = draft.build_options.lighting;
    $("#script-camera", root).value = draft.build_options.camera;
    $("#script-seed", root).value = draft.build_options.seed;
    const follow = looks.querySelector('input[value=""]');
    follow.checked = true;
    follow.dispatchEvent(new Event("change", { bubbles: true }));
    state.voiceSettings.overrides = {};
    voiceControls.updatePlan({ plan: draft.plan });
    update(); resetDraft();
  }, () => {
    const previous = JSON.parse(localStorage.getItem("char3d-director-previous") || "null");
    if (!previous) return;
    editor.value = previous.script;
    for (const [id, value] of Object.entries(previous.settings)) $(`#${id}`, root).value = value;
    const choice = [...looks.querySelectorAll("input")].find(el => el.value === previous.look);
    if (choice) { choice.checked = true; choice.dispatchEvent(new Event("change", { bubbles: true })); }
    state.voiceSettings.overrides = previous.voices;
    voiceControls.resetPlan();
    localStorage.removeItem("char3d-director-previous");
    update(); resetDraft();
  });
  const perform = async (build) => {
    const parameters = args(build);
    const online = needsSpeechConsent("script_to_scene", parameters);
    if (online && !await authorizeSpeech("script_to_scene", parameters)) return;
    await scene(true);
    target.innerHTML =
      '<div class="panel panel-body"><div class="row">' +
      icon("clock") +
      '<strong id="build-status">Menyiapkan ' +
      (build ? "adegan" : "rencana") +
      '…</strong></div><p class="help" style="margin:10px 0 15px">Anda tetap dapat menjelajahi studio. Hasil akan muncul saat selesai.</p><div class="skeleton"></div></div>';
    const section = target.closest(".result-section");
    if (section && section.getBoundingClientRect().top > innerHeight - 160)
      section.scrollIntoView({
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "start",
      });
    const result = await run("script_to_scene", parameters, {
      confirmExternal: online,
      onUpdate: (job) => {
        const el = $("#build-status", target);
        if (el)
          el.textContent =
            (job.status === "queued"
              ? `Dalam antrean · posisi ${job.queue_position}`
              : build
                ? "Membangun karakter, gerak, dan kamera"
                : "Membaca alur naskah") + ` · ${seconds(job.elapsed_s)}`;
      },
    });
    if (build) {
      state.build = result.data;
      state.scene = null;
      state.shots = null;
    } else state.plan = result.data;
    voiceControls.updatePlan(result.data);
    showResult(target, result.data, build);
    setStep(root, build ? 3 : 2);
    if (build) {
      toast("Adegan siap. Menyiapkan pratinjau…");
      try {
        const frames = result.data.frames;
        const r = await run("render_frames", {
          frames: [frames?.[0] || 1],
          camera: "scene",
          engine_name: "workbench",
          size: 512,
        });
        state.previews = r.images;
        const el = $("#build-previews", target);
        if (el) el.innerHTML = filmstrip(r.images, ["Kamera adegan · draft"]);
      } catch (e) {
        const el = $("#build-previews", target);
        if (el) el.innerHTML = errorHTML(e);
      }
    }
  };
  for (const [id, build] of [
    ["plan", false],
    ["build", true],
  ])
    $(`#${id}`, root).onclick = () =>
      action($(`#${id}`, root), () => perform(build), target);
  return () => { resize.disconnect(); voiceControls.dispose(); disposeDirector(); };
}
function setStep(root, current) {
  for (const step of root.querySelectorAll("#script-steps .step")) {
    const n = Number(step.dataset.step);
    step.classList.toggle("active", n === current);
    step.classList.toggle("done", n < current);
    if (n === current) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  }
}
export function refreshResult(target) {
  if (target && state.latestScript)
    showResult(target, state.latestScript.data, state.latestScript.built);
}
function showResult(target, data, built) {
  const plan = data.plan || data;
  const frames = data.frames || plan.estimated_frames || [1, 1];
  const fps = plan.fps || 24;
  target.innerHTML = `<div class="panel"><div class="panel-head"><h2>${icon(built ? "check" : "eye")} ${esc(plan.title || plan.name || "Rencana adegan")}</h2><span class="chip ${built ? "green" : "warm"}">${built ? "Adegan terbangun" : "Rencana siap"}</span></div><div class="stats"><div class="stat"><strong>${plan.characters?.length || 0}</strong><span>KARAKTER</span></div><div class="stat"><strong>${plan.beats?.length || 0}</strong><span>BEAT CERITA</span></div><div class="stat"><strong>${Number(data.duration_s || (frames[1] - frames[0] + 1) / fps).toFixed(1)}<small class="muted" style="font-size:11px"> dtk</small></strong><span>${built ? "DURASI" : "ESTIMASI DURASI"} · ${fps} FPS</span></div><div class="stat"><strong>${built ? data.shots?.length || 0 : "—"}</strong><span>SHOT KAMERA</span></div></div><div class="panel-body">${plan.look ? `<p class="help">Suasana: ${esc(lookLabel(plan.look.preset))}</p>` : plan.recommended_look ? `<p class="help">Saran suasana: ${esc(lookLabel(plan.recommended_look))} · pilih di pengaturan untuk mencoba.</p>` : ""}<div class="cast-grid">${(plan.characters || []).map((c) => `<div class="cast-card"><div class="avatar">${esc(c.id?.slice(0, 1) || "?")}</div><div><h3>${esc(c.id)}</h3><p>${esc(c.age || 25)} tahun · ${c.gender === 0 ? "Perempuan" : c.gender === 1 ? "Laki-laki" : "Karakter"} · ${esc(c.hair || "tanpa rambut")}</p></div></div>`).join("")}</div><div class="beats">${(
    plan.beats || []
  )
    .map((beat, i) => {
      const f = beat.frames || beat.estimated_frames || [];
      return `<div class="beat"><span class="beat-number">${String(i + 1).padStart(2, "0")}</span><div><small>${esc(beat.say || beat.who || "ADEGAN")} ${beat.do ? "· " + esc(beat.do) : ""}</small><p>${esc(beat.text || beat.title || `${beat.do || "Jeda"} ${beat.on || beat.prop || beat.seconds || ""}`)}</p></div><span class="beat-time">${f.join(" – ")} f<br>${((f[1] - f[0] + 1) / fps || 0).toFixed(1)} dtk</span></div>`;
    })
    .join(
      "",
    )}</div><div class="stack" style="gap:10px;margin-top:16px">${warnings(data)}</div>${built ? `<div class="row" style="margin-top:20px"><a class="button" href="#adegan">${icon("scene")} Periksa adegan</a><a class="button primary" href="#render">${icon("render")} Render draft</a></div><div id="build-previews">${state.previews.length ? filmstrip(state.previews) : '<p class="help" style="margin-top:14px">Menunggu pratinjau kamera…</p>'}</div>` : ""}${json({ frames, timings: data.timings, ...(built ? { shots: data.shots, characters: data.characters } : { plan }) })}</div></div>`;
}
