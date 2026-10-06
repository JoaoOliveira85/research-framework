import json
import sys

a = json.load(open(sys.argv[1]))
b = json.load(open(sys.argv[2]))
ea = {e["path"]: e["rendered_sha256"] for e in a["entries"]}
eb = {e["path"]: e["rendered_sha256"] for e in b["entries"]}
for p in ea:
    sa, sb = ea[p], eb.get(p)
    if sa == sb:
        continue
    print("DIFF:", p, sa[:8], sb[:8] if sb else "MISSING")
