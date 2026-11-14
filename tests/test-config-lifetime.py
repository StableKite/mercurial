import io
import unittest
from unittest import mock

from mercurial import config, error, util


class ConfigLifetimeTests(unittest.TestCase):
    def test_owned_file_is_closed(self):
        stream = io.BytesIO(b'[ui]\neditor = example\n')
        with mock.patch.object(util, 'posixfile', return_value=stream):
            settings = config.config()
            settings.read(b'example.rc')
        self.assertEqual(settings.get(b'ui', b'editor'), b'example')
        self.assertTrue(stream.closed)

    def test_owned_file_is_closed_after_parse_failure(self):
        stream = io.BytesIO(b'[ui]\ninvalid line\n')
        with mock.patch.object(util, 'posixfile', return_value=stream):
            with self.assertRaises(error.ConfigError):
                config.config().read(b'invalid.rc')
        self.assertTrue(stream.closed)

    def test_caller_owned_file_stays_open(self):
        stream = io.BytesIO(b'[ui]\neditor = example\n')
        self.addCleanup(stream.close)
        settings = config.config()
        settings.read(b'example.rc', fp=stream)
        self.assertEqual(settings.get(b'ui', b'editor'), b'example')
        self.assertFalse(stream.closed)


if __name__ == '__main__':
    import silenttestrunner

    silenttestrunner.main(__name__)
