"""Small optional multi-scene arrangement of offline dialogue templates."""
import re


def arrange(script, opts):
    from .offline import SET_WORDS
    matches = sorted((m.start(), place) for place, pattern in SET_WORDS
                     if (m := re.search(pattern, opts['idea'], re.I)))
    places = list(dict.fromkeys(p for _, p in matches))
    if opts.get('location'):
        places = [opts['location']]
    if len(places) < 2 and opts['duration_s'] <= 45:
        return script
    if not places:
        places = [re.search(r'^LOKASI: (.+)$', script, re.M)[1]]
    count = min(3, max(len(places), 3 if opts['duration_s'] > 45 else 2))
    body = [s for s in script.splitlines() if s and not re.match(r'^(JUDUL|LOKASI|SUASANA|CUACA):', s)]
    # Split after complete speech/action beats; declarations at first appearance persist.
    cut = [round(i*len(body)/count) for i in range(count+1)]
    title = re.search(r'^JUDUL: (.+)$', script, re.M)[0]
    look = re.search(r'^SUASANA: (.+)$', script, re.M)[1]
    weather = re.search(r'^CUACA: (.+)$', script, re.M)[1]
    lines = [title]
    for i in range(count):
        if i:
            lines.append('[TRANSISI: dissolve 0.5 detik]')
        lines.extend([f'ADEGAN {i+1}: Bagian {i+1}', f'LOKASI: {places[min(i,len(places)-1)]}',
                      f'SUASANA: {look}', f'CUACA: {weather}', *body[cut[i]:cut[i+1]]])
    return '\n'.join(lines)
