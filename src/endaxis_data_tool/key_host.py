"""Obtain the local VFS key in an isolated AKE IL2CPP host process."""

import base64
import os
import sys
import threading
from pathlib import Path


def main():
    ake_root, runtime, scratch = [Path(p).resolve(strict=True) for p in sys.argv[1:]]
    sys.path.insert(0, str(ake_root))
    from ake_tool.json_host.runtime import Host

    keepalive = []

    def read_key():
        try:
            host = Host(runtime, scratch)
            keepalive.append(host)
            host.initialize(())
            print(
                "ENDAXIS_KEY " + base64.b64encode(host.common_key()).decode(),
                flush=True,
            )
        except BaseException as error:
            print(
                "Native key initialization failed: " + type(error).__name__,
                file=sys.stderr,
                flush=True,
            )
            os._exit(1)
        # Exit while the IL2CPP-attached thread is still alive. Returning from
        # this thread can invoke native thread teardown after callbacks finish.
        os._exit(0)

    threading.stack_size(16 * 1024 * 1024)
    thread = threading.Thread(target=read_key)
    thread.start()
    thread.join()


if __name__ == "__main__":
    main()
