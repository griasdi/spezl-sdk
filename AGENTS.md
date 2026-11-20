# Repository Guidelines

## Project Overview
The Python and TypeScript SDKs and the example bots of spezl, the bot runner of griasdi, MIT-licensed and public. spezl itself (the `spezl` CLI and the `spezl serve` sidecar these SDKs drive over JSON-RPC on stdio) is closed source and published as a binary for Linux; https://griasdi.github.io/bots/ documents it and the protocol (`#protocol`). Never mention its source, internal paths or private repositories here. Commit conventions, security rules and the checks are in `CONTRIBUTING.md`.

## Key Directories
| Path | Purpose |
|---|---|
| `sdk/python/src/spezl/` | Python SDK (`_bot.py`, `_rpc.py`, `_types.py`), stdlib only, Python ≥3.10; published on PyPI as `spezl` |
| `sdk/typescript/src/` | TS SDK (`index.ts`, `bot.ts`, `rpc.ts`, `types.ts`), `node:` modules only, no build step for development; `npm run build` (run by `prepack`) emits `dist/` for npm; exposes camelCase (`botId`, `replyTo`, `mentionsMe`) |
| `sdk/python/tests/`, `sdk/typescript/test/` | unittest and `node:test` suites: `bot` against the fake serve, `serve` against the real one |
| `tests/fake_spezl.py` | the stand-in for `spezl serve` both suites share |
| `examples/` | one folder per example bot: `hello/{python,typescript}` and `poll/{python,typescript}`; the WoW Forever raid sign-up bot `raid/raid.py` (SQLite storage, `replace_card`, a composition picture drawn by `roster_image.py` with Pillow from the icons in `icons/` (game-icons.net, CC BY 3.0, `icons/LICENSE.md`) in the bundled font of `fonts/` (SIL OFL 1.1, `fonts/OFL.txt`), `upload_image`, tallies, a private leader panel, `reveal`), with its game data in `wow_forever.py`; the voice bot `mickey/mickey.py`; the video bot `stream/stream.py <dir>`; and the welcome bot `welcome/welcome.py <owner/repo>` (greets new members, files `/issue` and `/request` through `gh issue create`). Each folder has a README; Python folders have their own `pyproject.toml` and `uv.lock` |

## Runtime/Tooling Preferences
- TypeScript: **npm** (`package-lock.json`).
  - Node ≥22.18 runs the `.ts` files natively, with `bun` as fallback.
  - The tsconfig uses `erasableSyntaxOnly` and `verbatimModuleSyntax`, so use only type syntax that can be erased: no enums and no namespaces.
  - Use explicit `.ts` import extensions.
- Python: **uv** (`uv_build` backend).
  - Every Python example folder (`examples/{hello,poll}/python`, `examples/{raid,mickey,stream,welcome}`) has its own `pyproject.toml` that depends on `sdk/python` as an editable path source.
  - Keep the SDK free of third-party dependencies.

## Testing
- `cd sdk/python && python3 -m unittest discover -s tests` and `cd sdk/typescript && npm install && npm run check && npm test`; no griasdi server needed.
- `tests/fake_spezl.py` stands in for `spezl serve`: a scenario (env `FAKE_SPEZL_SCENARIO`) of notifications sent after `set_voice`, errors per method; every request logged to `FAKE_SPEZL_LOG`. Both SDKs' `bot` tests use it.
- The `serve` tests run the real `spezl serve` of a fresh bot home without a server and check that it takes every command field and card block (one block per card; a card is refused with `not a server link` only once its wire and griasdi's limits passed). Skipped without `spezl` (`SPEZL_BIN` or `PATH`).
