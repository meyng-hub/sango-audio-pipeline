#!/usr/bin/env python3
"""Fail when a change ADDS a credential to the repository.

Checks only ADDED lines of a diff (`--staged` for pre-commit, `--range` for CI),
plus the names of added files. History is exempt by construction. `--paths`
scans whole files and exists to measure false positives against a tree.

Rules match known credential FORMATS, not entropy: an entropy rule fires on
hashes and digests, and a gate that is red for unrelated reasons teaches you to
skim the red. The cost: a credential in an unknown format passes.

A finding never prints the value -- only file, line, rule id and a length.

To allow a line that is genuinely not a secret (documented example, test
fixture), add `secret-scan: allow` on the same line with a reason.

Does NOT: scan binary files, history, other branches; verify a match is live.

Usage:
    python scripts/ci/secret-scan-gate.py --staged
    python scripts/ci/secret-scan-gate.py --range origin/main...HEAD
    python scripts/ci/secret-scan-gate.py --paths <file> [<file> ...]
    python scripts/ci/secret-scan-gate.py --self-test

Exit: 0 clean, 1 findings, 2 UNDETERMINED (git failed) -- fails closed.
Stdlib only, offline, no credentials.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass

ALLOW_MARKER = "secret-scan: allow"

# (rule id, compiled pattern). Every pattern is a published or in-repo format.
RULES: list[tuple[str, re.Pattern[str]]] = [
    # Product-minted keys look like `sk_<tier>_<urlsafe b64>`; any lowercase tier word.
    ("prefixed-api-key", re.compile(r"\bsk_[a-z]{3,10}_[A-Za-z0-9_-]{20,}")),
    ("payment-restricted-key", re.compile(r"\brk_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("payment-webhook-secret", re.compile(r"\bwhsec_[A-Za-z0-9+/=]{20,}")),
    ("cloud-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("cloud-secret-key", re.compile(
        r"(?i)a" r"ws_secret_access_key\s*[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+]{40}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})")),
    ("ai-provider-key-a", re.compile(r"\bsk-an" r"t-[A-Za-z0-9_-]{20,}")),
    ("ai-provider-key-b", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}")),
    ("cloud-api-key-b", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("hub-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("chat-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----")),
]

# Values that match a format but are documented placeholders.
PLACEHOLDER = re.compile(r"(?i)EXAMPLE|PLACEHOLDER|REDACTED|x{8,}|0{16,}|your[_-]?(?:api[_-]?)?key|<[^>]*>")

# Added FILES whose name alone says "credential". `.env.example` and friends pass.
BAD_NAME = re.compile(
    r"(?:^|/)(?:\.env(?:\.(?!example$|sample$|template$)[^/]+)?"
    r"|[^/]*\.(?:pem|p12|pfx|jks|keystore)"
    r"|id_(?:rsa|dsa|ecdsa|ed25519)"
    r"|credentials(?:\.json)?"
    # `test_api_key.json` style names, but not config such as `disable-api-key-required.json`.
    r"|[^/]*api[_-]?keys?(?:[_-](?:live|prod|test|dev))?\.json)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    length: int

    def render(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        detail = f"{self.length}-char match, value withheld" if self.length else "credential-shaped filename"
        return f"  {where}  [{self.rule}]  ({detail})"


def scan_line(path: str, lineno: int, text: str) -> list[Finding]:
    if ALLOW_MARKER in text:
        return []
    out: list[Finding] = []
    for rule, pat in RULES:
        for m in pat.finditer(text):
            if PLACEHOLDER.search(m.group(0)):
                continue
            out.append(Finding(path, lineno, rule, len(m.group(0))))
    return out


def scan_name(path: str) -> list[Finding]:
    return [Finding(path, 0, "credential-filename", 0)] if BAD_NAME.search(path) else []


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def scan_diff(diff: str) -> list[Finding]:
    """Scan unified diff text (-U0). Only '+' lines and added file names count."""
    findings: list[Finding] = []
    path = ""
    lineno = 0
    is_new_file = False
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path, lineno, is_new_file = "", 0, False
        elif raw.startswith("new file mode"):
            is_new_file = True
        elif raw.startswith("+++ "):
            target = raw[4:].strip()
            path = target[2:] if target.startswith("b/") else target
            if path != "/dev/null" and is_new_file:
                findings += scan_name(path)
        elif raw.startswith("rename to "):
            findings += scan_name(raw[len("rename to "):].strip())
        elif (h := _HUNK.match(raw)):
            lineno = int(h.group(1))
        elif raw.startswith("+") and not raw.startswith("+++"):
            findings += scan_line(path, lineno, raw[1:])
            lineno += 1
    return findings


def git_diff(args: list[str]) -> str:
    cmd = ["git", "diff", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACMR", *args]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} exited {res.returncode}: {res.stderr.strip()}")
    return res.stdout


def scan_paths(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for p in paths:
        findings += scan_name(p.replace("\\", "/"))
        try:
            with open(p, encoding="utf-8", errors="strict") as fh:
                for i, line in enumerate(fh, 1):
                    findings += scan_line(p, i, line)
        except (UnicodeDecodeError, IsADirectoryError):
            continue  # binary / directory: out of scope, same as the diff modes
    return findings


def report(findings: list[Finding], scope: str) -> int:
    if not findings:
        print(f"secret-scan: clean ({scope})")
        return 0
    print(f"secret-scan: {len(findings)} finding(s) in {scope}:")
    for f in findings:
        print(f.render())
    print(
        "\nIf a match is a real credential: do NOT just delete the line -- it is already in\n"
        "your commit/branch. Revoke or rotate it first, then remove it.\n"
        f"If it is not a secret, add `{ALLOW_MARKER}` to that line with a reason."
    )
    return 1


def self_test() -> int:
    """Plant one violation per rule, assert each fires, assert controls stay clean.

    Planted values are assembled at runtime so this file never contains a literal
    that the gate itself would flag when it is committed.
    """
    j = "".join
    tail = "A1b2C3d4E5f6G7h8J9k0LmNoPqRsTuVw"  # 32 chars, no placeholder pattern
    must_fire = {
        "prefixed-api-key": j(["sk_", "free_", tail, "xyz_-Q"]),
        "payment-restricted-key": j(["rk_", "live_", tail]),
        "payment-webhook-secret": j(["whsec_", tail]),
        "cloud-access-key-id": j(["AKIA", "Q3ZT7WMN2PLR4VXY"]),
        "cloud-secret-key": j(["a", "ws_secret_access_key = ", tail, "abcdEFGH"]),
        "github-token": j(["ghp_", tail, "wxyz"]),
        "ai-provider-key-a": j(["sk-", "ant-", tail]),
        "ai-provider-key-b": j(["sk-", "proj-", tail]),
        "cloud-api-key-b": j(["AIza", tail, "Q9z"]),
        "hub-token": j(["hf_", tail]),
        "chat-token": j(["xox", "b-", "1234567890-abcdef"]),
        "private-key-block": j(["-----BEGIN ", "RSA PRIVATE KEY-----"]),
    }
    failures: list[str] = []
    assert set(must_fire) == {r for r, _ in RULES}, "every rule needs a planted violation"

    for rule, value in must_fire.items():
        hits = {f.rule for f in scan_line("t.py", 1, f'x = "{value}"')}
        if rule not in hits:
            failures.append(f"planted {rule} did NOT fire")

    # A committed key file, replayed as a diff: must fire on content AND name.
    incident = j([
        "diff --git a/scripts/test_api_key.json b/scripts/test_api_key.json\n",
        "new file mode 100644\n",
        "--- /dev/null\n+++ b/scripts/test_api_key.json\n",
        "@@ -0,0 +1,2 @@\n+{\n",
        '+  "api_key": "', "sk_", "free_", tail, 'abcdefghijklmnop",\n',
    ])
    got = scan_diff(incident)
    if {f.rule for f in got} != {"prefixed-api-key", "credential-filename"}:
        failures.append(f"key-file replay: expected key+filename, got {sorted(f.rule for f in got)}")
    if any(f.line not in (0, 2) for f in got):
        failures.append(f"key-file replay: wrong line numbers {[f.line for f in got]}")

    # Negative controls: each is a documented placeholder or a hash.
    must_not_fire = [
        'api_key = "sk_live_" + base64.urlsafe_b64encode(random_bytes).decode()',
        '"key_preview": "sk_live_••••••••",',
        j(["AW", "S_KEY=AKIA", "IOSFODNN7EXAMPLE"]),
        j(['token = "ghp_', "x" * 36, '"']),
        j(['k = "', "sk_", "free_", tail, '"  # secret-scan: allow -- fixture']),
        j(['"STRI', 'PE_SECRET_KEY": "sk_', 'test_placeholder_update_via_console"']),
        "sha = 'eaaea71b37d725de1cc31b91be3bebc1496fb155d7507d065bc197e7f4837c02'",
        'integrity="sha384-oqVuAfXRKap7fdgcCY5uykM6+R9GqQ8K/uxy9rx7HNQlGYl1kPzQho1wx4JwY8wC"',
    ]
    for text in must_not_fire:
        if scan_line("t.py", 1, text):
            failures.append(f"negative control fired: {text[:50]!r}")

    # Removed lines and context must never count -- history is exempt.
    removed = j([
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -3 +3 @@\n",
        '-k = "', "sk_", "free_", tail, '"\n+k = None\n',
    ])
    if scan_diff(removed):
        failures.append("a REMOVED line was reported")

    # Filenames: bad names fire, templates do not.
    for bad in [".env", "infra/.env.production", "certs/server.pem", "android/upload.keystore",
                "scripts/test_api_key.json", "scripts/test_api_key_prod.json", "home/id_ed25519"]:
        if not scan_name(bad):
            failures.append(f"bad filename passed: {bad}")
    for ok in [".env.example", "frontend/.env.sample", "docs/api-keys.md", "src/keystore.ts",
               "config/disable-api-key-required.json"]:
        if scan_name(ok):
            failures.append(f"good filename fired: {ok}")

    # The value must never be printed.
    secret = j(["sk_", "free_", tail, "zzzz"])
    rendered = "\n".join(f.render() for f in scan_line("t.py", 7, secret))
    if not rendered or secret in rendered or tail in rendered:
        failures.append("render() leaked the value, or rendered nothing")

    if failures:
        print("secret-scan SELF-TEST FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"secret-scan self-test: {len(must_fire)} rules fire, key-file replay, "
          f"{len(must_not_fire)} negative controls clean, removals exempt, value never printed")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Fail when a change adds a credential")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true", help="scan the staged diff (pre-commit)")
    g.add_argument("--range", metavar="A...B", help="scan added lines in a commit range (CI)")
    g.add_argument("--paths", nargs="+", metavar="FILE", help="scan whole files")
    g.add_argument("--self-test", action="store_true")
    a = p.parse_args()

    if a.self_test:
        return self_test()
    try:
        if a.staged:
            return report(scan_diff(git_diff(["--cached"])), "staged changes")
        if a.range:
            return report(scan_diff(git_diff([a.range])), a.range)
        return report(scan_paths(a.paths), f"{len(a.paths)} file(s)")
    except RuntimeError as e:
        print(f"secret-scan: UNDETERMINED -- {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
