"""Check real Mercurial compression paths without enabling the GIL."""
from concurrent.futures import ThreadPoolExecutor
from compression import zstd as stdlib
from pathlib import Path
import os
import sys
import sysconfig
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mercurial import policy
from mercurial import wireprotoframing
from mercurial.utils import compression

zstd = policy.importmod('zstd')


class PortableBackend(unittest.TestCase):
    def test_backend_selection(self):
        if sysconfig.get_config_var('Py_GIL_DISABLED'):
            self.assertEqual(policy.policy, b'py')
            self.assertIs(policy.get_zstd(), zstd)
            self.assertFalse(sys._is_gil_enabled())

    def check_roundtrip(self, data):
        for threads in (0, 2):
            compressor = zstd.ZstdCompressor(level=3, threads=threads)
            encoded = compressor.compress(data)
            self.assertEqual(stdlib.decompress(encoded), data)
            stream = compressor.compressobj()
            encoded = stream.compress(data[:17]) + stream.compress(data[17:])
            encoded += stream.flush()
            self.assertEqual(stdlib.decompress(encoded), data)
            decoder = zstd.ZstdDecompressor().decompressobj()
            decoded = b''.join(decoder.decompress(encoded[i:i + 13])
                               for i in range(0, len(encoded), 13))
            self.assertEqual(decoded, data)

    def test_empty_small_large_and_parallel_streams(self):
        inputs = [b'', b'x', b'x' * 8192, os.urandom(32768), b'FT' * 600000]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(self.check_roundtrip, inputs))
        if sysconfig.get_config_var('Py_GIL_DISABLED'):
            self.assertFalse(sys._is_gil_enabled())

    def test_real_revlog_and_stream_compression(self):
        engine = compression.compengines[b'zstd']
        self.assertTrue(engine.available())
        for data in (b'FT' * 8192, b'FT' * 600000):
            encoded = engine.revlogcompressor().compress(data)
            self.assertEqual(engine.revlogcompressor().decompress(encoded), data)
            encoded = b''.join(engine.compressstream([data[:5], data[5:]]))
            self.assertEqual(stdlib.decompress(encoded), data)

    def test_wire_protocol_block_flush_and_window_limit(self):
        encoder = wireprotoframing.zstd8mbencoder(None)
        decoder = wireprotoframing.zstd8mbdecoder(None, [])
        first, second = b'first' * 1000, b'second' * 1000
        block = encoder.encode(first) + encoder.flush()
        self.assertEqual(decoder.decode(block), first)
        final = encoder.encode(second) + encoder.finish()
        self.assertEqual(decoder.decode(final), second)
        oversized = stdlib.compress(
            b'x' * (9 * 1024 * 1024),
            options={stdlib.CompressionParameter.window_log: 24},
        )
        bounded = zstd.ZstdDecompressor(max_window_size=8 * 1048576).decompressobj()
        with self.assertRaises(zstd.ZstdError):
            bounded.decompress(oversized)


if __name__ == '__main__':
    unittest.main()
