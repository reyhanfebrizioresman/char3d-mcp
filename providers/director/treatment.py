"""Offline editorial pass and exports of the shared treatment contract."""
from engine.treatment import TREATMENT_SCHEMA, check, markdown, validate_treatment


def beat_event(beat, language='id'):
    """Readable action, including its actors/target, rather than parser enum names."""
    from engine.director_cues import display_size, display_move
    en = language == 'en'
    if 'say' in beat:
        return beat['say']+': '+beat['text']
    action = beat.get('do')
    who = beat.get('who', '')
    if action == 'camera':
        detail = ('automatic dialogue coverage' if en else 'coverage dialog otomatis') if beat['shot'] == 'auto' else (
            display_size(beat['shot'])+' '+', '.join(beat.get('subject') or ['all characters' if en else 'semua tokoh'])+', '+display_move(beat['move'], language))
        return ('camera' if en else 'kamera')+' → '+detail
    if action == 'music':
        return ('music' if en else 'musik')+' → '+mood_label(beat['mood'], language)
    if action in ('pause', 'silence'):
        return (('silence' if action == 'silence' else 'pause') if en else ('hening' if action == 'silence' else 'jeda'))+f" {beat['seconds']:g} "+('seconds' if en else 'detik')
    if action == 'look':
        return who+(' looks at ' if en else ' menatap ')+str(beat['at'])
    if action == 'interact':
        names = who+(' and ' if en else ' dan ')+beat['with']
        kinds = {'handshake': 'bersalaman', 'hug': 'berpelukan', 'high_five': 'tos', 'handover': 'serah terima',
                 'fist_bump': 'adu kepalan', 'pat_shoulder': 'tepuk bahu'}
        return names+' '+(beat['kind'].replace('_', ' ') if en else kinds.get(beat['kind'], beat['kind']))
    labels = {'walk': 'berjalan ke', 'sit': 'duduk di', 'stand': 'berdiri', 'hold': 'memegang', 'gesture': 'bergerak', 'pose': 'berpose'}
    detail = beat.get('to', beat.get('on', beat.get('prop', beat.get('name', ''))))
    return ' '.join(str(v) for v in (who, action if en else labels.get(action, 'kartu judul'), detail or beat.get('title', '')) if v)


def mood_label(value, language='id'):
    if language == 'en':
        return value or 'stop'
    return {'calm': 'tenang', 'warm': 'hangat', 'happy': 'ceria', 'sad': 'sedih', 'romantic': 'romantis',
            'tense': 'tegang', 'mysterious': 'misterius', 'epic': 'epik', 'playful': 'lucu', 'nostalgic': 'nostalgia',
            'auto': 'otomatis', None: 'berhenti'}.get(value, value)


