# Contributing to the spezl SDKs

## Before you send a change

Run the checks of the SDK you changed; all of them must pass. They need no
griasdi server.

```sh
cd sdk/python && python3 -m unittest discover -s tests
cd sdk/typescript && npm install && npm run check && npm test
```

`npm run check` type-checks the TypeScript SDK, its tests and
`examples/*/typescript`. The tests run each SDK against two sidecars:

- `tests/fake_spezl.py`, a stand-in for `spezl serve` (Python 3, stdlib only)
  that plays a scripted list of notifications and records what the SDK asks
  for. It needs nothing else.
- the real `spezl serve`, which checks the wire of every command field and
  card block the SDK writes as strictly as it does with a server. These tests
  need `spezl` (`SPEZL_BIN`, else on `PATH`; Linux x86_64 and ARM64, from
  https://griasdi.github.io/bots/) and are skipped without it. Run them
  before you send a change that touches what goes on the wire.

To try an example bot for real, you need a griasdi community to invite it to,
on your own server or one you are a member of: `spezl new`, `spezl join
<invite link>`, then `spezl run <example>` (see the example's README). The
maintainers also run every example bot end to end against a test server
before a release.

## Security rules

- Dependencies: the Python SDK stays stdlib-only, and the TypeScript SDK uses
  only `node:` modules.
- Secrets and message plaintext never reach logs or error messages. Bot
  authors log message bodies in their own code, not in the SDKs.
- Report a security problem privately, through "Report a vulnerability" on the
  repository's Security tab, never in a public issue. Security fixes carry
  `Changelog: security`.

## Protocol changes

The SDKs speak the protocol of `spezl serve`, documented at
https://griasdi.github.io/bots/#protocol; `spezl` itself is not open source.
A change of the protocol comes from the maintainers, together with the
matching change of `sdk/python/src/spezl/` and `sdk/typescript/src/`. Open an
issue to ask for one.

## Naming

spezl and griasdi are described on their own terms. Never name another chat
or voice product or position griasdi against one ("like X", "an X
alternative") in code, comments, UI text, docs or commit messages, and never
use another product's brand colors or marks.

## Commits

One logical change per commit. The subject is a plain summary: imperative
mood, capitalized, no trailing period, at most 72 characters.

**No prefixes.** The subject never starts with a type or scope such as
`feat:`, `fix:`, `chore:`, `docs:` or `fix(serve):`. What kind of change it is
goes into the `Changelog` trailer (below), not into the subject.

```
Retry a locked bot home while a child process exits
```

not

```
fix(cli): retry locked home
```

Use the body to explain why, not what.

`main` has a linear history: a branch lands by fast-forward or rebase, and
GitHub does not notice that it was merged. Whoever lands a branch deletes it
on the remote right after the push to `main`
(`git push origin --delete <branch>`); otherwise it lingers as a branch
behind `main` with nothing of its own.

## Changelog trailer

The changelog is generated from commit trailers; there is no hand-edited
`CHANGELOG.md`. A commit that bot authors using the CLI, the sidecar protocol
or the SDKs would notice carries a `Changelog` trailer as the last paragraph
of its message:

```
Retry a locked bot home while a child process exits

Changelog: fixed
```

| Value | Use for |
|---|---|
| `added` | new features |
| `changed` | changes in existing behavior |
| `deprecated` | features that will be removed |
| `removed` | features removed |
| `fixed` | bug fixes |
| `security` | vulnerability fixes and hardening |
| `performance` | noticeable speed or resource improvements |

Commits without the trailer (refactors, tests, formatting, internal chores) do
not appear in the changelog. The commit subject becomes the changelog entry, so
write it for a reader of release notes.

Add the trailer when committing:

```sh
git commit -m "Retry a locked bot home while a child process exits" --trailer "Changelog: fixed"
```

or amend it onto the last commit with `git commit --amend --no-edit --trailer "Changelog: fixed"`.

List the entries since a tag, one per line, category first:

```sh
git log --format='%(trailers:key=Changelog,valueonly,separator=%x2C)%x09%s' v0.1.0..HEAD | grep -v '^[[:space:]]'
```
