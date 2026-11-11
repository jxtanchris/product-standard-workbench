# -*- coding: utf-8 -*-
"""限值单元格解析（± / 上偏差 / 区间 / 代号）的回归测试。

函数写在 templates/index.html 里，这里把它抠出来交给 node 跑，
避免"界面逻辑没测试"。

    .venv/bin/python test_parse.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "templates" / "index.html"

CASES = [
    # (单元格文本, 解释方式, 期望 [下限, 上限])
    ["±0.05", "auto", [-0.05, 0.05]],
    ["士0.05", "auto", [-0.05, 0.05]],          # OCR 常把 ± 认成 士
    ["h≤0.5 士0.05", "auto", [-0.05, 0.05]],    # 合并单元格里带着分档文字
    ["2.5<h≤4 士0.3", "auto", [-0.3, 0.3]],
    ["+0.1", "auto", [0, 0.1]],
    ["-0.52", "auto", [-0.52, 0]],
    ["0.1~0.2", "auto", [0.1, 0.2]],
    ["0.03", "auto", [None, 0.03]],
    ["0.05", "sym", [-0.05, 0.05]],
    ["0.3", "max", [None, 0.3]],
    ["0.3", "min", [0.3, None]],
    ["0.03", "plus", [0, 0.03]],
    ["H13", "auto", [None, None]],              # 代号不参与数值解析
    ["IT12", "auto", [None, None]],
    ["0.03 0.03", "auto", [None, 0.03]],
]


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("SKIP  没有 node，跳过节解析测试")
        return 0
    html = HTML.read_text(encoding="utf-8")
    body = html[html.index("function detectTol"):html.index("async function openSource(){")]

    script = body + """
const cases = %s;
let bad = 0;
for (const [t, m, exp] of cases) {
  const got = parseValue(t, m);
  const ok = JSON.stringify(got) === JSON.stringify(exp);
  if (!ok) bad++;
  console.log((ok ? "PASS  " : "FAIL  ") + JSON.stringify(t).padEnd(20) + m.padEnd(6) +
              "-> " + JSON.stringify(got) + "  期望 " + JSON.stringify(exp));
}
console.log("__RESULT__" + JSON.stringify({total: cases.length, bad}));
""" % json.dumps(CASES, ensure_ascii=False)

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(script)
        path = f.name
    out = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    Path(path).unlink(missing_ok=True)

    ok = True
    for line in out.stdout.splitlines():
        if line.startswith("__RESULT__"):
            res = json.loads(line[len("__RESULT__"):])
            ok = res["bad"] == 0
            print(f"\n结果：{res['total'] - res['bad']} 通过 / {res['bad']} 失败")
        else:
            print("  " + line)
    if out.returncode != 0 and not out.stdout:
        print(out.stderr[:400])
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
