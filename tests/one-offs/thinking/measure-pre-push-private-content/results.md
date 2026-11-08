# Results: who would a pre-push private-content refusal affect? (2026-11-06)

`python probe.py` over every git-repokit-common consumer found under the local code root (a folder holding `repokit_config.py` or `sync-versions.py`, up to depth 6), read-only. The per-project output, which names local projects and paths, is kept out of public history.

**Control arm:** PASS. A throwaway repository with `logs/x.log` on main and a pushed `feature/x` was counted in both questions.

| Question | Result | What it rules out |
|---|---|---|
| Q1: main already tracks a path on the private-content list (built-in + `private-patterns`, minus the allowlist) | **4 / 51** (2 hold `private/claude/` files; 1 holds `private_*.py` modules matched by `^.*/private_.*`; 1 is a copy of another) | a refusal that checks the pushed branch's whole tree: it would refuse every push of these 4 |
| Q2: a remote branch whose name is in the default private-branches list | **1 / 51** (`origin/private`, pushed on purpose) | a refusal by branch name: it would refuse that project, and every `feature/*` push of a consumer that sets nothing |

**The rule built (0.4.4):** refuse only when a commit the push sends, one the remote does not have yet, adds a file on the list. None of the 51 is refused for what it already has.

Prediction, written before the run: Q1 at most 5 of about 50, mostly `*.log` / `.bak`; Q2 a handful of `feature/*`. Q1 held in count and missed in kind: it was `private/` and `private_` paths, not logs. Q2 was one `private`, not `feature/*`.
