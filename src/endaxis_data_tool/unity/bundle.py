"""Read standard UnityFS and the current Endfield bundle layout."""

from dataclasses import dataclass

from .binary import FormatError, Reader
from .compression import MAX_BLOCK_BYTES, decompress, lz4
from .endfield_transform import rotate, transform_block


@dataclass(frozen=True)
class BundleEntry:
    name: str
    flags: int
    data: bytes


def _word(high, low):
    return rotate((((high ^ low ^ 0xA121) & 65535) << 16) | low, -18) ^ 0xF74324EE


def _wide(high, low, rotation):
    return (
        rotate(((high ^ low ^ 0xDAD76848) << 32) | low, rotation, 64)
        ^ 0xA4F1A11747816520
    )


def _count(reader, mask, xor):
    encoded = reader.u32() ^ mask
    lo = encoded & 65535
    value = rotate(((((encoded >> 16) ^ lo) & 65535) << 16) | lo, -18) ^ xor
    if value > 1_000_000:
        reader.fail(f"invalid directory/block count {value}")
    return value


def _endfield(data):
    r = Reader(data, ">", label="Endfield bundle")
    first, check = r.u32(), r.u32()
    seed = first ^ 0x4A92F0CD
    if check != (((seed << 2) & 0xFFFF0000) ^ rotate(seed, -14) ^ 0xD8B1E637):
        r.fail("unknown bundle header")
    packed_low, flags_low, layout = r.u16(), r.u32(), r.u32()
    size_low, flags_high, plain_high = r.u32(), r.u32(), r.u16()
    r.take(4)
    plain_low, size_high, packed_high = r.u16(), r.u32(), r.u16()
    r.take(1)
    packed_size = _word(packed_high, packed_low)
    plain_size = _word(plain_high, plain_low)
    size = _wide(size_high, size_low, 14)
    flags = flags_high ^ flags_low ^ 0xA7F49310
    if size != len(data):
        r.fail(f"bundle length {len(data)} != declared {size}")
    head_end = 48 if (layout ^ flags_low) >= 7 else 40
    r.seek(size - packed_size if flags & 128 else head_end)
    info = r.take(packed_size)
    if flags & 63:
        info = lz4(transform_block(info), plain_size)
    elif len(info) != plain_size:
        r.fail("uncompressed directory size mismatch")
    meta = Reader(info, ">", label="Endfield directory")
    blocks = []
    for _ in range(_count(meta, 0x23F77B8A, 0x91CE0A4F)):
        a, b, c, f, d = [meta.u16() for _ in range(5)]
        f ^= 0x9CD6
        decoded_flags = (
            c
            ^ rotate(((((f & 255) ^ (f >> 8)) & 255) << 8) | (f & 255), 14, 16)
            ^ 0x523F
        ) & 65535
        blocks.append((_word(b, d), _word(a, c), decoded_flags))
    directory = []
    for _ in range(_count(meta, 0x6B0AE55D, 0xE4C1D9F2)):
        a, b, c, d = meta.u32() ^ 0x8E06A9F8, meta.u32(), meta.u32(), meta.u32()
        encoded_name = bytearray()
        for _ in range(65):
            byte = meta.u8()
            if byte == 0:
                break
            encoded_name.append(byte)
        else:
            meta.fail("unterminated CAB name")
        name = bytes(byte ^ (i ^ 0x97) for i, byte in enumerate(encoded_name)).decode(
            "ascii"
        )
        e = meta.u32()
        f = (
            rotate(((((a >> 16) ^ a) & 65535) << 16) | (a & 65535), -18)
            ^ 0xF13927C4
            ^ b
        )
        directory.append((name, f, _wide(d, c, 14), _wide(b, e, 14)))
    meta.complete()
    data_start = head_end
    if not flags & 128:
        data_start += ((packed_size + 15) & ~15) if flags & 512 else packed_size
    r.seek(data_start)
    parts = []
    total = 0
    for packed, plain, kind in blocks:
        total += plain
        if total > MAX_BLOCK_BYTES:
            r.fail("bundle exceeds configuration size limit")
        block = r.take(packed)
        if kind == 5:
            block = lz4(transform_block(block), plain, inverted=True)
        elif kind == 0 and packed == plain:
            pass
        else:
            r.fail(f"unsupported Endfield block compression {kind}")
        parts.append(block)
    return _entries(b"".join(parts), directory)


def _entries(payload, directory):
    names = set()
    result = []
    for name, flags, offset, size in directory:
        if name in names or offset < 0 or size < 0 or offset + size > len(payload):
            raise FormatError(f"invalid or duplicate bundle entry {name!r}")
        names.add(name)
        result.append(BundleEntry(name, flags, payload[offset : offset + size]))
    return result


def read_bundle(data):
    if not data.startswith(b"UnityFS\0"):
        return _endfield(data)
    r = Reader(data, ">", label="UnityFS bundle")
    r.cstring()
    version = r.u32()
    if version not in (6, 7, 8):
        r.fail(f"unsupported UnityFS version {version}")
    r.cstring()
    r.cstring()
    size, packed, plain, flags = r.u64(), r.u32(), r.u32(), r.u32()
    if size != len(data):
        r.fail("bundle size mismatch")
    if version >= 7:
        r.align(16)
    head_end = r.pos
    if flags & 128:
        r.seek(size - packed)
    info = Reader(
        decompress(r.take(packed), plain, flags & 63), ">", label="UnityFS directory"
    )
    info.take(16)
    blocks = []
    for _ in range(info.count(10)):
        unpacked, compressed, kind = info.u32(), info.u32(), info.u16()
        blocks.append((compressed, unpacked, kind & 63))
    directory = []
    for _ in range(info.count(21)):
        offset, length, kind = info.u64(), info.u64(), info.u32()
        directory.append((info.cstring(), kind, offset, length))
    info.complete()
    r.seek(head_end if flags & 128 else head_end + packed)
    if flags & 512:
        r.align(16)
    if sum(block[1] for block in blocks) > MAX_BLOCK_BYTES:
        r.fail("bundle exceeds configuration size limit")
    payload = b"".join(
        decompress(r.take(packed), plain, kind) for packed, plain, kind in blocks
    )
    return _entries(payload, directory)
