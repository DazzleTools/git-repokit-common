# Mutation survivors triaged as equivalent or don't-care

Entries expire when the file's `git hash-object` no longer matches its heading; re-triage before reuse.

## hooks/pre-commit @ 4efdab3495dc

(Re-triaged 2026-09-27 at this hash: the change from fb5c666359e6 was header comments only; the stripped line is unchanged, so the entry below stands.)

- `NR == FNR { sub(/\r$/, ""); sub(/^\.\//, "");` -> `NR == FNR { sub(/^\.\//, "");` -- **equivalent (in this environment)**. repokit_config.py on Windows writes CRLF, but Git for Windows' awk (MSYS gawk) strips the CR on input, so entries never carry it (measured: `od -c` shows `a / \r \n`, awk reports length 2). The strip is kept for awk builds that read in binary mode. 2026-09-27, generation mode 1. Update the same day: repokit_config.py now writes LF on every platform, so no CR reaches the hook from it at all; the verdict stands for a second reason.
