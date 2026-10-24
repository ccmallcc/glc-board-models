r"""提取 docx 文本（不需要 python-docx：直接解析 word/document.xml）"""
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def para_text(p):
    parts = []
    for node in p.iter():
        tag = node.tag.split("}")[-1]
        if tag == "t" and node.text:
            parts.append(node.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag == "br":
            parts.append("\n")
    return "".join(parts)


def main(path, out):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        media = [n for n in names if n.startswith("word/media/")]
        xml = z.read("word/document.xml")

    root = ET.fromstring(xml)
    body = root.find("w:body", NS)
    lines = []
    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            t = para_text(child).strip()
            if t:
                lines.append(t)
        elif tag == "tbl":
            lines.append("[表格]")
            for row in child.findall("w:tr", NS):
                cells = [para_text(c).strip().replace("\n", " ") for c in row.findall("w:tc", NS)]
                lines.append("  | " + " | ".join(cells))
            lines.append("[/表格]")

    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(f"段落/表格行数: {len(lines)}")
    print(f"内嵌图片数: {len(media)}")
    print(f"图片总大小: {sum(0 for _ in media)}")
    print(f"已写入: {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
