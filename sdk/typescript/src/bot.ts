import { Buffer } from "node:buffer";
import { resolve } from "node:path";
import { CLOSE_TIMEOUT_MS, Connection } from "./rpc.ts";
import {
  Invocation,
  Message,
  Press,
  SpezlError,
  Submit,
  cardToWire,
  commandToWire,
  memberJoinedFromWire,
  messageFromWire,
  streamEndedFromWire,
  type Card,
  type CardImage,
  type Channel,
  type CommandSpec,
  type Community,
  type MemberJoined,
  type StreamEnded,
  type WireMemberJoined,
  type WireStreamEnded,
  type WireInvocation,
  type WireMessage,
  type WirePress,
  type WireSubmit,
} from "./types.ts";

const PROTOCOL = 2;

export interface BotOptions {
  /** Bot home directory, passed to `spezl --home`. Default: `$SPEZL_HOME`, else serve's own default. */
  home?: string;
  /** Path of the `spezl` binary. Default: `$SPEZL_BIN`, else `spezl` on `PATH`. */
  binary?: string;
}

type MessageHandler = (msg: Message) => void | Promise<void>;
type ReadyHandler = (server: string) => void | Promise<void>;
type InvocationHandler = (inv: Invocation) => void | Promise<void>;
type PressHandler = (press: Press) => void | Promise<void>;
type SubmitHandler = (submit: Submit) => void | Promise<void>;
type StreamEndedHandler = (ended: StreamEnded) => void | Promise<void>;
type MemberJoinedHandler = (joined: MemberJoined) => void | Promise<void>;

interface Info {
  protocol: number;
  user_id: string;
  name: string;
  bot_id: boolean;
  servers: string[];
}

export class Bot {
  readonly #home: string | undefined;
  readonly #binary: string;
  readonly #messageHandlers: MessageHandler[] = [];
  readonly #mentionHandlers: MessageHandler[] = [];
  readonly #readyHandlers: ReadyHandler[] = [];
  readonly #tasks = new Set<Promise<void>>();
  readonly #commands = new Map<string, { spec: CommandSpec; handler: InvocationHandler }>();
  readonly #pressHandlers: PressHandler[] = [];
  readonly #submitHandlers: SubmitHandler[] = [];
  readonly #streamEndedHandlers: StreamEndedHandler[] = [];
  readonly #memberJoinHandlers: MemberJoinedHandler[] = [];
  #conn: Connection | undefined;
  #info: Info | undefined;
  #closing: Promise<void> | undefined;

  constructor(options: BotOptions = {}) {
    // `||`: an empty variable counts as unset.
    this.#home = options.home || process.env["SPEZL_HOME"] || undefined;
    this.#binary = options.binary || process.env["SPEZL_BIN"] || "spezl";
  }

  /** Called for every message in a text channel the bot can read. */
  onMessage(handler: MessageHandler): this {
    this.#messageHandlers.push(handler);
    return this;
  }

  /** Called for messages that @mention the bot. */
  onMention(handler: MessageHandler): this {
    this.#mentionHandlers.push(handler);
    return this;
  }

  /** Called when a server is connected and synced. */
  onReady(handler: ReadyHandler): this {
    this.#readyHandlers.push(handler);
    return this;
  }

  /** Offers the slash command `/name` in every channel; members fill in its `fields` and
   * `handler` runs. One handler per name. */
  command(spec: CommandSpec, handler: InvocationHandler): this {
    this.#commands.set(spec.name, { spec, handler });
    return this;
  }

  /** Called for presses of buttons on the bot's cards. */
  onPress(handler: PressHandler): this {
    this.#pressHandlers.push(handler);
    return this;
  }

  /** Called for forms members send from the bot's cards. */
  onSubmit(handler: SubmitHandler): this {
    this.#submitHandlers.push(handler);
    return this;
  }

  /** Called when a stream of the bot ended. */
  onStreamEnded(handler: StreamEndedHandler): this {
    this.#streamEndedHandlers.push(handler);
    return this;
  }

  /** Called once for each member who joined a community of the bot, also for one who joined
   * while the bot was offline. */
  onMemberJoin(handler: MemberJoinedHandler): this {
    this.#memberJoinHandlers.push(handler);
    return this;
  }

  get userId(): string {
    return this.#requireInfo().user_id;
  }

  get name(): string {
    return this.#requireInfo().name;
  }

  #requireInfo(): Info {
    if (!this.#info) throw new SpezlError("the bot is not running yet: call run() first");
    return this.#info;
  }

