"""A stand-in for one benchmark child process (tests/test_vision_bench_run.py): sleeps, crashes or answers."""
import json
import sys
import time

mode = sys.argv[1]
if mode == "sleep":
    time.sleep(60)
elif mode == "crash":
    sys.exit(3)
elif mode == "ok":
    print("some log line")
    print(json.dumps({"status": "ok", "load_s": 0.1, "ms_per_item": 5.0, "scores": {"all": 1.0}, "items": []}))
elif mode == "crash_msg":
    sys.stderr.write("Traceback ...\nFileNotFoundError: model file missing: x.onnx\n")
    sys.exit(1)
