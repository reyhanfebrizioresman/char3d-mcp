import { run, state } from "./api.js";
import { $, $$, esc, icon, select, field, button, confirm, warnings, errorHTML, seconds, toast } from "./ui.js";
import { LOOKS } from "./looks.js";

const examples = [
  ["Reuni saat senja", "Dua sahabat bertemu lagi di taman saat senja setelah 10 tahun, haru."],
  ["Obrolan podcast", "Wawancara podcast dua rekan tentang berani memulai lagi, hangat dan santai."],
  ["Komedi kecil", "Tiga rekan kerja di kantor, salah jadwal rapat, komedi ringan."],
];

export function panel() {
  return `<section class="panel director-panel" id="director" aria-labelledby="director-title">
    <div class="director-heading"><div class="director-symbol" aria-hidden="true">${icon("spark")}</div><div><span class="eyebrow">DARI SATU IDE</span><h2 id="director-title">Sutradara AI</h2><p>Bayangkan ceritanya. Temukan arah visual dan naskah pertamanya.</p></div><span class="chip director-draft-tag">DRAF KREATIF</span></div>
    <div class="director-body"><label for="director-idea" class="field-label">Apa yang ingin Anda ceritakan?</label><textarea id="director-idea" maxlength="8000" spellcheck="false" placeholder="Dua sahabat bertemu lagi di taman saat senja setelah 10 tahun, haru…" aria-describedby="director-idea-help"></textarea>
    <div class="director-examples"><span id="director-idea-help">Coba sebuah ide</span>${examples.map(([title], i) => `<button class="director-example" data-idea="${i}" type="button">${esc(title)} ${icon("arrow")}</button>`).join("")}</div>
    <details class="director-options"><summary>Atur arah cerita <span>Durasi, tokoh, genre & suasana · opsional</span></summary><div class="director-options-grid">
      ${field("Durasi target", select("director-duration", [["30", "Otomatis · ±30 detik"], ["10", "±10 detik"], ["15", "±15 detik"], ["45", "±45 detik"], ["60", "±60 detik"], ["90", "±90 detik"]]))}
      ${field("Jumlah tokoh", select("director-cast", [["", "Otomatis"], ["1", "1 tokoh"], ["2", "2 tokoh"], ["3", "3 tokoh"], ["4", "4 tokoh"]]))}
      ${field("Gaya / genre", select("director-style", [["", "Otomatis"], ["reunion", "Reuni · haru"], ["comedy", "Komedi ringan"], ["confession", "Pengakuan · romantis"], ["argument", "Konflik"], ["interview", "Wawancara / podcast"], ["lesson", "Pelajaran"], ["sales", "Presentasi produk"], ["celebration", "Perayaan"], ["farewell", "Perpisahan"]]))}
      ${field("Suasana / look", select("director-look", [["", "Otomatis"], ...LOOKS.map(([k, label]) => [k, label])]))}
      ${field("Lokasi", select("director-location", [["", "Otomatis"], ["park", "Taman"], ["beach", "Pantai"], ["cafe_terrace", "Teras kafe"], ["city_street", "Jalan kota"], ["podcast_studio", "Studio podcast"], ["living_room", "Ruang keluarga"], ["office", "Kantor"], ["classroom", "Ruang kelas"], ["stage", "Panggung"], ["news_desk", "Studio berita"]]))}
    </div></details>
    <div class="director-controls"><div class="director-generator">${field("Generator", select("director-generator", [["offline", "Offline · gratis"], ["claude_cli", "Claude langganan · via Claude Code"], ["claude", "Claude API · berbayar"], ["auto", "Otomatis · pilih layanan tersedia"]]))}<p id="director-status" class="help" role="status">Memeriksa generator…</p></div>${button("director-generate", "Kembangkan ide", "spark", "primary")}</div>
    <div id="director-progress" role="status" aria-live="polite" hidden></div><div id="director-error" role="alert"></div>
    </div><div id="director-result" hidden></div>
    <div class="director-restore" id="director-restore" hidden><span>${icon("script")} Naskah sebelumnya tetap tersimpan.</span>${button("director-undo", "Kembalikan naskah sebelumnya", "refresh", "small subtle")}</div>
  </section>`;
}

