"""Run in the audio image: python -m unittest discover -s /tests -v."""

import asyncio
import io
import subprocess
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app import chatterbox_engine as cloning
from app import kokoro_engine as kokoro
from app import audio_encode


class AudioEncodingRegressionTests(unittest.TestCase):
    def test_concatenated_mp3_sentences_decode_without_header_errors(self):
        import soundfile as sf

        sample_rate = 24000
        signal = 0.1 * np.sin(2 * np.pi * 440 * np.arange(sample_rate) / sample_rate)
        wav = io.BytesIO()
        sf.write(wav, signal, sample_rate, format="WAV")
        encoded = audio_encode.encode(wav.getvalue(), "mp3")
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-i", "pipe:0", "-f", "s16le", "pipe:1"],
            input=encoded + encoded, capture_output=True, check=True,
        )
        self.assertEqual(result.stderr, b"")
        self.assertGreaterEqual(len(result.stdout), sample_rate * 2 * 2)


class KokoroRegressionTests(unittest.TestCase):
    def test_long_clause_stays_after_earlier_clause(self):
        text = "Keep this first, " + "then continue with the rest of the message " * 12
        chunks = kokoro._chunk_long(text.strip())
        self.assertEqual(" ".join(chunks), text.strip())
        self.assertTrue(all(len(chunk) <= 400 for chunk in chunks))

    def test_unbroken_text_is_bounded_without_losing_characters(self):
        text = "a" * 1100
        chunks = kokoro._chunk_long(text)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= 400 for chunk in chunks))

    def test_overflow_retries_preserve_speech_in_both_output_paths(self):
        text = "one two three four five six seven eight nine ten"
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                spoken = []

                def create(chunk, **kwargs):
                    if len(chunk) > 15:
                        raise IndexError("voice embedding token overflow")
                    spoken.append(chunk)
                    return np.zeros(100, dtype=np.float32), 24000

                with patch.object(kokoro, "_kokoro", SimpleNamespace(create=create)):
                    if streaming:
                        outputs = list(kokoro.synthesize_stream(text, "voice", "b", 1.0, "wav"))
                        self.assertTrue(outputs)
                    else:
                        self.assertTrue(kokoro.synthesize(text, "voice", "b", 1.0, "wav"))
                self.assertEqual(" ".join(spoken), text)

    def test_unrecoverable_overflow_is_reported(self):
        def create(*args, **kwargs):
            raise IndexError("broken model")

        with patch.object(kokoro, "_kokoro", SimpleNamespace(create=create)):
            with self.assertRaisesRegex(RuntimeError, "minimal chunk"):
                kokoro._create_samples("x", "voice", "b", 1.0)


class ConditioningRegressionTests(unittest.TestCase):
    def make_model(self):
        model = SimpleNamespace(conds={"voice": "default", "settings": [0.5]})

        def prepare(reference, exaggeration):
            model.conds = {"voice": reference, "settings": [exaggeration]}

        model.prepare_conditionals = prepare
        return model

    def test_default_is_restored_after_reference_and_failed_generation(self):
        model = self.make_model()
        default = model.conds
        with self.assertRaisesRegex(ValueError, "generation failed"):
            with cloning._voice_conditioning(model, "alice", 0.7):
                self.assertEqual(model.conds["voice"], "alice")
                raise ValueError("generation failed")
        self.assertIs(model.conds, default)
        with cloning._voice_conditioning(model, None, 0.5):
            model.conds["settings"][0] = 0.9
            self.assertEqual(model.conds["voice"], "default")
        self.assertEqual(default["settings"], [0.5])

    def test_concurrent_requests_do_not_change_each_others_voice(self):
        model = self.make_model()

        def request(voice):
            with cloning._voice_conditioning(model, voice, 0.5):
                time.sleep(0.01)
                return model.conds["voice"]

        voices = ["alice", "bob", "carol", "dave"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(request, voices)), voices)
        self.assertEqual(model.conds["voice"], "default")

    def test_single_multilingual_model_handles_english_with_v3_parameters(self):
        import torch

        calls = []
        model = self.make_model()
        model.sr = 24000

        def generate(text, **kwargs):
            calls.append(kwargs)
            return torch.zeros(1, 100)

        model.generate = generate
        with (
            patch.object(cloning, "_en_model", None),
            patch.object(cloning, "_mtl_model", model),
            patch.object(cloning.config, "CHATTERBOX_ENGLISH_MODEL", "multilingual"),
            patch.object(cloning.config, "CHATTERBOX_MULTILINGUAL_VERSION", "v3"),
        ):
            self.assertTrue(cloning.synthesize("Hello.", language="en"))
        self.assertEqual(calls[0]["language_id"], "en")
        self.assertEqual(calls[0]["repetition_penalty"], 1.2)


class TranscriptionRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcription_leaves_event_loop_responsive(self):
        from starlette.datastructures import UploadFile
        from app import main

        release = threading.Event()
        observed = []

        def transcribe(*args, **kwargs):
            observed.append(release.wait(timeout=1))
            return {"text": "hello"}

        async def other_request():
            await asyncio.sleep(0.02)
            release.set()

        task = asyncio.create_task(other_request())
        with patch.object(main.whisper_engine, "transcribe_bytes", transcribe):
            result = await main.transcriptions(
                file=UploadFile(io.BytesIO(b"audio"), filename="test.wav"),
                model="whisper-1", language=None, response_format="json",
            )
        await task
        self.assertEqual(observed, [True])
        self.assertEqual(result.status_code, 200)


if __name__ == "__main__":
    unittest.main()
