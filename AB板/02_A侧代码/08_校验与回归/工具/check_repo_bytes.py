# -*- coding: utf-8 -*-
"""check_repo_bytes.py —— 核对「仓库里存的字节」和「工作区文件的字节」是否一致。

为什么需要它
------------
版本包是**原始取证**：包内 `README.txt` 列了每个文件的 md5。
如果 `.gitattributes` 把某些报告当文本处理（提交时 CRLF↔LF 转换），
那么别人 clone 下来重算 md5 就会跟 README 里写的对不上 ——
「每个数字都能追到文件」这条规矩就断了。

仓库根 `.gitattributes` 末尾有一条 `assets/版本包_20260926/**  -text`
就是为这件事钉的。这个脚本用来**验证**它确实生效。

用法
----
    python check_repo_bytes.py                     # 默认查 assets/版本包_20260926
    python check_repo_bytes.py <路径前缀>           # 也可以查单个文件/别的目录
    可以在任意目录下执行（脚本自己找仓库根）。

退出码：0 = 全部一致；1 = 有文件不一致（会逐条列出）。
"""
import hashlib
import os
import subprocess
import sys


def git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True)


def md5(b):
    return hashlib.md5(b).hexdigest()


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "assets/版本包_20260926"

    top = git(["rev-parse", "--show-toplevel"], os.getcwd()).stdout.decode("utf-8").strip()
    if not top:
        raise SystemExit("这里不是 git 仓库（找不到 toplevel）")
    top = os.path.abspath(top)
    print("仓库：%s" % top)
    print("范围：%s" % prefix)

    raw = git(["ls-files", "-z", "--", prefix], top).stdout.decode("utf-8")
    paths = [p for p in raw.split("\0") if p]
    if not paths:
        raise SystemExit("这个范围下没有已入库的文件")

    diff = []
    for p in paths:
        blob = git(["cat-file", "blob", "HEAD:" + p], top).stdout
        disk_path = os.path.join(top, p.replace("/", os.sep))
        try:
            with open(disk_path, "rb") as f:
                disk = f.read()
        except OSError as e:
            diff.append((p, "读不到工作区文件：%s" % e))
            continue
        if md5(blob) != md5(disk):
            diff.append((p, "blob(HEAD)=%s  工作区=%s" % (md5(blob), md5(disk))))

    print("检查 %d 个文件：不一致 %d" % (len(paths), len(diff)))
    for p, why in diff:
        print("  DIFF  %s\n        %s" % (p, why))
    if diff:
        return 1
    print("OK —— 克隆下来重算 md5 与包内 README.txt 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
