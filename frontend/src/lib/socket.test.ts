import { describe, expect, it, vi } from "vitest";
import type { UIEvent } from "./protocol";
import { GuiSocketSession, type SocketLike } from "./socket";

class FakeSocket implements SocketLike {
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  receive(value: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
}

describe("GuiSocketSession", () => {
  it("queues commands, reconnects, and reports resync sequence", () => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    const statuses: boolean[] = [];
    const resyncs: number[] = [];
    const results: Array<Record<string, unknown>> = [];
    const events: UIEvent[] = [];
    const client = new GuiSocketSession({
      url: "ws://localhost/session",
      createWebSocket: () => new FakeSocket(),
      getLastSeq: () => 4,
      onEvent: (event) => events.push(event),
      onResync: (latestSeq) => resyncs.push(latestSeq),
      onCommandResult: (result) => results.push(result),
      onStatus: (connected) => statuses.push(connected),
      retryBaseMs: 10,
      retryMaxMs: 10
    });

    client.start();
    client.send({ type: "resolve_user_request", interaction_id: "q-1", decision: "北京" });
    expect(FakeSocket.instances).toHaveLength(1);
    expect(FakeSocket.instances[0].sent).toEqual([]);

    FakeSocket.instances[0].open();
    expect(JSON.parse(FakeSocket.instances[0].sent[0])).toEqual({ type: "subscribe", last_seq: 4 });
    expect(JSON.parse(FakeSocket.instances[0].sent[1])).toEqual({
      type: "resolve_user_request",
      interaction_id: "q-1",
      decision: "北京"
    });

    FakeSocket.instances[0].receive({ type: "resync_required", latest_seq: 9 });
    expect(resyncs).toEqual([9]);
    FakeSocket.instances[0].receive({ type: "interaction_result", ok: false });
    expect(results).toEqual([{ type: "interaction_result", ok: false }]);

    FakeSocket.instances[0].close();
    FakeSocket.instances[0].receive({ type: "event", event: { seq: 10 } });
    expect(events).toEqual([]);
    expect(statuses).toEqual([true, false]);
    vi.advanceTimersByTime(10);
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.instances[1].open();
    expect(JSON.parse(FakeSocket.instances[1].sent[0])).toEqual({ type: "subscribe", last_seq: 4 });

    client.stop();
    vi.useRealTimers();
  });
});
