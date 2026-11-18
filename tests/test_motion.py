"""Motion score/metadata/parser checks; no Blender or downloaded assets required."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.motion_library import MOTIONS, cycle_frames, total_frames, score  # noqa: E402
from engine.script_plan import parse_script  # noqa: E402


def main():
    required = set("sad angry nervous happy excited tired confident shy bored laugh cry shrug "
                   "startle surprised facepalm thinking sigh clap bow nod_agree disagree point beckon "
                   "cover_mouth arms_crossed kneel lie_down get_up sit_floor type drink eat phone_call "
                   "read_book look_around stretch pick_up dance_casual dance_energetic dance_traditional "
                   "punch kick block dodge hit_react fall_down".split())
    assert set(MOTIONS) == required
    for name, meta in MOTIONS.items():
        assert meta["category"] in ("body_language", "reaction", "action", "dance", "fight")
        assert type(meta["loops"]) is bool and meta["frames_per_cycle"] >= 24
        assert len(meta["description"]) > 25 and isinstance(meta["required_props"], list)
        for i in range(101):
            spec, loc = score(name, i/100)
            assert all(math.isfinite(v) for xyz in [*spec.values(), loc] for v in xyz), name
            assert all(spec.get("shin."+s, [0])[0] <= 0 for s in "LR"), name
        if meta["loops"]:
            assert score(name, 0) == score(name, 1) == score(name, 3), name
            a, b = score(name, 1-1e-6), score(name, 1+1e-6)
            assert max(abs(x-y) for bone in a[0] for x, y in zip(a[0][bone], b[0][bone])) < .01, name
        if meta["category"] == "dance":
            for fps in (24, 30, 60):
                for bpm in (60, 90, 120, 180):
                    assert abs(cycle_frames(name, fps, bpm=bpm)-4*60*fps/bpm) <= .5
            assert cycle_frames(name, bpm=60) == 2*cycle_frames(name, bpm=120)
            assert abs(total_frames(name, 100, bpm=132)-4*60*24*100/132) <= .5
    for args in (("sad", 24, 1, 100), ("dance_casual", 24, 1, float("nan")),
                 ("dance_casual", 24, 0, 100), ("dance_casual", 24, 1, 0)):
        try:
            cycle_frames(*args)
        except ValueError:
            pass
        else:
            raise AssertionError(args)
    pairs = [("Ana menangis", "cry"), ("Budi tertawa", "laugh"), ("Ana sedih", "sad"),
             ("Budi marah", "angry"), ("Ana gugup", "nervous"), ("Ana berjoget", "dance_casual"),
             ("Ana menari tradisional", "dance_traditional"), ("Budi berlutut", "kneel"),
             ("Ana berbaring", "lie_down"), ("Budi bangun", "get_up"), ("Ana mengetik", "type"),
             ("Budi minum", "drink"), ("Ana menelepon", "phone_call"), ("Budi membaca buku", "read_book"),
             ("Ana mengangkat bahu", "shrug"), ("Budi bertepuk tangan", "clap"), ("Ana membungkuk", "bow"),
             ("Ana duduk di lantai", "sit_floor"), ("Ana is sad", "sad"), ("Budi feels nervous", "nervous"),
             ("Budi punches Ana", "punch"),
             ("Ana lies down", "lie_down"), ("Budi covers mouth", "cover_mouth")]
    text = "ANA: Halo.\nBUDI: Hi.\n"+"\n".join(f"[{s}]" for s, _ in pairs)+"\n[Ana teleports]\n"
    plan = parse_script(text)
    assert [b["name"] for b in plan["beats"][2:]] == [v for _, v in pairs]
    assert any("teleports" in w for w in plan["warnings"])
    assert plan["beats"][-3]["at"] == "ANA"
    plan = parse_script({"characters": [{"id": "Ana"}], "beats": [
        {"do": "gesture", "who": "Ana", "name": "dance_casual", "bpm": 90, "cycles": 2}]})
    assert plan["beats"][0]["estimated_frames"] == [1, 129]
    for body, face in (("nervous", "fear"), ("excited", "big_smile"), ("tired", "sleepy"), ("happy", "smile")):
        plan = parse_script({"characters": [{"id": "Ana"}], "beats": [{"say": "Ana", "text": "Halo", "emotion": body}]})
        assert plan["beats"][0]["body_emotion"] == body and plan["beats"][0]["emotion"] == face
    for phase in ("down", "hold", "up"):
        assert score("kneel", .5, phase=phase)
    assert score("kneel", 1, phase="down") == score("kneel", 0, phase="up")
    print(f"MOTION UNIT OK ({len(MOTIONS)} clips; bilingual parsing, loop seams, BPM, phases)")


if __name__ == "__main__":
    main()