  #requireConn(): Connection {
    if (!this.#conn) throw new SpezlError("the bot is not running yet: call run() first");
    return this.#conn;
  }

  async communities(): Promise<Community[]> {
    return (await this.#requireConn().request("communities")) as Community[];
  }

  /** Sends `text` into `channel`. Returns the seq of the new message. */
  async send(channel: Channel, text: string, options: { replyTo?: number } = {}): Promise<number> {
    const result = (await this.#requireConn().request("send", {
      server: channel.server,
      group: channel.group,
      text,
      reply_to: options.replyTo ?? null,
    })) as { seq: number };
    return result.seq;
  }

  /** Sends `text` as a direct message to member `user` (user id) on `server`. Returns its seq. */
  async sendDm(server: string, user: string, text: string): Promise<number> {
    const result = (await this.#requireConn().request("send_dm", { server, user, text })) as {
      seq: number;
    };
    return result.seq;
  }

  /** Posts `card` into `channel`; `answers` is the seq of the invocation it answers, `to` the
   * member (user id) who alone sees the card. Returns the card's seq. */
  async postCard(
    channel: Channel,
    card: Card,
    options: { answers?: number; to?: string } = {},
  ): Promise<number> {
    const result = (await this.#requireConn().request("post_card", {
      server: channel.server,
      group: channel.group,
      card: cardToWire(card),
      answers: options.answers ?? null,
      ...(options.to !== undefined ? { to: options.to } : {}),
    })) as { seq: number };
    return result.seq;
  }

  /** Replaces the markdown body of the bot's own card `seq` in `channel`; its buttons and poll
   * stay. */
  async editCard(channel: Channel, seq: number, body: string): Promise<void> {
    await this.#requireConn().request("edit_card", {
      server: channel.server,
      group: channel.group,
      seq,
      body,
    });
  }

  /** Replaces the bot's own card `seq` in `channel`, body and blocks, in place. */
  async replaceCard(channel: Channel, seq: number, card: Card): Promise<void> {
    await this.#requireConn().request("replace_card", {
      server: channel.server,
      group: channel.group,
      seq,
      card: cardToWire(card),
    });
  }

  /** Deletes the bot's own message `seq` in `channel` for everyone. */
  async deleteMessage(channel: Channel, seq: number): Promise<void> {
    await this.#requireConn().request("delete_message", {
      server: channel.server,
      group: channel.group,
      seq,
    });
  }

  /** Scrolls the chat of the member who sent `action` (the seq of a press or form submission
   * on one of the bot's cards in `channel`) to the bot's card `target` there that they see.
   * Their app follows only the first reveal per press, within 10 s of it, on the device they
   * pressed on, while that chat is open. Rejects when `action` is no press on the bot's card or
   * `target` no card of the bot the member sees. */
  async reveal(channel: Channel, action: number, target: number): Promise<void> {
    await this.#requireConn().request("reveal", {
      server: channel.server,
      group: channel.group,
      action,
      target,
    });
  }

  /** Stores a picture (PNG, JPEG, GIF or WebP; griasdi shrinks it to at most 1200 px per side)
   * encrypted on `channel`'s server for one card's image block. Deleting that card, or
   * replacing it with one that no longer shows the picture, deletes it, so every card uploads
   * its own. Rejects when `data` is no image griasdi can open. */
  async uploadImage(channel: Channel, data: Uint8Array): Promise<CardImage> {
    return (await this.#requireConn().request("upload_image", {
      server: channel.server,
      group: channel.group,
      data: Buffer.from(data).toString("base64"),
    })) as CardImage;
  }

  /** Streams the video file at `path` into `channel` as a screen share titled `title` (blank:
   * the file name). A running stream stops first. Resolves once the stream is live; it plays
   * from the first viewer on, and the `onStreamEnded` handlers run at its end. `startMs`: where
   * in the file to begin; a start within about 2 s of the end fails with
   * `video: start at … too close to the end …`. */
  async streamFile(
    channel: Channel,
    path: string,
    options: { title?: string; startMs?: number } = {},
  ): Promise<void> {
    await this.#requireConn().request("stream_file", {
      server: channel.server,
      group: channel.group,
      path: resolve(path),
      title: options.title ?? "",
      start_ms: options.startMs ?? 0,
    });
  }

  /** Stops the running stream; resolves to whether one ran. */
  async stopStream(): Promise<boolean> {
    return (await this.#requireConn().request("stop_stream")) as boolean;
  }

  /** Runs the bot until serve ends (or `close()` / SIGINT / SIGTERM). */
  async run(): Promise<void> {
    const conn = await Connection.open(this.#binary, this.#home);
    this.#conn = conn;
    this.#closing = undefined;
    // serve may send notifications right behind the info response, before `info` is
    // processed here; hold them back so handlers can already use `name` and `userId`.
    const early: Array<[string, unknown]> = [];
    conn.onNotification((method, params) => {
      if (this.#info) this.#dispatch(method, params);
      else early.push([method, params]);
    });
    try {
      const info = (await conn.request("info")) as Info;
      if (info.protocol !== PROTOCOL) {
        throw new SpezlError(
          `spezl serve speaks protocol ${info.protocol}, this SDK ${PROTOCOL}`,
        );
      }
      this.#info = info;
      conn.onNotification((method, params) => this.#dispatch(method, params));
      for (const [method, params] of early) this.#dispatch(method, params);
      // Always, also an empty set: it withdraws the commands of an earlier run.
      await conn.request("set_commands", {
        commands: [...this.#commands.values()].map(({ spec }) => commandToWire(spec)),
      });
      // Always, so that a home that once ran a voice bot stops offering voice.
      await conn.request("set_voice", { voice: false });
    } catch (err) {
      await conn.close();
      throw err;
    }

    const onSignal = () => {
      void this.close();
    };
    process.once("SIGINT", onSignal);
    process.once("SIGTERM", onSignal);
    try {
      await conn.done;
      await Promise.allSettled([...this.#tasks]);
    } finally {
      process.off("SIGINT", onSignal);
      process.off("SIGTERM", onSignal);
    }
    if (conn.exitCode !== 0 && this.#closing === undefined) {
      throw new SpezlError(conn.exitMessage());
    }
  }

  /** Asks serve to shut down and waits for it to exit. */
  close(): Promise<void> {
    if (!this.#conn) return Promise.resolve();
    this.#closing ??= this.#close();
    return this.#closing;
  }

  async #close(): Promise<void> {
    const conn = this.#conn;
    if (!conn) return;
    await Promise.race([
      conn.request("shutdown").catch(() => {
        // serve may already be gone
      }),
      new Promise((r) => setTimeout(r, CLOSE_TIMEOUT_MS).unref()),
    ]);
    await conn.close();
  }

  #dispatch(method: string, params: unknown): void {
    if (method === "ready") {
      const server = (params as { server: string }).server;
      for (const handler of this.#readyHandlers) this.#spawn(() => handler(server));
    } else if (method === "message") {
      const msg = messageFromWire(params as WireMessage, (channel, text, options) =>
        this.send(channel, text, options),
      );
      for (const handler of this.#messageHandlers) this.#spawn(() => handler(msg));
      if (msg.mentionsMe) {
        for (const handler of this.#mentionHandlers) this.#spawn(() => handler(msg));
      }
    } else if (method === "invocation") {
      const inv = new Invocation(params as WireInvocation, (channel, card, options) =>
        this.postCard(channel, card, options),
      );
      const command = this.#commands.get(inv.command);
      if (command) this.#spawn(() => command.handler(inv));
    } else if (method === "press") {
      const press = new Press(
        params as WirePress,
        (channel, text, options) => this.send(channel, text, options),
        (channel, card, options) => this.postCard(channel, card, options),
        (channel, action, target) => this.reveal(channel, action, target),
      );
      for (const handler of this.#pressHandlers) this.#spawn(() => handler(press));
    } else if (method === "submit") {
      const submit = new Submit(
        params as WireSubmit,
        (channel, text, options) => this.send(channel, text, options),
        (channel, card, options) => this.postCard(channel, card, options),
        (channel, action, target) => this.reveal(channel, action, target),
      );
      for (const handler of this.#submitHandlers) this.#spawn(() => handler(submit));
    } else if (method === "stream_ended") {
      const ended = streamEndedFromWire(params as WireStreamEnded);
      for (const handler of this.#streamEndedHandlers) this.#spawn(() => handler(ended));
    } else if (method === "member_joined") {
      const joined = memberJoinedFromWire(params as WireMemberJoined);
      for (const handler of this.#memberJoinHandlers) this.#spawn(() => handler(joined));
    }
  }

  #spawn(fn: () => void | Promise<void>): void {
    const task = (async () => {
      try {
        await fn();
      } catch (err) {
        console.error(err);
      }
    })();
    this.#tasks.add(task);
    void task.finally(() => this.#tasks.delete(task));
  }
}