def template_pass(script, opts, genre, chars, narrative=None):
    """Use three motivated overrides, yielding speaker coverage between them."""
    import re
    from engine.film_plan import is_film, parse_film
    from engine.script_plan import parse_script
    from engine.director_cues import display_size, display_move
    from engine.music.cues import resolve
    from engine.music.description import describe
    en = opts['language'] == 'en'
    lang = opts['language']
    camera, music = ('CAMERA', 'MUSIC') if en else ('KAMERA', 'MUSIK')
    group = chars[0]['id'] if len(chars)==1 else ('two-shot' if en else 'dua tokoh') if len(chars)==2 else ''
    auto = f'[{camera}: '+('auto' if en else 'otomatis')+']'
    def cue(size, subject='', move='static'):
        return f'[{camera}: {display_size(size)}'+(' '+subject if subject else '')+f', {display_move(move, lang)}]'
    parts = re.split(r'(?=^ADEGAN\s+\d+:)', script, flags=re.M) if is_film(script) else [script]
    output = []
    for part in parts:
        raw = part.splitlines()
        speech = [i for i, ln in enumerate(raw) if re.match(r'^[^:[\]]+(?:\([^)]*\))?: .+', ln)
                  and not re.match(r'^(JUDUL|LOKASI|SUASANA|CUACA|ADEGAN|TITLE|LOCATION):', ln)
                  and not ln.startswith(('ADEGAN ', '[', 'MUSIK:', 'MUSIC:'))]
        if not speech:
            output.extend(raw)
            continue
        # Locate the scenario's decisive request/answer, falling back to a late response.
        from .story import TURN_WORDS
        peak = next((i for i in speech[1:] if re.search(TURN_WORDS[genre][int(en)], raw[i], re.I)),
                    speech[max(1, len(speech)*2//3)] if len(speech)>1 else speech[0])
        inserts = {speech[0]: [f'[{music}: {mood_label("calm", lang)}]', cue('medium_full', group)]}
        if len(speech)>1:
            inserts.setdefault(speech[1], []).append(auto)
        who = re.match(r'^([^:(]+)', raw[peak])[1].strip()
        inserts.setdefault(peak, []).extend(['[SILENCE 1 second]' if en else '[HENING 1 detik]',
            f'[{music}: {mood_label("warm", lang)}]', cue('close_up', who, 'push_in')])
        after = next((i for i in speech if i>peak), None)
        if after is not None:
            inserts.setdefault(after, []).append(auto)
        for i, ln in enumerate(raw):
            output.extend(inserts.get(i, [])); output.append(ln)
        output += [cue('medium_full', group, 'dolly_out'),
                   '[pause 2 seconds]' if en else '[jeda 2 detik]']
    script = '\n'.join(output)
    plan = parse_film(script, seed=opts['seed']) if is_film(script) else parse_script(script, seed=opts['seed'])
    scenes = plan.get('scenes') or [{'plan': plan, 'film_frames': plan['estimated_frames'], 'transition_in': {'kind': 'cut'}}]
    beats, shots, silences, transitions, sections, cuts = [], [], [], [], [], []
    for scene in scenes:
        p = scene['plan']; offset = scene['film_frames'][0]-1; events = []; override = False
        for i, b in enumerate(p['beats']):
            at = b['estimated_frames'][0]
            if b.get('do') == 'camera':
                override = b['shot'] != 'auto'
                if override:
                    role = 'peak' if b['move'] == 'push_in' else 'establish' if not events else 'echo'
                    events.append((i, at, b['shot'], b['move'], b.get('angle',20), role, b.get('subject') or []))
            elif 'say' in b and not override:
                events.append((i, at, 'medium', 'static', 0, 'reply', [b['say']]))
            t = round((offset+at-1)/24, 3)
            if b.get('do') == 'silence':
                silences.append(dict(t=t, seconds=b['seconds']))
            beats.append(dict(t=t, event=beat_event(b, lang)))
        for j, (i, start, size, move, angle, role, subject) in enumerate(events):
            end = events[j+1][1] if j+1<len(events) else p['estimated_frames'][1]+1
            reasons = {
                'establish': ('Establish the shared place and the distance between the partners.', 'Kenalkan tempat bersama dan jarak awal di antara tokoh.'),
                'reply': (f'Let {", ".join(subject)} receive the previous line and answer in their own frame.', f'Beri {", ".join(subject)} ruang untuk menerima ucapan sebelumnya lalu menjawab.'),
                'peak': ('Move closer as the guarded thought becomes a direct request; stay through its consequence.', 'Dekati wajah ketika hal yang ditahan menjadi permintaan terus terang; tahan reaksi sesudahnya.'),
                'echo': ('Return to the opening space with the distance between them changed; release the conversation.', 'Kembalikan ruang pembuka setelah jarak emosional berubah; lepaskan percakapan.'),
            }
            shots.append(dict(beat=len(beats)-len(p['beats'])+i,size=size,angle=angle,move=move,
                              seconds=round((end-start)/24,3),reason=reasons[role][int(not en)]))
            cuts.append(round((offset+start-1)/24,3))
        cfg = p['music']; tempo = cfg['tempo'] if cfg else 80
        changes = resolve([dict(frame=b['estimated_frames'][0],mood=b['mood']) for b in p['beats'] if b.get('do')=='music'],
                          tempo,24,1,p['estimated_frames'][1]+1)
        for j, c in enumerate(changes):
            end = changes[j+1]['frame'] if j+1<len(changes) else p['estimated_frames'][1]+1
            seconds=(end-c['frame'])/24
            sections.append(dict(name=('Opening' if j==0 else 'Response') if en else ('Pembuka' if j==0 else 'Jawaban'),
                start_s=round((offset+c['frame']-1)/24,3),end_s=round((offset+end-1)/24,3),
                music_state=mood_label(c['mood'],lang),instrumentation=describe(c['mood'],seconds,tempo,opts['seed']+j,language=lang)))
        if offset:
            transitions.append(dict(t=round(offset/24,3),kind=scene['transition_in']['kind'],audio=scene['transition_in'].get('audio')))
    spoken = [b for scn in scenes for b in scn['plan']['beats'] if 'say' in b]
    peak_line = next((b for b in spoken if re.search(TURN_WORDS[genre][int(en)],b['text'],re.I)), spoken[len(spoken)*2//3])
    candidates = (['Begin with a familiar detail, risk a direct question, then return to the shared space',
                   'Reveal the answer first and uncover what made it difficult', 'Build around a shared task that changes meaning'] if en else
                  ['Mulai dari hal yang dikenali, beranikan pertanyaan, lalu kembali ke ruang bersama',
                   'Perlihatkan jawaban lebih dahulu lalu ungkap mengapa ia sulit diucapkan', 'Ikuti kegiatan bersama sampai artinya berubah'])
    story = narrative or dict(logline='A meeting changes what the partners are willing to ask.' if en else 'Sebuah pertemuan mengubah keberanian tokoh untuk meminta.',
                              arc=dict(setup='An encounter' if en else 'Pertemuan',turn='A question' if en else 'Pertanyaan',ending='A response' if en else 'Jawaban'))
    arc = {k:story['arc'][k]+f' — {b["say"]}: “{b["text"]}”' for k,b in zip(('setup','turn','ending'),(spoken[0],peak_line,spoken[-1]))}
    t = dict(structures=dict(candidates=candidates,chosen=candidates[0],why='A visible change can grow from listening without adding exposition.' if en else 'Perubahan tumbuh dari kegiatan mendengar tanpa menambah penjelasan panjang.'),
        logline=story['logline'],arc=arc,
        hook=(f'{spoken[0]["say"]} opens on a shared detail: “{spoken[0]["text"]}”' if en else f'{spoken[0]["say"]} membuka dengan hal yang dikenali bersama: “{spoken[0]["text"]}”'),
        ending_echo='Return to the opening two-shot and pull back for a two-second release.' if en else 'Kembali ke two-shot pembuka dan mundur perlahan selama dua detik untuk melepas percakapan.',
        signature_shot='A close-up push on the decisive request, after one second of quiet; return to the replying speaker.' if en else 'Push close-up pada permintaan penentu setelah satu detik hening; kembali ke pembicara yang menjawab.',
        shot_list=shots,beat_sheet=beats,cue_map=dict(tempo=tempo,sections=sections,cuts=sorted(cuts),silences=silences,transitions=transitions),
        sound_design=[dict(section=s['name'],ambience='Quiet location bed, dipped during the held silence' if en else 'Latar lokasi pelan, turun selama hening',
            foley='Movement and contact sounds follow the action' if en else 'Bunyi gerak dan kontak mengikuti tindakan',music=s['music_state']+('; lower under speech' if en else '; turunkan saat dialog')) for s in sections],
        subtitle_design='Phrase captions held at least 1.8 s and 0.6 s beyond speech, up to 17 characters/s.' if en else 'Subtitle per frasa, tahan minimal 1,8 detik dan 0,6 detik setelah ucapan, maksimal 17 karakter/detik.')
    validate_treatment(t)
    return script,t
