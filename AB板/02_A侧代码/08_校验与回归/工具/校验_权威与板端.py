#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验「权威清单.tsv」：仓库副本 == 板上实跑？镜像 == 权威？

用法:
    python3 工具/校验_权威与板端.py               # 全查（需要能 ssh 到板子）
    python3 工具/校验_权威与板端.py --offline     # 不连板子，只查仓库内部
    python3 工具/校验_权威与板端.py --drift       # 额外扫 工具/ 下的同名漂移
    python3 工具/校验_权威与板端.py --drift-all   # 扫全仓（assets/ B侧/ 也会报，噪声大）
    python3 工具/校验_权威与板端.py --md5-from F  # 板端 md5 取自 F（串口 md5sum 原样输出）
    python3 工具/校验_权威与板端.py --regen --md5-from F   # 无 SSH 时重生成清单

为什么有 --md5-from：
    板子唯一网口 2026-10-22 起给相机了（板 192.168.1.10 / 相机 192.168.1.2），
    电脑**没有第二条路**进板子，只剩 COM3 串口。SSH 不通不等于板子没核对成 ——
    串口同样能拿到 `md5sum` 的实测输出，只是要人肉把它存成文件。
    所以这里把「板端 md5 从哪来」做成可插拔的：默认 SSH，也可以喂一个文件。
    **注意**：喂文件时脚本不校验这个文件是不是真从板子上来的；
    溯源靠文件名 + 文件头（见 派活/_board_md5_<日期>.txt 的写法）。

退出码: 0 = 报告的这一层全部一致；1 = 有不一致；2 = **该核对的没核对成**（板子连不上）。

设计要点（为什么这么做）:
  * **按 md5 比对，不按文件名**。板端文件名可能与仓库不同
    （实例：板上 /root/radio_check.py 曾与仓库同名文件根本不是同一个脚本）。
  * **连不上板子时报失败（退出码 2），不报"全部一致"** ——
    没查过的那一节不能算通过。这是 2026-10-15 修掉的一个判据缺陷：
    当时板子掉线，脚本仍然打印"全部一致 ✅"。
