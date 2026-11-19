export interface Sender {
  id: string;
  name: string;
  /** Whether the id carries the bot marker: a convention of honest bot software, not proof. */
  botId: boolean;
}

export interface Channel {
  server: string;
  id: string;
  name: string;
  group: string;
}

export interface CommunityRef {
  id: string;
  name: string;
}

export interface Community {
  server: string;
  id: string;
  name: string;
  channels: Channel[];
}

/** A stream of the bot ended. `error` says why when `reason` is "failed"; "lost" means the
 * server ended the share. `path`: the file's absolute path (the SDK resolves a relative
 * `streamFile` path against the working directory); `positionMs`: how far it played (the
 * start when nobody watched). */
export interface StreamEnded {
  channel: Channel;
  path: string;
  title: string;
  reason: "finished" | "stopped" | "failed" | "lost";
  error: string | null;
  positionMs: number;
}

export interface WireStreamEnded {
  channel: Channel;
  path: string;
  title: string;
  reason: "finished" | "stopped" | "failed" | "lost";
  error: string | null;
  position_ms: number;
}

export function streamEndedFromWire(wire: WireStreamEnded): StreamEnded {
  return {
    channel: wire.channel,
    path: wire.path,
    title: wire.title,
    reason: wire.reason,
    error: wire.error,
    positionMs: wire.position_ms,
  };
}

/** Someone joined a community of the bot. `member.name` is their profile name, or the first 8
 * hex digits of their id when no profile arrived within 30 s. */
export interface MemberJoined {
  /** The community, with the text channels the bot can view. */
  community: Community;
  member: Sender;
}

export interface WireMemberJoined {
  community: Community;
  member: { id: string; name: string; bot_id: boolean };
}

export function memberJoinedFromWire(wire: WireMemberJoined): MemberJoined {
  const m = wire.member;
  return { community: wire.community, member: { id: m.id, name: m.name, botId: m.bot_id } };
}

export class SpezlError extends Error {
  readonly code: number | undefined;

  constructor(message: string, code?: number) {
    super(message);
    this.name = "SpezlError";
    this.code = code;
  }
}

/** Sends `text` into `channel`; the part of `Bot` that `Message.reply` needs. */
export type SendFn = (
  channel: Channel,
  text: string,
  options?: { replyTo?: number },
) => Promise<number>;

/** A chat message in a text channel the bot can read. */
export class Message {
  readonly community: CommunityRef;
  readonly channel: Channel;
  readonly seq: number;
  /** The sender's own clock, unchecked: never use it to decide what a member may do. */
  readonly tsMs: number;
  readonly sender: Sender;
  readonly text: string;
  readonly replyTo: number | null;
  readonly mentionsMe: boolean;
  readonly #send: SendFn;

  constructor(
    fields: {
      community: CommunityRef;
      channel: Channel;
      seq: number;
      tsMs: number;
      sender: Sender;
      text: string;
      replyTo: number | null;
      mentionsMe: boolean;
    },
    send: SendFn,
  ) {
    this.community = fields.community;
    this.channel = fields.channel;
    this.seq = fields.seq;
    this.tsMs = fields.tsMs;
    this.sender = fields.sender;
    this.text = fields.text;
    this.replyTo = fields.replyTo;
    this.mentionsMe = fields.mentionsMe;
    this.#send = send;
  }

  /** Answers in the same channel, as a reply to this message. Returns the new message's seq. */
  reply(text: string): Promise<number> {
    return this.#send(this.channel, text, { replyTo: this.seq });
  }
}

/** The `message` notification as it comes over the wire. */
export interface WireMessage {
  community: CommunityRef;
  channel: Channel;
  seq: number;
  ts_ms: number;
  sender: { id: string; name: string; bot_id: boolean };
  text: string;
  reply_to: number | null;
  mentions_me: boolean;
}

export function messageFromWire(wire: WireMessage, send: SendFn): Message {
  return new Message(
    {
      community: wire.community,
      channel: wire.channel,
      seq: wire.seq,
      tsMs: wire.ts_ms,
      sender: { id: wire.sender.id, name: wire.sender.name, botId: wire.sender.bot_id },
      text: wire.text,
      replyTo: wire.reply_to,
      mentionsMe: wire.mentions_me,
    },
    send,
  );
}

// -- bot interfaces -----------------------------------------------------------

/** A field of a command's or card form's form. `required` defaults to true; a toggle is always
 * sent. */
