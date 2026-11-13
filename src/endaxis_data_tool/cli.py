import argparse
from pathlib import Path

from .export import export
from .extract import extract
from .prepare import prepare
from .server import SourceFiles, serve


def main():
    parser = argparse.ArgumentParser(
        description="Export supplementary Endaxis data and serve AKE exports"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    bundles = commands.add_parser("prepare")
    bundles.add_argument("--ake-tool-root", type=Path, required=True)
    bundles.add_argument("--vfs-root", type=Path, required=True)
    key_source = bundles.add_mutually_exclusive_group(required=True)
    key_source.add_argument("--key-file", type=Path)
    key_source.add_argument("--runtime-root", type=Path)
    bundles.add_argument("--output", type=Path, required=True)
    bundles.add_argument("--version", required=True)
    objects = commands.add_parser("extract")
    objects.add_argument("--input", type=Path, required=True)
    objects.add_argument("--output", type=Path, required=True)
    objects.add_argument("--version", required=True)
    publish = commands.add_parser("export")
    publish.add_argument("--manifest", type=Path, required=True)
    publish.add_argument("--output", type=Path, required=True)
    http = commands.add_parser("serve")
    http.add_argument("--json-root", type=Path, required=True)
    http.add_argument("--table-root", type=Path, required=True)
    http.add_argument("--supplemental-root", type=Path, required=True)
    http.add_argument("--version", required=True)
    http.add_argument("--image-root", type=Path)
    http.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(
            args.ake_tool_root,
            args.vfs_root,
            args.key_file,
            args.output,
            args.version,
            args.runtime_root,
        )
    elif args.command == "export":
        export(args.manifest, args.output)
    elif args.command == "extract":
        extract(args.input, args.output, args.version)
    else:
        serve(
            SourceFiles(
                args.json_root,
                args.table_root,
                args.supplemental_root,
                args.version,
                args.image_root,
            ),
            args.port,
        )


if __name__ == "__main__":
    main()
