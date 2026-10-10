#!/usr/bin/env python3
"""从 @ant-design/icons-svg（阿里 Ant Design 官方图标，MIT）生成本地 SVG sprite，零 CDN。
用法: npm i @ant-design/icons-svg && python3 build_sprite.py <node_modules/@ant-design/icons-svg 路径>
"""
import re, sys, pathlib
SRC = pathlib.Path(sys.argv[1]) / "inline-svg"
ICONS = {  # 图标名 -> 主题
 "download":"outlined","export":"outlined","info-circle":"outlined","search":"outlined","reload":"outlined","printer":"outlined",
 "down":"outlined","up":"outlined","left":"outlined","right":"outlined","plus":"outlined","check":"outlined","close":"outlined","user":"outlined",
 "logout":"outlined","setting":"outlined","team":"outlined","lock":"outlined","file-excel":"outlined","filter":"outlined","menu":"outlined",
 "warning":"outlined","exclamation-circle":"outlined","check-circle":"outlined","close-circle":"outlined","delete":"outlined","edit":"outlined",
 "eye":"outlined","home":"outlined","bar-chart":"outlined","shop":"outlined","safety":"outlined","table":"outlined","unordered-list":"outlined",
 "form":"outlined","audit":"outlined","file-text":"outlined","clock-circle":"outlined","arrow-left":"outlined","arrow-up":"outlined","arrow-down":"outlined",
 "caret-up":"filled","caret-down":"filled","appstore":"outlined","cloud-download":"outlined","robot":"outlined","car":"outlined","message":"outlined",
 "key":"outlined","save":"outlined","undo":"outlined","upload":"outlined","inbox":"outlined","dashboard":"outlined","apartment":"outlined","control":"outlined",
 "bell":"outlined","link":"outlined","more":"outlined","stop":"outlined","play-circle":"outlined","solution":"outlined","line-chart":"outlined","database":"outlined",
}
out = ['<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute" aria-hidden="true">']
for n, th in ICONS.items():
    f = SRC / th / f"{n}.svg"
    if not f.exists():
        print("missing", n, file=sys.stderr); continue
    s = f.read_text()
    vb = re.search(r'viewBox="([^"]+)"', s).group(1)
    inner = re.search(r'<svg[^>]*>(.*)</svg>', s, re.S).group(1).strip()
    out.append(f'<symbol id="i-{n}" viewBox="{vb}">{inner}</symbol>')
out.append("</svg>")
pathlib.Path(__file__).with_name("sprite.svg").write_text("".join(out))
print(len(out) - 2, "icons")
