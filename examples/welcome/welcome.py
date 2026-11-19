"""Welcome Bot: greets each new member of a community in its Hello channel and sends them the
details by direct message. Members file bugs with /issue and feature requests with /request;
the bot files each as a GitHub issue in the repository given as argument (via `gh`, which must be
logged in) as soon as the form is sent.

Run it with `spezl run examples/welcome/welcome.py <owner>/<repo>`."""

import asyncio
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import spezl

HELLO = "Hello"
"""The channel the bot greets new members in."""
REQUEST = "Request"
"""The channel for feature requests while the bot is offline."""
ISSUE = "Issue"
"""The channel for issues while the bot is offline."""
TEAM = "griasdi dev team"
"""Who reports go to, as the chat says it: the repository is private, so the chat never names
GitHub."""

PER_HOUR = 3
"""Reports one member may send per hour."""
PER_DAY = 10
"""Reports one member may send per day."""
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
DRAFT_TTL_MS = 3_600_000
"""How long a failed report's Try again works."""
GH_TIMEOUT = 60
"""Seconds `gh issue create` may take."""

LABELS = {"issue": "bug", "request": "enhancement"}
"""The GitHub label per kind of report."""
KINDS = {"issue": "Issue", "request": "Feature request"}
"""The summary heading per kind of report."""

DB_PATH = Path(os.environ.get("SPEZL_HOME") or ".") / "welcome.sqlite3"

DETAILS = """Hi {name}, welcome to {community}! Here is how to reach the {team}:

**Found a bug?** Type /issue in any channel. A form asks what happened, how to make it happen again and what you expected; your app fills in your system and app version, and you can change them. It goes to the team as soon as you send the form.

**Missing something?** Type /request and say what you want to do and why it would help you.

Your name goes with every report, so the team can ask you about it. You can send {per_hour} reports per hour and {per_day} per day.

If I'm offline, post in {issue} or {request} instead. Say hi in {hello} whenever you like. Have fun!"""


def setup() -> tuple[str, str, set[str]]:
    """Checks the repository argument and `gh`, and returns `(gh, repo, labels)`;
    exits with a message when something is missing."""
    if len(sys.argv) < 2:
        sys.exit("usage: spezl run examples/welcome/welcome.py <owner/repo>")
    repo = sys.argv[1]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        sys.exit(f"not a GitHub repository: {repo!r} (want owner/repo)")
    gh = shutil.which("gh")
    if gh is None:
        sys.exit("gh not found on PATH: install the GitHub CLI and run gh auth login")

    def run_gh(*args: str) -> str:
        done = subprocess.run([gh, *args], capture_output=True, text=True, timeout=30)
        if done.returncode != 0:
            sys.exit(f"gh {' '.join(args)} failed: {done.stderr.strip()}")
        return done.stdout.strip()

    login = run_gh("api", "user", "--jq", ".login")
    issues = run_gh("repo", "view", repo, "--json", "hasIssuesEnabled", "--jq", ".hasIssuesEnabled")
    if issues != "true":
        sys.exit(f"{repo} has issues turned off")
    labels = set(
        run_gh(
            "label", "list", "--repo", repo, "--json", "name", "--jq", ".[].name", "--limit", "200"
        ).splitlines()
    )
    for label in LABELS.values():
        if label not in labels:
            print(
                f"label {label!r} not in {repo}: those reports go without a label",
                file=sys.stderr,
                flush=True,
            )
    print(f"GitHub: signed in as {login}, posting /issue and /request to {repo}", flush=True)
    return gh, repo, labels


GH, REPO, labels = setup()

db = sqlite3.connect(DB_PATH)
db.execute(
    "CREATE TABLE IF NOT EXISTS sent "
    "(user TEXT NOT NULL, kind TEXT NOT NULL, number INTEGER, at_ms INTEGER NOT NULL)"
)
db.commit()

bot = spezl.Bot()


def now_ms() -> int:
    """The bot's clock: an invocation's `ts_ms` is the sender's, unchecked."""
    return int(time.time() * 1000)


inflight: dict[str, int] = {}
"""Reports per member that `gh` is filing right now."""


def limit_reason(user: str, now: int) -> str | None:
    """Why `user` may not send another report now, or None."""
    for window, cap, what in [(HOUR_MS, PER_HOUR, "per hour"), (DAY_MS, PER_DAY, "per day")]:
        rows = [
            at
            for (at,) in db.execute(
                "SELECT at_ms FROM sent WHERE user = ? AND at_ms > ? ORDER BY at_ms",
                (user, now - window),
            )
        ]
        if len(rows) + inflight.get(user, 0) >= cap:
            oldest = rows[0] if rows else now  # only in-flight reports: recorded about now
            wait = math.ceil((oldest + window - now) / 60_000)
            return f"You can send {cap} reports {what}. Try again in {wait} min."
    return None


def record(user: str, kind: str, number: int | None, at: int) -> None:
    db.execute(
        "INSERT INTO sent (user, kind, number, at_ms) VALUES (?, ?, ?, ?)",
        (user, kind, number, at),
    )
    db.commit()


