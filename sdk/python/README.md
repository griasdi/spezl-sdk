# spezl

The Python SDK for [spezl](https://griasdi.github.io/bots/), the bot runner of griasdi. It has
no dependencies and needs Python ≥ 3.10 and the `spezl` program: download it from
https://griasdi.github.io/bots/.

```sh
pip install spezl   # or: uv add spezl
```

```python
import spezl

bot = spezl.Bot()  # Bot(home=..., binary=...) overrides SPEZL_HOME / SPEZL_BIN


@bot.on_ready
async def ready(server: str) -> None:
    print(f"{bot.name} ready on {server}", flush=True)


@bot.on_mention  # @bot.on_message gets every message
async def greet(msg: spezl.Message) -> None:
    await msg.reply(f"hi, @{msg.sender.name}!")


bot.run()
```

The full API and the example bots are at https://github.com/griasdi/spezl-sdk.
