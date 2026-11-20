import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from pause_probe import analyze


class PauseProbeTest(unittest.TestCase):
    def test_reference_and_exact_cut(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sound = root / "sample.wav"
            rate = 48000
            with wave.open(str(sound), "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(rate)
                frames = bytearray()
                for i in range(int(rate * 4.5)):
                    t = i / rate
                    value = 0 if 1 <= t < 1.4 or 2.4 <= t < 2.9 else int(5000 * math.sin(2 * math.pi * 220 * t))
                    frames.extend(struct.pack("<hh", value, value))
                output.writeframes(frames)
            source = {
                "fps": 50,
                "audio_rows": [{"start_frame": 0, "end_frame": 225,
                                "source_in_seconds": 0, "path": str(sound)}],
                "cues": [{"start_frame": 0, "end_frame": 50, "speaker": "A", "sentence_end": True},
                         {"start_frame": 70, "end_frame": 120, "speaker": "A", "sentence_end": True},
                         {"start_frame": 145, "end_frame": 195, "speaker": "A", "sentence_end": True}],
                "candidates": [{"start_frame": 50, "end_frame": 70}],
                "cuts": [{"start_frame": 55, "end_frame": 65},
                         {"start_frame": 65, "end_frame": 75}],
            }
            result = analyze(source, root / "cache")
            self.assertEqual(result["reference_by_speaker_and_kind"]["A|sentence_end"]["n"], 2)
            self.assertAlmostEqual(result["sentence_end_all_speakers"]["median"], .45, delta=.04)
            self.assertTrue(result["cuts"][0]["all_channels_exact_zero"])
            self.assertFalse(result["cuts"][1]["all_channels_exact_zero"])
            self.assertTrue(result["candidates"][0]["low_energy_spans_timeline_seconds"])
            split = dict(source)
            split["audio_rows"] = [
                {"start_frame": 0, "end_frame": 130, "source_in_seconds": 0, "path": str(sound)},
                {"start_frame": 130, "end_frame": 225, "source_in_seconds": 2.6, "path": str(sound)},
            ]
            split["cuts"] = [{"start_frame": 125, "end_frame": 135}]
            across_edit = analyze(split, root / "cache")
            self.assertTrue(across_edit["cuts"][0]["all_channels_exact_zero"])
            self.assertGreater(across_edit["cuts"][0]["checked_sample_frames"], 0)


if __name__ == "__main__":
    unittest.main()
