from pathlib import Path

text = Path(r"C:\Users\AMIR\Desktop\TradingBot new\live_dashboard.hta").read_text(
    encoding="utf-8"
)
marker = '<script language="VBScript">'
start = text.index(marker) + len(marker)
end = text.index("</script>", start)
block = text[start:end].lower()
for pat in ["</span>", "</div>", "</table>", "</tr>", "</td>", "</script>"]:
    print(pat, block.count(pat))
