from __future__ import annotations

import json
import sys


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
    customer_id = payload.get("customer_id", "unknown")
    tier = payload.get("tier", "standard")
    message = payload.get("message", "")

    out = {
        "subject": f"Support update for {customer_id}",
        "body": f"Hello, thanks for contacting support. Tier={tier}. We received: {message}",
    }
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
