#!/usr/bin/env python3
"""A stand-in for `spezl serve` for the SDK tests: no griasdi, no network.

It answers `info` (protocol 2 unless the scenario says otherwise), gives every `send`,
`send_dm` and `post_card` a fresh seq and every other method `null`, and appends each request
it reads to the file `FAKE_SPEZL_LOG` as one JSON line. Right after answering `set_voice`, the
last request of an SDK's start, it sends the scenario's notifications. It ends on `shutdown`
or when stdin closes.

The scenario is the JSON object in `FAKE_SPEZL_SCENARIO`:
- `info`: keys that replace those of the default `info` answer;
- `notifications`: `{"method", "params"}` objects to send;
- `errors`: method name to the `{"code", "message"}` it fails with.
"""

from __future__ import annotations

import json
import os
import sys

INFO = {
    "protocol": 2,
    "user_id": "b07b" + "00" * 30,
    "name": "TestBot",
    "bot_id": True,
    "servers": [],
}


def write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    if sys.argv[-1:] != ["serve"]:
        print("fake spezl only knows `serve`", file=sys.stderr)
        return 2
    scenario = json.loads(os.environ.get("FAKE_SPEZL_SCENARIO") or "{}")
    errors = scenario.get("errors", {})
    seq = 100
    with open(os.environ["FAKE_SPEZL_LOG"], "a", encoding="utf-8") as log:
        for line in sys.stdin:
            request = json.loads(line)
            log.write(json.dumps(request) + "\n")
            log.flush()
            method = request.get("method")
            if method in errors:
                write({"jsonrpc": "2.0", "id": request["id"], "error": errors[method]})
                continue
            if method == "info":
                result = {**INFO, **scenario.get("info", {})}
            elif method in ("send", "send_dm", "post_card"):
                seq += 1
                result = {"seq": seq}
            elif method == "communities":
                result = []
            else:
                result = None
            write({"jsonrpc": "2.0", "id": request["id"], "result": result})
            if method == "set_voice":
                for note in scenario.get("notifications", []):
                    write({"jsonrpc": "2.0", **note})
            if method == "shutdown":
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
