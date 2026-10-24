# -*- coding: utf-8 -*-
r"""Parse an icraft quantize *_ftmps.csv.

Columns: ftmp_id, size, max, sat, normratio, scale, exp
Each of the last five columns is a space separated per-channel array.

Usage: python ftmps_probe.py <csv> [nrows]
"""
import sys


def main():
    fn = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    with open(fn, "r", encoding="utf-8", errors="replace") as f:
        hdr = f.readline().strip().split(",")
        print("HEADER: %s" % hdr)
        print("%-8s %-22s %-11s %-11s %-11s %-11s %-11s %s"
              % ("ftmp_id", "size", "max", "sat", "normratio", "scale", "exp", "uniq"))
        for i, line in enumerate(f):
            if i >= n:
                break
            p = line.rstrip("\n").split(",")
            if len(p) < 7:
                print("  short row: %d fields" % len(p))
                continue
            fid, size = p[0], p[1]
            cols = []
            uniq = []
            for c in p[2:7]:
                v = c.split()
                cols.append(v[0] if v else "-")
                uniq.append(len(set(v)))
            print("%-8s %-22s %-11s %-11s %-11s %-11s %-11s %s"
                  % (fid, size, cols[0], cols[1], cols[2], cols[3], cols[4], uniq))


if __name__ == "__main__":
    main()
