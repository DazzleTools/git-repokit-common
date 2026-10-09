CC ?= cc
CFLAGS ?= -O2 -Wall -Iinclude

build/__RK_PROJECT__: src/__RK_SNAKE__.c include/__RK_SNAKE__/version.h
	mkdir -p build
	$(CC) $(CFLAGS) -o $@ src/__RK_SNAKE__.c

.PHONY: clean
clean:
	rm -rf build