export type Field =
  | {
      type: "text";
      id: string;
      label: string;
      placeholder?: string;
      /** Default 300. */
      maxChars?: number;
      required?: boolean;
    }
  | {
      type: "textList";
      id: string;
      label: string;
      placeholder?: string;
      /** Default 1. */
      min?: number;
      /** Default 10. */
      max?: number;
      /** Characters per line; default 100. */
      maxChars?: number;
      required?: boolean;
    }
  | { type: "toggle"; id: string; label: string; default?: boolean }
  | {
      type: "choice";
      id: string;
      label: string;
      options: { id: string; label: string }[];
      default?: string;
      required?: boolean;
    }
  | { type: "dateTime"; id: string; label: string; required?: boolean }
  | {
      /** The member's operating system and app version, which their app fills in when the
       * form opens; they may edit or clear it. The value is a string of at most 300
       * characters, written for people: its format is not fixed. */
      type: "clientInfo";
      id: string;
      label: string;
      required?: boolean;
    }
  | {
      /** One of `options`; with `on` (an earlier choice or select field), an option with a
       * non-empty `when` is offered only while `on` holds one of those ids. `tiles` shows a
       * grid of tiles instead of a dropdown. */
      type: "select";
      id: string;
      label: string;
      options: { id: string; label: string; when?: string[] }[];
      on?: string;
      tiles?: boolean;
      default?: string;
      required?: boolean;
    };

/** A slash command: `/name`, with the form `fields`. */
export interface CommandSpec {
  name: string;
  description: string;
  fields?: Field[];
}

/** How a button looks. "disabled" is shown but not pressable: neither the press nor a form
 * behind it reaches the bot. "selected" marks the current choice and stays pressable. */
export type ButtonStyle =
  | "primary"
  | "secondary"
  | "danger"
  | "success"
  | "warning"
  | "disabled"
  | "selected";

export interface Button {
  id: string;
  label: string;
  /** Default "secondary". */
  style?: ButtonStyle;
}

/** A button of a hinted buttons row; `hint` (at most 200 characters, no control characters)
 * shows while the pointer is over it. */
export interface HintedButton extends Button {
  hint?: string;
}

/** An option of a tally block: a hinted button and `members`, the user ids of the members who
 * chose it (at most 100, each in at most one option of the row). */
export interface TallyOption extends HintedButton {
  members?: string[];
}

/** A button of a links row that opens `url`, an http or https address, in the browser; a press
 * sends nothing to the bot. */
export interface LinkButton {
  label: string;
  url: string;
  /** Default "secondary". */
  style?: ButtonStyle;
}

/** A picture `Bot.uploadImage` stored on the server, for an image block. It belongs to one
 * card: deleting that card, or replacing it with one that no longer shows the picture, deletes
 * it on the server, so another card uploads its own copy. `key` opens it: keep it out of logs. */
export interface CardImage {
  blob: string;
  key: string;
  nonce: string;
  mime: string;
  width: number;
  height: number;
}

/** A poll every member's client counts itself. */
export interface Poll {
  type: "poll";
  question: string;
  options: string[];
  multiple?: boolean;
  hiddenResults?: boolean;
  /** Default true. */
  showVoters?: boolean;
  /** When voting ends, Unix milliseconds. */
  closesMs?: number | null;
  /** The user id who may end the poll besides the bot. */
  creator?: string | null;
}

/** A row of a list block: a bold `title`, a muted `detail` line and buttons on the right. */
export interface ListItem {
  title: string;
  detail?: string;
  buttons?: Button[];
}

/** A form a form block's button opens as a dialog; what the member fills in arrives as a
 * `Submit`. `submit` labels its send button, default "Submit". */
export interface Form {
  title: string;
  text?: string;
  fields: Field[];
  submit?: string;
}

export type Block =
  | { type: "buttons"; buttons: Button[] }
  | Poll
  | { type: "list"; items: ListItem[] }
  | { type: "form"; button: Button; form: Form }
  /** 2–3 markdown columns side by side, each at most 1000 characters, one not blank. */
  | { type: "columns"; columns: string[] }
  /** A row of 1–5 buttons with hints. */
  | { type: "hintedButtons"; buttons: HintedButton[] }
  /** A picture at the card's width; `alt` shows while it loads. At most two per card. */
  | { type: "image"; image: CardImage; alt?: string }
  /** A row of 1–5 link buttons. */
  | { type: "links"; links: LinkButton[] }
  /** A row of 2–5 options in equal widths; members see the counts and their own option marked. */
  | { type: "tally"; options: TallyOption[] };

/** What a bot posts: markdown `body` above `blocks` (buttons, hinted buttons, lists, form
 * buttons, columns, links, tallies, at most two images and at most one poll). */
export interface Card {
  body?: string;
  blocks?: Block[];
}

/**
 * A field value: a string (text, choice, select, client info), strings (text list), a bool
 * (toggle) or a number (date and time, Unix milliseconds).
 */
export type FieldValue = string | string[] | boolean | number;

