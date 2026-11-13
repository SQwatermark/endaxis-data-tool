"""Explicit byte order and bounded views; offsets remain relative to the input."""

from __future__ import annotations

import math
import struct


class FormatError(ValueError):
    pass


class Reader:
    def __init__(self, data, endian="<", *, start=0, length=None, label="input"):
        self.data = memoryview(data)
        self.start = self.pos = start
        self.end = len(self.data) if length is None else start + length
        self.endian = endian
        self.label = label
        if not 0 <= start <= self.end <= len(self.data):
            raise FormatError(f"{label}: invalid byte range")

    @property
    def remaining(self):
        return self.end - self.pos

    def fail(self, message):
        raise FormatError(f"{self.label} at 0x{self.pos:x}: {message}")

    def take(self, size):
        if size < 0 or size > self.remaining:
            self.fail(f"cannot read {size} bytes ({self.remaining} remain)")
        result = self.data[self.pos : self.pos + size]
        self.pos += size
        return result.tobytes()

    def seek(self, position):
        if not self.start <= position <= self.end:
            self.fail(f"invalid position {position}")
        self.pos = position

    def align(self, boundary=4):
        self.seek((self.pos + boundary - 1) // boundary * boundary)

    def number(self, code):
        value = struct.unpack(self.endian + code, self.take(struct.calcsize(code)))[0]
        return value

    def i32(self):
        return self.number("i")

    def u32(self):
        return self.number("I")

    def i64(self):
        return self.number("q")

    def u64(self):
        return self.number("Q")

    def u16(self):
        return self.number("H")

    def u8(self):
        return self.number("B")

    def f32(self):
        return self.number("f")

    def f64(self):
        return self.number("d")

    def boolean(self, *, wide=False):
        value = self.i32() if wide else self.u8()
        if value not in (0, 1):
            self.fail(f"invalid boolean {value}")
        return bool(value)

    def count(self, minimum_size=1, maximum=1_000_000):
        value = self.i32()
        if value < 0 or value > maximum or value * minimum_size > self.remaining:
            self.fail(f"invalid count {value}")
        return value

    def string(self):
        size = self.count()
        value = self.take(size).decode("utf-8", errors="strict")
        self.align()
        return value

    def cstring(self, maximum=65536):
        stop = self.pos
        while stop < min(self.end, self.pos + maximum) and self.data[stop]:
            stop += 1
        if stop == min(self.end, self.pos + maximum):
            self.fail("unterminated string")
        value = self.take(stop - self.pos).decode("utf-8", errors="strict")
        self.take(1)
        return value

    def complete(self):
        if self.remaining:
            self.fail(f"{self.remaining} unconsumed bytes")

    def finite(self, code):
        value = self.number(code)
        if not math.isfinite(value):
            self.fail("non-finite numeric field")
        return value
