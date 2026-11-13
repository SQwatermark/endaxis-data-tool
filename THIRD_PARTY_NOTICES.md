# Third-party components

AKE Data Tool is loaded from a caller-provided checkout for VFS resource preparation. It is not bundled in this repository. Its own source and dependency licenses apply to that checkout.

The Python resource reader implements the UnityFS, SerializedFile, TypeTree and Endfield configuration bundle formats. Format validation uses synthetic inputs and independently generated resource exports; game assets are not bundled.

Python dependencies are declared in `pyproject.toml` and retain their respective licenses. No .NET assemblies or native animation libraries are distributed by this package.
