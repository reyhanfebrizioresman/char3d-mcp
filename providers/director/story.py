"""Dramatic intentions for our local scenarios, expressed independently of dialogue."""
import re

TURN_WORDS = {
    'reunion': (r'Boleh kita mulai lagi', r'Can we start again'),
    'argument': (r'bantu aku mengerti|ingin didengarkan', r'Help me understand|wanted you to listen'),
    'confession': (r'ingin kita lebih sering', r'want to see you more often'),
    'interview': (r'mulai mendengarkan', r'learned to listen'),
    'lesson': (r'berani mencoba|tidak harus langsung', r'understand now|Try it slowly'),
    'sales': (r'sesuaikan dengan kebutuhan|contoh pemakaiannya', r'review the options|show one example'),
    'comedy': (r'waktunya yang salah|cari rencananya', r'Wrong day|need to find it'),
    'celebration': (r'tetap menemani', r'Thank you for staying'),
    'farewell': (r'tidak semua harus selesai|pertemuan nanti', r'Save a story|Save.*next time'),
    'conversation': (r'mau mendengar|ingin kucoba', r'Thank you for listening|want to try'),
}

# goal/stakes, setup, turn, resolution. Dialogue is evidence, not the synopsis.
STORIES = {
    'reunion': (
        ('mencoba menyambung persahabatan setelah lama terpisah; keberanian meminta waktu bersama menentukan apakah keduanya akan dekat lagi',
         'Tempat yang dikenali bersama mencairkan kecanggungan, tetapi jarak selama berpisah belum terucapkan',
         'Salah satu sahabat berhenti berlindung di balik kenangan dan meminta kesempatan memulai lagi',
         'Jawaban menerima mengubah nostalgia menjadi janji untuk menyediakan waktu'),
        ('try to renew a friendship after years apart; asking for time together decides whether the reunion becomes a new beginning',
         'A familiar place eases their awkwardness while the years apart remain unspoken',
         'One friend stops sheltering behind memories and asks for another beginning',
         'Acceptance turns nostalgia into a promise to make time')),
    'argument': (
        ('ingin didengarkan setelah salah paham; percakapan dapat membuka jalan berdamai atau memperlebar jarak',
         'Keluhan terdengar sebagai tuduhan sehingga pasangan bicara saling melindungi diri',
         'Permintaan memahami menggantikan keinginan membuktikan siapa yang benar',
         'Kesediaan membahas satu persoalan memberi mereka cara untuk melanjutkan'),
        ('want to be heard after a misunderstanding; listening can repair the relationship or leave them further apart',
         'A complaint lands as an accusation and both partners defend themselves',
         'A request to understand replaces the need to win',
         'Agreeing to take one issue at a time gives them a way forward')),
    'confession': (
        ('ingin mengungkapkan kedekatan yang selama ini disembunyikan; jawaban lawan bicara akan mengubah hubungan mereka',
         'Keinginan bicara tertahan oleh takut ditolak, sementara pendengar memberi ruang',
         'Keinginan untuk lebih sering bertemu akhirnya disampaikan terus terang',
         'Penerimaan membuat kerentanan terasa aman dan memungkinkan kedekatan baru'),
        ('want to reveal an affection they have kept hidden; the answer will change their relationship',
         'Fear of rejection delays the confession while the listener makes room',
         'The wish to spend more time together is finally spoken plainly',
         'A welcoming answer makes vulnerability safe and opens a closer relationship')),
    'interview': (
        ('mencari alasan di balik keputusan untuk mulai; pengalaman pribadi perlu menjadi pegangan yang berguna bagi pendengar',
         'Pertanyaan pembuka mengundang cerita tentang dorongan pertama',
         'Pengalaman gagal dan mendengarkan menggeser jawaban dari prestasi ke proses',
         'Saran kecil yang dapat dicoba memberi pendengar jalan masuk'),
        ('seek the reason behind a decision to begin; a personal experience must become something useful to a listener',
         'An opening question invites the story of the first impulse',
         'Difficulty and listening shift the answer from achievement to process',
         'A small practical suggestion gives the listener a place to begin')),
    'lesson': (
        ('mencari cara memahami satu contoh; keberanian bertanya menentukan apakah kebingungan berubah menjadi percobaan',
         'Contoh sederhana membuka ruang bagi pertanyaan tanpa mempermalukan murid',
         'Penjelasan dengan kata sendiri mengubah ragu menjadi pemahaman',
         'Satu pengamatan kecil memberi keberanian untuk mencoba lagi'),
        ('seek a way to understand one example; asking a question can turn confusion into an attempt',
         'A small example makes room for questions without embarrassment',
         'Explaining it in their own words turns doubt into understanding',
         'One concrete observation gives them confidence to try again')),
    'sales': (
        ('menguji apakah satu pilihan menjawab kebutuhan nyata; keputusan harus lahir dari pemahaman, bukan desakan',
         'Pertanyaan kebutuhan menahan dorongan untuk langsung menawarkan produk',
         'Contoh penggunaan mengubah janji umum menjadi pilihan yang dapat diperiksa',
         'Waktu mempertimbangkan menjaga keputusan tetap pada calon pengguna'),
        ('test whether an option meets a real need; the decision must come from understanding rather than pressure',
         'A question about needs delays the urge to pitch',
         'A concrete example turns a broad promise into an option they can inspect',
         'Time to compare leaves the decision with the prospective user')),
    'comedy': (
        ('ingin membuktikan bahwa mereka sudah siap; kesalahan kecil mengubah kebanggaan menjadi kesempatan menertawakan diri',
         'Keyakinan datang tepat waktu menyiapkan harapan bahwa rencana berjalan baik',
         'Satu rincian waktu membalik arti kesiapan mereka',
         'Ajakan pulang mengembalikan kalimat pembuka dengan arti yang lucu'),
        ('want to prove they are prepared; a small mistake turns pride into shared self-mockery',
         'Confidence about arriving early sets up an orderly plan',
         'One detail about the date reverses the meaning of being ready',
         'Going home returns to the opening claim with a comic meaning')),
    'celebration': (
        ('ingin menikmati hasil usaha bersama; mengingat saat hampir menyerah memberi kemenangan arti yang lebih pribadi',
         'Kegembiraan tiba lebih dulu daripada kesadaran tentang perjalanan mereka',
         'Ucapan terima kasih mengubah pencapaian menjadi pengakuan atas kebersamaan',
         'Keputusan menikmati hari ini melepaskan tuntutan untuk segera mengejar hal berikutnya'),
        ('want to enjoy a shared success; remembering how close they came to giving up makes the victory personal',
         'Excitement arrives before reflection on the journey',
         'Thanks turn an achievement into recognition of companionship',
         'Choosing to enjoy today releases the pressure to chase the next goal')),
    'farewell': (
        ('ingin berpisah tanpa memutus hubungan; cerita yang belum selesai menjadi alasan untuk kembali berkabar',
         'Waktu berangkat memaksa percakapan menghadapi perpisahan',
         'Hal yang belum selesai diterima sebagai cerita untuk pertemuan berikutnya',
         'Janji berkabar mengubah kehilangan menjadi penantian yang dapat ditanggung'),
        ('want to leave without losing contact; an unfinished story becomes a reason to speak again',
         'Departure time makes the separation unavoidable',
         'Unfinished thoughts become stories saved for the next meeting',
         'A promise to keep in touch turns loss into bearable anticipation')),
    'conversation': (
        ('mencari keberanian mencoba satu hal kecil; kesediaan mendengar dapat mengubah niat menjadi langkah bersama',
         'Waktu yang akhirnya tersedia membuka percakapan yang sempat tertunda',
         'Sebuah keinginan kecil disampaikan dan mendapat perhatian',
         'Memilih langkah pertama membuat dukungan terasa konkret'),
        ('seek courage to try something small; being heard can turn an intention into a shared first step',
         'Finally having time opens a conversation they had postponed',
         'A small wish is voiced and receives attention',
         'Choosing the first step makes support concrete')),
}

