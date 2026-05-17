
import sys

prompt = sys.stdin.read()
if "BAKEOFF_FORMAT_RETRY_V1" in prompt:
    print('<final_json>{"ok": true}</final_json>')
else:
    print('<final_json>{"ok": false}</final_json>')
