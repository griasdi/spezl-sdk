import spezl

bot = spezl.Bot()


@bot.on_ready
async def ready(server: str) -> None:
    print(f"{bot.name} ready on {server}", flush=True)


@bot.on_mention
async def greet(msg: spezl.Message) -> None:
    await msg.reply(f"hi, @{msg.sender.name}!")


bot.run()
