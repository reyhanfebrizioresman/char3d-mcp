"""Seeded local treatments. No model, file reads, downloads or network."""
import random
import re

from .common import LIGHTING, LOCATIONS

# Each pair is a complete setup/response; seeds select voice and story variations.
DIALOG = {
    'reunion': (
        ('Bangkunya masih di sini.', 'Aku ingat kamu selalu duduk di ujung.'),
        ('Sepuluh tahun terasa cepat, ya.', 'Tapi caramu menyapa masih sama.'),
        ('Aku sempat takut kamu lupa.', 'Mana mungkin. Kita belum selesai bercerita.'),
        ('Boleh kita mulai lagi?', 'Boleh. Kali ini jangan lama menghilang.'),
    ),
    'argument': (
        ('Aku kecewa kamu tidak bilang dulu.', 'Aku kira kamu butuh waktu sendiri.'),
        ('Aku cuma ingin didengarkan.', 'Baik. Aku dengar. Ceritakan pelan-pelan.'),
        ('Bukan itu yang kumaksud kemarin.', 'Kalau begitu, bantu aku mengerti.'),
        ('Kita bicarakan satu per satu, ya.', 'Ya. Aku juga tidak ingin terus begini.'),
    ),
    'confession': (
        ('Ada yang lama ingin kukatakan.', 'Aku di sini. Tidak perlu buru-buru.'),
        ('Aku gugup setiap mulai bicara.', 'Mulai dari yang paling sederhana saja.'),
        ('Aku ingin kita lebih sering bertemu.', 'Aku juga. Aku menunggu kamu bilang.'),
        ('Rasanya lega akhirnya jujur.', 'Terima kasih sudah percaya padaku.'),
    ),
    'interview': (
        ('Apa yang membuat Anda mulai?', 'Ada satu pertanyaan yang belum terjawab.'),
        ('Bagian tersulitnya apa?', 'Berani memulai sebelum semuanya sempurna.'),
        ('Apa yang berubah setelah itu?', 'Saya mulai mendengarkan orang lain.'),
        ('Apa pesan Anda untuk pendengar?', 'Mulai kecil, lalu periksa lagi hasilnya.'),
    ),
    'lesson': (
        ('Kita mulai dari satu contoh dulu.', 'Kalau belum paham, boleh bertanya, Bu?'),
        ('Coba jelaskan dengan kata-katamu.', 'Berarti satu langkah dulu, baru berikutnya?'),
        ('Betul. Tidak harus langsung sempurna.', 'Sekarang saya berani mencoba.'),
        ('Apa yang kamu perhatikan dari contoh ini?', 'Hal kecil ternyata bisa mengubah hasil.'),
    ),
    'sales': (
        ('Apa yang paling Anda butuhkan?', 'Saya mencari cara yang lebih sederhana.'),
        ('Mari lihat satu contoh pemakaiannya.', 'Boleh. Saya ingin tahu langkah awalnya.'),
        ('Kita sesuaikan dengan kebutuhan Anda.', 'Baik. Jelaskan pilihan yang tersedia.'),
        ('Silakan pertimbangkan dulu.', 'Terima kasih, saya akan memeriksanya.'),
    ),
    'comedy': (
        ('Aku datang lebih awal hari ini.', 'Bagus. Acaranya ternyata besok.'),
        ('Katanya kamu punya rencana matang.', 'Matang sekali. Tinggal cari rencananya.'),
        ('Kamu yakin ini tempat yang benar?', 'Yakin. Cuma waktunya yang salah.'),
        ('Setidaknya kita sudah siap.', 'Siap pulang dulu, maksudmu?'),
    ),
    'celebration': (
        ('Akhirnya kita sampai di sini!', 'Masih ingat waktu kita hampir menyerah?'),
        ('Ini hasil usaha kita bersama.', 'Hari ini kita boleh bangga sebentar.'),
        ('Terima kasih sudah tetap menemani.', 'Tentu. Perjalanan ini juga milikku.'),
        ('Setelah ini, apa rencana kita?', 'Rayakan dulu. Besok kita pikirkan lagi.'),
    ),
    'farewell': (
        ('Sudah waktunya aku berangkat.', 'Aku tahu. Tetap kabari aku, ya.'),
        ('Rasanya masih banyak yang belum selesai.', 'Tidak semua harus selesai hari ini.'),
        ('Terima kasih untuk semua waktunya.', 'Simpan ceritanya untuk pertemuan nanti.'),
        ('Sampai bertemu lagi.', 'Jaga dirimu. Aku tunggu kabarmu.'),
    ),
    'conversation': (
        ('Hari ini terasa berbeda, ya.', 'Mungkin karena akhirnya kita punya waktu.'),
        ('Ada hal kecil yang ingin kucoba.', 'Ceritakan. Kita pikirkan bersama.'),
        ('Terima kasih sudah mau mendengar.', 'Aku senang kamu mau bercerita.'),
        ('Kita mulai dari mana?', 'Dari satu langkah yang bisa kita lakukan.'),
    ),
}
ENGLISH = {
    'reunion': [('You still come here?', 'Some things are worth keeping.'), ('Ten years went by so fast.', 'Your hello still sounds the same.'), ('I was afraid you had forgotten.', 'We still have stories to finish.'), ('Can we start again?', 'Yes. Let us make time this time.')],
    'argument': [('I wish you had told me first.', 'I thought you needed some space.'), ('I just wanted you to listen.', 'I am listening now.'), ('That is not what I meant.', 'Help me understand, then.'), ('One thing at a time?', 'Yes. We can do that.')],
    'confession': [('There is something I need to say.', 'Take your time. I am here.'), ('I keep losing my words.', 'Start with something small.'), ('I want to see you more often.', 'I was hoping you would say that.'), ('I feel better now.', 'Thank you for trusting me.')],
    'interview': [('What made you begin?', 'A question I could not leave alone.'), ('What was the hardest part?', 'Starting before everything was ready.'), ('What changed after that?', 'I learned to listen.'), ('Any advice for our listeners?', 'Start small, then check your work.')],
    'lesson': [('Let us try one example.', 'Can I ask a question first?'), ('Explain it in your own words.', 'One step before the next?'), ('Exactly. Try it slowly.', 'I think I understand now.'), ('What changed in this example?', 'A small detail made a difference.')],
    'sales': [('What do you need most?', 'Something that is easier to use.'), ('Let me show one example.', 'Please show me the first step.'), ('We can review the options.', 'I would like time to compare them.'), ('Take your time.', 'Thank you for explaining.')],
    'comedy': [('I got here early today.', 'Great. The event is tomorrow.'), ('You said you had a solid plan.', 'Yes. I just need to find it.'), ('Are we in the right place?', 'Right place. Wrong day.'), ('At least we are ready.', 'Ready to go home?')],
    'celebration': [('We finally made it!', 'Remember when we almost gave up?'), ('We did this together.', 'We can be proud for a moment.'), ('Thank you for staying.', 'I wanted to see this through.'), ('What comes next?', 'Let us enjoy today first.')],
    'farewell': [('It is time for me to go.', 'Keep in touch, will you?'), ('There is so much left to say.', 'Save a story for next time.'), ('Thank you for everything.', 'I am glad we had this time.'), ('Until we meet again.', 'Take care. I will wait for your news.')],
    'conversation': [('Today feels a little different.', 'We finally have time to talk.'), ('There is something I want to try.', 'Tell me. We can work it out.'), ('Thank you for listening.', 'I am glad you told me.'), ('Where do we start?', 'With one small step.')],
}
GENRES = (
    ('reunion', r'reuni|bertemu lagi|reunion|reunite|years apart|friend.*again'),
    ('argument', r'bertengkar|pertengkaran|berdebat|konflik|marah|argument|argue|conflict'),
    ('confession', r'pengakuan|mengaku|cinta|confess|romantis|romantic|love'),
    ('interview', r'wawancara|podcast|interview'),
    ('lesson', r'pelajaran|belajar|guru|murid|lesson|teach|student'),
    ('sales', r'jualan|menjual|promosi|produk|sales|pitch|product'),
    ('comedy', r'komedi|lucu|comedy|funny|joke'),
    ('celebration', r'perayaan|merayakan|ulang tahun|menang|celebrat|birthday|victory'),
    ('farewell', r'perpisahan|berpisah|pamit|farewell|goodbye|leaving'),
)
GENRE_LABELS = {'reunion': 'reuni', 'argument': 'konflik', 'confession': 'pengakuan',
                'interview': 'wawancara', 'lesson': 'pelajaran', 'sales': 'presentasi produk',
                'comedy': 'komedi', 'celebration': 'perayaan', 'farewell': 'perpisahan',
                'conversation': 'percakapan hangat'}
