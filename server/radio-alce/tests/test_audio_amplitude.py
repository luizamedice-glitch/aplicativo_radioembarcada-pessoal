import unittest
from unittest.mock import patch
from types import SimpleNamespace
from audio_amplitude import require_audible, volume_detect


class AudioAmplitudeTests(unittest.TestCase):
    def test_silent_stream_fails_even_when_file_and_decoder_are_valid(self):
        for volume in (-91., -80., float('-inf')):
            with self.assertRaises(AssertionError):
                require_audible({'mean_volume':volume,'max_volume':volume})

    def test_real_signal_passes(self):
        require_audible({'mean_volume':-19.,'max_volume':-15.})

    def test_volumedetect_parses_actual_ffmpeg_fields(self):
        with patch('audio_amplitude.subprocess.run', return_value=SimpleNamespace(
                stderr='[Parsed_volumedetect] mean_volume: -91.0 dB\nmax_volume: -91.0 dB')):
            levels=volume_detect('fixture.mp3')
        with self.assertRaises(AssertionError): require_audible(levels)

    def test_missing_amplitude_report_is_not_success(self):
        with patch('audio_amplitude.subprocess.run',return_value=SimpleNamespace(stderr='HTTP 200')):
            with self.assertRaises(AssertionError): volume_detect('fixture.mp3')