function fieldToWire(f: Field): unknown {
  switch (f.type) {
    case "text":
      return {
        type: "text",
        id: f.id,
        label: f.label,
        required: f.required ?? true,
        placeholder: f.placeholder ?? "",
        max_chars: f.maxChars ?? 300,
      };
    case "textList":
      return {
        type: "text_list",
        id: f.id,
        label: f.label,
        required: f.required ?? true,
        placeholder: f.placeholder ?? "",
        min: f.min ?? 1,
        max: f.max ?? 10,
        max_chars: f.maxChars ?? 100,
      };
    case "toggle":
      return { type: "toggle", id: f.id, label: f.label, default: f.default ?? false };
    case "choice":
      return {
        type: "choice",
        id: f.id,
        label: f.label,
        required: f.required ?? true,
        options: f.options.map((o) => ({ id: o.id, label: o.label })),
        default: f.default ?? null,
      };
    case "dateTime":
      return { type: "date_time", id: f.id, label: f.label, required: f.required ?? true };
    case "clientInfo":
      return { type: "client_info", id: f.id, label: f.label, required: f.required ?? true };
    case "select":
      return {
        type: "select",
        id: f.id,
        label: f.label,
        required: f.required ?? true,
        options: f.options.map((o) => ({ id: o.id, label: o.label, when: o.when ?? [] })),
        default: f.default ?? null,
        on: f.on ?? null,
        tiles: f.tiles ?? false,
      };
  }
}

function buttonToWire(b: Button): Record<string, unknown> {
  return { id: b.id, label: b.label, style: b.style ?? "secondary" };
}

export function commandToWire(spec: CommandSpec): unknown {
  return {
    name: spec.name,
    description: spec.description,
    fields: (spec.fields ?? []).map(fieldToWire),
  };
}

export function cardToWire(card: Card): unknown {
  return {
    body: card.body ?? "",
    blocks: (card.blocks ?? []).map((b) => {
      switch (b.type) {
        case "buttons":
          return { type: "buttons", buttons: b.buttons.map(buttonToWire) };
        case "poll":
          return {
            type: "poll",
            question: b.question,
            options: b.options,
            multiple: b.multiple ?? false,
            hidden_results: b.hiddenResults ?? false,
            show_voters: b.showVoters ?? true,
            closes_ms: b.closesMs ?? null,
            creator: b.creator ?? null,
          };
        case "list":
          return {
            type: "list",
            items: b.items.map((i) => ({
              title: i.title,
              detail: i.detail ?? "",
              buttons: (i.buttons ?? []).map(buttonToWire),
            })),
          };
        case "form":
          return {
            type: "form",
            button: buttonToWire(b.button),
            form: {
              title: b.form.title,
              text: b.form.text ?? "",
              fields: b.form.fields.map(fieldToWire),
              submit: b.form.submit ?? "Submit",
            },
          };
        case "columns":
          return { type: "columns", columns: b.columns };
        case "hintedButtons":
          return {
            type: "hinted_buttons",
            buttons: b.buttons.map((h) => ({ ...buttonToWire(h), hint: h.hint ?? "" })),
          };
        case "image":
          return {
            type: "image",
            blob: b.image.blob,
            key: b.image.key,
            nonce: b.image.nonce,
            mime: b.image.mime,
            width: b.image.width,
            height: b.image.height,
            alt: b.alt ?? "",
          };
        case "links":
          return {
            type: "links",
            links: b.links.map((l) => ({
              label: l.label,
              url: l.url,
              style: l.style ?? "secondary",
            })),
          };
        case "tally":
          return {
            type: "tally",
            options: b.options.map((o) => ({
              ...buttonToWire(o),
              hint: o.hint ?? "",
              members: o.members ?? [],
            })),
          };
      }
    }),
  };
}

/** Posts `card` into `channel` as the answer to `answers`, seen only by `to` when set; the part
 * of `Bot` `respond` and a private `reply` need. */
export type PostCardFn = (
  channel: Channel,
  card: Card,
  options?: { answers?: number; to?: string },
) => Promise<number>;

/** Scrolls the chat of the member who sent `action` to the bot's card `target`; the part of
 * `Bot` that `Press.reveal` and `Submit.reveal` need. */
export type RevealFn = (channel: Channel, action: number, target: number) => Promise<void>;

interface WireContext {
  community: CommunityRef;
  channel: Channel;
  seq: number;
  ts_ms: number;
  sender: { id: string; name: string; bot_id: boolean };
}

export interface WireInvocation extends WireContext {
  command: string;
  values: Record<string, FieldValue>;
}

export interface WirePress extends WireContext {
  card: number;
  button: string;
}

