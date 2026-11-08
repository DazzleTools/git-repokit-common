"""Red-green audit for 0.4.4 (the pre-push private-content refusal, the
refused-commit wording, rk_private_paths moved into lib.sh).

Each mutant reverts one behaviour in a hook file (never its interface), runs
the named tests, and expects at least the named ones to FAIL; the file is then
restored from a backup taken first. Safety (Critical Rule 1b): a mutant that
disables the refusal lets a push land -- in a bare remote under the tests'
tmp_path, with core.hooksPath pinned to the temp repository; nothing reaches a
real remote. Backups are written to BACKUP before any edit, so a hard kill is
recoverable: copy them back over hooks/.

    python redgreen.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HOOKS = ROOT / "hooks"
BACKUP = Path(__file__).resolve().parent / "backup"

PP = "tests/test_pre_push_hook.py"
PC = "tests/test_pre_commit_hook.py"

MUTANTS = [
    ("M1 refusal off", "pre-push", 'RK_ALLOWLIST="$_rk_allow" rk_private_paths "$_rk_added" > "$_rk_hits"', ': > "$_rk_hits"',
     [f"{PP}::test_a_push_that_adds_a_private_file_is_refused",
      f"{PP}::test_a_private_file_on_a_public_branch_is_refused_at_push",
      f"{PP}::test_a_file_deleted_later_in_the_push_still_blocks",
      f"{PP}::test_a_rename_into_a_private_folder_blocks",
      f"{PP}::test_a_project_private_pattern_blocks_at_push",
      f"{PP}::test_the_environment_override_lets_one_push_through"]),
    ("M2 renames followed", "pre-push", "git log -z --no-renames --format=", "git log -z --format=",
     [f"{PP}::test_a_rename_into_a_private_folder_blocks"]),
    ("M3 whole history read", "pre-push", '_rk_not=(--not "--remotes=$1")', "_rk_not=()",
     [f"{PP}::test_files_the_remote_already_has_never_block"]),
    ("M4 env override ignored", "pre-push",
     'case "${REPOKIT_ALLOW_PRIVATE_PUSH:-}" in ""|0|false|no) ;; *) _rk_allow_private=true ;; esac',
     ":", [f"{PP}::test_the_environment_override_lets_one_push_through",
           f"{PP}::test_files_the_remote_already_has_never_block",
           f"{PP}::test_deleting_a_remote_branch_is_not_blocked"]),
    ("M5 config override ignored", "pre-push",
     '[ "$(git config --bool --get repokit.allowPrivatePush 2>/dev/null)" = true ] && _rk_allow_private=true',
     ":", [f"{PP}::test_the_git_config_override_lets_every_push_through"]),
    ("M6 deletes read", "pre-push", 'case "$local_sha" in *[!0]*) ;; *) continue ;; esac', ":",
     [f"{PP}::test_deleting_a_remote_branch_is_not_blocked"]),
    ("M7 allowlist ignored", "lib.sh", 'rk_allowed "$_rk_pp" || printf', "printf",
     [f"{PP}::test_the_allowlist_exempts_a_file_at_push",
      f"{PC}::test_the_allowlist_still_exempts_a_configured_prefix"]),
    ("M8 project patterns dropped", "lib.sh", 'if [ -n "${REPOKIT_PRIVATE_PATTERNS-}" ]; then', "if false; then",
     [f"{PP}::test_a_project_private_pattern_blocks_at_push",
      f"{PC}::test_a_configured_prefix_blocks_in_a_clone"]),
    ("M9 old wording", "pre-commit", '    echo "To commit them anyway:"\n', '    echo "  1. Switch to private branch: git checkout private"\n',
     [f"{PC}::test_the_refusal_names_the_ways_to_commit_anyway"]),
    ("M10 any-override value accepted as 0", "pre-push", '""|0|false|no) ;;', '"") ;;',
     [f"{PP}::test_the_environment_override_lets_one_push_through"]),
    # -- the consent flow (djdarcy, 2026-11-07) --
    ("N1 allowlist read from the working tree", "pre-push",
     'RK_ALLOWLIST="$_rk_allow" rk_private_paths "$_rk_added" > "$_rk_hits"', 'rk_private_paths "$_rk_added" > "$_rk_hits"',
     [f"{PP}::test_the_push_reads_the_allowlist_from_the_commits_it_sends"]),
    ("N2 push never asks", "pre-push", 'if rk_can_prompt && rk_ask "Are these meant', 'if false && rk_ask "Are these meant',
     [f"{PP}::test_a_person_who_says_yes_at_the_terminal_pushes_and_the_allowlist_records_it"]),
    ("N3 Claude Code not detected", "lib.sh", '    [ -z "${CLAUDECODE:-}" ] || return 1\n', "",
     [f"{PP}::test_an_agent_or_ci_is_refused_at_once_never_asked",
      f"{PC}::test_no_answer_or_no_person_refuses_with_the_stable_line"]),
    ("N4 CI not detected", "lib.sh", '    [ -z "${CI:-}" ] || return 1\n', "",
     [f"{PP}::test_an_agent_or_ci_is_refused_at_once_never_asked",
      f"{PC}::test_no_answer_or_no_person_refuses_with_the_stable_line"]),
    ("N5 REPOKIT_INTERACTIVE ignored", "lib.sh", '    [ "${REPOKIT_INTERACTIVE:-1}" != 0 ] || return 1\n', "",
     [f"{PP}::test_an_agent_or_ci_is_refused_at_once_never_asked"]),
    ("N6 private branch treated as public", "pre-push", 'if rk_is_private_branch "$_rk_branch"; then', "if false; then",
     [f"{PP}::test_a_push_that_adds_a_private_file_is_refused",
      f"{PP}::test_a_private_branch_is_never_offered_the_allowlist"]),
    ("N7 CR kept in the answer", "lib.sh", '    _rk_ans="${_rk_ans%"$(printf \'\\r\')"}"', "    :",
     [f"{PP}::test_a_person_who_says_yes_at_the_terminal_pushes_and_the_allowlist_records_it",
      f"{PC}::test_a_person_who_says_yes_commits_the_file_and_its_allowlist_entry_together"]),
    ("N8 commit never asks", "pre-commit", 'if rk_can_prompt && rk_ask "Add these paths', 'if false && rk_ask "Add these paths',
     [f"{PC}::test_a_person_who_says_yes_commits_the_file_and_its_allowlist_entry_together"]),
    ("N9 allowlist not staged with the commit", "pre-commit", 'if git add -- "$REPO_ROOT/.repokit-allowlist"; then', "if true; then",
     [f"{PC}::test_a_person_who_says_yes_commits_the_file_and_its_allowlist_entry_together"]),
    ("N10 no machine-readable line", "lib.sh", "        printf 'repokit-common: refused", "        : printf 'repokit-common: refused",
     [f"{PP}::test_a_push_that_adds_a_private_file_is_refused",
      f"{PP}::test_a_private_file_on_a_public_branch_is_refused_at_push",
      f"{PC}::test_no_answer_or_no_person_refuses_with_the_stable_line"]),
    ("N11 any answer is yes", "lib.sh", "    case \"$_rk_ans\" in [yY]|[yY][eE][sS]) return 0 ;; esac\n    return 1",
     "    return 0",
     [f"{PP}::test_a_person_who_says_no_or_nothing_is_refused",
      f"{PC}::test_no_answer_or_no_person_refuses_with_the_stable_line"]),
]


def run_tests(ids):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *ids],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    failed = {line.split(" ", 1)[1].split(" - ")[0].strip() for line in r.stdout.splitlines()
              if line.startswith("FAILED ")}
    return r.returncode, failed, r.stdout.splitlines()[-1] if r.stdout else ""


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    BACKUP.mkdir(exist_ok=True)
    names = sorted({m[1] for m in MUTANTS})
    for n in names:
        shutil.copy2(HOOKS / n, BACKUP / n)
    originals = {n: (HOOKS / n).read_bytes() for n in names}
    results = []
    try:
        for label, fname, old, new, ids in MUTANTS:
            raw = originals[fname]
            eol = b"\r\n" if b"\r\n" in raw else b"\n"
            o = old.encode().replace(b"\n", eol)
            nw = new.encode().replace(b"\n", eol)
            if raw.count(o) != 1:
                results.append((label, "ANCHOR", f"found {raw.count(o)} times"))
                continue
            (HOOKS / fname).write_bytes(raw.replace(o, nw))
            rc, failed, last = run_tests(ids)
            (HOOKS / fname).write_bytes(raw)
            # a parametrized test fails as "<id>[<params>]"; any failed case counts
            missing = [i for i in ids if not any(f == i or f.startswith(i + "[") for f in failed)]
            results.append((label, "RED" if not missing else "SURVIVED", last if not missing else f"stayed green: {missing}"))
        rc, failed, last = run_tests(sorted({i for m in MUTANTS for i in m[4]}))
        results.append(("restored", "GREEN" if rc == 0 else "NOT GREEN", last))
    finally:
        for n in names:
            (HOOKS / n).write_bytes(originals[n])
    for row in results:
        print(" | ".join(row))
    for n in names:
        assert (HOOKS / n).read_bytes() == (BACKUP / n).read_bytes(), f"{n} not restored"
    print("hooks restored byte-identical to backup")


if __name__ == "__main__":
    main()
