"""Run inside signal-bot: python -m unittest discover -s data/custom_skills/music_download -p 'test_*.py'."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import music

trim = music._trim_mod


class TrimTests(unittest.TestCase):
    def test_offsets(self):
        for value, expected in [('1:25', 85), ('85', 85), ('01:02:03.5', 3723.5), ('0', 0)]:
            self.assertEqual(trim.parse_offset(value), expected)
        for value in ['-1', 'nan', 'inf', '1:60', '1:99:00', '', '85 garbage']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                trim.parse_offset(value)

    def test_command_flags(self):
        self.assertEqual(
            music._parse_trim_options('rock https://example.com/a --trim-start 1:25', None, None),
            ('rock https://example.com/a', True, 85, 0),
        )
        self.assertEqual(music._parse_trim_options('url', '85', '2'), ('url', True, 85, 2))
        self.assertEqual(music._parse_trim_options("artist's song", None, None), ("artist's song", False, 0, 0))
        for text in ['url --trim-start', 'url --trim-start nope', 'url --trim-start 2 --trim-start 3']:
            with self.assertRaises(ValueError):
                music._parse_trim_options(text, None, None)

    def test_trailing_offset_and_youtube_links(self):
        base = 'https://www.youtube.com/watch?v=gYC9HkdDNYA'
        for suffix in [' 1:25', ' 85', '&t=85', '&t=85s', '&t=1m25s', '&start=85', '#t=1m25s']:
            with self.subTest(suffix=suffix):
                self.assertEqual(music._parse_trim_options('rock ' + base + suffix, None, None),
                                 ('rock ' + base, True, 85, 0))
        self.assertEqual(music._parse_trim_options('https://youtu.be/id?si=abc&t=1h2m3s', None, None),
                         ('https://youtu.be/id?si=abc', True, 3723, 0))
        self.assertEqual(music._parse_trim_options(base + '&t=30s 1:25', None, None),
                         (base, True, 85, 0))
        self.assertEqual(music._parse_trim_options(base + '&t=30s', '0', None),
                         (base, True, 0, 0))
        self.assertEqual(music._parse_trim_options('https://example.com/?t=85', None, None),
                         ('https://example.com/?t=85', False, 0, 0))
        for suffix in [' 1:99', ' -5', '&t=garbage', '&t=85&start=30']:
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                music._parse_trim_options(base + suffix, None, None)

    def test_shorthand_reaches_trimmer_with_clean_source(self):
        base = 'https://www.youtube.com/watch?v=gYC9HkdDNYA'
        for suffix in [' 1:25', '&t=1m25s']:
            with patch.object(music, 'resolve_from_text', return_value=None), \
                 patch.object(music, 'download_audio', return_value=('Artist', 'Title')) as download, \
                 patch.object(music, 'trim_exact', side_effect=RuntimeError('stop before saving')) as exact, \
                 patch.object(music, 'trim_audio') as auto:
                music.download_music(input='rock ' + base + suffix)
                self.assertEqual(download.call_args.args[0], base)
                self.assertEqual(exact.call_args.args[2:], (85, 0))
                auto.assert_not_called()

    def test_failed_explicit_trim_does_not_save(self):
        with patch.object(music, 'resolve_from_text', return_value=None), \
             patch.object(music, 'download_audio', return_value=('Artist', 'Title')), \
             patch.object(music, 'trim_exact', side_effect=RuntimeError('test failure')), \
             patch.object(music, 'trim_audio') as auto, \
             patch.object(music, 'classify') as classify:
            result = music.download_music(input='https://example.com/audio', trim_start='1:25')
        self.assertIn('No file saved', result)
        auto.assert_not_called()
        classify.assert_not_called()

    def test_real_audio_85_second_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = str(Path(tmp) / 'source.wav'), str(Path(tmp) / 'trim.mp3')
            # First 85 seconds are silent, last 15 seconds are a tone.
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'aevalsrc=if(lt(t\\,85)\\,0\\,0.5*sin(2*PI*440*t)):s=16000:d=100',
                            src], check=True)
            self.assertEqual(trim.trim_exact(src, dest, 85, 0), (85, 0))
            self.assertAlmostEqual(trim._get_duration(dest), 15, delta=0.15)
            # Verify content at the cut, not only the resulting duration.
            import array
            decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', dest, '-t', '1',
                                      '-f', 'f32le', '-acodec', 'pcm_f32le', '-'],
                                     capture_output=True, check=True).stdout
            samples = array.array('f', decoded)
            rms = (sum(x*x for x in samples) / len(samples)) ** 0.5
            self.assertGreater(rms, 0.3)
            trim.trim_exact(src, dest, 85, 5)
            self.assertAlmostEqual(trim._get_duration(dest), 10, delta=0.15)
            with self.assertRaises(ValueError):
                trim.trim_exact(src, dest, 100, 0)


if __name__ == '__main__':
    unittest.main()
