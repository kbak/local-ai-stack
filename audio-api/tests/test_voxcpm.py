"""VoxCPM adapter contracts, without loading model weights or a GPU."""

import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from app import config, voxcpm_engine as engine
from app.inference import validate_audio_gpu


class VoxCPMAdapterTests(unittest.TestCase):
    def setUp(self):
        self.model = SimpleNamespace(
            tts_model=SimpleNamespace(sample_rate=48000),
            generate=Mock(return_value=np.full(4800, 0.1, dtype=np.float32)),
        )
        self.model_patch = patch.object(engine, "_model", self.model)
        self.model_patch.start()
        self.addCleanup(self.model_patch.stop)

    def test_long_text_preserves_every_word_at_native_sample_rate(self):
        text = "Read this first. " + "Continue with all the remaining words " * 25 + "That is the end."
        wav = engine.synthesize(text, language="en")
        calls = self.model.generate.call_args_list
        self.assertGreater(len(calls), 1)
        self.assertEqual(" ".join(call.kwargs["text"] for call in calls), text)
        self.assertTrue(all(len(call.kwargs["text"]) <= 350 for call in calls))
        samples, rate = sf.read(io.BytesIO(wav))
        self.assertEqual(rate, 48000)
        self.assertEqual(len(samples), len(calls) * 4800 + (len(calls) - 1) * 9600)
        # Chatterbox's default cfg_weight=0.5 must not override VoxCPM's CFG=2.
        self.assertEqual(calls[0].kwargs["cfg_value"], 2.0)
        self.assertFalse(calls[0].kwargs["normalize"])
        self.assertFalse(calls[0].kwargs["denoise"])

    def test_reference_is_not_reused_when_next_request_omits_voice(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "speaker.wav"
            reference.touch()
            with patch.object(config, "VOICE_SAMPLES_DIR", Path(directory)):
                engine.synthesize("Dzień dobry.", voice="speaker", language="pl")
                engine.synthesize("Hello.", language="en")
        calls = self.model.generate.call_args_list
        self.assertEqual(calls[0].kwargs["reference_wav_path"], str(reference))
        self.assertIsNone(calls[1].kwargs["reference_wav_path"])

    def test_failed_later_chunk_does_not_return_partial_audio(self):
        self.model.generate.side_effect = [np.zeros(4800), np.array([float("nan")])]
        with self.assertRaisesRegex(RuntimeError, "invalid audio"):
            engine.synthesize("A long sentence with several words. " * 15)

    def test_bad_inputs_are_rejected_before_inference(self):
        for kwargs in ({"text": " "}, {"text": "Hello", "language": "xx"},
                       {"text": "Hello", "response_format": "invalid"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                engine.synthesize(**kwargs)
        with self.assertRaises(FileNotFoundError):
            engine.synthesize("Hello", voice="/missing/reference.wav")
        self.model.generate.assert_not_called()

    def test_rest_and_mcp_use_the_selected_backend(self):
        from fastapi.testclient import TestClient
        from app import main, cloning_engine

        self.assertIs(cloning_engine.synthesize, engine.synthesize)
        with patch.object(cloning_engine, "synthesize", return_value=b"RIFFtest") as generate:
            response = TestClient(main.app).post("/v1/audio/clone", json={
                "text": "Dzień dobry.", "voice": "speaker", "language": "pl",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"RIFFtest")
            result = main.clone_voice("Hello.", voice="speaker", language="en")
            self.assertEqual(result["bytes"], 8)
            self.assertEqual(generate.call_count, 2)
        self.assertIn("pl", cloning_engine.supported_languages())
        self.assertEqual(main.clone_voices()["backend"], "voxcpm2")


class AudioGPUIsolationTests(unittest.TestCase):
    def test_rejects_wrong_gpu_or_multiple_visible_gpus(self):
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "GPU-audio"}):
            with patch("torch.cuda.device_count", return_value=2):
                with self.assertRaisesRegex(RuntimeError, "Exactly one"):
                    validate_audio_gpu()
            with patch("torch.cuda.device_count", return_value=1):
                with patch("torch.cuda.get_device_name", return_value="NVIDIA RTX PRO 6000"):
                    with self.assertRaisesRegex(RuntimeError, "Audio GPU must"):
                        validate_audio_gpu()
                with patch("torch.cuda.get_device_name", return_value="NVIDIA GeForce RTX 5060 Ti"):
                    validate_audio_gpu()


if __name__ == "__main__":
    unittest.main()
