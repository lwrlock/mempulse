CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -D_GNU_SOURCE

.PHONY: all test clean

all: mempulse-probe

mempulse-probe: src/native/mem_probe.c
	$(CC) $(CFLAGS) -o $@ $<

test: all
	/usr/bin/python3 -m py_compile src/mempulse/*.py
	./mempulse-probe --json >/dev/null
	PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v

clean:
	rm -f mempulse-probe
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
