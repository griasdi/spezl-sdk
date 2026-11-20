# @griasdilab/spezl

The TypeScript SDK for [spezl](https://griasdi.github.io/bots/), the bot runner of griasdi. It
has no dependencies, runs on Node ≥ 22.18 and on Bun, and needs the `spezl` program: download
it from https://griasdi.github.io/bots/.

```sh
npm install @griasdilab/spezl
```

Your `package.json` needs `"type": "module"`.

```ts
import { Bot } from "@griasdilab/spezl";

const bot = new Bot(); // new Bot({ home, binary }) overrides SPEZL_HOME / SPEZL_BIN
bot.onReady((server) => console.log(`${bot.name} ready on ${server}`));
bot.onMention(async (msg) => {
  await msg.reply(`hi, @${msg.sender.name}!`);
});
await bot.run(); // resolves when the bot stops (SIGINT/SIGTERM or bot.close())
```

The full API and the example bots are at https://github.com/griasdi/spezl-sdk.
