import time

import spezl

bot = spezl.Bot()

ENDS = {"1h": 3_600_000, "1d": 86_400_000, "1w": 604_800_000}


@bot.on_ready
async def ready(server: str) -> None:
    print(f"{bot.name} ready on {server}", flush=True)


@bot.command(
    "poll",
    "Start a poll",
    fields=[
        spezl.TextField(
            "question",
            "Question",
            placeholder="What should we play tonight?",
            max_chars=300,
        ),
        spezl.TextListField(
            "options", "Options", placeholder="Option", min=2, max=10, max_chars=100
        ),
        spezl.ToggleField("multiple", "Allow several answers", default=False),
        spezl.ToggleField("hidden", "Show results only when it ends", default=False),
        spezl.ToggleField("voters", "Show who voted", default=True),
        spezl.ChoiceField(
            "ends",
            "Ends",
            [
                ("never", "When I end it"),
                ("1h", "In 1 hour"),
                ("1d", "In 1 day"),
                ("1w", "In 1 week"),
            ],
            default="never",
        ),
    ],
)
async def poll(inv: spezl.Invocation) -> None:
    v = inv.values
    ends = ENDS.get(v["ends"])
    await inv.respond(
        spezl.Card(
            blocks=[
                spezl.Poll(
                    v["question"],
                    v["options"],
                    multiple=v["multiple"],
                    hidden_results=v["hidden"],
                    show_voters=v["voters"],
                    closes_ms=None if ends is None else int(time.time() * 1000) + ends,
                    creator=inv.sender.id,
                )
            ]
        )
    )


bot.run()