PLACES = {
    'park': ('taman', 'the park'), 'beach': ('pantai', 'the beach'),
    'cafe_terrace': ('teras kafe', 'a cafe terrace'), 'living_room': ('ruang keluarga', 'the living room'),
    'office': ('kantor', 'the office'), 'classroom': ('kelas', 'the classroom'),
    'podcast_studio': ('studio podcast', 'the podcast studio'), 'stage': ('panggung', 'the stage'),
    'news_desk': ('meja siaran', 'the news desk'), 'city_street': ('jalan kota', 'a city street'),
}


def narrative(genre, chars, location, en=False, idea=''):
    goal, setup, turn, ending = STORIES[genre][int(en)]
    relation = chars[0]['relationship']
    if en:
        relation = {'sahabat': 'old friends', 'ibu dan anak': 'a mother and child',
                    'guru dan murid': 'a teacher and students', 'pasangan': 'partners',
                    'rekan kerja': 'colleagues', 'rekan bicara': 'conversation partners'}.get(relation, 'companions')
    if genre == 'reunion' and re.search(r'\b10\b|sepuluh|ten years', idea, re.I):
        goal = goal.replace('after years apart', 'after ten years apart').replace('setelah lama terpisah', 'setelah sepuluh tahun terpisah')
    who = (' and ' if en else ' dan ').join(c['id'] for c in chars)
    place = PLACES.get(location, (location.replace('_', ' '), location.replace('_', ' ')))[int(en)]
    if len(chars) == 1:
        who += ', a speaker' if en else ', seorang pembicara'
    else:
        who += ', '+relation
    return dict(logline=(f'{who}, meet in {place} and {goal}.' if en else f'{who}, bertemu di {place} dan {goal}.'),
                arc=dict(setup=setup, turn=turn, ending=ending))
