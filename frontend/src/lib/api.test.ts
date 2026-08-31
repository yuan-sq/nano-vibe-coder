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
});
