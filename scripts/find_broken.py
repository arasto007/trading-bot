from pathlib import Path
text = Path(r"C:\Users\AMIR\Desktop\TradingBot new\live_dashboard.hta").read_text(encoding="utf-8")
m = '<script language="VBScript">'
s = text.index(m) + len(m)
e = text.index("</script>", s)
for i, ln in enumerate(text[s:e].splitlines(), 1):
    if '"" & "/' in ln or 'Chr(60) & Chr(60)' in ln or '" & "' in ln and '/td>' in ln:
        print(i, ln[:140])
