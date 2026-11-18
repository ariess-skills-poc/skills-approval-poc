"""Email the owning teams of a pull request through Unieuro Email Hub.

usage: python3 notify_owners.py <base-ref> <pr-number> <pr-title> <pr-url> <author> [--publish <topic> --project <p>]

Finds the files the PR changes, resolves their owners with CODEOWNERS (last matching line wins),
maps owners to email addresses with .github/owners.json, and builds one Email Hub message.
Without --publish it only prints the message (dry run).
"""
import json, subprocess, sys
from fnmatch import fnmatch
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def owners_of(path, rules):
    found = []
    for pat, who in rules:
        p = pat.strip("/")
        if ("*" in p and fnmatch(path, p)) or path == p or path.startswith(p + "/"):
            found = who
    return found


def main():
    args = sys.argv[1:]
    base, num, title, url, author = args[:5]
    publish = args[args.index("--publish") + 1] if "--publish" in args else None
    project = args[args.index("--project") + 1] if "--project" in args else "uni-email-hub"
    rules = []
    for line in (ROOT / "CODEOWNERS").read_text().splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 2:
            rules.append((parts[0], parts[1:]))
    mb = git("merge-base", base, "HEAD").strip()
    files = [f for f in git("diff", "--name-only", mb, "HEAD").splitlines() if f]
    teams = sorted({t for f in files for t in owners_of(f, rules)})
    emails_map = json.loads((ROOT / ".github" / "owners.json").read_text())
    to = sorted({m for t in teams for m in emails_map.get(t, [])})
    if not to:
        print(f"no recipients (teams: {teams})"); return 0
    skills = sorted({f.split("/")[3] for f in files if f.startswith("data/") and len(f.split("/")) > 4})
    rows = "".join(f"<li><code>{escape(f)}</code></li>" for f in files[:20])
    html = (f"<p><b>{escape(author)}</b> ha aperto una pull request che riguarda il vostro team "
            f"({escape(', '.join(teams))}).</p><p><a href=\"{escape(url)}\">#{escape(num)} {escape(title)}</a></p>"
            f"<p>Skill: {escape(', '.join(skills) or '-')}</p><p>File modificati:</p><ul>{rows}</ul>"
            f"<p>Per approvare: apri la PR, controlla che la CI sia verde, poi <i>Review changes → Approve</i>.</p>")
    msg = {"message_id": f"skills-pr-{num}-opened-{git('rev-parse', '--short', 'HEAD').strip()}",
           "sender": "dataplatform", "to": to,
           "subject": f"[Skill] Revisione richiesta: #{num} {title}",
           "body": "", "body_html": html, "timestamp": "", "cc": [], "bcc": [],
           "reply_to": "", "template": "", "template_data": "{}"}
    print(f"teams: {teams}\nrecipients: {to}\nsubject: {msg['subject']}")
    if publish:
        out = subprocess.run(["gcloud", "pubsub", "topics", "publish", publish, f"--project={project}",
                              f"--message={json.dumps(msg)}"], capture_output=True, text=True)
        print(out.stdout.strip() or out.stderr.strip())
        return out.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
