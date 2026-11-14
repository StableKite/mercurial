# zstd.py - Mercurial's small streaming interface over stdlib Zstandard
#
# Copyright 2026 Robolightning <irobolightning@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from __future__ import annotations

from compression import zstd as _zstd
import os

__version__ = _zstd.zstd_version
ZstdError = _zstd.ZstdError
COMPRESSION_RECOMMENDED_INPUT_SIZE = 128 * 1024
DECOMPRESSION_RECOMMENDED_INPUT_SIZE = 128 * 1024
COMPRESSOBJ_FLUSH_FINISH = 0
COMPRESSOBJ_FLUSH_BLOCK = 1


class ZstdCompressor:
    def __init__(self, level=3, threads=0):
        self._options = {_zstd.CompressionParameter.compression_level: level}
        if threads:
            self._options[_zstd.CompressionParameter.nb_workers] = (
                (os.cpu_count() or 1) if threads < 0 else threads
            )

    def _new(self):
        return _zstd.ZstdCompressor(options=self._options)

    def compress(self, data):
        context = self._new()
        context.set_pledged_input_size(len(data))
        return context.compress(data, context.FLUSH_FRAME)

    def compressobj(self):
        return _CompressObject(self._new())


class _CompressObject:
    def __init__(self, context):
        self._context = context
        self._finished = False

    def compress(self, data):
        if self._finished:
            raise ZstdError('compression object is already finished')
        return self._context.compress(data)

    def flush(self, mode=COMPRESSOBJ_FLUSH_FINISH):
        if self._finished:
            raise ZstdError('compression object is already finished')
        if mode == COMPRESSOBJ_FLUSH_BLOCK:
            return self._context.flush(self._context.FLUSH_BLOCK)
        if mode != COMPRESSOBJ_FLUSH_FINISH:
            raise ValueError('unknown compression flush mode')
        self._finished = True
        return self._context.flush(self._context.FLUSH_FRAME)


class ZstdDecompressor:
    def __init__(self, max_window_size=0):
        if max_window_size < 0:
            raise ValueError('maximum window size must be nonnegative')
        self._options = {}
        if max_window_size:
            # Mercurial's wire protocol requires a power-of-two byte limit.
            # Rounding down is conservative for other caller-supplied bounds.
            self._options[_zstd.DecompressionParameter.window_log_max] = (
                max_window_size.bit_length() - 1
            )

    def decompressobj(self):
        return _DecompressObject(self._options)


class _DecompressObject:
    def __init__(self, options):
        self._context = _zstd.ZstdDecompressor(options=options)

    def decompress(self, data):
        try:
            return self._context.decompress(data)
        except EOFError as error:
            # Mercurial's stream reader uses ZstdError to recognize EOF.
            raise ZstdError(str(error)) from error