def defang(text: str) -> str:
    """`text` without GitHub mentions: a zero-width space after each `@`, so member text never
    notifies GitHub users or teams."""
    return text.replace("@", "@\u200b")


@dataclass
class Draft:
    kind: str
    """"issue" or "request"."""
    author_id: str
    author_name: str
    community: str
    channel: str
    title: str
    sections: list[tuple[str, str]]
    """(heading, markdown) in order."""
    client: str
    """The member's system and app version as their app filled it in; empty for a request."""
    made_ms: int
    sending: bool = False


drafts: dict[tuple[str, str, int], Draft] = {}
"""Reports `gh` could not file, waiting for Try again, by (server, group, card seq). Lost on
restart."""


class FileError(Exception):
    """`gh issue create` failed."""


def summary(d: Draft) -> list[str]:
    """The paragraphs of the report `d`."""
    parts = [f"**{KINDS[d.kind]}: {d.title}**"]
    parts += [f"**{h}**\n{text}" for h, text in d.sections]
    if d.client:
        parts.append(f"**System**\n{d.client}")
    parts.append(f"From {d.author_name} ({d.author_id[:8]}) in {d.community}, #{d.channel}")
    return parts


def sent_card(d: Draft, number: int | None) -> spezl.Card:
    sent = f"✅ Sent to the {TEAM}" + (f" as #{number}" if number is not None else "")
    return spezl.Card("\n\n".join([f"{sent}. Thanks, {d.author_name}!", *summary(d)]))


def failed_card(d: Draft) -> spezl.Card:
    """`d` with Try again and Discard. While the bot files it, the member's app shows the
    pressed button busy until the card changes."""
    return spezl.Card(
        "\n\n".join([*summary(d), "⚠️ Could not send it right now. Try again in a minute."]),
        [
            spezl.Buttons(
                [
                    spezl.Button("send", "Try again", "primary"),
                    spezl.Button("discard", "Discard"),
                ]
            )
        ],
    )


def issue_body(d: Draft, sent_at: datetime) -> str:
    body = "\n\n".join(f"### {h}\n\n{defang(t)}" for h, t in d.sections)
    if d.client:
        body += f"\n\n### System\n\n{defang(d.client)}"
    body += (
        "\n\n### Reported via griasdi\n\n"
        f"- Reporter: {defang(d.author_name)} (`{d.author_id[:8]}`)\n"
        f"- Community: {defang(d.community)}\n"
        f"- Channel: #{defang(d.channel)}\n"
        f"- Sent: {sent_at:%Y-%m-%d %H:%M} UTC"
    )
    return body


