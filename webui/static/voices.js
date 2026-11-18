import { run, state } from "./api.js";
import { $, $$, esc, icon, select, field, button, confirm, action, errorHTML } from "./ui.js";

export function needsSpeechConsent(tool, args) {
  if (!["text_to_speech", "script_to_scene", "dialog"].includes(tool)) return false;
  if (tool !== "text_to_speech" && (args.voice === false || args.build === false || (tool === "dialog" && !args.voice))) return false;
  const choices = [args.tts_engine || args.engine || "piper"];
  if (typeof args.voice === "string") choices.push(args.voice.split(":")[0]);
  for (const char of args.script?.characters || []) if (char.voice) choices.push(char.voice.split(":")[0]);
  for (const profile of Object.values(args.voices || {})) choices.push(typeof profile === "string" ? profile.split(":")[0] : profile.voice?.split(":")[0] || profile.engine);
  if (typeof args.script === "string" && /(?:suara|voice)\s*:\s*(edge|chatterbox):/i.test(args.script)) return true;
  return choices.some((name) => ["edge", "chatterbox"].includes(name));
}

export async function authorizeSpeech(tool, args) {
  return confirm(
    "Gunakan suara online?",
    "Teks dialog dikirim ke <strong>Microsoft</strong> untuk Edge atau <strong>Hugging Face / ResembleAI</strong> untuk Chatterbox. Layanan pihak ketiga dapat menyimpan data. Edge memakai API tidak resmi; Chatterbox memiliki kuota. Lanjutkan hanya untuk teks yang Anda izinkan dibagikan.",
    "Setuju & kirim teks",
  );
}

