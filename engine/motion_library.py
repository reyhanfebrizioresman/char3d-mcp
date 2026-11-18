"""Original procedural motion scores, independent of Blender.

Angles use anim's basic-skeleton convention. Distances are fractions of standing
height; scores share eased phrases, but different joints lead and settle at different
times. Dance phrases occupy four beats and return to their initial pose exactly.
"""
import math


def ease(t):
    t = max(0.0, min(1.0, t))
    return t*t*(3-2*t)


def phrase(t, attack=.25, release=.78):
    return ease(t/attack) * (1-ease((t-release)/(1-release)))


def track(t, keys):
    if t <= keys[0][0]:
        return keys[0][1]
    for (a, x), (b, y) in zip(keys, keys[1:]):
        if t <= b:
            return x+(y-x)*ease((t-a)/(b-a))
    return keys[-1][1]


def _entry(category, frames, loop, description, props=(), seat=False):
    return dict(category=category, frames_per_cycle=frames, loops=loop,
                description=description, required_props=list(props), required_seat=seat,
                beats_per_cycle=4 if category == "dance" else None)


MOTIONS = {}
for name, desc in {
    "sad": "Slumped chest, lowered gaze, slow breathing and weight shifts.",
    "angry": "Forward tension, fists and restrained sharp weight changes.",
    "nervous": "Small hand fidgets, shifting weight and uncertain glances.",
    "happy": "Open chest and buoyant, relaxed sway.",
    "excited": "Quicker bounce, lifted shoulders and open hands.",
    "tired": "Heavy shoulders, delayed head and slow breathing.",
    "confident": "Lifted chest, grounded stance, hands resting on hips.",
    "shy": "Low folded arms, inward shoulders and a soft head tilt.",
    "bored": "Uneven stance, drifting gaze and a slow exhale.",
}.items():
    MOTIONS[name] = _entry("body_language", 120, True, desc)
for name, frames, desc in (
    ("laugh", 72, "Chest-led laugh with delayed shoulder pulses and head release."),
    ("cry", 120, "Hands shelter the face; shoulders rise and fall with sobs."),
    ("shrug", 56, "Shoulders rise before palms open; a delayed release."),
    ("startle", 42, "Quick recoil into open guard, followed by a slow recovery."),
    ("surprised", 48, "Small anticipatory recoil and open hands."),
    ("facepalm", 84, "Right palm to forehead, a held beat, then release."),
    ("thinking", 96, "Hand to chin, a searching glance and a soft release."),
    ("sigh", 80, "Inhale, shoulders drop, chest and head settle afterwards."),
    ("clap", 72, "Three soft claps with cupped palms and elbow follow-through."),
    ("bow", 84, "Grounded polite bow, brief hold and measured recovery."),
    ("nod_agree", 54, "Two diminishing nods with a small torso agreement."),
    ("disagree", 64, "Head shake accompanied by a restrained palm-out wave."),
    ("point", 64, "Prepare, extend the index toward the front, then settle."),
    ("beckon", 72, "Palm-up invitation with two finger curls."),
    ("cover_mouth", 72, "Right hand gently covers the mouth and returns."),
    ("arms_crossed", 96, "Fold the forearms across the chest, hold, then release."),
):
    MOTIONS[name] = _entry("reaction", frames, False, desc)
for name, frames, loop, desc, props, seat in (
    ("kneel", 144, False, "Lower to both knees, hold and rise; phase selects down/hold/up/full.", (), False),
    ("lie_down", 144, False, "Crouch, sit, brace and recline onto the floor; ends lying down.", (), False),
    ("get_up", 144, False, "Roll forward, brace, gather the feet and stand from the floor.", (), False),
    ("sit_floor", 120, False, "Lower into a grounded seated pose with bent knees; ends seated.", (), False),
    ("type", 96, True, "Seated typing with alternating finger taps; preserves sit_on legs/root.", (), True),
    ("drink", 108, False, "Lift a held cup to the lips, sip upright and lower it.", ("cup",), False),
    ("eat", 96, False, "Bring the right hand to the mouth, pause and return (pantomime).", (), False),
    ("phone_call", 120, True, "Hold a phone beside the ear with small listening movements.", ("phone",), False),
    ("read_book", 144, True, "Support a held book in front of the chest, looking down at its pages.", ("book",), False),
    ("look_around", 96, False, "Chest follows a head-led scan, then returns to the front.", (), False),
    ("stretch", 120, False, "Reach overhead with an inhale and stretch gently to either side.", (), False),
    ("pick_up", 120, False, "Bend the knees, reach toward the floor, gather and stand.", (), False),
):
    MOTIONS[name] = _entry("action", frames, loop, desc, props, seat)
