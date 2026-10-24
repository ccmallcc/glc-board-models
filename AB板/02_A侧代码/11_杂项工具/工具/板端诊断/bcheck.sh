#!/bin/sh
# bcheck.sh -- READ-ONLY board health collector for FMQL30TAI (GLC project)
#
# SAFETY CONTRACT (do not extend this script without re-reading it):
#   * NO writes of any kind.
#   * NO devmem / /dev/mem access. Not one byte.
#   * NO systemctl start/stop/restart.
#   * NO bitstream load (nothing is echoed into fpga_manager).
#   * NO apt/dpkg install, no file creation outside $OUT.
#
# Reason: on this SoC a read of an unmapped PL AXI window (e.g. 0x40040000)
# wedges the PS bus and the board needs a power cycle. We are operating a
# teammate's board over SSH, so a hang costs them a physical trip.
#
# Usage:
#   sh bcheck.sh              -> print to stdout only
#   sh bcheck.sh /tmp/r.txt   -> tee to file as well
#
# Every probe is wrapped so a missing tool or missing sysfs node never aborts.

OUT="$1"
TMP=/tmp/bcheck.$$.txt

L=40   # default max lines per block
CT=20  # hard per-probe timeout (s); a probe must never wedge the session
command -v timeout >/dev/null 2>&1 && TO="timeout $CT" || TO=""

emit() {
  # emit <title> <command string run via sh -c>
  echo ""
  echo "===== $1 ====="
  echo "--- \$ $2"
  $TO sh -c "$2" 2>&1 | head -n "$L"
  echo "--- [end]"
}

