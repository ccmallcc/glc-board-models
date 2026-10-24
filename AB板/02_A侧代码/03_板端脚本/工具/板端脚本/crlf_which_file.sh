#!/bin/bash
# Which file types actually break on CRLF? (make 4.2.1, bash 5.0)
T=/tmp/crlftest2
rm -rf "$T"; mkdir -p "$T"; cd "$T"

echo "### 1) Makefile with CRLF"
printf 'all:\n\t@echo hello-from-makefile\n' > Makefile
make -s 2>&1 | head -2; echo "  exit=$?"
sed -i 's/$/\r/' Makefile
file Makefile | sed 's/.*: //'
make -s 2>&1 | head -2; echo "  exit=$?"
echo

echo "### 2) shell script with CRLF"
printf '#!/bin/bash\necho hello-from-shell\n' > s.sh
chmod +x s.sh
./s.sh; echo "  LF exit=$?"
sed -i 's/$/\r/' s.sh
file s.sh | sed 's/.*: //'
./s.sh 2>&1 | head -3; echo "  CRLF exit=$?"
echo

echo "### 3) shell script with CRLF, run via 'bash s.sh'"
bash s.sh 2>&1 | head -3; echo "  exit=$?"
echo

echo "### 4) variable assignment read from a CRLF file (the classic make trap)"
printf 'x86\r\n' > arch.txt
printf 'ARCH := $(shell cat arch.txt)\nall:\n\t@echo "[$(ARCH)]"\nifeq ($(ARCH),x86)\n\t@echo MATCHED-x86\nelse\n\t@echo NOT-MATCHED\nendif\n' > Makefile
make -s 2>&1 | head -4
