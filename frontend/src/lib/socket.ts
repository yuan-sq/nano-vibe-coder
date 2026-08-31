import type { UIEvent } from "./protocol";

export interface SocketLike {
  readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  send(data: string): void;
  close(): void;
}

export type SocketCommand = Record<string, unknown>;
export type SocketFactory = (url: string) => SocketLike;

interface GuiSocketOptions {
  url: string;
  getLastSeq: () => number;
  onEvent: (event: UIEvent) => void;
  onResync: (latestSeq: number) => void;
  onCommandResult?: (result: Record<string, unknown>) => void;
  onStatus: (connected: boolean) => void;
  createWebSocket?: SocketFactory;
  retryBaseMs?: number;
  retryMaxMs?: number;
}

const OPEN = 1;

export class GuiSocketSession {
  private socket: SocketLike | null = null;
  private retryTimer: number | null = null;
  private stopped = true;
  private attempt = 0;
  private queuedCommands: SocketCommand[] = [];
  private readonly createWebSocket: SocketFactory;
  private readonly retryBaseMs: number;
  private readonly retryMaxMs: number;

  constructor(private readonly options: GuiSocketOptions) {
    this.createWebSocket = options.createWebSocket ?? ((url) => new WebSocket(url) as unknown as SocketLike);
    this.retryBaseMs = options.retryBaseMs ?? 250;
    this.retryMaxMs = options.retryMaxMs ?? 5_000;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.attempt = 0;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer !== null) {
      globalThis.clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    this.options.onStatus(false);
  }

  send(command: SocketCommand): void {
    if (this.socket?.readyState === OPEN) {
      try {
        this.socket.send(JSON.stringify(command));
        return;
      } catch {
        this.queuedCommands.push(command);
        this.socket.close();
        return;
      }
    }
    this.queuedCommands.push(command);
  }

  private connect(): void {
    if (this.stopped || this.socket !== null) return;
    const socket = this.createWebSocket(this.options.url);
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket || this.stopped) return;
      this.attempt = 0;
      this.options.onStatus(true);
      this.send({ type: "subscribe", last_seq: this.options.getLastSeq() });
      const queued = this.queuedCommands.splice(0);
      for (const command of queued) this.send(command);
    };
    socket.onmessage = (message) => {
      if (this.socket !== socket || this.stopped) return;
      let value: unknown;
      try {
        value = JSON.parse(message.data);
      } catch {
        return;
      }
      if (!value || typeof value !== "object") return;
      const data = value as { type?: unknown; event?: unknown; latest_seq?: unknown };
      if (data.type === "event" && data.event && typeof data.event === "object") {
        this.options.onEvent(data.event as UIEvent);
      } else if (data.type === "resync_required") {
        const latestSeq = typeof data.latest_seq === "number" ? data.latest_seq : 0;
        this.options.onResync(latestSeq);
      } else if (data.type === "interaction_result" || data.type === "error") {
        this.options.onCommandResult?.(value as Record<string, unknown>);
      }
    };
    socket.onerror = () => {
      // The close callback owns reconnect scheduling; browsers usually emit both events.
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.options.onStatus(false);
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.retryTimer !== null) return;
    const delay = Math.min(this.retryBaseMs * 2 ** this.attempt, this.retryMaxMs);
    this.attempt += 1;
    this.retryTimer = globalThis.setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }
}