export interface WireSubmit extends WireContext {
  card: number;
  button: string;
  values: Record<string, FieldValue>;
}

/** A member ran one of the bot's commands. Every toggle of the form is in `values`. */
export class Invocation {
  readonly community: CommunityRef;
  readonly channel: Channel;
  readonly seq: number;
  /** The sender's own clock, unchecked: never use it to decide what a member may do. */
  readonly tsMs: number;
  readonly sender: Sender;
  readonly command: string;
  readonly values: Record<string, FieldValue>;
  readonly #postCard: PostCardFn;

  constructor(wire: WireInvocation, postCard: PostCardFn) {
    this.community = wire.community;
    this.channel = wire.channel;
    this.seq = wire.seq;
    this.tsMs = wire.ts_ms;
    this.sender = { id: wire.sender.id, name: wire.sender.name, botId: wire.sender.bot_id };
    this.command = wire.command;
    this.values = wire.values;
    this.#postCard = postCard;
  }

  /** Answers with `card` in the invocation's channel. `private`: only the invoking member sees
   * it. Returns the card's seq. */
  respond(card: Card, options: { private?: boolean } = {}): Promise<number> {
    return this.#postCard(this.channel, card, {
      answers: this.seq,
      ...(options.private ? { to: this.sender.id } : {}),
    });
  }
}

/** A member pressed button `button` on the bot's card `card`. */
export class Press {
  readonly community: CommunityRef;
  readonly channel: Channel;
  readonly seq: number;
  /** The sender's own clock, unchecked: never use it to decide what a member may do. */
  readonly tsMs: number;
  readonly sender: Sender;
  readonly card: number;
  readonly button: string;
  readonly #send: SendFn;
  readonly #postCard: PostCardFn;
  readonly #reveal: RevealFn;

  constructor(wire: WirePress, send: SendFn, postCard: PostCardFn, reveal: RevealFn) {
    this.community = wire.community;
    this.channel = wire.channel;
    this.seq = wire.seq;
    this.tsMs = wire.ts_ms;
    this.sender = { id: wire.sender.id, name: wire.sender.name, botId: wire.sender.bot_id };
    this.card = wire.card;
    this.button = wire.button;
    this.#send = send;
    this.#postCard = postCard;
    this.#reveal = reveal;
  }

  /** Answers in the card's channel, as a reply to the card. `private`: only the presser sees
   * it, as a card. Returns the new message's seq. */
  reply(text: string, options: { private?: boolean } = {}): Promise<number> {
    if (options.private) {
      return this.#postCard(this.channel, { body: text, blocks: [] }, { to: this.sender.id });
    }
    return this.#send(this.channel, text, { replyTo: this.card });
  }

  /** Scrolls the presser's chat to the bot's card `target` in this channel that they see: one
   * just posted for them or one just replaced (see `Bot.reveal`). */
  reveal(target: number): Promise<void> {
    return this.#reveal(this.channel, this.seq, target);
  }
}

/** A member filled in the form behind button `button` of the bot's card `card`. Every toggle of
 * the form is in `values`. */
export class Submit {
  readonly community: CommunityRef;
  readonly channel: Channel;
  readonly seq: number;
  /** The sender's own clock, unchecked: never use it to decide what a member may do. */
  readonly tsMs: number;
  readonly sender: Sender;
  readonly card: number;
  readonly button: string;
  readonly values: Record<string, FieldValue>;
  readonly #send: SendFn;
  readonly #postCard: PostCardFn;
  readonly #reveal: RevealFn;

  constructor(wire: WireSubmit, send: SendFn, postCard: PostCardFn, reveal: RevealFn) {
    this.community = wire.community;
    this.channel = wire.channel;
    this.seq = wire.seq;
    this.tsMs = wire.ts_ms;
    this.sender = { id: wire.sender.id, name: wire.sender.name, botId: wire.sender.bot_id };
    this.card = wire.card;
    this.button = wire.button;
    this.values = wire.values;
    this.#send = send;
    this.#postCard = postCard;
    this.#reveal = reveal;
  }

  /** Answers in the card's channel, as a reply to the card. `private`: only the member who sent
   * the form sees it, as a card. Returns the new message's seq. */
  reply(text: string, options: { private?: boolean } = {}): Promise<number> {
    if (options.private) {
      return this.#postCard(this.channel, { body: text, blocks: [] }, { to: this.sender.id });
    }
    return this.#send(this.channel, text, { replyTo: this.card });
  }

  /** Scrolls the chat of the member who sent the form to the bot's card `target` in this
   * channel that they see: one just posted for them or one just replaced (see `Bot.reveal`). */
  reveal(target: number): Promise<void> {
    return this.#reveal(this.channel, this.seq, target);
  }
}
