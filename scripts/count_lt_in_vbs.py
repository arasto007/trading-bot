from pathlib import Path
text = Path(r"C:\Users\AMIR\Desktop\TradingBot new\live_dashboard.hta").read_text(encoding="utf-8")
m = '<script language="VBScript">'
s = text.index(m) + len(m)
e = text.index("</script>", s)
block = text[s:e]
count = block.count("<")
print("lt_count", count)
for i, ln in enumerate(block.splitlines(), 1):
    if "<" in ln and not ln.strip().startswith("'"):
        print(i, ln[:100])