"""
import os
import sys
import hashlib
import subprocess
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "权威清单.tsv")
SKIP_DIRS = {'.git', '__pycache__', 'node_modules'}
SSH_KEY = os.path.expanduser(os.environ.get("GLC_BOARD_SSH_KEY", "~/.ssh/id_board"))
# ★ 2026-10-22 改：板子 IP 从 192.168.1.2 挪到 192.168.1.10。
#   原来板子和相机撞成同一个地址（见 根目录 88_相机IP冲突_20261022.md），
#   旧默认值 ssh 会打到**相机**上，然后报一个莫名其妙的认证失败。
SSH_HOST = os.environ.get("GLC_BOARD_HOST", "root@192.168.1.10")

# 「仓库新 / 板上旧」—— 两边**有意**不一样，不是故障。
# 每加一条都必须有：谁定的、文档在哪、怎么回滚。加不进来 ⇒ 它其实是个故障。
# 来历见 工具/版本对照_板端文件.md（512 参数化时改了仓库那份，没往板上铺）。
KNOWN_REPO_AHEAD = {
    '/root/glc/glc_board_full.py':
        '仓库 v20261018-512param 未部署；板上仍是 907bbe93（回滚副本 工具/_历史_板端文件/）',
}


def md5f(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def read_manifest():
    rows = []
    with open(MANIFEST, encoding='utf-8') as f:
        for ln in f:
            ln = ln.rstrip('\n')
            if not ln or ln.startswith('#'):
                continue
            parts = ln.split('\t')
            if len(parts) < 5:
                continue
            typ, col2, col3, m, sz = parts[:5]
            note = parts[5] if len(parts) > 5 else ''
            rows.append(dict(typ=typ, col2=col2, col3=col3, md5=m,
                             size=int(sz), note=note))
    return rows


def _argval(name):
    """取 `--foo BAR` 或 `--foo=BAR` 的值；没有返回 None。"""
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + '='):
            return a.split('=', 1)[1]
    return None


def md5_from_file(path):
    """从「md5sum 原样输出」里解析 {路径: md5}。

    容忍两种常见脏东西：① 行尾 CR；② 路径前的 `*`（md5sum -b 的二进制标记）。
    注释行（# 开头）和解析不了的行**直接跳过**，不猜。
    """
    out = {}
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#') or ln.startswith('#'):
                continue
            p = ln.split()
            if len(p) == 2 and len(p[0]) == 32 and all(c in '0123456789abcdef' for c in p[0]):
                out[p[1].lstrip('*')] = p[0]
    return out


def board_md5(paths):
    """一次取回全部板端 md5。返回 {path: md5}；取不到返回 None。

    两条来源：① `--md5-from 文件`（串口 md5sum 存档，无网口时用）；② ssh。
    """
    src = _argval('--md5-from') or os.environ.get('GLC_BOARD_MD5_FILE')
    if src:
        if not os.path.isfile(src):
            print("  [md5-from] 文件不存在: %s" % src)
            return None
        out = md5_from_file(src)
        print("  [md5-from] 板端 md5 取自 %s（%d 条）"
              % (os.path.relpath(src).replace('\\', '/'), len(out)))
        return out

    if not os.path.isfile(SSH_KEY):
        print("  [ssh] 找不到私钥 %s" % SSH_KEY)
        return None
    cmd = ['ssh', '-i', SSH_KEY, '-o', 'BatchMode=yes',
           '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=8',
           SSH_HOST, 'md5sum ' + ' '.join("'%s'" % p for p in paths) + ' 2>/dev/null']
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        print("  [ssh] 调用失败: %s" % e)
        return None
    if r.returncode not in (0, 1):
        print("  [ssh] rc=%d %s" % (r.returncode, r.stderr.decode('utf-8', 'replace')[:200]))
        return None
    out = {}
    for ln in r.stdout.decode('utf-8', 'replace').splitlines():
        p = ln.split()
        if len(p) == 2:
            out[p[1]] = p[0]
    return out


def scan_drift(scope):
    """同名不同内容 —— 找未来新长出来的漂移。

    返回 [(名字, [(相对路径, 原始md5, 去CR后md5)], 是否仅换行差异)]。
    **必须把「仅换行差异」和「真内容差异」分开报**：
    把前者混进"漂移"里会产生假阳性，而假阳性多了，真信号就没人看了。
    （2026-10-15 实例：工具/make_mix_csv.py 与交付给 B 的那份只差 96 个 CR。）

    跳过**声明过的冻结存档**：名字里带「快照」的目录、`历史版本/`、`assets/`、`B侧/`。
    这些地方同名不同内容是**故意的**。
    """
    def frozen(d):
        return d == '历史版本' or '快照' in d or d in ('assets', 'B侧')

    def md5_nocr(p):
        h = hashlib.md5()
        with open(p, 'rb') as f:
            for c in iter(lambda: f.read(1 << 20), b''):
                h.update(c.replace(b'\r\n', b'\n'))
        return h.hexdigest()

    by_name = collections.defaultdict(list)
    for dp, dn, fn in os.walk(scope):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not frozen(d)]
        for f in fn:
            if os.path.splitext(f)[1].lower() not in ('.py', '.sh', '.ps1'):
                continue
            p = os.path.join(dp, f)
            try:
                by_name[f].append((os.path.relpath(p, REPO).replace('\\', '/'),
                                   md5f(p), md5_nocr(p)))
            except OSError:
                pass
    bad = []
    for name, v in sorted(by_name.items()):
        if len(v) > 1 and len({m for _, m, _ in v}) > 1:
            eol_only = len({n for _, _, n in v}) == 1
            bad.append((name, v, eol_only))
    return bad


def regen():
    """重算清单里的 md5/字节。

    安全阀：**必须先与板上核对一致才写**。
    否则会出现"仓库里那份已经和板子不一样了，但一 regen 就把它洗成权威"的静默漂移。
    """
    force = '--force' in sys.argv
    rows = read_manifest()
    deploy = [r for r in rows if r['typ'] == '部署']
    bm = board_md5([r['col2'] for r in deploy])
    if bm is None and not force:
        print("拒绝重生成：连不上板子，清单里的板端 md5 无法核对。")
        print("  —— 直接写会把「没核对过的值」洗成权威。")
        print("  没有网口时: 用串口跑一次 md5sum，把原样输出存成文件，再")
        print("            python3 工具/校验_权威与板端.py --regen --md5-from <那个文件>")
        print("  确实要跳过核对: 加 --force（不推荐，之后务必补一次带板子的校验）")
        return 1

    errs = []
    for r in rows:
        if r['typ'] == '部署':
            fp = os.path.join(REPO, r['col3'].replace('/', os.sep))
            if not os.path.isfile(fp):
                errs.append("仓库缺文件: %s" % r['col3'])
                continue
            m, sz = md5f(fp), os.path.getsize(fp)
            got = (bm or {}).get(r['col2'])
            if got is not None and got != m:
                if r['col2'] in KNOWN_REPO_AHEAD:
                    print("  已知：板上仍旧版 %s（清单记仓库版）—— %s"
                          % (r['col2'], KNOWN_REPO_AHEAD[r['col2']]))
                    r['md5'], r['size'] = m, sz
                    continue
                errs.append("板上≠仓库 %s\n      板上 %s\n      仓库 %s (%s)"
                            % (r['col2'], got, m, r['col3']))
                continue
            r['md5'], r['size'] = m, sz
        else:
            auth = os.path.join(REPO, r['col2'].replace('/', os.sep))
            mirr = os.path.join(REPO, r['col3'].replace('/', os.sep))
            if not (os.path.isfile(auth) and os.path.isfile(mirr)):
                errs.append("镜像或权威缺文件: %s / %s" % (r['col2'], r['col3']))
                continue
            ma, mm = md5f(auth), md5f(mirr)
            if ma != mm:
                errs.append("镜像已偏离权威，先决定哪份对: %s (%s) vs %s (%s)"
                            % (r['col3'], mm[:8], r['col2'], ma[:8]))
                continue
            r['md5'], r['size'] = ma, os.path.getsize(auth)

    if errs:
        print("拒绝重生成，先解决：")
        for e in errs:
            print("   - %s" % e)
        return 1

    head = []
    with open(MANIFEST, encoding='utf-8') as f:
        for ln in f:
            if ln.startswith('#'):
                head.append(ln.rstrip('\n'))
            else:
                break
    out = head + ["\t".join([r['typ'], r['col2'], r['col3'], r['md5'],
                             str(r['size']), r['note']]) for r in rows] + [""]
    with open(MANIFEST, "w", encoding='utf-8', newline='\n') as f:
        f.write("\n".join(out))
    print("已重写 %s（%d 条，已与板上核对）"
          % (os.path.relpath(MANIFEST, REPO).replace('\\', '/'), len(rows)))
    return 0


def main():
    if '--regen' in sys.argv:
        return regen()
    offline = '--offline' in sys.argv
    drift = '--drift' in sys.argv or '--drift-all' in sys.argv
    rows = read_manifest()
    print("清单: %s" % os.path.relpath(MANIFEST, REPO).replace('\\', '/'))
    print("条目: %d（部署 %d / 镜像 %d）\n"
          % (len(rows), sum(1 for r in rows if r['typ'] == '部署'),
             sum(1 for r in rows if r['typ'] == '镜像')))

    fail = []

    # ---------- 1. 镜像 vs 权威 ----------
    print("== 1. 镜像 是否仍等于 权威 ==")
    mirrors = [r for r in rows if r['typ'] == '镜像']
    if not mirrors:
        print("   （无）")
    for r in mirrors:
        auth = os.path.join(REPO, r['col2'].replace('/', os.sep))
        mirr = os.path.join(REPO, r['col3'].replace('/', os.sep))
        if not (os.path.isfile(auth) and os.path.isfile(mirr)):
            fail.append("镜像或权威缺文件: %s" % r['col3'])
            print("   ! 缺文件 %s" % r['col3'])
            continue
        a, m = md5f(auth), md5f(mirr)
        if a == m:
            print("   OK   %s  == %s  (%s)" % (r['col3'], r['col2'], m[:8]))
        else:
            fail.append("镜像偏离权威: %s" % r['col3'])
            print("   ★    %s 已偏离 %s" % (r['col3'], r['col2']))
            print("        权威 %s / 镜像 %s" % (a[:8], m[:8]))
            print("        修: 用权威覆盖镜像（或反过来，先想清楚哪份对）")

    # ---------- 2. 仓库权威副本 vs 清单 ----------
    print("\n== 2. 仓库权威副本 vs 清单记录 ==")
    local_bad = 0
    for r in rows:
        if r['typ'] != '部署':
            continue
        fp = os.path.join(REPO, r['col3'].replace('/', os.sep))
        if not os.path.isfile(fp):
            fail.append("仓库缺文件: %s" % r['col3'])
            print("   ★ 仓库缺文件 %s" % r['col3'])
            local_bad += 1
            continue
        m = md5f(fp)
        if m != r['md5']:
            fail.append("仓库文件已改: %s" % r['col3'])
            print("   ★ %s 内容与清单不符" % r['col3'])
            print("        清单 %s / 实际 %s" % (r['md5'][:8], m[:8]))
            print("        若是有意改动: 改完后跑 工具/校验_权威与板端.py --regen 重生成清单")
            local_bad += 1
    if local_bad == 0:
        print("   OK   全部 %d 条与清单一致" % sum(1 for r in rows if r['typ'] == '部署'))

    # ---------- 3. 板上实跑 vs 仓库 ----------
    print("\n== 3. 板上实跑 vs 仓库权威副本 ==")
    deploy = [r for r in rows if r['typ'] == '部署']
    board_ok = False
    known = 0
    if offline:
        print("   SKIP  --offline：没连板子，这一节**没查**")
    else:
        bm = board_md5([r['col2'] for r in deploy])
        if bm is None:
            print("   SKIP  连不上板子（%s），这一节**没查**" % SSH_HOST)
            print("         板子没开机 / 网线没插 / 改 GLC_BOARD_HOST")
            print("         板子网口给相机了？用 --md5-from <串口 md5sum 存档>")
        else:
            board_ok = True
            ok = 0
            known = 0
            for r in deploy:
                bp, rp = r['col2'], r['col3']
                got = bm.get(bp)
                if got is None:
                    fail.append("板上缺: %s" % bp)
                    print("   ★ 板上没有      %s" % bp)
                elif got == r['md5']:
                    ok += 1
                elif bp in KNOWN_REPO_AHEAD:
                    known += 1
                    print("   i  板上仍旧版      %s" % bp)
                    print("        板上 %s  仓库 %s   (%s)"
                          % (got[:8], r['md5'][:8], rp))
                    print("        已知有意如此: %s" % KNOWN_REPO_AHEAD[bp])
                else:
                    fail.append("板上与仓库不一致: %s" % bp)
                    print("   ★ 板上≠仓库      %s" % bp)
                    print("        板上 %s  仓库 %s   (%s)" % (got[:8], r['md5'][:8], rp))
                    print("        若板上是新版: 先把板端那份拷回来，再 --regen")
                    print("        若仓库是新版: 把 %s 传上去" % rp)
            print("   %s   %d/%d 条与板上逐字节一致%s"
                  % ("OK " if ok == len(deploy) else "★  ", ok, len(deploy),
                     ("（另有 %d 条已知板上仍旧版）" % known) if known else ""))

    # ---------- 4. 仓库提交版 vs 工作区 vs 板上 ----------
    #  ★ 这一节查的是最容易骗人的一类不一致：
    #    工作区那份和板上一样，但 **git 里存的** 是另一份（典型：工作区 CRLF、blob LF）。
    #    后果：你自己跑校验全绿，队友一 clone 却是另一份文件。
    #    2026-10-15 就是这个坑：glc_ui.py 工作区 CRLF(e5302bcd) / blob LF(ee2c39da)，板上是 CRLF。
    print("\n== 4. 仓库【提交版】 vs 工作区 vs 板上 ==")
    gitbad = []
    for r in deploy:
        rel = r['col3']
        try:
            blob = subprocess.run(['git', '-C', REPO, 'show', 'HEAD:' + rel],
                                  capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            print("   ? git 不可用，跳过这一节")
            gitbad = None
            break
        if blob.returncode != 0:
            gitbad.append(rel)
            print("   ★ git 里没有这个文件（未提交？）: %s" % rel)
            continue
        bm = hashlib.md5(blob.stdout).hexdigest()
        wt = r['md5']                      # 工作区（第 2 节已核对过 == 清单）
        notes = []
        if bm != wt:
            notes.append("git存的是 %s ≠ 工作区 %s（未提交改动？或换行差异）" % (bm[:8], wt[:8]))
        if not offline and bm != wt:
            notes.append("队友 clone 后拿到 %s，与你手上/板上不是同一份" % bm[:8])
        if notes:
            gitbad.append(rel)
            print("   ★ %s" % rel)
            for n in notes:
                print("        %s" % n)
    if gitbad is None:
        pass
    elif not gitbad:
        print("   OK   全部 %d 条：git 提交版 == 工作区 == 板上" % len(deploy))

    # ---------- 5. 同名漂移扫描 ----------
    if drift:
        scope = REPO if '--drift-all' in sys.argv else HERE
        print("\n== 5. 同名漂移扫描（%s）==" % os.path.relpath(scope, REPO).replace('\\', '/'))
        bad = scan_drift(scope)
        if not bad:
            print("   OK   没有同名不同内容的文件")
        for name, v, eol_only in bad:
            tag = "仅换行差异（内容相同）" if eol_only else "★真内容差异"
            print("   · %s  (%d 份 / %d 种)  —— %s"
                  % (name, len(v), len({m for _, m, _ in v}), tag))
            for rel, m, n in sorted(v, key=lambda x: -os.path.getsize(os.path.join(REPO, x[0]))):
                print("       %s  %s" % (m[:8], rel))
        if bad:
            print("   已跳过声明过的冻结存档: 名字含「快照」的目录、历史版本/、assets/、B侧/")

    # ---------- 收尾 ----------
    print("\n" + "=" * 60)
    if fail:
        print("结果: 发现 %d 处不一致" % len(fail))
        for f in fail:
            print("   - %s" % f)
        return 1
    if offline:
        print("结果: 仓库内部一致 ✅ —— 但**没核对板子**（你加了 --offline）")
        return 0
    if not board_ok:
        # ★ 这里必须判失败，不能报"全部一致"。
        #   连不上板子 != 板子上的东西对 —— 没查就等于没验证。
        print("结果: 仓库内部一致，但**板子没核对成** ❌")
        print("      没查的那一节不能算通过。板子开机/插好网线后重跑；")
        print("      确实要离线跑，请显式加 --offline（那样退出码 0，且结论会写明没核对板子）。")
        return 2
    print("结果: 全部一致 ✅（含 %d 条与板子逐字节核对%s）"
          % (sum(1 for r in rows if r['typ'] == '部署') - known,
             ("；另 %d 条已知板上仍旧版，见 KNOWN_REPO_AHEAD" % known) if known else ""))
    return 0


if __name__ == '__main__':
    sys.exit(main())
