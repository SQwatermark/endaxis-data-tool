# Third-party components

AKE Data Tool is part of [AKEDatabase](https://github.com/NagiYume/AKEDatabase), whose root license is GNU General Public License version 3. This project imports its VFS reader and IL2CPP runtime host from a caller-provided checkout for resource preparation. AKE source is not bundled here; its copyright notices and dependency licenses remain applicable. This project is distributed under GPL-3.0-only; see [LICENSE](LICENSE).

The Python resource reader implements the UnityFS, SerializedFile, TypeTree and Endfield configuration bundle formats. Format validation uses synthetic inputs and independently generated resource exports; game assets are not bundled.

Python dependencies are declared in `pyproject.toml` and retain their respective licenses. No .NET assemblies or native animation libraries are distributed by this package.
