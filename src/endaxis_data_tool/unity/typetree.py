"""Decode schemas carried by a SerializedFile, with byte ranges for each value."""

import math
import struct
from dataclasses import dataclass, field
from decimal import Decimal

from .binary import FormatError
from .serialized_file import TypeNode

PRIMITIVES = {
    "SInt8": "b",
    "UInt8": "B",
    "char": "H",
    "short": "h",
    "SInt16": "h",
    "UInt16": "H",
    "unsigned short": "H",
    "int": "i",
    "SInt32": "i",
    "UInt32": "I",
    "unsigned int": "I",
    "Type*": "I",
    "long long": "q",
    "SInt64": "q",
    "UInt64": "Q",
    "unsigned long long": "Q",
    "FileSize": "Q",
    "float": "f",
    "double": "d",
}


def float_text(value, *, single=False):
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if single:
        bits = struct.pack("<f", value)
        for precision in range(1, 10):
            text = format(value, f".{precision}g")
            if struct.pack("<f", float(text)) == bits:
                break
    else:
        text = repr(value)
    if "e" in text and 0.0001 <= abs(value) < 1_000_000_000:
        text = format(Decimal(text), "f")
    if "e" not in text and text.endswith(".0"):
        text = text[:-2]
    return text.replace("e", "E")


@dataclass
class Value:
    node: TypeNode
    data: object
    start: int
    end: int
    children: list = field(default_factory=list)
    array: bool = False

    def child(self, name):
        matches = [item for item in self.children if item.node.name == name]
        if len(matches) != 1:
            raise FormatError(f"expected one field {name}, found {len(matches)}")
        return matches[0]


class TypeTreeDecoder:
    def __init__(self, file):
        self.file = file
        self.references = {}
        self.budget = 2_000_000

    def decode(self, info):
        nodes = self.file.types[info.type_index].nodes
        if len(nodes) != 1:
            raise FormatError(f"{self.file.name}:{info.path_id}: missing root TypeTree")
        reader = self.file.reader(info)
        value = self.read(nodes[0], reader)
        reader.complete()
        return value

    def read(self, node, reader, depth=0):
        self.budget -= 1
        if depth > 128 or self.budget < 0:
            reader.fail("TypeTree traversal limit exceeded")
        start, children, array = reader.pos, [], False
        kind = node.type
        if kind in PRIMITIVES:
            data = reader.number(PRIMITIVES[kind])
        elif kind == "bool":
            data = reader.boolean()
        elif kind == "string":
            data = reader.string()
        elif kind == "TypelessData":
            data = reader.take(reader.count())
        elif kind == "ReferencedObject":
            rid = reader.i64()
            identity = (reader.string(), reader.string(), reader.string())
            payload_start = reader.pos
            if rid == -2 and identity == ("", "", ""):
                payload_nodes = []
            else:
                roots = self.file.ref_types.get(identity)
                if not roots or len(roots) != 1:
                    reader.fail(
                        f"missing managed-reference schema {identity} (rid {rid})"
                    )
                payload_nodes = [
                    n
                    for n in roots[0].children
                    if n.type != "ManagedReferencesRegistry"
                ]
            payload = self._fields(payload_nodes, reader, depth + 1)
            data = {
                "rid": rid,
                "type": dict(zip(("class", "ns", "asm"), identity)),
                "data": {item.node.name: item.data for item in payload},
            }
            children = payload
            if rid in self.references:
                reader.fail(f"duplicate managed reference {rid}")
            self.references[rid] = (identity, payload_start, reader.pos, payload)
        elif node.children and node.children[0].type == "Array":
            array = True
            schema = node.children[0]
            if len(schema.children) != 2 or schema.children[0].name != "size":
                reader.fail(f"invalid array schema {node.name}")
            count = reader.count(0, maximum=1_000_000)
            for _ in range(count):
                children.append(self.read(schema.children[1], reader, depth + 1))
            data = [item.data for item in children]
            if schema.flags & 0x4000:
                reader.align()
        else:
            if not node.children and node.size != 0:
                reader.fail(f"unknown leaf {kind} {node.name}")
            children = self._fields(node.children, reader, depth + 1)
            data = {item.node.name: item.data for item in children}
        if node.flags & 0x4000:
            reader.align()
        return Value(node, data, start, reader.pos, children, array)

    def _fields(self, nodes, reader, depth):
        names = [node.name for node in nodes]
        if len(set(names)) != len(names):
            reader.fail("duplicate TypeTree field names")
        return [self.read(node, reader, depth) for node in nodes]


def dump_text(root):
    lines = []

    def line(level, text):
        lines.append("\t" * level + text)

    def render(value, level):
        node, data = value.node, value.data
        heading = f"{node.type} {node.name}"
        if node.type == "ReferencedObject":
            line(level, heading)
            line(level + 1, f"SInt64 rid = {data['rid']}")
            line(level + 1, "ReferencedManagedType type")
            for key, text in data["type"].items():
                line(level + 2, f'string {key} = "{text}"')
            line(level + 1, "ReferencedObjectData data")
            for child in value.children:
                render(child, level + 2)
        elif node.type == "string":
            line(level, f'{heading} = "{data}"')
        elif node.type in PRIMITIVES or node.type == "bool":
            if node.type in ("float", "double"):
                text = float_text(data, single=node.type == "float")
            elif node.type == "bool":
                text = "True" if data else "False"
            elif node.type == "char":
                text = chr(data)
            else:
                text = str(data)
            line(level, f"{heading} = {text}")
        elif node.type == "TypelessData":
            line(level, heading)
            line(level, f"int size = {len(data)}")
        elif value.array:
            line(level, heading)
            line(level + 1, "Array Array")
            line(level + 1, f"int size = {len(value.children)}")
            for index, child in enumerate(value.children):
                line(level + 2, f"[{index}]")
                render(child, level + 2)
        else:
            line(level, heading)
            for child in value.children:
                render(child, level + 1)

    render(root, 0)
    return "\r\n".join(lines) + "\r\n"
