import json
import sys


def main() -> None:
    raw = sys.stdin.read().strip() or "{}"
    params = json.loads(raw)
    message = str(params.get("message", ""))
    times = int(params.get("times", 1) or 1)
    times = max(1, min(times, 5))

    lines = [f"echo[{i + 1}]: {message}" for i in range(times)]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
