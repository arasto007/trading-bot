from pathlib import Path
text = Path(r"C:\Users\AMIR\Desktop\TradingBot new\live_dashboard.hta").read_text(encoding="utf-8")
m = '<script language="VBScript">'
s = text.index(m) + len(m)
e = text.index("</script>", s)
lines = text[s:e].splitlines()
for i in range(720, 727):
    print(i + 1, repr(lines[i]))