export function mountVoices(root, getScriptArgs) {
  const settings = state.voiceSettings ||= { engine: "piper", overrides: {} };
  let catalog = { engines: {}, voices: [] }, current = null, disposed = false, revision = 0;
  root.innerHTML = `<div class="panel-head"><div><h2>${icon("audio")} Suara</h2><p class="help">Pilih suara yang menghidupkan cerita.</p></div><span class="chip green" id="voice-mode">OFFLINE</span></div>
    <div class="panel-body"><div class="voice-engine-row">${field("Mesin suara", select("tts-engine", [
      ["piper", "Piper · offline"], ["edge", "Edge · online"], ["f5", "F5 · jika terpasang"],
      ["chatterbox", "Chatterbox · online"], ["none", "Tanpa suara"],
    ], settings.engine))}<p class="help">Audio rekaman dalam naskah tetap dipakai.</p></div>
    <div class="voice-status" id="voice-status" role="status">Memeriksa suara terpasang…</div>
    <div class="voice-cast-head"><span class="eyebrow">SUARA PER KARAKTER</span><span class="help">Pitch & tempo dapat disesuaikan</span></div>
    <div id="voice-cast"><p class="voice-empty">Klik <strong>Lihat rencana</strong> untuk memilih suara setiap karakter.</p></div>
    <div id="voice-preview" aria-live="polite"></div></div>`;
  const mode = $("#tts-engine", root);
  const parameters = () => ({ voice: mode.value !== "none", tts_engine: mode.value === "none" ? "piper" : mode.value, voices: settings.overrides });
  const status = () => {
    const name = mode.value, engine = catalog.engines[name];
    const online = engine?.online;
    const badge = $("#voice-mode", root);
    badge.textContent = name === "none" ? "TEKS SAJA" : online ? "ONLINE" : "OFFLINE";
    badge.className = `chip ${online ? "warm" : "green"}`;
    const descriptions = {
      piper: "Lokal di perangkat Anda. Satu speaker Indonesia dengan variasi pitch dan tempo. Model news_tts: penggunaan pribadi karena lisensi dataset belum jelas.",
      edge: "Suara neural Ardi & Gadis. Teks dikirim ke Microsoft hanya setelah Anda setuju. API tidak resmi dapat berubah.",
      f5: "Kloning suara lokal. Perlu rekaman dan transkrip milik sendiri atau berizin. Bobot dasar untuk penggunaan nonkomersial.",
      chatterbox: "Hugging Face Space online, dengan kuota harian. Bahasa Indonesia belum tersedia; pilih Melayu secara eksplisit.",
      none: "Gerak mulut dari teks tanpa suara sintetis. Rekaman yang Anda tambahkan tetap diputar.",
    };
    $("#voice-status", root).innerHTML = `<div class="voice-status-title">${icon(online ? "shield" : "check")}<strong>${name === "none" ? "Suara sintetis dimatikan" : engine?.installed ? "Siap digunakan" : "Belum terpasang"}</strong>${online ? '<span class="mono">PERLU PERSETUJUAN</span>' : ""}</div><p>${esc(descriptions[name])}</p>${engine && !engine.installed ? `<code class="voice-install">${esc(engine.install_hint)}</code>` : ""}`;
  };
  const draw = () => {
    status();
    if (!current) return;
    const chars = current.plan?.characters || [];
    const lang = getScriptArgs().language;
    const entries = catalog.voices.filter(v => lang === "auto" || v.language.toLowerCase().replaceAll("_", "-").startsWith(lang));
    $("#voice-cast", root).innerHTML = `<div class="voice-cast-grid">${chars.map((char, i) => {
      const profile = current.voices?.[char.id] || {};
      const custom = settings.overrides[char.id] || {};
      const pitch = custom.pitch ?? profile.pitch ?? 0, rate = custom.rate ?? profile.rate ?? 1;
      const choices = [["", `Otomatis · ${profile.voice?.split(":")[0] || mode.value}`], ...entries.map(v => [v.id, `${v.name} · ${v.language}${v.installed ? "" : " · belum terpasang"}`])];
      if (profile.voice && !choices.some(v => v[0] === profile.voice)) choices.push([profile.voice, profile.voice]);
      return `<article class="voice-card" data-character="${esc(char.id)}"><div class="voice-card-title"><div class="avatar">${esc(char.id.slice(0, 1))}</div><div><h3>${esc(char.id)}</h3><p>${esc(char.age)} tahun · ${char.gender < .5 ? "Perempuan" : "Laki-laki"}</p></div>${button(`listen-${i}`, "Dengarkan", "play", "small subtle voice-listen")}</div>
        ${field("Pilihan suara", select(`cast-voice-${i}`, choices, custom.voice || ""))}
        <div class="voice-sliders"><label for="cast-pitch-${i}"><span>Pitch <output>${Number(pitch) > 0 ? "+" : ""}${Number(pitch).toFixed(1)} st</output></span><input id="cast-pitch-${i}" type="range" min="-12" max="12" step="0.1" value="${pitch}"></label><label for="cast-rate-${i}"><span>Tempo <output>${Number(rate).toFixed(2)}×</output></span><input id="cast-rate-${i}" type="range" min="0.5" max="2" step="0.01" value="${rate}"></label></div></article>`;
    }).join("")}</div>`;
    chars.forEach((char, i) => {
      const card = $$('[data-character]', root)[i];
      const picker = $(`#cast-voice-${i}`, root), pitch = $(`#cast-pitch-${i}`, root), rate = $(`#cast-rate-${i}`, root);
      const save = () => {
        settings.overrides[char.id] = { ...(picker.value ? { voice: picker.value } : {}), pitch: Number(pitch.value), rate: Number(rate.value) };
        pitch.previousElementSibling.querySelector("output").textContent = `${Number(pitch.value) > 0 ? "+" : ""}${Number(pitch.value).toFixed(1)} st`;
        rate.previousElementSibling.querySelector("output").textContent = `${Number(rate.value).toFixed(2)}×`;
      };
      picker.onchange = save;
      pitch.oninput = save;
      rate.oninput = save;
      card.querySelectorAll("input,select,button").forEach(el => el.disabled = mode.value === "none");
      $(`#listen-${i}`, root).onclick = () => action($(`#listen-${i}`, root), async () => {
        const selected = picker.value || current.voices?.[char.id]?.voice;
        const args = { text: current.plan.beats.find(b => b.say === char.id && b.text)?.text?.slice(0, 180) || "Halo, apa kabar?", voice: selected, engine: mode.value, language: lang === "auto" ? "id" : lang, pitch: Number(pitch.value), rate: Number(rate.value) };
        const online = needsSpeechConsent("text_to_speech", args);
        if (online && !await authorizeSpeech("text_to_speech", args)) return;
        const preview = $("#voice-preview", root);
        preview.innerHTML = '<p class="help">Menyiapkan contoh suara…</p>';
        const result = await run("text_to_speech", args, { confirmExternal: online });
        const url = "/api/files/imports/" + result.data.path.split("/").map(encodeURIComponent).join("/");
        preview.innerHTML = `<div class="voice-player"><div><strong>${esc(char.id)}</strong><span class="help">${esc(result.data.engine)} · ${result.data.duration_s.toFixed(1)} detik${result.data.cached ? " · dari cache" : ""}</span></div><audio controls autoplay src="${url}" aria-label="Contoh suara ${esc(char.id)}"></audio></div>`;
      }, $("#voice-preview", root));
    });
  };
  const updatePlan = (data) => {
    current = data;
    const valid = new Set(data.plan?.characters?.map(c => c.id));
    for (const id of Object.keys(settings.overrides)) if (!valid.has(id)) delete settings.overrides[id];
    draw();
  };
  mode.onchange = async () => {
    const request = ++revision;
    settings.engine = mode.value;
    status();
    try {
      if (mode.value === "edge") {
        const updated = await run("list_voices", { engine: "edge" });
        if (disposed || request !== revision) return;
        catalog.voices = [...catalog.voices.filter(v => !v.id.startsWith("edge:")), ...updated.data.voices];
      }
      if (current) {
        const r = await run("script_to_scene", { ...getScriptArgs(), ...parameters(), build: false });
        if (!disposed && request === revision) updatePlan(r.data);
      } else draw();
    } catch (e) { if (!disposed && request === revision) $("#voice-preview", root).innerHTML = errorHTML(e); }
  };
  run("list_voices").then(r => {
    if (disposed) return;
    catalog = r.data;
    if (state.latestScript) updatePlan(state.latestScript.data);
    else status();
  }).catch(e => { if (!disposed) $("#voice-status", root).innerHTML = errorHTML(e); });
  return { parameters, updatePlan, dispose: () => { disposed = true; root.querySelectorAll("audio").forEach(a => a.pause()); } };
}