async def file_issue(d: Draft) -> tuple[int | None, str]:
    """Files `d` as an issue in `REPO`; returns its number (None when `gh`'s output has none)
    and URL."""
    args = ["issue", "create", "--repo", REPO, "--title", defang(d.title), "--body-file", "-"]
    if LABELS[d.kind] in labels:
        args += ["--label", LABELS[d.kind]]
    try:
        proc = await asyncio.create_subprocess_exec(
            GH,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        raise FileError(f"cannot run gh: {e}") from None
    body = issue_body(d, datetime.now(timezone.utc)).encode()
    try:
        out, err = await asyncio.wait_for(proc.communicate(body), GH_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise FileError("gh timed out") from None
    if proc.returncode != 0:
        raise FileError(err.decode().strip())
    lines = [line for line in out.decode().splitlines() if line.strip()]
    url = lines[-1].strip() if lines else ""
    match = re.search(r"/issues/(\d+)$", url)
    return (int(match.group(1)) if match else None), url


async def submit(d: Draft) -> int | None:
    """Files `d`, records and logs it, and returns the issue number; raises `FileError`."""
    inflight[d.author_id] = inflight.get(d.author_id, 0) + 1
    try:
        number, url = await file_issue(d)
    except FileError as e:
        print(f"cannot file {d.kind} from {d.author_name}: {e}", file=sys.stderr, flush=True)
        raise
    finally:
        inflight[d.author_id] -= 1
        if inflight[d.author_id] == 0:
            del inflight[d.author_id]
    record(d.author_id, d.kind, number, now_ms())
    print(f"{d.author_name} sent {d.kind} #{number}: {url}", flush=True)
    return number


async def report(inv: spezl.Invocation, kind: str) -> None:
    """Files the report of `inv` and answers privately with the result; a failed one keeps
    Try again until `DRAFT_TTL_MS`."""
    if inv.sender.bot_id:
        return
    now = now_ms()
    reason = limit_reason(inv.sender.id, now)
    if reason is not None:
        await inv.respond(spezl.Card(reason), private=True)
        return
    v = inv.values
    if kind == "issue":
        steps = v.get("steps") or []
        sections = [("What happened", v["what"])]
        if steps:
            sections.append(
                ("Steps to reproduce", "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))
            )
        if v.get("expected"):
            sections.append(("Expected", v["expected"]))
        client = v["client"]
    else:
        sections = [("What", v["what"])]
        if v.get("why"):
            sections.append(("Why", v["why"]))
        client = ""
    d = Draft(
        kind=kind,
        author_id=inv.sender.id,
        author_name=inv.sender.name,
        community=inv.community.name,
        channel=inv.channel.name,
        title=v["title"],
        sections=sections,
        client=client,
        made_ms=now,
    )
    try:
        number = await submit(d)
    except FileError:
        seq = await inv.respond(failed_card(d), private=True)
        for k in [k for k, old in drafts.items() if now - old.made_ms > DRAFT_TTL_MS]:
            del drafts[k]
        drafts[(inv.channel.server, inv.channel.group, seq)] = d
        return
    await inv.respond(sent_card(d, number), private=True)


@bot.on_ready
async def ready(server: str) -> None:
    print(f"{bot.name} ready on {server}", flush=True)


@bot.command(
    "issue",
    f"Report a bug to the {TEAM}; your name goes with it",
    fields=[
        spezl.TextField("title", "Title", placeholder="Short summary", max_chars=100),
        spezl.TextField("what", "What happened?", max_chars=1000),
        spezl.TextListField(
            "steps",
            "Steps to reproduce",
            placeholder="Open the app",
            min=1,
            max=8,
            max_chars=150,
            required=False,
        ),
        spezl.TextField("expected", "What did you expect?", max_chars=500, required=False),
        spezl.ClientInfoField("client", "Your system and app version"),
    ],
)
async def issue(inv: spezl.Invocation) -> None:
    await report(inv, "issue")


@bot.command(
    "request",
    f"Suggest a feature to the {TEAM}; your name goes with it",
    fields=[
        spezl.TextField("title", "Title", placeholder="Short summary", max_chars=100),
        spezl.TextField("what", "What do you want to do?", max_chars=1000),
        spezl.TextField("why", "Why would it help you?", max_chars=1000, required=False),
    ],
)
async def request(inv: spezl.Invocation) -> None:
    await report(inv, "request")


@bot.on_press
async def press(press: spezl.Press) -> None:
    if press.button not in ("send", "discard"):
        return
    slot = (press.channel.server, press.channel.group, press.card)
    d = drafts.get(slot)
    if d is None or now_ms() - d.made_ms > DRAFT_TTL_MS:
        drafts.pop(slot, None)
        await bot.replace_card(
            press.channel,
            press.card,
            spezl.Card(
                "This report is gone: I restarted or it is older than an hour. "
                "Type /issue or /request again."
            ),
        )
        return
    if press.sender.id != d.author_id or d.sending:
        return
    if press.button == "discard":
        drafts.pop(slot, None)
        await bot.delete_message(press.channel, press.card)
        return
    reason = limit_reason(d.author_id, now_ms())
    if reason is not None:
        drafts.pop(slot, None)
        await bot.replace_card(press.channel, press.card, spezl.Card(reason))
        return
    d.sending = True
    try:
        number = await submit(d)
    except FileError:
        await bot.replace_card(press.channel, press.card, failed_card(d))
        return
    finally:
        d.sending = False
    drafts.pop(slot, None)
    await bot.replace_card(press.channel, press.card, sent_card(d, number))


@bot.on_member_join
async def welcome(joined: spezl.MemberJoined) -> None:
    if joined.member.bot_id:
        return
    name = joined.member.name
    community = joined.community.name
    hello = find(joined.community, HELLO)
    if hello is None:
        print(
            f"no {HELLO} channel in {community}: not greeting {name}",
            file=sys.stderr,
            flush=True,
        )
        return
    request = mention(joined.community, REQUEST)
    issue = mention(joined.community, ISSUE)
    try:
        await bot.send(
            hello,
            f"Welcome to {community}, @{name}! 👋 Found a bug? Type /issue. Missing something? "
            "Type /request. I've sent you the details in a direct message.",
        )
    except spezl.SpezlError as e:
        print(f"cannot greet {name} in {hello.name}: {e}", file=sys.stderr, flush=True)
    details = DETAILS.format(
        name=name,
        community=community,
        request=request,
        issue=issue,
        hello=f"#{hello.name}",
        team=TEAM,
        per_hour=PER_HOUR,
        per_day=PER_DAY,
    )
    try:
        await bot.send_dm(joined.community.server, joined.member.id, details)
    except spezl.SpezlError as e:
        print(f"cannot send {name} the details: {e}", file=sys.stderr, flush=True)


def key(name: str) -> str:
    """`name` as compared: its letters and digits in lower case, so `Hello!` and `# hello`
    match `Hello`."""
    return "".join(c for c in name.lower() if c.isalnum())


def find(community: spezl.Community, name: str) -> spezl.Channel | None:
    return next((ch for ch in community.channels if key(ch.name) == key(name)), None)


def mention(community: spezl.Community, name: str) -> str:
    """`#<channel>` for the channel called `name`, as plain text: griasdi cannot link a
    channel."""
    channel = find(community, name)
    return f"#{channel.name if channel else name}"


bot.run()
