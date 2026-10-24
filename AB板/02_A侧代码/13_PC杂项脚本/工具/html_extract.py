#!/usr/bin/env python3
"""Sphinx HTML -> plain text, keep code blocks. 用法: html_extract.py <file.html> [...]"""
import sys, re, html, io

def extract(path):
    raw = open(path, 'r', encoding='utf-8', errors='replace').read()
    # 只取主内容区
    m = re.search(r'<div[^>]*role="main"[^>]*>(.*?)</div>\s*</div>\s*</div>', raw, re.S)
    body = m.group(1) if m else raw
    # 去掉 script/style/nav
    body = re.sub(r'<(script|style)\b.*?</\1>', '', body, flags=re.S)
    body = re.sub(r'<a[^>]*class="headerlink"[^>]*>.*?</a>', '', body, flags=re.S)
    body = re.sub(r'<a[^>]*class="reference internal"[^>]*>(.*?)</a>', r'\1', body, flags=re.S)
    body = re.sub(r'<br\s*/?>', '\n', body)
    body = re.sub(r'</(p|div|li|tr|h1|h2|h3|h4|dt|dd|pre)>', '\n', body)
    body = re.sub(r'<li[^>]*>', '  - ', body)
    body = re.sub(r'<td[^>]*>', ' | ', body)
    body = re.sub(r'<[^>]+>', '', body)
    body = html.unescape(body)
    body = re.sub(r'[ \t]+', ' ', body)
    body = re.sub(r'\n\s*\n\s*\n+', '\n\n', body)
    return '\n'.join(l.rstrip() for l in body.splitlines()).strip()

out = io.StringIO()
for p in sys.argv[1:]:
    out.write('\n' + '=' * 78 + '\n### ' + p + '\n' + '=' * 78 + '\n')
    out.write(extract(p) + '\n')
sys.stdout.write(out.getvalue())
