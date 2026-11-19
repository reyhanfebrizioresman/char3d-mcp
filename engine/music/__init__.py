"""Original procedural scoring, usable without Blender or IO until write_cached."""
from .catalog import ALIASES, PALETTES, infer_mood, mood_name
from .compose import compose, script_settings, settings
from .dsp import RATE, instrument, loudness, master, metrics, render, spectral_metrics, true_peak, write_cached

__all__ = ["ALIASES", "PALETTES", "infer_mood", "mood_name", "compose", "script_settings", "settings",
           "RATE", "instrument", "loudness", "master", "metrics", "render", "spectral_metrics", "true_peak", "write_cached"]
