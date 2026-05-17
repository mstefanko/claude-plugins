
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text('<final_json>{"ok": true}</final_json>', encoding='utf-8')
print('plain prose without final json')
