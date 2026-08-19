from pathlib import Path

text = Path(r"C:\Users\AMIR\Desktop\TradingBot new\live_dashboard.hta").read_text(
    encoding="utf-8"
)
marker = '<script language="VBScript">'
start = text.index(marker)
end = text.index("</script>", start)
block = text[start + len(marker) : end]
print("block_len", len(block))
print("contains </script>", "</script>" in block.lower())
for pat in ["<script", "<!--", "-->"]:
    if pat in block.lower():
        print("found", pat)
bad = [(block[:i].count("\n") + 1, c, ord(c)) for i, c in enumerate(block) if ord(c) > 127]
print("non_ascii", len(bad))
for line, c, o in bad[:20]:
    print(line, hex(o), repr(c))

import re
from collections import Counter

subs = re.findall(r"^(Sub|Function)\s+(\w+)", block, re.M)
c = Counter(n for _, n in subs)
dups = [n for n, v in c.items() if v > 1]
print("subs", len(subs), "dups", dups)

lines = block.splitlines()
for i in range(303, min(316, len(lines))):
    print(i + 1, lines[i][:100])

for pat in ["</span>", "</div>", "</table>", "</tr>", "</script>"]:
    print(pat, block.lower().count(pat.lower()))
