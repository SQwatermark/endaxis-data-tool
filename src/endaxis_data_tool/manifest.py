"""Read only the asset-to-bundle records needed by the data exporter."""

import struct

import brotli

HEAD1 = 0xFF11FF11
HEAD2 = 0xF1F2F3F4
BUNDLE_RECORD_SIZE = 48
ASSET_RECORD_SIZE = 24
SCHEMA_VERSION = 3


def _dotnet_string(data: bytes, offset: int) -> tuple[str, int]:
    length = struct.unpack_from("<I", data, offset)[0]
    start = offset + 4
    end = start + length * 2
    if end > len(data):
        raise ValueError(f"UTF-16 string exceeds manifest at 0x{offset:x}")
    return data[start:end].decode("utf-16-le"), end


def _header(data: bytes) -> tuple[dict, int]:
    if struct.unpack_from("<I", data)[0] != HEAD1:
        raise ValueError("invalid HGM manifest header")
    version, offset = _dotnet_string(data, 4)
    if struct.unpack_from("<I", data, offset)[0] != HEAD2:
        raise ValueError("invalid HGM manifest body header")
    manifest_hash, offset = _dotnet_string(data, offset + 4)
    perforce_cl, offset = _dotnet_string(data, offset)
    return {
        "version": version,
        "hash": manifest_hash,
        "perforceCL": perforce_cl,
    }, offset


def _layout(data: bytes, body_offset: int) -> tuple[int, int, int, int, int]:
    first_value_offset, asset_count = struct.unpack_from("<II", data, body_offset)
    assets_offset = body_offset + 8 + asset_count * 8
    bundle_table = body_offset + first_value_offset + 4
    bundle_value_offset, bundle_count = struct.unpack_from("<II", data, bundle_table)
    bundle_values = bundle_table + bundle_value_offset
    if struct.unpack_from("<I", data, bundle_values + 8)[0] != bundle_count:
        raise ValueError("bundle count mismatch")
    bundles_offset = bundle_values + 12
    data_offset = bundles_offset + bundle_count * BUNDLE_RECORD_SIZE + 4
    return assets_offset, asset_count, bundles_offset, bundle_count, data_offset


def _ref_string(data: bytes, base: int, ref: int) -> str:
    offset = base + ref
    byte_count = struct.unpack_from("<i", data, offset)[0]
    if byte_count < 0 or offset + 4 + byte_count > len(data):
        raise ValueError(f"invalid manifest string at 0x{offset:x}")
    return data[offset + 4 : offset + 4 + byte_count].decode("utf-16-le")


def _compressed_string(data: bytes, base: int, ref: int) -> str:
    offset = base + ref
    byte_count = struct.unpack_from("<I", data, offset)[0]
    if offset + 4 + byte_count > len(data):
        raise ValueError(f"invalid compressed string at 0x{offset:x}")
    return brotli.decompress(data[offset + 4 : offset + 4 + byte_count]).decode(
        "utf-16-le"
    )


def assets(payload: bytes):
    data = brotli.decompress(payload)
    header, body = _header(data)
    asset_start, count, bundle_start, bundle_count, base = _layout(data, body)
    if asset_start < 0 or bundle_start < 0 or base > len(data):
        raise ValueError("Invalid manifest layout")
    bundles = []
    for i in range(bundle_count):
        row = struct.unpack_from("<6I4I2I", data, bundle_start + i * BUNDLE_RECORD_SIZE)
        if row[0] != i:
            raise ValueError("Invalid bundle index")
        bundles.append(_ref_string(data, base, row[1]))
    for i in range(count):
        _, ref, bundle, size, padding = struct.unpack_from(
            "<qIiiI", data, asset_start + i * ASSET_RECORD_SIZE
        )
        if padding or not 0 <= bundle < bundle_count or size < 0:
            raise ValueError("Invalid asset record")
        path = _compressed_string(data, base, ref).replace(chr(92), "/").lower()
        yield path, bundles[bundle]
