# Welcome Bot

Greets each new member of a community in its Hello channel with an `@mention`, tells them about
`/issue` and `/request`, and sends them the details by direct message.

It greets everyone who joins after its first start in a community, also someone who joined while
it was offline: it remembers the members it has seen in `members.toml` in its bot home. Bots are
not greeted.

Members report bugs with `/issue` (title, what happened, steps to reproduce, what they expected,
and their system and app version, which their app fills in through a `ClientInfoField`) and
suggest features with `/request` (title, what, why). Sending the form files the report right
away (the member's app shows that the bot is answering meanwhile) with
`gh issue create` as an issue in the GitHub repository given as argument, labelled `bug` or
`enhancement` when the repository has that label. The issue body carries the member's text (every
`@` defanged with a zero-width space, so nobody on GitHub gets mentioned), the reporter's name and
id prefix, the community, the channel and the time. The bot answers privately with what it sent;
when `gh` fails, the answer has Try again and Discard buttons instead. The chat never names
GitHub nor links the issue: the repository may be private.

Each member may send 3 reports per hour and 10 per day, counted in `welcome.sqlite3` in the bot
home, plus the reports being filed. Try again works for an hour and only until the bot restarts.

## What it shows

- New members with `@bot.on_member_join`.
- Direct messages with `await bot.send_dm(server, user, text)`.
- Finding channels by name in `joined.community.channels`.
- Commands with optional fields, private answers (`inv.respond(card, private=True)`) and
  replacing or deleting them on a press (`bot.replace_card`, `bot.delete_message`).

See the [Python SDK](../../README.md#python).

## Run it

From the repo root:

```sh
gh auth login
spezl new "Welcome Bot"
spezl --bot "Welcome Bot" join '<invite link>'
spezl --bot "Welcome Bot" run examples/welcome/welcome.py <owner>/<repo>
```

`--bot "Welcome Bot"` can go when it is the default bot (`spezl default "Welcome Bot"`).

At start the bot checks the repository and prints the GitHub account it files as:
`GitHub: signed in as <login>, posting /issue and /request to <owner/repo>`. It stops when `gh`
is missing or logged out, or the repository has issues turned off.

The community needs text channels named Hello, Request and Issue; the names match in any case
and without punctuation (`Hello!`, `# hello`). Request and Issue are where members post while the
bot is offline. The constants `HELLO`, `REQUEST` and `ISSUE` at the top of `welcome.py` change
them, `TEAM` the name the chat uses for whoever reads the issues, `PER_HOUR` and `PER_DAY` the
limits. In a community without a Hello channel the bot greets nobody and sends no direct message.
It needs the right to post in Hello.

## Requirements

[uv](https://docs.astral.sh/uv/) (Python ≥ 3.10) and the [GitHub CLI](https://cli.github.com/)
`gh`, logged in with access to the repository.
