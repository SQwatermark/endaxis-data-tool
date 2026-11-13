"""Endfield bundle wire constants and the sampled-block transform.

These are format parameters, not a VFS runtime key. The outer BLC/CHK layer
and its runtime key remain owned by AKE's resource preparation.
"""

from functools import lru_cache

SUBSTITUTION = bytes.fromhex(
    "e4b9450792822f43f5c92225a94f466d4a718b6c8cebb2accf0c9e013832d393"
    "9863da96e5c4c36b7f2672d797d580bc5dbb55671073b38de2352947a8603fc5"
    "ef68ecbeabc6b85cd8150954f37a40a2300adc53fadbf178deadf0b5c1819f3e"
    "839031f2fb21288506cacd1ed43ca0c823166e891de7ee5e42bdcb1350a64e49"
    "58df2c8487b69152dd19f92b4d77ba04a541ce943d5ffc9b799a7e655ab16634"
    "56a71abfea7d270b592eae1433c05139c73a2a9df47cccd1d670370e75021be3"
    "e9480d242df7d2b7afa3a1647bedf805953b74fd62d00fff4baa885b03b4e89c"
    "b0171c7657e0a44420d98e11866936fe4c6f616a8fe1188a1299e61f0008f6c2"
)
KEY = bytes.fromhex("3af18c47b2096dee5124907c18d3a462")
IV = bytes.fromhex("c7125ea904db3388f20e774965ba1c93")
FEEDBACK = (0xF19AB7752CDD0196).to_bytes(8, "little")


def rotate(value, bits, width=32):
    bits %= width
    mask = (1 << width) - 1
    return ((value << bits) | (value >> (width - bits))) & mask


def _xtime(value):
    return ((value << 1) ^ (0x11B if value & 128 else 0)) & 255


@lru_cache(maxsize=1)
def _round_keys():
    words = [list(KEY[i : i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for index in range(4, 44):
        word = words[-1][:]
        if index % 4 == 0:
            word = [SUBSTITUTION[x] for x in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([a ^ b for a, b in zip(words[index - 4], word)])
    return [sum(words[i : i + 4], []) for i in range(0, 44, 4)]


def _keystream(block):
    keys = _round_keys()
    state = [a ^ b for a, b in zip(block, keys[0])]
    for turn in range(1, 11):
        substituted = [SUBSTITUTION[x] for x in state]
        state = [
            substituted[((column + row) % 4) * 4 + row]
            for column in range(4)
            for row in range(4)
        ]
        if turn != 10:
            for start in range(0, 16, 4):
                a, b, c, d = state[start : start + 4]
                total = a ^ b ^ c ^ d
                state[start : start + 4] = [
                    a ^ total ^ _xtime(a ^ b),
                    b ^ total ^ _xtime(b ^ c),
                    c ^ total ^ _xtime(c ^ d),
                    d ^ total ^ _xtime(d ^ a),
                ]
        state = [a ^ b for a, b in zip(state, keys[turn])]
    return state


def _transform(data):
    output = bytearray()
    feedback = IV
    for start in range(0, len(data), 16):
        stream = _keystream(feedback)
        output.extend(a ^ b for a, b in zip(data[start : start + 16], stream))
        feedback = [
            SUBSTITUTION[rotate(value ^ ((31 * i) & 255) ^ FEEDBACK[i % 8], 3, 8)]
            for i, value in enumerate(stream)
        ]
    return output


def transform_block(data):
    if len(data) <= 256:
        return bytes(_transform(data))
    block_count = len(data) // 16
    step = max(1, 256 // block_count)
    positions = [
        block * 16 + byte
        for block in range(min(block_count, 256))
        for byte in range(step)
    ]
    sampled = bytearray(256)
    for index, position in enumerate(positions):
        sampled[index] = data[position]
    decoded = _transform(sampled)
    output = bytearray(data)
    for index, position in enumerate(positions):
        output[position] = decoded[index]
    return bytes(output)
