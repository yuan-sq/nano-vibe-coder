import { describe, expect, it } from "vitest";
import { GuiApi } from "./api";

describe("GuiApi", () => {
  it("calls browser fetch with the global receiver", async () => {
    let receiver: unknown;
    function browserFetch(
      this: unknown,
      _input: RequestInfo | URL,
      _init?: RequestInit
    ): Promise<Response> {
      receiver = this;
      if (this !== globalThis) throw new TypeError("Illegal invocation");
      return Promise.resolve(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        })
      );
    }

    const api = new GuiApi(
      "http://127.0.0.1:8000",
      browserFetch as typeof fetch
    );

    await expect(api.projects()).resolves.toEqual([]);
    expect(receiver).toBe(globalThis);
  });

  it("encodes trace tail mode in the query", async () => {
    let requestedUrl = "";
    const api = new GuiApi("http://127.0.0.1:8000", async (input) => {
      requestedUrl = String(input);
      return new Response(JSON.stringify({ items: [], next_offset: 0, has_more: false, total: 0 }), { status: 200 });
    });

    await api.trace("session-1", { event: "tool_end", tail: true, limit: 3 });

    const url = new URL(requestedUrl);
    expect(url.pathname).toBe("/api/v1/sessions/session-1/trace");
    expect(url.searchParams.get("event")).toBe("tool_end");
    expect(url.searchParams.get("tail")).toBe("true");
    expect(url.searchParams.get("limit")).toBe("3");
  });
});
