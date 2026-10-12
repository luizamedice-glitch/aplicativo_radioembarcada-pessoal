import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from horoscope import CHAPTER, SIGNS, HoroscopeProvider, parse_episodes, seconds


def rss(date="12 de Outubro de 2026", timestamps=True):
    lines = [f"{i//60:02d}:{i%60:02d} - {sign}" for i, sign in
             zip(range(6, 6 + 12 * 42, 42), SIGNS)]
    lines += ["08:30 - Encerramento"]
    description = "\n".join(lines) if timestamps else "sem marcas"
    return f"""<rss><channel><item><title>Horóscopo do Dia, Segunda-feira, {date}. Todos os signos.</title>
    <pubDate>Mon, 12 Oct 2026 11:00:00 GMT</pubDate>
    <description><![CDATA[{description}]]></description>
    <enclosure url="https://example.com/episode.mp3" type="audio/mpeg"/>
    </item></channel></rss>""".encode()


class HoroscopeTests(unittest.TestCase):
    def test_time_marks(self):
        self.assertEqual(seconds("08:30"), 510)
        self.assertTrue(CHAPTER.search("01:42 - Gêmeos"))

    def test_parsing(self):
        episode = parse_episodes(rss(), "2026-10-12")
        self.assertIsNotNone(episode)
        self.assertEqual(len(episode["points"]), 13)
        self.assertEqual(episode["points"][0], 6)
        self.assertIsNone(parse_episodes(rss(timestamps=False), "2026-10-12"))
        self.assertIsNone(parse_episodes(rss(), "2026-10-13"))

    def test_disabled_does_not_contact_network(self):
        class Storage:
            def get(self, *_):
                return None
        with tempfile.TemporaryDirectory() as root:
            provider = HoroscopeProvider(Path(root), fetch=lambda _: self.fail("unexpected request"))
            with patch("config.HOROSCOPE_PRIVATE_TEST", False):
                self.assertIsNone(provider.slot(1791802800, Storage(), set()))

if __name__ == "__main__":
    unittest.main()