for name, desc in (
    ("dance_casual", "Four-beat side-to-side groove, soft knees and relaxed arm swing."),
    ("dance_energetic", "Four-beat pop-inspired bounce with alternating arm accents."),
    ("dance_traditional", "Graceful hand-led phrase inspired by general Indonesian dance vocabulary; no specific regional dance."),
):
    MOTIONS[name] = _entry("dance", 64, True, desc)
for name, frames, desc in (
    ("punch", 48, "Guard, wind-up, stylized right jab and recoil."),
    ("kick", 66, "Weight to the support leg, chamber, low front kick and recover."),
    ("block", 54, "Raise the forearms into a protective guard, absorb and recover."),
    ("dodge", 60, "Dip and slip sideways with bent knees, then recover."),
    ("hit_react", 54, "Non-gory torso recoil with delayed arms and recovery."),
    ("fall_down", 108, "Stylized backward loss of balance, seated catch and floor landing."),
):
    MOTIONS[name] = _entry("fight", frames, False, desc)

FLOOR = {"kneel", "lie_down", "get_up", "sit_floor", "fall_down", "pick_up"}
BASES = {k for k, v in MOTIONS.items() if v["category"] == "body_language"}


def cycle_frames(name, fps=24, speed=1, bpm=None):
    """Inclusive endpoint is keyed separately, so frames denote cycle duration."""
    for value, label, low, high in ((fps, "fps", 1, 240), (speed, "speed", .05, 4)):
        if isinstance(value, bool) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{label} must be finite in {low}..{high}")
    m = MOTIONS[name]
    if bpm is not None:
        if m["category"] != "dance":
            raise ValueError("bpm is supported by dance clips only")
        if isinstance(bpm, bool) or not math.isfinite(bpm) or not 30 <= bpm <= 240:
            raise ValueError("bpm must be finite in 30..240")
        return max(4, round(m["beats_per_cycle"]*60*fps/(bpm*speed)))
    return max(4, round(m["frames_per_cycle"]*fps/(24*speed)))


def total_frames(name, cycles=1, fps=24, speed=1, bpm=None):
    """Round the entire dance phrase once, avoiding accumulated tempo drift."""
    period = cycle_frames(name, fps, speed, bpm)
    count = max(1, int(cycles)) if MOTIONS[name]["loops"] else 1
    if bpm is not None:
        return max(4, round(4*60*fps*count/(bpm*speed)))
    return period*count


