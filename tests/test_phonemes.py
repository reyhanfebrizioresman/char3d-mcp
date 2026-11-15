"""Offline pronunciation/timing invariants and MCP Whisper forwarding (no model download)."""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.phonemes import (choose_language, sounds, timed_phonemes, viseme_frames,
                             relative_duration)  # noqa: E402


class PronunciationTests(unittest.TestCase):
    def test_indonesian_and_malay(self):
        for word, expected in {
            "ngopi": "ng ow p iy", "nyanyi": "ny aa ny iy", "syarat": "sh aa r aa t",
            "akhir": "aa kh iy r", "cuci": "ch uw ch iy", "jalan": "jh aa l aa n",
            "pulau": "p uw l aw", "pantai": "p aa n t ay", "amboi": "aa m b oy",
            "anak": "aa n aa q", "dengan": "d ax ng aa n", "té": "t eh",
            "bebek": "b eh b eh q",
            "te\u0301": "t eh",
        }.items():
            with self.subTest(word=word):
                self.assertEqual(sounds(word, "id"), expected.split())
                self.assertEqual(sounds(word, "ms"), expected.split())

    def test_english_exceptions_and_rules(self):
        for word, expected in {
            "hello": "h ax l ow", "people": "p iy p ax l", "one": "w ah n",
            "the": "dh ax", "you’re": "y ao r", "three": "th r iy",
            "cat": "k ae t", "city": "s ih t iy", "cake": "k ey k",
            "ship": "sh ih p", "phone": "f ow n", "night": "n ay t",
            "rain": "r ey n", "action": "ae k sh ax n", "jumped": "jh ah m p t",
            "wanted": "w ae n t ih d", "candle": "k ae n d ax l",
        }.items():
            with self.subTest(word=word):
                self.assertEqual(sounds(word, "en"), expected.split())

    def test_language_selection(self):
        self.assertEqual(choose_language("Halo saya punya dua ide"), "id")
        self.assertEqual(choose_language("Hello this is my voice"), "en")
        self.assertEqual(choose_language("awak boleh makan ini", "ms"), "ms")
        self.assertEqual(choose_language("hello", "id-ID"), "id")
        self.assertEqual(choose_language("unknown"), "id")
        with self.assertRaises(ValueError):
            choose_language("hello", "fr")

    def test_timing_stays_inside_words(self):
        words = [("membuka", 7.5, 31.25), ("pulau", 48.0, 64.0)]
        events = timed_phonemes(words, "id")
        for word, start, end in words:
            phones = [e for e in events if e["word"] == word]
            self.assertEqual(phones[0]["start"], start)
            self.assertEqual(phones[-1]["end"], end)
            self.assertTrue(all(start <= e["start"] < e["end"] <= end for e in phones))
            self.assertTrue(all(a["end"] == b["start"] for a, b in zip(phones, phones[1:])))
        self.assertGreater(relative_duration("aa"), relative_duration("p"))
        self.assertLess(relative_duration("t", final=True), relative_duration("t"))
        self.assertEqual(timed_phonemes([("!", 1, 2), ("a", 2, 2)], "id"), [])
        quick = timed_phonemes([("pop", 1.3, 6.7)], "en")
        list(viseme_frames(quick, 1, 8, 24, 0.9))
        self.assertTrue(all(e["frame"] is not None for e in quick))

    def test_contact_rounding_silence_and_smoothing(self):
        events = timed_phonemes([("poma", 5, 65), ("fava", 90, 120)], "id")
        frames = dict(viseme_frames(events, 1, 150, 24, 0.8, lambda f: 0.1))
        for e in events:
            if e["frame"] is None:
                continue
            target = frames[e["frame"]]
            if e["phoneme"] in ("p", "m"):
                self.assertEqual(target["p_b_m_21"], 1.0)
                self.assertEqual(sum(target.values()), 1.0)
            if e["phoneme"] in ("f", "v"):
                self.assertGreaterEqual(target["f_v_18"], 0.95)
        anticipate = timed_phonemes([("to", 1, 20)], "id")
        rounded = dict(viseme_frames(anticipate, 1, 23, 24, 0.9))
        self.assertGreater(rounded[anticipate[0]["frame"]].get("ow_08", 0), 0)
        self.assertTrue(all(0 <= v <= 1 for target in frames.values() for v in target.values()))
        self.assertTrue(all(sum(target.values()) <= 1.000001 for target in frames.values()))
        self.assertEqual(sum(frames[80].values()), 0)  # pause between words
        self.assertEqual(sum(frames[140].values()), 0)  # silent audio tail
        held = timed_phonemes([("aaaa", 1, 49)], "id")
        smoothed = dict(viseme_frames(held, 1, 51, 24, 0.9))
        self.assertTrue(all(abs(sum(smoothed[f].values()) - 0.9) < 1e-6 for f in range(8, 44)))
        tiny = timed_phonemes([("membuka", 3.1, 3.8)], "id")
        list(viseme_frames(tiny, 1, 6, 24, 0.9))
        self.assertTrue(all(e["frame"] is None for e in tiny))

    def test_mcp_whisper_forwarding(self):
        from mcp_server import server
        words = [{"word": "hello", "start": 0.1, "end": 0.8}]
        transcript = {"text": "hello", "words": words, "language": "en"}

        async def check():
            with patch.object(server.speech, "transcribe", return_value=transcript) as transcribe, \
                    patch.object(server, "run", new_callable=AsyncMock) as run:
                run.return_value = {"mode": "words", "detail": "phoneme"}
                result = await server.lip_sync_audio("Hero", "line.wav", timing="whisper",
                                                     language="auto", detail="phoneme")
                self.assertEqual(result["mode"], "whisper")
                self.assertEqual(result["transcript"], "hello")
                self.assertEqual(run.call_args.kwargs["words"], words)
                self.assertEqual(run.call_args.kwargs["detail"], "phoneme")
                self.assertIsNone(transcribe.call_args.args[1])
                await server.lip_sync_audio("Hero", "line.wav", timing="whisper", language="ms")
                self.assertEqual(transcribe.call_args.args[1], "ms")
        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
