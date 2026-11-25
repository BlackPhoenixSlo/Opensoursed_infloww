from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    bombadil, out = sys.argv[1], Path(sys.argv[2])
    trace = out / "trace.bin"
    res = subprocess.run([bombadil, "trace", "--json", str(trace)], capture_output=True, text=True)
    if res.returncode:
        print(f"ui-explore: trace decoder failed ({res.returncode}): {res.stderr.strip()}", file=sys.stderr)
        return 1
    states = [json.loads(line) for line in res.stdout.splitlines() if line.startswith("{")]
    paths = {s["metadata"]["state"]["url"].split("?")[0] for s in states}
    props: dict[str, dict] = {}
    for s in states:
        for v in s["metadata"].get("violations") or []:
            p = props.setdefault(v["name"], {"states": 0, "first": s["index"]})
            p["states"] += 1
            if p["states"] == 1:
                p["url"] = s["metadata"]["state"]["url"]
                p["action"] = s["metadata"]["action"]
                p["detail"] = v["violation"]
    shots = out / "violations"
    for name, p in props.items():
        shots.mkdir(exist_ok=True)
        subprocess.run([bombadil, "trace", "--state", str(p["first"]), "--screenshots", str(shots), str(trace)],
                       capture_output=True)
        p["screenshot"] = next((str(f) for f in shots.glob(f"{p['first']}.*")), None)
    (out / "summary.json").write_text(json.dumps({"states": len(states), "paths": sorted(paths),
                                                  "violations": props}, indent=2))
    print(f"ui-explore: {len(states)} states, {len(paths)} distinct paths")
    for name, p in props.items():
        detail = json.dumps(p["detail"])
        print(f"  VIOLATION {name}: {p['states']} states, first #{p['first']} {p['url']}\n"
              f"    after {json.dumps(p['action'])[:300]}\n    {detail[:900]}\n    screenshot {p['screenshot']}")
    if not states:
        print(f"ui-explore: no states recorded; Bombadil failed, see {out / 'bombadil.log'}")
    elif not props:
        print("ui-explore: no violations")
    return int(not states or bool(props))


if __name__ == "__main__":
    sys.exit(main())