// Small safe Markdown subset for our text treatment. Raw HTML/links never execute.
export function treatment(text) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  return text.split(/\n\s*\n/).map(block => {
    if (/^#{1,3} /.test(block)) {
      const [line, ...rest] = block.split("\n");
      const level = Math.min(4, line.match(/^#+/)[0].length + 1);
      return `<h${level}>${inline(line.replace(/^#+ /, ""))}</h${level}>${rest.length ? `<p>${inline(rest.join(" "))}</p>` : ""}`;
    }
    if (/^- /.test(block)) return `<ul>${block.split("\n").map(line => `<li>${inline(line.replace(/^- /, ""))}</li>`).join("")}</ul>`;
    return `<p>${inline(block).replaceAll("\n", "<br>")}</p>`;
  }).join("");
}

export function mountDirector(root, apply, restore) {
  let catalog = null, disposed = false, busy = false;
  let current = state.latestDirector || null;
  let tab = "brief";
  const idea = $("#director-idea", root), generator = $("#director-generator", root);
  idea.value = localStorage.getItem("char3d-director-idea") || "";
  idea.oninput = () => localStorage.setItem("char3d-director-idea", idea.value);
  $$("[data-idea]", root).forEach(el => el.onclick = () => {
    idea.value = examples[Number(el.dataset.idea)][1];
    idea.dispatchEvent(new Event("input"));
    idea.focus();
  });
  const restoreRow = $("#director-restore", root);
  restoreRow.hidden = !localStorage.getItem("char3d-director-previous");
  $("#director-undo", root).onclick = () => {
    restore();
    restoreRow.hidden = true;
    toast("Naskah sebelumnya dipulihkan.");
  };
  const status = () => {
    const mode = generator.value, entry = catalog?.generators?.[mode];
    $("#director-status", root).textContent = mode === "offline" ? "Lokal, tanpa mengirim ide. Variasi mengikuti seed adegan." :
      mode === "auto" ? "Dengan persetujuan: Claude Code → API → offline. Tidak pernah pindah otomatis ke layanan berbayar setelah gagal." :
      !catalog ? "Memeriksa ketersediaan…" : !entry?.available ? (mode === "claude" ? "Belum dikonfigurasi · tambahkan key di ~/.config/char3d/env." : "CLI belum ditemukan · atur CHAR3D_CLAUDE_BIN.") :
      mode === "claude_cli" ? "CLI tersedia · login diperiksa saat pertama dipakai · memakai kuota langganan." : "API dikonfigurasi · biasanya ±$0.05–$0.25 per draf.";
  };
  status();
  generator.onchange = status;
  const draw = () => {
    if (!current) return;
    const box = $("#director-result", root);
    box.hidden = false;
    const source = current.generator === "offline" ? "Offline · gratis" : current.generator === "claude_cli" ? "Claude langganan" : "Claude API";
    box.innerHTML = `<div class="director-result-bar"><div role="tablist" aria-label="Hasil sutradara" class="director-tabs"><button id="director-tab-brief" type="button" role="tab" aria-controls="director-content" aria-selected="${tab === "brief"}" tabindex="${tab === "brief" ? 0 : -1}" data-tab="brief">Prompt sutradara</button><button id="director-tab-script" type="button" role="tab" aria-controls="director-content" aria-selected="${tab === "script"}" tabindex="${tab === "script" ? 0 : -1}" data-tab="script">Naskah char3d</button></div>${button("director-copy", "Salin", "copy", "small subtle")}</div>
      <div id="director-content" role="tabpanel" tabindex="0" aria-labelledby="director-tab-${tab}" class="director-content ${tab === "brief" ? "director-treatment" : "director-screenplay"}">${tab === "brief" ? treatment(current.brief) : `<pre>${esc(current.script)}</pre>`}</div>
      <div class="director-result-footer"><div class="row"><span class="chip green">${esc(source)}</span><span class="help">${current.plan?.characters?.length || 0} tokoh · ${esc(current.plan?.environment || "")} ${current.model ? `· ${esc(current.model)}` : ""}</span></div>${button("director-use", "Pakai naskah ini", "arrow", "primary")}</div>
      <div class="director-notes">${current.cost_usd_estimate != null ? `<p>Estimasi biaya API: <strong>$${Number(current.cost_usd_estimate).toFixed(4)}</strong> · termasuk perbaikan bila ada.</p>` : ""}${current.billing_note ? `<p>${esc(current.billing_note)}</p>` : ""}${current.usage ? `<details><summary>Pemakaian token & biaya</summary><p>${Object.entries(current.usage).map(([k,v]) => `${esc(k)}: ${Number(v).toLocaleString("id-ID")}`).join(" · ")}</p>${current.cost_basis ? `<p>${esc(current.cost_basis)}</p>` : ""}</details>` : ""}<details><summary>Catatan draf · ${current.warnings?.length || 0}</summary><div class="stack">${warnings(current)}</div></details>${current.requested_generator && current.generator !== current.requested_generator ? `<div class="notice">${esc(current.fallback_reason || "Layanan online gagal.")} Hasil ini dibuat offline.</div>` : ""}</div>`;
    $$("[data-tab]", box).forEach(el => {
      el.onclick = () => { tab = el.dataset.tab; draw(); $(`#director-tab-${tab}`, root).focus(); };
      el.onkeydown = event => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          tab = event.key === "Home" ? "brief" : event.key === "End" ? "script" : tab === "brief" ? "script" : "brief";
          draw(); $(`#director-tab-${tab}`, root).focus();
        }
      };
    });
    $("#director-copy", root).onclick = async () => {
      try { await navigator.clipboard.writeText(current[tab]); toast("Teks disalin."); }
      catch { toast("Tidak dapat menyalin. Pilih teks di pratinjau lalu salin.", "error"); }
    };
    $("#director-use", root).onclick = () => {
      apply(current);
      restoreRow.hidden = false;
      toast("Naskah dimuat. Periksa rencana sebelum membangun.");
      $("#script-text", root).focus();
    };
  };
  draw();
  run("director_status").then(r => { catalog = r.data; if (!disposed) status(); }).catch(() => {
    if (!disposed) $("#director-status", root).textContent = "Status online belum terbaca. Offline tetap dapat digunakan.";
  });
  const generateButton = $("#director-generate", root);
  generateButton.onclick = async () => {
    if (busy) return;
    const text = idea.value.trim();
    if (!text) { idea.focus(); toast("Tulis satu ide terlebih dahulu.", "error"); return; }
    let mode = generator.value;
    if (mode === "auto") mode = catalog?.auto_with_consent || "offline";
    const online = mode !== "offline";
    if (online && !await confirm("Kirim ide ke Anthropic?", `<p>Ide (${text.length} karakter) dan opsi cerita akan dikirim ke <strong>Anthropic</strong> untuk membuat draf. Lanjutkan hanya untuk teks yang Anda izinkan dibagikan.</p><p class="notice" style="margin-top:14px">${mode === "claude_cli" ? "<strong>Claude langganan:</strong> memakai kuota langganan lewat Claude Code, tanpa tagihan API per panggilan dari char3d. Login mungkin diperlukan." : "<strong>Claude API · berbayar:</strong> biasanya sekitar $0.05–$0.25 per draf. Maksimal 16000 token output sekitar $0.32 + input per permintaan; satu perbaikan dapat menambah biaya. Estimasi aktual tampil bersama hasil."}</p>`, "Setuju & kembangkan")) return;
    busy = true;
    generateButton.disabled = true;
    generator.disabled = true;
    $("#director-error", root).innerHTML = "";
    const progress = $("#director-progress", root);
    progress.hidden = false;
    progress.innerHTML = `<div class="director-loading"><span class="pulse">${icon("spark")}</span><div><strong id="director-progress-label">Menyusun arah cerita…</strong><p>Merangkai treatment, dialog dan blocking, lalu memeriksa format naskah.</p></div><span class="chip">${online ? "ANTHROPIC" : "LOKAL"}</span></div><div class="skeleton"></div>`;
    root.querySelector("#director").setAttribute("aria-busy", "true");
    try {
      const result = await run("direct_scene", { idea: text, generator: mode, consent: online,
        language: $("#script-language", root).value === "auto" ? "id" : $("#script-language", root).value,
        duration_s: Number($("#director-duration", root).value),
        characters: Number($("#director-cast", root).value) || null,
        style: $("#director-style", root).value || null, look: $("#director-look", root).value || null,
        location: $("#director-location", root).value || null, seed: Number($("#script-seed", root).value),
      }, { confirmExternal: online, onUpdate: job => {
        const label = $("#director-progress-label", root);
        if (label) label.textContent = `Menyusun treatment & memeriksa naskah · ${seconds(job.elapsed_s)}`;
      }});
      current = result.data;
      state.latestDirector = current;
      tab = "brief";
      if (!disposed) draw();
    } catch (e) { if (!disposed) $("#director-error", root).innerHTML = errorHTML(e); }
    finally {
      busy = false;
      generateButton.disabled = false;
      generator.disabled = false;
      progress.hidden = true;
      root.querySelector("#director").removeAttribute("aria-busy");
    }
  };
  return () => { disposed = true; };
}
