"""Block decoding, including the Endfield token/offset variant of LZ4."""

import lzma

from .binary import FormatError, Reader

MAX_BLOCK_BYTES = 256 * 1024 * 1024


def lz4(data, size, *, inverted=False):
    if not 0 <= size <= MAX_BLOCK_BYTES:
        raise FormatError(f"invalid decoded block size {size}")
    source = Reader(data, label="LZ4 block")
    output = bytearray()

    def length(n):
        if n == 15:
            while True:
                extra = source.u8()
                n += extra
                if extra != 255:
                    break
        return n

    while source.remaining:
        token = source.u8()
        if inverted:
            literals = (token & 3) | ((token >> 2) & 12)
            matches = ((token >> 2) & 3) | ((token >> 4) & 12)
        else:
            literals, matches = token >> 4, token & 15
        literal_count = length(literals)
        if len(output) + literal_count > size:
            source.fail("literal exceeds output boundary")
        output.extend(source.take(literal_count))
        if not source.remaining:
            break
        offset = int.from_bytes(source.take(2), "big" if inverted else "little")
        match_count = length(matches) + 4
        if not 0 < offset <= len(output) or len(output) + match_count > size:
            source.fail("invalid match range")
        # Repetition handles overlapping matches without a byte-at-a-time copy.
        pattern = output[-offset:]
        output.extend((pattern * ((match_count + offset - 1) // offset))[:match_count])
    if len(output) != size:
        raise FormatError(f"LZ4 produced {len(output)} bytes, expected {size}")
    return bytes(output)


def decompress(data, size, kind):
    if not 0 <= size <= MAX_BLOCK_BYTES:
        raise FormatError(f"invalid decoded block size {size}")
    if kind == 0:
        result = data
    elif kind == 1:
        # Unity stores LZMA properties followed by the raw stream, without size.
        if len(data) < 5:
            raise FormatError("truncated LZMA properties")
        stream = data[:5] + size.to_bytes(8, "little") + data[5:]
        decoder = lzma.LZMADecompressor(lzma.FORMAT_ALONE, memlimit=MAX_BLOCK_BYTES)
        result = decoder.decompress(stream, max_length=size + 1)
    elif kind in (2, 3):
        return lz4(data, size)
    else:
        raise FormatError(f"unsupported compression {kind}")
    if len(result) != size:
        raise FormatError(f"decoded {len(result)} bytes, expected {size}")
    return result
