"""Small, game-resource-free SerializedFile/UnityFS writers for reader checks."""

import struct

from endaxis_data_tool.unity.serialized_file import TypeNode as N


def aligned_string(text):
    data = text.encode("utf-8")
    output = struct.pack("<i", len(data)) + data
    return output + bytes(-len(output) % 4)


def array(name, element, kind="vector"):
    return N(
        kind,
        name,
        children=[N("Array", "Array", children=[N("int", "size", 4), element])],
    )


def serialized_file(types, objects):
    meta = bytearray(b"2021.3.34f5\0" + struct.pack("<i?i", 19, True, len(types)))
    for class_id, root in types:
        nodes, strings = [], bytearray()

        def text(value):
            offset = len(strings)
            strings.extend(value.encode() + b"\0")
            return offset

        def walk(node, depth):
            nodes.append(
                struct.pack(
                    "<HBBIIiiiQ",
                    1,
                    depth,
                    0,
                    text(node.type),
                    text(node.name),
                    node.size,
                    len(nodes),
                    node.flags,
                    0,
                )
            )
            for child in node.children:
                walk(child, depth + 1)

        walk(root, 0)
        meta.extend(struct.pack("<i?h", class_id, False, -1))
        meta.extend(bytes(32 if class_id == 114 else 16))
        meta.extend(struct.pack("<ii", len(nodes), len(strings)))
        meta.extend(b"".join(nodes) + strings + struct.pack("<i", 0))
    meta.extend(struct.pack("<i", len(objects)))
    payload = bytearray()
    for path_id, type_index, raw in objects:
        meta.extend(bytes(-len(meta) % 4))
        payload.extend(bytes(-len(payload) % 8))
        meta.extend(struct.pack("<qqIi", path_id, len(payload), len(raw), type_index))
        payload.extend(raw)
    meta.extend(struct.pack("<iii", 0, 0, 0) + b"\0")
    offset = (48 + len(meta) + 15) & ~15
    header = struct.pack(">4I", 0, 0, 22, 0) + bytes(4)
    header += struct.pack(">IQQQ", len(meta), offset + len(payload), offset, 0)
    return header + meta + bytes(offset - 48 - len(meta)) + payload


def unityfs(name, payload):
    info = bytes(16) + struct.pack(
        ">iIIHiQQI", 1, len(payload), len(payload), 0, 1, 0, len(payload), 4
    )
    info += name.encode() + b"\0"
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0fixture\0"
    header = prefix + struct.pack(
        ">QIII", len(prefix) + 20 + len(info) + len(payload), len(info), len(info), 0x40
    )
    return header + info + payload


def configuration_bundle(path_id=11):
    path = "assets/beyond/dynamicassets/gamedata/gameplayconfig/skillsetting.asset"
    pointer = lambda name: N(
        "PPtr<Object>",
        name,
        children=[N("int", "m_FileID", 4), N("SInt64", "m_PathID", 8)],
    )
    asset_info = N(
        "AssetInfo",
        "second",
        children=[
            N("int", "preloadIndex", 4),
            N("int", "preloadSize", 4),
            pointer("asset"),
        ],
    )
    pair = N("pair", "data", children=[N("string", "first"), asset_info])
    bundle_type = N(
        "AssetBundle",
        "Base",
        children=[
            N("string", "m_Name"),
            array("m_PreloadTable", pointer("data")),
            array("m_Container", pair, "map"),
        ],
    )
    config_type = N(
        "MonoBehaviour",
        "Base",
        children=[N("string", "m_Name"), N("float", "factor", 4)],
    )
    config = aligned_string("skillsetting") + struct.pack("<f", 0.35)
    bundle = aligned_string("fixture") + struct.pack("<iiq", 1, 0, path_id)
    bundle += (
        struct.pack("<i", 1)
        + aligned_string(path)
        + struct.pack("<iiiq", 0, 1, 0, path_id)
    )
    data = serialized_file(
        [(114, config_type), (142, bundle_type)],
        [(path_id, 0, config), (22, 1, bundle)],
    )
    return unityfs("CAB-synthetic", data), path