{
echo "############################################################"
echo "# bcheck.sh report"
echo "# collected host : $(hostname 2>/dev/null)"
echo "# collected at   : $(date -u '+%Y-%m-%dT%H:%M:%SZ') UTC"
echo "# script md5     : $(md5sum "$0" 2>/dev/null | cut -d' ' -f1)"
echo "############################################################"

########################################################################
echo ""
echo "########## S1  IDENTITY / ENVIRONMENT ##########"
########################################################################
emit "uname"            "uname -a"
emit "device tree model" "tr -d '\\000' < /proc/device-tree/model; echo"
emit "compatible"       "tr -d '\\000' < /proc/device-tree/compatible; echo"
emit "os release"       "cat /etc/os-release"
emit "uptime / boot"    "uptime; echo; who -b 2>/dev/null; echo; cat /proc/uptime"
emit "kernel cmdline"   "cat /proc/cmdline"
emit "rtc present"      "ls -l /dev/rtc* 2>&1; dmesg 2>/dev/null | grep -i -E 'rtc|hctosys' | tail -5"

########################################################################
echo ""
echo "########## S2  PS HEALTH (CPU / MEM / THERMAL / STORAGE / NET) ##########"
########################################################################
emit "cpuinfo"          "grep -E 'processor|model name|BogoMIPS|Features' /proc/cpuinfo | head -12; echo; grep -c ^processor /proc/cpuinfo"
emit "loadavg / meminfo" "cat /proc/loadavg; echo; head -5 /proc/meminfo"
emit "free"             "free -m 2>/dev/null || true"
emit "thermal zones"    "for z in /sys/class/thermal/thermal_zone*; do [ -d \"\$z\" ] && echo \"\$z type=\$(cat \$z/type 2>/dev/null) temp=\$(cat \$z/temp 2>/dev/null)\"; done; echo '(none printed above => no thermal zone)'"
emit "hwmon (volt/curr)" "for h in /sys/class/hwmon/hwmon*; do [ -d \"\$h\" ] || continue; echo \"== \$h \$(cat \$h/name 2>/dev/null)\"; for f in \"\$h\"/in*_input \"\$h\"/curr*_input \"\$h\"/temp*_input; do [ -f \"\$f\" ] && echo \"  \$f = \$(cat \$f 2>/dev/null)\"; done; done; echo '(none printed above => no hwmon)'"
emit "cpufreq"          "for c in /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq; do [ -f \"\$c\" ] && echo \"\$c = \$(cat \$c)\"; done | head -8; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null"
emit "disk"             "df -h"
emit "mmc / sd errors"  "dmesg 2>/dev/null | grep -i -E 'mmc[0-9]|sdhci|I/O error|EXT4-fs error|remount' | tail -15"
emit "net interfaces"   "ip -br a 2>/dev/null || ifconfig -a"
emit "net link speed"   "for i in /sys/class/net/*; do n=\$(basename \$i); echo \"\$n: carrier=\$(cat \$i/carrier 2>/dev/null) speed=\$(cat \$i/speed 2>/dev/null) mtu=\$(cat \$i/mtu 2>/dev/null)\"; done"
emit "routes"           "ip route 2>/dev/null | head -10"
emit "dmesg errors(all)" "dmesg 2>/dev/null | grep -i -E 'error|fail|denied|timeout|Oops|BUG:|Call trace' | tail -25"

########################################################################
echo ""
echo "########## S3  PL / BITSTREAM STATE  (the NPU lives here) ##########"
########################################################################
echo ""
echo "!! NOTE: the NPU (ZG330) is an IP core INSIDE the PL fabric."
echo "!!       If the loaded bitstream does not contain it, the NPU is"
echo "!!       simply not on the bus -- that is a bitstream fact, not a"
echo "!!       broken chip. S3 tells us which .bin was last loaded."
emit "fpga_manager state" "ls -l /sys/class/fpga_manager/ 2>&1; for m in /sys/class/fpga_manager/*; do echo \"\$m: state=\$(cat \$m/state 2>/dev/null) name=\$(cat \$m/name 2>/dev/null)\"; done"
emit "firmware dir"     "ls -l /lib/firmware/ 2>&1 | head -40"
emit "firmware md5"     "for f in /lib/firmware/*.bin; do [ -f \"\$f\" ] && md5sum \"\$f\"; done 2>&1"
emit "dmesg fpga lines" "dmesg 2>/dev/null | grep -i -E 'fpga_manager|devcfg|PCAP|bitstream|FPGA Manager' | tail -20"
emit "who loads bitstream (unit files)" "grep -n 'fpga_manager' /etc/rc.local /etc/systemd/system/*.service /lib/systemd/system/*.service 2>/dev/null | head -20"
emit "who loads bitstream (root text)"  "grep -ln 'fpga_manager' /root/*.sh /root/*.py /root/*.service 2>/dev/null | head -20; echo '(file names only)'"
emit "iomem map"        "cat /proc/iomem | head -60"

########################################################################
echo ""
echo "########## S4  NPU / ICRaFT RUNTIME  (read-only) ##########"
########################################################################
echo ""
echo "!! NOTE: no register is read here on purpose. S4 only inspects"
echo "!!       driver/runtime/library state, which costs nothing to break."
emit "relevant /dev nodes" "ls -l /dev/uio* /dev/icraft* /dev/npu* /dev/zg* /dev/devcfg* 2>&1"
emit "interrupts"       "cat /proc/interrupts"
emit "lsmod"            "cat /proc/modules | sort | head -30; echo '--- count:'; wc -l < /proc/modules"
emit "dmesg npu/axi/dma" "dmesg 2>/dev/null | grep -i -E 'npu|zg330|icraft|ai7030|axi|dma|devcfg|uio' | tail -30"
emit "device tree npu"  "find /proc/device-tree -maxdepth 3 \\( -iname '*npu*' -o -iname '*zg*' -o -iname '*icraft*' -o -iname '*ai70*' \\) 2>/dev/null | head -20; echo '(empty => NPU has no DT node, expected for /dev/mem access)'"
emit "reserved memory"  "dmesg 2>/dev/null | grep -i -E 'reserved|memory@|cma|MemBlock|memory block' | tail -15"
emit "libicraft files"  "ls -l /usr/lib/libicraft* /usr/lib/*/libicraft* /usr/local/lib/libicraft* /opt/*/lib*/libicraft* 2>&1"
emit "ldconfig icraft"  "ldconfig -p 2>/dev/null | grep -i -E 'icraft|xrt|zg330'"
emit "dpkg icraft"      "dpkg -l 2>/dev/null | grep -i -E 'icraft|zg330|npu|icraft' | head -20"
emit "python icraft"    "python3 -c 'import icraft,sys;print(\"icraft:\",getattr(icraft,\"__file__\",None))' 2>&1; python3 -c 'import xrt,sys;print(\"xrt:\",getattr(xrt,\"__file__\",None))' 2>&1"
emit "icraft env vars"  "env | grep -i -E 'icraft|xrt|zg330|npu|LC_ALL|LANG' | sort"
emit "clock summary"    "mount | grep -q debugfs || echo '(debugfs not mounted)'; head -30 /sys/kernel/debug/clk/clk_summary 2>&1"

########################################################################
echo ""
echo "########## S5  SERVICE / DEMO STATE  (glc-demo and friends) ##########"
########################################################################
emit "glc-demo unit"    "systemctl cat glc-demo 2>&1 | head -30"
emit "glc-demo status"  "systemctl is-enabled glc-demo 2>&1; systemctl is-active glc-demo 2>&1; systemctl status glc-demo --no-pager 2>&1 | head -20"
emit "safe_restart.sh"  "ls -l /root/safe_restart.sh 2>&1; echo '--- content:'; cat /root/safe_restart.sh 2>/dev/null | head -60"
emit "demo log tail"    "ls -l /root/demo.log 2>&1; tail -40 /root/demo.log 2>&1"
emit "running services" "systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | head -25"
emit "journal err"      "journalctl -b -p err --no-pager 2>/dev/null | tail -30"
emit "root listing"     "ls -la /root 2>&1 | head -40"
emit "tmpfs usage"      "df -h /dev/shm /tmp /run 2>&1"

########################################################################
echo ""
echo "########## S6  NOT EXECUTED -- THE LANDMINES ##########"
########################################################################
cat <<'LANDMINE'
The following were deliberately NOT run by this script.
Read them out loud before anyone types them by hand:

  1) busybox devmem 0x40040000      -> wedged the PS bus on OUR SAME BOARD
                                       (documented: A-side 03 / 21). Board
                                       then requires a POWER CYCLE.
  2) any devmem sweep 0x4000_0000.. -> same class of landmine.
  3) echo <x>.bin > fpga_manager/firmware  while glc-demo is ACTIVE
                                       -> AXI traffic in flight during a
                                          reconfig => PS AXI hang.
                                       MUST `systemctl stop glc-demo` first.
  4) systemctl restart glc-demo     -> not allowed; use
                                       `sh /root/safe_restart.sh`.
  5) anything that re-flashes BOOT.bin / mtd  -> one-way, no undo here.

Rule that came out of our own two hangs: a register window is only
"known" if some piece of the vendor runtime already reads it. Everything
else is 0x40040000 until proven otherwise.
LANDMINE

echo ""
echo "########## END ##########"
} | if [ -n "$OUT" ]; then tee "$OUT"; else cat; fi

[ -n "$OUT" ] && echo "" && echo "written: $OUT  ($(wc -c < "$OUT") bytes)  md5=$(md5sum "$OUT" | cut -d' ' -f1)"
rm -f "$TMP"
exit 0
