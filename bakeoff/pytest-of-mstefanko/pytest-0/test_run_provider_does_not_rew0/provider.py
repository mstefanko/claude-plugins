
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text('<final_json>{"ok": false}</final_json>', encoding='utf-8')
print('stdout fallback has ok true nowhere')