SET_WORDS = (
    ('park', r'taman|\bpark\b'), ('beach', r'pantai|beach'),
    ('cafe_terrace', r'kafe|café|cafe|coffee'), ('city_street', r'jalan kota|street|trotoar'),
    ('podcast_studio', r'podcast|wawancara|interview'), ('news_desk', r'berita|news'),
    ('classroom', r'kelas|sekolah|classroom|school'), ('office', r'kantor|office'),
    ('stage', r'panggung|stage'), ('living_room', r'rumah|keluarga|living room|home'),
)
LOOK_WORDS = (
    ('blue_hour', r'jam biru|blue hour|twilight'), ('golden_hour', r'jam emas|golden hour|keemasan'),
    ('sunset', r'senja|sunset|dusk'), ('misty_morning', r'pagi|morning'),
    ('night', r'malam|night|gelap|horror'), ('overcast_soft', r'mendung|overcast|rain|hujan'),
    ('dreamy', r'mimpi|dream|fantasi'), ('epic', r'epik|epic|heroic'),
)
PALETTES = {
    'golden_hour': ('#285b6a', '#e7a063', '#fff0bc'), 'sunset': ('#53487d', '#ca7292', '#ffbd83'),
    'misty_morning': ('#8eafbb', '#cad5ce', '#f5e9d1'), 'blue_hour': ('#172c58', '#517296', '#efb87c'),
    'night': ('#080f24', '#233b66', '#bb8955'), 'overcast_soft': ('#7c9096', '#b2bebc', '#e0dbcf'),
    'dreamy': ('#8e98bc', '#e7b6ca', '#fff0d5'), 'epic': ('#182d40', '#696d70', '#e5b66f'),
    'studio_film': ('#243d42', '#957866', '#e3bf97'), 'none': ('#616b70', '#a4a9a2', '#d4d1be'),
}
DRESSING = {
    'park': 'Pepohonan, jalan setapak dan bangku menjadi lapisan belakang; sisakan lantai percakapan terbuka.',
    'beach': 'Palem dan garis laut menjadi latar; tempatkan wajah di atas garis horizon agar siluet terbaca.',
    'cafe_terrace': 'Meja, kursi dan awning memberi kedalaman; jaga jalur kamera depan tetap terbuka.',
    'city_street': 'Fasad dan mobil statis memberi konteks kota; percakapan berlangsung di area bebas kendaraan.',
    'podcast_studio': 'Meja dan mikrofon menandai studio; jangan biarkan mikrofon menutup mulut.',
    'office': 'Meja dan rak memberi konteks kerja; gunakan area percakapan di depan furnitur.',
    'classroom': 'Papan dan meja kelas memberi konteks; isi papan khusus perlu gambar lokal secara manual.',
    'stage': 'Panggung dan praktikal membingkai presenter; sisakan ruang tangan pada shot medium.',
    'living_room': 'Sofa, lampu dan meja menjadi latar domestik; tempatkan kamera di sisi ruangan yang terbuka.',
    'news_desk': 'Meja berita dan layar menjadi latar; grafik khusus memerlukan gambar lokal manual.',
}


