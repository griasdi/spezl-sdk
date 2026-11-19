import { Bot } from "../../../sdk/typescript/src/index.ts";

const ENDS: Record<string, number> = { "1h": 3_600_000, "1d": 86_400_000, "1w": 604_800_000 };

const bot = new Bot();
bot.onReady((server) => console.log(`${bot.name} ready on ${server}`));
bot.command(
  {
    name: "poll",
    description: "Start a poll",
    fields: [
      {
        type: "text",
        id: "question",
        label: "Question",
        placeholder: "What should we play tonight?",
        maxChars: 300,
      },
      {
        type: "textList",
        id: "options",
        label: "Options",
        placeholder: "Option",
        min: 2,
        max: 10,
        maxChars: 100,
      },
      { type: "toggle", id: "multiple", label: "Allow several answers", default: false },
      { type: "toggle", id: "hidden", label: "Show results only when it ends", default: false },
      { type: "toggle", id: "voters", label: "Show who voted", default: true },
      {
        type: "choice",
        id: "ends",
        label: "Ends",
        options: [
          { id: "never", label: "When I end it" },
          { id: "1h", label: "In 1 hour" },
          { id: "1d", label: "In 1 day" },
          { id: "1w", label: "In 1 week" },
        ],
        default: "never",
      },
    ],
  },
  async (inv) => {
    const v = inv.values;
    const ends = ENDS[v["ends"] as string];
    await inv.respond({
      blocks: [
        {
          type: "poll",
          question: v["question"] as string,
          options: v["options"] as string[],
          multiple: v["multiple"] as boolean,
          hiddenResults: v["hidden"] as boolean,
          showVoters: v["voters"] as boolean,
          closesMs: ends === undefined ? null : Date.now() + ends,
          creator: inv.sender.id,
        },
      ],
    });
  },
);
await bot.run();
