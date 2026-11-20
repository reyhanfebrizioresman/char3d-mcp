import { state, run, scene } from './api.js';
import { esc, button, action, seconds, warnings, toast, confirm } from './ui.js';
import { lookLabel } from './looks.js';

export const filmScript = script => typeof script === 'object' ? !!script?.scenes : /^(ADEGAN|SCENE)\s*(\d+\s*)?:/im.test(script);
export const scriptTool = script => filmScript(script) ? 'script_to_film' : 'script_to_scene';

export function storyboard(target, data, built) {
  const film = data.film || data.plan || data;
  const scenes = film.scenes || [];
  const title = film.title || film.name;
  target.innerHTML = `<section class="panel"><div class="panel-head"><h2>${esc(title)}</h2><span class="chip">${scenes.length} adegan · ${seconds(data.duration_s || film.duration_s)}</span></div><ol class="film-storyboard" aria-label="Storyboard film">${scenes.map(s => `<li class="film-scene-card"><div class="row between"><span class="eyebrow">ADEGAN ${s.index}</span><span class="chip">${esc(s.status === 'built' ? 'Terbangun' : 'Rencana')}</span></div><h3>${esc(s.name)}</h3><dl><dt>Lokasi</dt><dd>${esc(s.environment || 'Tanpa set')}</dd><dt>Suasana</dt><dd>${esc(lookLabel(s.look?.preset) || s.look?.preset || 'Asli')}</dd><dt>Cuaca</dt><dd>${esc(s.weather || 'clear')}</dd><dt>Tokoh</dt><dd>${s.cast.map(esc).join(', ')}</dd><dt>Durasi</dt><dd>${seconds(s.duration_s || (s.estimated_frames[1] - s.estimated_frames[0]+1)/(film.fps || 24))}</dd><dt>Transisi masuk</dt><dd>${esc(s.transition_in.kind)}${s.transition_frames ? ` · ${s.transition_in.duration_s} dtk` : ''}</dd>${s.card ? `<dt>Kartu</dt><dd>${esc(s.card.text)}</dd>` : ''}</dl><div class="row">${built ? button(`film-open-${s.index}`, 'Buka adegan', 'folder', 'small subtle') + button(`film-rebuild-${s.index}`, 'Bangun ulang', 'refresh', 'small') : ''}</div><div id="film-scene-progress-${s.index}" class="help" role="status"></div></li>`).join('')}</ol>${built ? '<div id="build-previews" class="panel-body"></div>' : ""}${warnings(data.warnings || film.warnings)}<div class="panel-body help">${built ? 'Simpan perubahan adegan sebelum merender atau <a href="#review">membuka Review film</a>.' : 'Bangun semua adegan untuk membuat proyek film.'}</div></section>`;
  for (const s of scenes) {
    const open = target.querySelector(`#film-open-${s.index}`);
    if (open) open.onclick = () => action(open, async () => {
      if (!await confirm('Buka adegan film?', 'Simpan perubahan adegan saat ini terlebih dahulu.', 'Buka adegan')) return;
      await run('open_film_scene', { name: film.name, index: s.index });
      state.scene = null; state.previews = [];
      location.hash = 'adegan';
    }, target.querySelector(`#film-scene-progress-${s.index}`));
    const rebuild = target.querySelector(`#film-rebuild-${s.index}`);
    if (rebuild) rebuild.onclick = () => action(rebuild, () => target.rebuildScene?.(s.index), target);
  }
}

export function buildProgress(progress) {
  return `<ol class="film-build-progress">${(progress.scenes || []).map(s => `<li><strong>${esc(s.name)}</strong><span class="chip">${esc(({built:'Terbangun',building:'Membangun',pending:'Menunggu',running:'Merender',done:'Selesai',reused:'Cache'})[s.status] || s.status)}${s.progress ? ` · ${esc(s.progress)}` : ''}</span></li>`).join('')}</ol>`;
}

export async function switcher(root, refresh) {
  const info = await scene();
  const target = root.querySelector('#film-switcher');
  if (!target) return;
  if (!info.film) { target.innerHTML = ''; state.film = null; return; }
  const film = (await run('film_info', {name:info.film.name})).data;
  state.film = film;
  target.innerHTML = `<div class="panel-head"><h2>Film · ${esc(film.title || film.name)}</h2><span class="chip">${film.scenes.length} adegan</span></div><div class="panel-body row"><label class="field">Adegan aktif<select id="film-scene-select" aria-label="Adegan film">${film.scenes.map(s=>`<option value="${s.index}" ${s.index === info.film.index ? 'selected' : ''}>${s.index}. ${esc(s.name)}</option>`).join('')}</select></label><p class="help">Simpan proyek untuk memasukkan perubahan ke film.</p></div>`;
  const select = target.querySelector('select');
  select.onchange = () => action(select, async () => {
    if (!await confirm('Pindah adegan?', 'Simpan perubahan adegan saat ini terlebih dahulu.', 'Pindah adegan')) { select.value=info.film.index; return; }
    await run('open_film_scene', {name:film.name,index:Number(select.value)});
    state.scene=null; state.previews=[];
    root.querySelector('#scene-viewport').innerHTML = '<p class="help" role="status">Adegan dibuka. Buat pratinjau untuk memeriksa kamera.</p>';
    root.querySelector('#scene-filmstrip').innerHTML = '';
    await refresh();
    toast('Adegan film dibuka.');
  }, target);
}
