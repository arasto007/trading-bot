from pathlib import Path
text = Path(r"C:\Users\AMIR\Desktop\TradingBot new\live_dashboard.hta").read_text(encoding="utf-8")
m = '<script language="VBScript">'
s = text.index(m) + len(m)
e = text.index("</script>", s)
lines = text[s:e].splitlines()
base = "\n".join(lines[:309])
for pat in ["</span>", "</div>", "</table>", "</tr>", "</td>", "<script", "</script"]:
    c = base.lower().count(pat)
    if c:
        print(pat, c)
