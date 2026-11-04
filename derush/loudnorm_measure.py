#!/usr/bin/env python3
"""Read ffmpeg's loudnorm print_format=json output on stdin, print the
measured_* parameters for the second (linear) pass."""
import json
import sys

s = sys.stdin.read()
j = json.loads(s[s.rfind("{") : s.rfind("}") + 1])
parts = [f"measured_{k}={j["input_" + k.lower()]}" for k in ("I", "TP", "LRA", "thresh")]
parts.append(f"offset={j['target_offset']}")
print(":".join(parts))