def find(text, choices, default):
    return next((value for value, pattern in choices if re.search(pattern, text, re.I)), default)


def cast(opts, text, rng):
    nouns = r'\s+(?:tokoh|orang|sahabat|teman|karakter|rekan|pria|wanita|perempuan|murid|atlet|presenter|person|people|characters?|friends?|women|men|colleagues?|teachers?|students?)\b'
    count = opts['characters'] or find(text, tuple((n, r'\b(?:' + words + ')' + nouns) for n, words in
                         ((4, 'empat|four|4'), (3, 'tiga|three|3'), (2, 'dua|two|2'), (1, 'satu|one|1'))),
                         1 if re.search(r'sendiri|monolog|solo|seorang|presenter', text) else 2)
    if not opts['characters'] and re.search(r'(?:guru|teacher) (?:dan|and) (?:tiga|three) (?:murid|students)', text):
        count = 4
    relationship = find(text, (('ibu dan anak', r'ibu.*anak|mother.*child'), ('guru dan murid', r'guru|murid|teacher|student'),
                       ('pasangan', r'pasangan|couple|suami|istri'), ('rekan kerja', r'rekan kerja|colleague|coworker'),
                       ('sahabat', r'sahabat|friend')), 'rekan bicara')
    female = re.search(r'perempuan|wanita|women|female|girls', text, re.I)
    male = re.search(r'laki-laki|pria|\bmen\b|\bmale\b|boys', text, re.I)
    names = []
    named = re.search(r'(?:bernama|named|tokoh:)\s*([A-Z][A-Za-z]+)(?:\s+(?:dan|and)\s+([A-Z][A-Za-z]+))?', opts['idea'])
    pair = re.search(r'\b([A-Z][A-Za-z]+)\s+(?:dan|and)\s+([A-Z][A-Za-z]+)\b', opts['idea'])
    if named or pair:
        names = [v for v in (named or pair).groups() if v]
    women, men = rng.sample(['Sari', 'Naya', 'Rani', 'Ayu', 'Laras'], 4), rng.sample(['Dimas', 'Arif', 'Bima', 'Raka', 'Bayu'], 4)
    age_match = re.search(r'(?:usia|berusia|umur|aged?|perempuan|pria|wanita|laki-laki)\s*[, :]?\s*(\d{1,2})\b', text)
    if not age_match:
        age_match = re.search(r'\b(\d{1,2})\s*years? old', text)
    result = []
    for i in range(count):
        gender = 0 if female and not male else 1 if male and not female else i % 2
        age = int(age_match[1]) if age_match else 32 + i * 2
        if relationship == 'ibu dan anak':
            gender, age = (0, 42) if i == 0 else (i % 2, 12 + i)
        elif relationship == 'guru dan murid':
            age = 35 if i == 0 else 14 + i
        elif re.search(r'lansia|elderly|nenek|kakek', text):
            age = 67 + i * 2
        ident = names[i] if i < len(names) else (women if gender == 0 else men)[i]
        # Preserve explicit names while keeping all IDs unique.
        if ident in {c['id'] for c in result}:
            ident += str(i + 1)
        outfit = find(text, (('winter', r'salju|snow|winter|dingin'), ('sport', r'olahraga|sport'),
                       ('formal', r'formal|kantor|office|sales|pitch|guru|interview')), 'casual')
        hair = ('bob', 'ekor kuda')[rng.randrange(2)] if gender == 0 else 'pendek'
        result.append(dict(id=ident, gender=gender, age=max(1, min(90, age)), hair=hair,
                           outfit=outfit, relationship=relationship))
    return result


