import { describe, expect, it } from "vitest";
import { connectionConfig } from "./App";

describe("GUI connection configuration", () => {
  it("reads the persisted API URL after the startup hash is removed", () => {
    window.history.replaceState({}, "", "/?api=http%3A%2F%2F127.0.0.1%3A59591");

    expect(connectionConfig()).toEqual({
      apiUrl: "http://127.0.0.1:59591",
      token: null
    });
  });
});
