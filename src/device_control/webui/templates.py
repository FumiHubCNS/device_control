from __future__ import annotations


BASE_CSS = """
:root {
  color-scheme: light;
  --bg: #f5f6f8;
  --panel: #ffffff;
  --text: #202124;
  --muted: #687076;
  --line: #d8dde3;
  --blue: #1769e0;
  --green: #188038;
  --red: #d93025;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
}
main {
  width: min(1040px, calc(100% - 32px));
  margin: 24px auto 48px;
}
section, header {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 14px;
}
h1, h2 {
  margin: 0 0 12px;
  line-height: 1.2;
}
h1 { font-size: clamp(1.6rem, 4vw, 2.2rem); }
h2 { font-size: 1.05rem; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.metric {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}
.label {
  color: var(--muted);
  font-size: .88rem;
}
.value {
  font-size: 1.75rem;
  font-weight: 700;
  line-height: 1.25;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin: 10px 0;
}
input, button, select {
  font: inherit;
}
input, select {
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 7px 9px;
  background: #fff;
}
button {
  min-height: 38px;
  border: 0;
  border-radius: 6px;
  padding: 7px 12px;
  cursor: pointer;
  background: #e8eaed;
}
button.primary { background: var(--blue); color: #fff; }
button.safe { background: var(--green); color: #fff; }
button.danger { background: var(--red); color: #fff; }
button:disabled { opacity: .55; cursor: not-allowed; }
pre {
  margin: 0;
  overflow-x: auto;
  background: #111418;
  color: #d5f7d4;
  border-radius: 8px;
  padding: 12px;
}
.ok { color: var(--green); font-weight: 700; }
.ng { color: var(--red); font-weight: 700; }
canvas {
  display: block;
  width: 100%;
  height: 420px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
@media (max-width: 640px) {
  main { width: min(100% - 20px, 1040px); margin-top: 10px; }
  section, header { padding: 14px; }
  .value { font-size: 1.35rem; }
}
"""


def page(title: str, body: str, script: str = "", extra_head: str = "") -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>{BASE_CSS}</style>
  {extra_head}
</head>
<body>
  <main>
{body}
  </main>
  <script>
{script}
  </script>
</body>
</html>
"""
