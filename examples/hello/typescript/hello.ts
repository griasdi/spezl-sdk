import { Bot } from "../../../sdk/typescript/src/index.ts";

const bot = new Bot();
bot.onReady((server) => console.log(`${bot.name} ready on ${server}`));
bot.onMention(async (msg) => {
  await msg.reply(`hi, @${msg.sender.name}!`);
});
await bot.run();