def score(name, t, amplitude=1, phase="full"):
    """Return (Euler spec, (side, up, forward)/height) at normalized phrase time."""
    loop = MOTIONS[name]["loops"]
    t = t % 1 if loop else max(0., min(1., t))
    p = 2*math.pi*t
    s, c = math.sin(p), math.cos(p)
    breath = math.sin(p-.35)-math.sin(-.35)
    spec = {"upper_arm.L": [0, 0, -78], "upper_arm.R": [0, 0, -78],
            "forearm.L": [12, 0, 0], "forearm.R": [12, 0, 0]}
    x = z = fwd = 0.
    def rot(b, a=0, b_=0, c_=0):
        spec[b] = [a, b_, c_]
    if name in BASES:
        vals = {"sad": (12, 8, 19), "angry": (8, 7, -3), "nervous": (5, 2, 7),
                "happy": (-4, -3, -3), "excited": (-5, -4, -5), "tired": (14, 9, 23),
                "confident": (-5, -4, -3), "shy": (7, 4, 15), "bored": (6, 3, 8)}[name]
        rot("spine", vals[0]+1.2*breath, 1.5*s, 1.2*s)
        rot("chest", vals[1]+breath)
        rot("head", vals[2]+2*math.sin(p-.6), 5*s if name in ("nervous", "bored") else 1.5*s,
            7 if name == "shy" else 2*s)
        x = (.012 if name in ("nervous", "angry") else .006)*s
        z = -.008+.0015*breath
        if name in ("happy", "excited"):
            z = -.009+.006*(1-c)
            if name == "excited":
                z = -.014+.009*(1-math.cos(4*p))
            rot("chest", vals[1]-2*s)
        if name == "angry":
            rot("spine", 10+2*math.tanh(3*s), 3*math.tanh(3*s))
            rot("forearm.L", 28+3*s)
            rot("forearm.R", 30-3*s)
            rot("shoulder.L", 0, 0, 3); rot("shoulder.R", 0, 0, 3)
        if name in ("sad", "tired", "bored"):
            for side in "LR":
                rot("upper_arm."+side, vals[0]+vals[1]+2*breath, 0, -80)
        if name == "excited":
            rot("upper_arm.L", 12+5*s, 0, -65)
            rot("upper_arm.R", 12-5*s, 0, -65)
    elif name == "dance_energetic":
        # Four-beat pop phrase: each beat snaps into a pose (early hit, soft settle).
        beat = 4*t
        k = int(beat) % 4
        frac = beat - int(beat)
        hit = ease(min(1., frac*2.2))
        # (upper_arm X forward, Z down-angle, forearm curl) per side, per beat.
        poses = [
            {"R": (25, 48, 14), "L": (30, -76, 110)},   # right punch up, left at chest
            {"R": (34, -80, 86), "L": (34, -80, 86)},     # clap in front of the chest
            {"R": (30, -76, 110), "L": (25, 48, 14)},   # left punch up
            {"R": (-18, -70, 48), "L": (-18, -70, 48)},   # groove down and back
        ]
        a, b = poses[(k-1) % 4], poses[k]
        on = 1 - abs(math.sin(math.pi*frac))        # 1 on the beat, 0 between
        x = .03*math.sin(2*p)                        # hip sway every two beats
        z = -.02 - .028*on
        rot("hips", 0, 7*math.sin(2*p), 4*math.sin(2*p))
        rot("spine", 6 + 5*on, -5*math.sin(2*p), -3*math.sin(2*p))
        rot("chest", -4 + 6*on, 9*math.sin(2*p-.4), 3*math.sin(2*p))
        rot("head", 3 + 7*on, -5*math.sin(2*p-.6), -4*math.sin(2*p))
        for side, sign in (("L", 1), ("R", -1)):
            ax, az, af = (a[side][i] + (b[side][i]-a[side][i])*hit for i in range(3))
            rot("upper_arm."+side, ax, 0, az)
            rot("forearm."+side, af)
            rot("thigh."+side, 10 + 9*on + 6*sign*math.sin(2*p), 0, 4)
            rot("shin."+side, -20 - 16*on - 6*sign*math.sin(2*p))
            rot("foot."+side, 9 + 6*on)
    elif name in ("dance_casual", "dance_traditional"):
        energetic = False
        graceful = name == "dance_traditional"
        x = (.022 if graceful else .035)*s
        z = -.016-(.012 if energetic else .005)*(1-math.cos(4*p))
        rot("hips", 0, 4*s, 2*s)
        rot("spine", 3 if energetic else 1, -6*s, -4*s)
        rot("chest", -2, 7*math.sin(p-.3), 2*math.sin(p-.2))
        rot("head", 2, -4*math.sin(p-.5), -3*s)
        for side, sign in (("L", 1), ("R", -1)):
            rot("thigh."+side, 8+4*sign*s, 0, 4)
            rot("shin."+side, -15-5*sign*s)
            rot("foot."+side, 7+sign*s)
            rot("upper_arm."+side, 15+18*sign*math.sin(p-.3), 0, -66 if not energetic else -40+20*sign*s)
            rot("forearm."+side, 38+20*sign*math.sin(p-.7))
    elif name in ("kneel", "lie_down", "get_up", "sit_floor", "fall_down", "pick_up"):
        if name == "kneel":
            u = {"down": ease(t), "hold": 1., "up": 1-ease(t)}.get(phase,
                track(t, [(0, 0), (.12, .08), (.4, 1), (.65, 1), (1, 0)]))
            rot("thigh.L", -2*u); rot("thigh.R", -2*u)
            rot("shin.L", -92*u); rot("shin.R", -92*u)
            rot("foot.L", -82*u); rot("foot.R", -82*u)
            rot("spine", 12*math.sin(math.pi*u)); rot("head", 7*u)
            z = -.31*u
            # Move the pelvis over the knees as the calves fold back, rather
            # than dragging the ankles half a meter behind a stationary torso.
            fwd = .235*(math.sin(math.radians(2*u))+math.sin(math.radians(94*u)))
        elif name == "pick_up":
            u = track(t, [(0, 0), (.14, .12), (.44, 1), (.62, 1), (1, 0)])
            for side in "LR":
                rot("thigh."+side, 100*u); rot("shin."+side, -135*u); rot("foot."+side, 35*u)
            rot("spine", 38*u); rot("head", 15*u)
            z, fwd = -.26*u, .03*u
        else:
            q = 1-t if name == "get_up" else t
            sit = track(q, [(0, 0), (.12, .05), (.42, 1), (1, 1)])
            recline = 0 if name == "sit_floor" else track(q, [(0, 0), (.5, 0), (.66, .12), (1, 1)])
            rot("hips", -90*recline)
            rot("spine", 24*sit*(1-recline))
            rot("head", 10*sit*(1-recline))
            for side in "LR":
                rot("thigh."+side, 135*sit*(1-recline), 0, 7*sit)
                rot("shin."+side, -90*sit*(1-recline)-8*recline)
                rot("foot."+side, -45*sit*(1-recline))
                rot("upper_arm."+side, -15*sit, 0, -65)
                rot("forearm."+side, 20*sit)
            z, fwd = -.48*sit, -.16*sit
            if name == "fall_down":
                stumble = phrase(q, .12, .42)
                rot("spine", 24*sit*(1-recline)-20*stumble)
                rot("head", 10*sit*(1-recline)-12*stumble)
                for side in "LR":
                    rot("upper_arm."+side, 45*stumble-15*sit, 0, -65)
                fwd -= .025*stumble
    else:
        w = phrase(t)
        if name == "laugh":
            pulse = math.sin(8*math.pi*t)*w
            rot("spine", -5*w+3*pulse); rot("chest", -5*w+3*math.sin(8*math.pi*t-.6)*w)
            rot("head", -12*w+2*pulse); z = -.004*w+.003*pulse
            rot("shoulder.L", 0, 0, 3*math.sin(8*math.pi*t-.6)*w)
            rot("shoulder.R", 0, 0, 3*math.sin(8*math.pi*t-.6)*w)
        elif name == "cry":
            rot("spine", 14*w+2*math.sin(10*math.pi*t)*w)
            rot("chest", 10*w+2*math.sin(10*math.pi*t-.4)*w)
            rot("head", 24*w)
        elif name == "shrug":
            for side in "LR":
                rot("shoulder."+side, 0, 0, 12*phrase(t, .2, .55))
            rot("head", 0, 5*w, 6*w)
        elif name == "facepalm":
            rot("spine", 4*w); rot("chest", 2*w); rot("head", 10*w, 0, 4*w)
            x = -.006*w
        elif name == "thinking":
            rot("chest", 3*w); rot("head", 6*w, 3*math.sin(p)*w, -6*w)
            x = .007*w
        elif name == "cover_mouth":
            rot("spine", -3*w); rot("head", -5*w, 0, 2*w)
        elif name == "arms_crossed":
            rot("spine", -3*w); rot("head", 2*w, 3*w)
            x = .008*w
        elif name in ("point", "beckon"):
            rot("spine", 4*w, -4*w); rot("chest", 0, -4*w)
            rot("head", 2*w, 3*w); fwd = .008*w
        elif name == "clap":
            rot("chest", -2*w+math.sin(6*math.pi*t)*w)
            rot("head", -2*w); rot("shoulder.L", 0, 0, 2*w); rot("shoulder.R", 0, 0, 2*w)
        elif name in ("startle", "surprised"):
            w = track(t, [(0, 0), (.13, 1), (.32, .7), (.65, .3), (1, 0)])
            rot("spine", -10*w); rot("head", -8*w); fwd = -.025*w; z = -.012*w
        elif name == "sigh":
            inhale = track(t, [(0, 0), (.25, -5), (.48, -4), (.72, 9), (1, 0)])
            rot("chest", inhale); rot("spine", .5*inhale); rot("head", max(0, inhale)*1.4)
        elif name == "bow":
            rot("spine", 33*w); rot("chest", 12*w); rot("head", 10*w); fwd = -.012*w
            for side in "LR":
                rot("upper_arm."+side, 45*w, 0, -80)
        elif name == "nod_agree":
            rot("head", 12*math.sin(4*math.pi*t)*w); rot("chest", 2*w)
        elif name == "disagree":
            rot("head", 0, 19*math.sin(4*math.pi*t)*w)
        elif name == "look_around":
            v = track(t, [(0, 0), (.25, 35), (.42, 35), (.68, -40), (.8, -40), (1, 0)])
            rot("head", 3*w, v); rot("chest", 0, v*.24)
        elif name == "stretch":
            rot("spine", -5*w, 0, 8*math.sin(2*math.pi*t)*w); rot("head", -8*w)
        elif name in ("drink", "eat"):
            rot("head", -2*w); rot("chest", -1*w)
        elif name == "phone_call":
            rot("head", 3+2*s, 3*s, -4)
        elif name == "read_book":
            rot("head", 34+2*s, 3*s); rot("chest", 3)
        elif name == "type":
            rot("head", 12+2*s); rot("chest", 5)
        elif name in ("punch", "kick", "block", "dodge", "hit_react"):
            hit = track(t, [(0, 0), (.2, -.2), (.38, 1), (.5, .8), (.75, .12), (1, 0)])
            for side in "LR":
                rot("upper_arm."+side, 38, 0, -66); rot("forearm."+side, 115)
                rot("thigh."+side, 12); rot("shin."+side, -24); rot("foot."+side, 12)
            z = -.025
            if name == "punch":
                rot("chest", 5, -17*hit); rot("spine", 3, -8*hit)
                rot("upper_arm.R", 45+40*hit, 0, -60+55*hit)
                rot("forearm.R", 115-108*hit); fwd = .015*hit
            elif name == "kick":
                rot("thigh.R", 85*w); rot("shin.R", -100*w+90*max(0, hit)); rot("foot.R", -10*w)
                rot("spine", -10*w); x = .025*w
            elif name == "block":
                rot("forearm.L", 115+15*w); rot("forearm.R", 115+15*w); rot("spine", -5*w)
            elif name == "dodge":
                rot("spine", 16*w, 0, 15*w); x = -.045*w; z -= .045*w
            else:
                rot("spine", -17*hit, 8*hit); rot("head", -12*track(t, [(0, 0), (.42, 1), (.65, .2), (1, 0)]))
                fwd = -.035*max(0, hit)
    # Scaling around the hanging-arm stance prevents amplitude=0 from becoming a T-pose.
    for b, values in spec.items():
        base = [0, 0, -78] if b.startswith("upper_arm") else [12, 0, 0] if b.startswith("forearm") else [0, 0, 0]
        spec[b] = [a+(v-a)*amplitude for a, v in zip(base, values)]
    return spec, (x*amplitude, z*amplitude, fwd*amplitude)


