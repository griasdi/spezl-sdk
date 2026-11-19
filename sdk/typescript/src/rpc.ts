import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import { SpezlError } from "./types.ts";

const NOT_FOUND = "spezl not found: put it on PATH or set SPEZL_BIN";
/** Milliseconds `close` gives serve to end, before it is killed. It covers serve's stream stop
 * (5 s + 5 s), goodbye and its 5 s flush. */
export const CLOSE_TIMEOUT_MS = 20_000;

interface Pending {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
}

type NotificationHandler = (method: string, params: unknown) => void;

/** A running `spezl serve` and its JSON-RPC lines. */
export class Connection {
  readonly #child: ChildProcess;
  readonly #pending = new Map<number, Pending>();
  #nextId = 1;
  #onNotification: NotificationHandler = () => {};
  #exitCode: number | null = null;
  #exitSignal: NodeJS.Signals | null = null;
  #exited = false;
  readonly done: Promise<void>;

  private constructor(child: ChildProcess) {
    this.#child = child;
    child.stdin!.on("error", () => {}); // EPIPE once serve is gone; the exit path reports it
    const lines = createInterface({ input: child.stdout! });
    lines.on("line", (line) => this.#onLine(line));
    this.done = new Promise<void>((resolve) => {
      // "close" fires after the stdio streams ended, so every line has been dispatched.
      child.once("close", (code, signal) => {
        this.#exited = true;
        this.#exitCode = code;
        this.#exitSignal = signal;
        const error = new SpezlError(this.exitMessage());
        for (const pending of this.#pending.values()) pending.reject(error);
        this.#pending.clear();
        resolve();
      });
    });
  }

  /** Starts `<binary> [--home <home>] serve`. */
  static async open(binary: string, home: string | undefined): Promise<Connection> {
    const args = [...(home ? ["--home", home] : []), "serve"];
    const child = spawn(binary, args, { stdio: ["pipe", "pipe", "inherit"] });
    await new Promise<void>((resolve, reject) => {
      child.once("spawn", resolve);
      child.once("error", (err: NodeJS.ErrnoException) => {
        reject(
          err.code === "ENOENT"
            ? new SpezlError(NOT_FOUND)
            : new SpezlError(`cannot start ${binary}: ${err.message}`),
        );
      });
    });
    child.on("error", () => {}); // later errors (kill, write) surface through close/exit
    return new Connection(child);
  }

  /** Exit code of serve once it ended; `null` while running or when killed by a signal. */
  get exitCode(): number | null {
    return this.#exitCode;
  }

  exitMessage(): string {
    return this.#exitSignal
      ? `spezl serve exited with signal ${this.#exitSignal}`
      : `spezl serve exited with code ${this.#exitCode}`;
  }

  onNotification(fn: NotificationHandler): void {
    this.#onNotification = fn;
  }

  request(method: string, params?: unknown): Promise<unknown> {
    if (this.#exited) return Promise.reject(new SpezlError(this.exitMessage()));
    const id = this.#nextId++;
    const line = JSON.stringify({
      jsonrpc: "2.0",
      id,
      method,
      ...(params === undefined ? {} : { params }),
    });
    return new Promise<unknown>((resolve, reject) => {
      this.#pending.set(id, { resolve, reject });
      this.#child.stdin!.write(line + "\n", (err) => {
        if (err && this.#pending.delete(id)) {
          reject(new SpezlError(`cannot write to spezl serve: ${err.message}`));
        }
      });
    });
  }

  #onLine(line: string): void {
    if (line.trim() === "") return;
    let msg: any;
    try {
      msg = JSON.parse(line);
    } catch {
      console.error(`spezl: ignoring malformed line from serve: ${line}`);
      return;
    }
    if (msg === null || typeof msg !== "object") return;
    if (typeof msg.method === "string" && msg.id === undefined) {
      try {
        this.#onNotification(msg.method, msg.params);
      } catch (err) {
        console.error(err);
      }
      return;
    }
    const pending = typeof msg.id === "number" ? this.#pending.get(msg.id) : undefined;
    if (!pending) return;
    this.#pending.delete(msg.id);
    if (msg.error) {
      pending.reject(new SpezlError(String(msg.error.message ?? "error"), msg.error.code));
    } else {
      pending.resolve(msg.result);
    }
  }

  /** Closes stdin so serve shuts down, waits up to `CLOSE_TIMEOUT_MS`, then kills it. */
  async close(): Promise<void> {
    if (this.#exited) return;
    this.#child.stdin!.end();
    let timer: NodeJS.Timeout | undefined;
    const timeout = new Promise<"timeout">((resolve) => {
      timer = setTimeout(() => resolve("timeout"), CLOSE_TIMEOUT_MS);
    });
    const result = await Promise.race([this.done.then(() => "done" as const), timeout]);
    clearTimeout(timer);
    if (result === "timeout") {
      // SIGKILL: a serve that did not end on EOF may not end on SIGTERM either.
      this.#child.kill("SIGKILL");
      await this.done;
    }
  }
}
