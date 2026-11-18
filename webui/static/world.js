import { run, state } from './api.js';
import { $, $$, esc, head, field, select, input, button, errorHTML, toast, confirm, screenRoot } from './ui.js';

const examples = [
  ['Danau lentera', 'Lentera keemasan naik di atas danau biru saat senja, dua sahabat di dermaga.'],
  ['Penjaga kabut', 'Serpent giok melingkari gerbang pegunungan berkabut saat matahari terbit.'],
  ['Paus di langit', 'Paus besar berenang di antara awan senja dan balon sutra merah.'],
  ['Kepulauan udara', 'Pulau terapung dengan air terjun panjang dan burung di cahaya keemasan.'],
];
const storage = key => `char3d-world-${key}`;
export function mount(container) {
  const root = screenRoot(container);
  let disposed = false, busy = false, revision = 0, timer, catalog;
  root.innerHTML = head('MODE BEBAS', 'Sebuah dunia dari satu bayangan.',
    'Susun lanskap, makhluk dan cahaya menjadi tempat yang belum pernah ada.', '<span class="chip">✦ DUNIA ORIGINAL</span>') + `
    <section class="world-intro panel" aria-labelledby="world-title"><div><span class="eyebrow">BANGUN IMAJINASI</span><h2 id="world-title">Ke mana cerita Anda pergi?</h2><p>Satu pusat perhatian. Ruang untuk tokoh. Gerak yang membawa suasana.</p></div><span class="world-orbit" aria-hidden="true">◌</span></section>
    <div class="world-layout"><section class="panel world-form"><label class="field-label" for="world-idea">Ceritakan dunia Anda</label><textarea id="world-idea" maxlength="8000" rows="4" placeholder="Paus langit melintas pelan di antara awan senja…"></textarea>
    <div class="world-examples">${examples.map(([name], i) => `<button type="button" class="director-example" data-world-example="${i}">${esc(name)} ↗</button>`).join('')}</div>
    <div class="form-grid">${field('Generator',select('world-generator', [['offline','Offline · gratis'],['claude_cli','Claude langganan · via Claude Code'],['claude','Claude API · berbayar'],['auto','Otomatis']]),'span-2')}${field('Seed',input('world-seed',17,'number','min="0" max="2147483647" step="1"'))}</div>
    <p class="help" id="world-privacy" role="status">Offline: ide tetap di perangkat. Variasi mengikuti seed.</p>
    ${button('world-generate','Ciptakan dunia','spark','primary')}
    <div id="world-progress" role="status" aria-live="polite"></div><div id="world-error" role="alert"></div>
    <div class="world-contract"><span class="eyebrow">BAHAN KREASI</span><p>Alam prosedural · makhluk langit · arsitektur · cahaya · gerak</p><p class="help">Desain original. Resep terukur dan dapat diedit.</p></div></section>
    <section class="panel world-workbench" aria-label="Resep dan pratinjau"><div class="panel-head"><h2>Dunia Anda</h2><span class="chip" id="world-source">DRAF</span></div><div class="world-workbody">
    <div id="world-summary" class="world-summary" aria-live="polite"><h3>Mulai dengan sebuah tempat.</h3><p>Hasil akan menampilkan komposisi, perkiraan biaya geometri dan resep yang bisa Anda ubah.</p></div>
    <div id="world-preview" class="world-preview" hidden></div>
    <label class="field-label" for="world-json">Resep JSON</label><textarea id="world-json" class="world-json" spellcheck="false" rows="14" aria-describedby="world-validation" placeholder='{"version": 1, "elements": […]}'></textarea>
    <div id="world-validation" role="status" aria-live="polite"></div><div class="row world-actions">${button('world-validate','Periksa resep','check','subtle')}${button('world-preview-button','Pratinjau Eevee','eye','primary')}</div>
    <div class="divider"></div><div class="world-save">${field('Nama dunia',input('world-name','dunia-pertama','text','maxlength="80" pattern="[A-Za-z0-9_-]+"'))}<div class="row">${button('world-save','Simpan','save','subtle')}${button('world-use','Pakai di Naskah','arrow','primary')}</div></div><p class="help">Pratinjau membangun set di adegan aktif. Tokoh tetap ada. Simpan resep untuk dipakai kembali.</p>
    </div></section></div>`;
  const idea=$('#world-idea',root), editor=$('#world-json',root), generator=$('#world-generator',root), seed=$('#world-seed',root);
  idea.value=localStorage.getItem(storage('idea'))||'';
  editor.value=localStorage.getItem(storage('json'))||'';
  $('#world-name',root).value=localStorage.getItem(storage('name'))||'dunia-pertama';
  idea.oninput=()=>localStorage.setItem(storage('idea'),idea.value);
  $('#world-name',root).oninput=()=>localStorage.setItem(storage('name'),$('#world-name',root).value);
  $$('[data-world-example]',root).forEach(el=>el.onclick=()=>{idea.value=examples[Number(el.dataset.worldExample)][1];idea.dispatchEvent(new Event('input'));idea.focus();});
  const setBusy = value => { busy=value; $$('button',root).forEach(el=>el.disabled=value); root.setAttribute('aria-busy',String(value)); };
  const fail = error => { if(!disposed) $('#world-error',root).innerHTML=errorHTML(error); };
  const recipe = () => { try{return JSON.parse(editor.value);} catch(e){throw new Error(`JSON: ${e.message}`);} };
  const summary = report => {
    if(disposed)return;
    const r=report.recipe;
    $('#world-summary',root).innerHTML=`<h3>${esc(r.name)}</h3><p>${r.elements.length} elemen · ${esc(typeof r.look==='string'?r.look:r.look?.preset||'tanpa look')} · ${Number(r.duration_s)} detik</p><div class="world-costs"><span><b>${Number(report.cost.triangles).toLocaleString('id-ID')}</b> segitiga</span><span><b>${report.cost.instances}</b> instans</span><span><b>${report.cost.lights}</b> lampu</span></div><p class="help">${esc(r.elements.slice(0,7).map(e=>e.generator.replaceAll('_',' ')).join(' · '))}</p>`;
    $('#world-validation',root).innerHTML=`<p class="world-valid">✓ Resep valid · dalam batas anggaran</p><details><summary>Catatan · ${report.warnings.length}</summary>${report.warnings.map(w=>`<p class="help">${esc(w)}</p>`).join('')}</details>`;
    editor.removeAttribute('aria-invalid');
  };
  const validate = async () => {
    const current=revision;
    try {const data=recipe();const result=await run('compose_world',{recipe:data,build:false});if(current===revision&&!disposed)summary(result.data);return result.data;}
    catch(e){if(current===revision&&!disposed){editor.setAttribute('aria-invalid','true');$('#world-validation',root).innerHTML=errorHTML(e);}throw e;}
  };
  editor.oninput=()=>{$('#world-preview',root).hidden=true;revision++;localStorage.setItem(storage('json'),editor.value);clearTimeout(timer);timer=setTimeout(()=>validate().catch(()=>{}),850);};
  $('#world-validate',root).onclick=()=>validate().catch(()=>{});
  generator.onchange=()=>{
    $('#world-privacy',root).textContent=generator.value==='offline'?'Offline: ide tetap di perangkat. Variasi mengikuti seed.':generator.value==='claude'?'Dengan persetujuan: ide dikirim ke Anthropic. API berbayar, estimasi tampil pada hasil.':'Dengan persetujuan: ide dikirim ke Anthropic. Claude Code memakai kuota langganan; auto memilih layanan yang tersedia.';
  };
  run('director_status').then(r=>catalog=r.data).catch(()=>{});
  $('#world-generate',root).onclick=async()=>{
    if(busy)return;
    if(!idea.value.trim()){idea.focus();toast('Ceritakan satu ide dunia terlebih dahulu.','error');return;}
    let mode=generator.value;
    if(mode==='auto')mode=catalog?.auto_with_consent||'offline';
    const online=mode!=='offline';
    if(online&&!await confirm('Kirim ide dunia ke Anthropic?',`<p>Ide dan opsi dunia dikirim ke Anthropic. ${mode==='claude'?esc(catalog?.generators?.claude?.estimate||'Claude API berbayar. Maksimal 16000 token output per permintaan; satu perbaikan dapat menambah biaya.'):'Memakai kuota langganan Claude Code.'}</p>`,'Setuju & ciptakan'))return;
    setBusy(true);$('#world-error',root).innerHTML='';$('#world-progress',root).textContent='Menyusun komposisi dan memeriksa resep…';
    try{
      const result=await run('direct_world',{idea:idea.value,generator:mode,consent:online,seed:Number(seed.value)}, {confirmExternal:online});
      if(disposed)return;
      $('#world-preview',root).hidden=true;
      editor.value=JSON.stringify(result.data.recipe,null,2);revision++;localStorage.setItem(storage('json'),editor.value);
      $('#world-source',root).textContent=result.data.generator==='offline'?'OFFLINE':result.data.generator;
      summary(result.data);$('#world-summary',root).insertAdjacentHTML('beforeend',`<p>${esc(result.data.brief)}</p>${result.data.fallback_reason?`<p class="notice">${esc(result.data.fallback_reason)}</p>`:''}${result.data.privacy?`<p class="help">${esc(result.data.privacy)} ${esc(result.data.billing_note||'')} ${result.data.cost_usd_estimate!=null?`Estimasi API $${Number(result.data.cost_usd_estimate).toFixed(4)}`:''}</p>`:''}`);
    }catch(e){fail(e);}finally{if(!disposed){setBusy(false);$('#world-progress',root).textContent='';}}
  };
  const save=async()=>{await validate();const r=await run('save_world',{name:$('#world-name',root).value,recipe:recipe()});return r.data.name;};
  const task=async fn=>{if(busy)return;setBusy(true);$('#world-error',root).innerHTML='';try{await fn();}catch(e){fail(e);}finally{if(!disposed)setBusy(false);}};
  $('#world-save',root).onclick=()=>task(async()=>{await save();toast('Resep dunia disimpan.');});
  $('#world-use',root).onclick=()=>task(async()=>{
    const name=await save();const old=localStorage.getItem('char3d-script')||'ANA (perempuan, 28): Indah sekali!';
    localStorage.setItem('char3d-world-previous-script',old);
    localStorage.setItem('char3d-script',`DUNIA: ${name}\n`+old.replace(/^(DUNIA|WORLD):.*\n?/gim,'').replace(/^(LOKASI|LOCATION):.*\n?/gim,''));
    for(const setting of ['location','look'])localStorage.removeItem(`char3d-script-${setting}`);
    state.plan=null;state.latestScript=null;state.build=null;state.previews=[];
    location.hash='naskah';toast('Dunia disimpan dan header DUNIA dimuat ke Naskah.');
  });
  $('#world-preview-button',root).onclick=()=>task(async()=>{
    await validate();$('#world-progress',root).textContent='Membangun dunia dan merender cahaya…';
    const built=await run('compose_world',{recipe:recipe()});
    const result=await run('render_preview',{camera:built.data.hero_camera,engine_name:'eevee',width:512,height:288,frame:1});
    if(disposed)return;
    const box=$('#world-preview',root);box.hidden=false;
    box.innerHTML=result.images.map(url=>`<img src="${esc(url)}" alt="Pratinjau Eevee dunia dari kamera hero" width="512" height="288">`).join('');
    $('#world-progress',root).textContent='';
  });
  if(editor.value)validate().catch(()=>{});
  return()=>{disposed=true;clearTimeout(timer);};
}
