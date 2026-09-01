import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResizeDivider } from "./ResizeDivider";

describe("ResizeDivider", () => {
  it("updates the value from pointer movement and clamps to bounds", () => {
    const onChange = vi.fn();
    render(<ResizeDivider side="left" value={240} min={220} max={420} onChange={onChange} />);
    const divider = screen.getByRole("separator");
    Object.defineProperty(divider, "setPointerCapture", { value: vi.fn() });
    Object.defineProperty(divider, "hasPointerCapture", { value: vi.fn(() => true) });
    Object.defineProperty(divider, "releasePointerCapture", { value: vi.fn() });

    expect(divider).toHaveAttribute("aria-orientation", "horizontal");
    expect(divider).toHaveAttribute("aria-valuenow", "240");
    const dispatchPointer = (type: "pointerdown" | "pointermove" | "pointerup", clientX: number) => {
      const event = type === "pointerdown"
        ? createEvent.pointerDown(divider)
        : type === "pointermove"
          ? createEvent.pointerMove(divider)
          : createEvent.pointerUp(divider);
      Object.defineProperties(event, { clientX: { value: clientX }, pointerId: { value: 1 } });
      fireEvent(divider, event);
    };
    dispatchPointer("pointerdown", 100);
    dispatchPointer("pointermove", 180);
    expect(onChange).toHaveBeenLastCalledWith(320);
    dispatchPointer("pointermove", -1000);
    expect(onChange).toHaveBeenLastCalledWith(220);
    dispatchPointer("pointermove", 1000);
    expect(onChange).toHaveBeenLastCalledWith(420);
    dispatchPointer("pointerup", 1000);
  });
});