# Exact bilingual phrases are matched before the older one-word direction parser.
DIRECTIONS = {
    "cry": "menangis|cries|cry", "laugh": "tertawa|laughs|laugh",
    "sad": "sedih|sad", "angry": "marah|angry", "nervous": "gugup|nervous",
    "happy": "senang|bahagia|happy", "excited": "bersemangat|excited",
    "tired": "lelah|tired", "confident": "percaya diri|confident",
    "shy": "malu|shy", "bored": "bosan|bored",
    "dance_casual": "berjoget|menari|dances|dance",
    "dance_energetic": "menari energik|dances energetically",
    "dance_traditional": "menari tradisional|dances traditionally",
    "kneel": "berlutut|kneels|kneel", "lie_down": "berbaring|lies down|lie down",
    "get_up": "bangun|gets up|get up", "sit_floor": "duduk di lantai|sits on the floor",
    "type": "mengetik|types|type", "drink": "minum|drinks|drink",
    "eat": "makan|eats|eat", "phone_call": "menelepon|phones|phone call",
    "read_book": "membaca buku|reads a book|read book", "look_around": "melihat sekeliling|looks around",
    "stretch": "meregangkan tubuh|stretches|stretch", "pick_up": "mengambil dari lantai|picks up from floor",
    "shrug": "mengangkat bahu|shrugs|shrug", "clap": "bertepuk tangan|claps|clap",
    "bow": "membungkuk|bows|bow", "facepalm": "menepuk dahi|facepalms|facepalm",
    "thinking": "berpikir|thinks|thinking", "sigh": "menghela napas|sighs|sigh",
    "nod_agree": "mengangguk setuju|nods agreement", "disagree": "tidak setuju|disagrees",
    "beckon": "memanggil dengan tangan|beckons", "cover_mouth": "menutup mulut|covers mouth",
    "arms_crossed": "menyilangkan tangan|crosses arms", "startle": "terkejut|startles",
    "surprised": "kaget|surprised", "punch": "meninju|punches|punch",
    "kick": "menendang|kicks|kick", "block": "menangkis|blocks|block",
    "dodge": "mengelak|dodges|dodge", "hit_react": "bereaksi terpukul|reacts to hit",
    "fall_down": "terjatuh|falls down|fall down",
}