class Backend:
    online = False

    @staticmethod
    def available():
        return True

    def generate(self, opts, previous=None, feedback=None):
        rng = random.Random(opts['seed'])
        text = (opts['idea'] + ' ' + (opts['style'] or '')).casefold()
        genre = find(text, GENRES, 'conversation')
        # Explicit genre has precedence over a relationship keyword such as sahabat.
        if opts['style']:
            genre = find(opts['style'], GENRES, genre)
        location = opts['location'] or find(text, SET_WORDS, 'classroom' if genre == 'lesson' else
                    'podcast_studio' if genre == 'interview' else 'office' if genre == 'sales' else 'living_room')
        emotion = find(text, (('haru', r'haru|reunion|reuni'), ('sedih', r'sedih|sad|duka|grief'),
                             ('cemas', r'cemas|takut|fear|worr'), ('ceria', r'ceria|gembira|happy|joy|lucu|funny')), 'tenang')
        default_look = ('overcast_soft' if emotion == 'sedih' else 'blue_hour' if emotion == 'cemas' else
                        'golden_hour' if location in LOCATIONS[-4:] else 'studio_film')
        look = opts['look'] or find(text, LOOK_WORDS, default_look)
        weather = find(text, (('rain', r'hujan|rain'), ('snow', r'salju|snow'), ('fog', r'kabut|fog'),
                              ('wind', r'angin|wind')), 'clear')
        chars = cast(opts, text, rng)
        en = opts['language'] == 'en'
        pairs = list((ENGLISH if en else DIALOG)[genre])
        # Keep a coherent ending, vary which opening detail carries the scene.
        start = rng.randrange(3)
        pairs = pairs[start:3] + pairs[:start] + pairs[3:]
        title = rng.choice(['Ruang untuk Cerita', 'Satu Pertemuan', 'Sebelum Kita Pulang'])
        if genre == 'reunion':
            title = rng.choice(['Bangku yang Sama', 'Setelah Sepuluh Tahun' if re.search(r'10|sepuluh|ten years', text) else 'Satu Pertemuan Lagi', 'Kembali Menyapa'])
        if en:
            title = rng.choice(['A Moment Together', 'Before We Go', 'Room for a Story'])
        lines = [f'JUDUL: {title}', f'LOKASI: {location}', f'SUASANA: {look}', f'CUACA: {weather}', '']
        declared = set()
        speech = []
        if len(chars) == 1:
            speech = [p[0] for p in pairs]
            if genre in ('lesson', 'sales', 'interview'):
                speech = (['Start with one small example.', 'Explain it in your own words.', 'Then check what changed.', 'We can try again tomorrow.'] if en else
                          ['Mulai dari satu contoh kecil dulu.', 'Jelaskan dengan kata-katamu sendiri.', 'Lalu periksa apa yang berubah.', 'Besok kita bisa mencoba lagi.'])
        else:
            speech = [s for p in pairs for s in p]
        extra = (['I would like to hear more.', 'Let us take our time.', 'That gives me something to think about.', 'Thank you for being here.'] if en else
                 ['Aku ingin mendengar lebih banyak.', 'Kita tidak perlu buru-buru.', 'Ada yang ingin kupikirkan lagi.', 'Terima kasih sudah ada di sini.'])
        while len(speech) < 48:
            speech.extend(extra)
        from engine.script_plan import parse_script
        for i, words in enumerate(speech):
            char = chars[i % len(chars)]
            ident = char['id']
            if ident not in declared:
                desc = f"{'perempuan' if char['gender'] == 0 else 'laki-laki'}, {char['age']}, rambut {char['hair']}, {char['outfit']}, suara: piper:id_ID-news_tts-medium"
                lines.append(f'{ident} ({desc}): {words}')
                declared.add(ident)
            else:
                lines.append(f'{ident}: {words}')
            if i == len(chars) - 1:
                if len(chars) > 1:
                    lines.append(f"[{chars[0]['id']} melihat {chars[1]['id']}]")
                else:
                    lines.append(f"[{ident} melihat camera]")
                lines.append('[jeda 1 detik]')
            plan = parse_script('\n'.join(lines), seed=opts['seed'])
            elapsed = plan['estimated_frames'][1] / plan['fps']
            if len(declared) == len(chars) and elapsed >= opts['duration_s'] - 5:
                break
        if opts['duration_s'] >= 25:
            if len(chars) > 1 and genre in ('reunion', 'celebration', 'farewell'):
                lines.append(f"[{chars[0]['id']} dan {chars[1]['id']} bersalaman]")
            elif genre == 'lesson':
                lines.append(f"[{chars[0]['id']} menunjuk]")
            elif genre == 'comedy':
                lines.append(f"[{chars[0]['id']} melambai]")
        script = '\n'.join(lines)
        metadata = [dict(id=c['id'], appearance=f"{c['age']} tahun, rambut {c['hair']}",
                         outfit=c['outfit'], voice='Piper lokal, casting gender/usia otomatis',
                         relationship=c['relationship']) for c in chars]
        from .film import arrange
        from .treatment import template_pass, markdown
        script, treatment = template_pass(arrange(script, opts), opts, genre, chars)
        palette = PALETTES[look]
        brief = f"# {title}\n\n{genre}; {location}, {weather}. Look {look}; lighting {LIGHTING[look]}. "
        brief += f"Palette {', '.join(palette)}. Soft face key, light fill and separated background.\n\n"
        brief += DRESSING[location] + '\n\n' + markdown(treatment)
        warnings = ['Draf offline memakai skenario lokal; periksa dialog dan timing TTS sebelum membangun.',
                    'Cue kamera, musik dan hening dapat dijalankan; warna kostum dan dressing khusus perlu penataan.']
        if opts['language'] == 'ms':
            warnings.append('Offline memakai templat Indonesia; sesuaikan kosakata Melayu sebelum membangun.')
        if en:
            warnings.append('Select an installed English Piper model for English dialogue.')
        return dict(brief=brief, script=script, treatment=treatment, characters=metadata, warnings=warnings)
