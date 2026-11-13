"""SerializedFile metadata, object slices, and external reference identities."""

from __future__ import annotations

from dataclasses import dataclass, field

from .binary import Reader
from .common_strings import COMMON_STRINGS


@dataclass
class TypeNode:
    type: str
    name: str
    size: int = -1
    flags: int = 0
    children: list[TypeNode] = field(default_factory=list)


@dataclass
class SerializedType:
    class_id: int
    nodes: list[TypeNode]
    identity: tuple[str, str, str] | None = None


@dataclass(frozen=True)
class ObjectInfo:
    path_id: int
    offset: int
    size: int
    type_index: int


class SerializedFile:
    def __init__(self, name, data):
        self.name, self.data = name, data
        r = Reader(data, ">", label=name)
        metadata_size, file_size, self.version, data_offset = [
            r.u32() for _ in range(4)
        ]
        endian = r.u8()
        r.take(3)
        if self.version not in (20, 21, 22):
            r.fail(f"unsupported SerializedFile version {self.version}")
        if self.version == 22:
            metadata_size, file_size, data_offset = r.u32(), r.u64(), r.u64()
            r.take(8)
        if (
            file_size != len(data)
            or not r.pos + metadata_size <= data_offset <= file_size
        ):
            r.fail("invalid file/metadata/data bounds")
        if endian not in (0, 1):
            r.fail("invalid byte order")
        self.endian = "<" if endian == 0 else ">"
        r = Reader(
            data,
            self.endian,
            start=r.pos,
            length=metadata_size,
            label=name + " metadata",
        )
        self.unity_version, self.platform, has_tree = r.cstring(), r.i32(), r.boolean()

        def tree():
            count, buffer_size = r.count(32), r.i32()
            records = []
            for _ in range(count):
                r.u16()
                level, _type_flags = r.u8(), r.u8()
                type_offset, name_offset, size = r.u32(), r.u32(), r.i32()
                r.i32()
                flags = r.i32()
                r.u64()
                records.append((level, type_offset, name_offset, size, flags))
            strings = r.take(buffer_size)

            def text(offset):
                if offset & 0x80000000:
                    try:
                        return COMMON_STRINGS[offset & 0x7FFFFFFF]
                    except KeyError:
                        r.fail(
                            f"unknown built-in TypeTree string {offset & 0x7FFFFFFF}"
                        )
                source = Reader(strings, label=name + " type strings")
                source.seek(offset)
                return source.cstring()

            roots, stack = [], []
            for level, t, n, size, flags in records:
                if level > len(stack):
                    r.fail("TypeTree skipped a nesting level")
                del stack[level:]
                node = TypeNode(text(t), text(n), size, flags)
                (stack[-1].children if stack else roots).append(node)
                stack.append(node)
            return roots

        def read_type(reference=False):
            class_id = r.i32()
            r.boolean()
            script_index = r.number("h")
            if (reference and script_index >= 0) or (not reference and class_id == 114):
                r.take(16)
            r.take(16)
            nodes = tree() if has_tree else []
            identity = None
            if has_tree and self.version >= 21:
                if reference:
                    identity = (r.cstring(), r.cstring(), r.cstring())
                else:
                    r.take(r.count(4) * 4)
            return SerializedType(class_id, nodes, identity)

        self.types = [read_type() for _ in range(r.count(23))]
        self.objects = {}
        for _ in range(r.count(20)):
            r.align()
            path_id = r.i64()
            offset = (r.u64() if self.version >= 22 else r.u32()) + data_offset
            size, type_index = r.u32(), r.i32()
            if (
                path_id in self.objects
                or not 0 <= type_index < len(self.types)
                or offset < data_offset
                or offset + size > len(data)
            ):
                r.fail(f"invalid object {path_id}")
            self.objects[path_id] = ObjectInfo(path_id, offset, size, type_index)
        for _ in range(r.count(12)):
            r.i32()
            r.align()
            r.i64()
        self.externals = []
        for _ in range(r.count(22)):
            r.cstring()
            r.take(16)
            r.i32()
            self.externals.append(r.cstring().replace("\\", "/").rsplit("/", 1)[-1])
        self.ref_types = {}
        for _ in range(r.count(23)):
            entry = read_type(True)
            if entry.identity:
                if entry.identity in self.ref_types:
                    r.fail(f"duplicate reference type {entry.identity}")
                self.ref_types[entry.identity] = entry.nodes
        self.user_information = r.cstring()
        r.complete()

    def raw(self, info):
        return self.data[info.offset : info.offset + info.size]

    def reader(self, info):
        return Reader(self.raw(info), self.endian, label=f"{self.name}:{info.path_id}")
