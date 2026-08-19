from pathlib import Path
text = Path(r"C:\Users\AMIR\Desktop\TradingBot new\live_dashboard.hta").read_text(encoding="utf-8")
s = text.lower().find("<script")
pre = text[:s]
for pat in ["</script", "<script", "<!--", "-->", "</style", "<style"]:
    c = pre.lower().count(pat.lower())
    if c:
        print(pat, c)
# unclosed table tags
for tag in ["table", "tr", "td", "div"]:
    o = pre.lower().count(f"<{tag}")
    c = pre.lower().count(f"</{tag}")
    print(tag, "open", o, "close", c, "delta", o - c)
