import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

interface ResizeDividerProps {
  side: "left" | "right";
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function ResizeDivider({ side, value, min, max, onChange }: ResizeDividerProps) {
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ pointerId: number; startX: number; startValue: number } | null>(null);

  const finish = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current || event.pointerId !== dragRef.current.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    dragRef.current = null;
    setDragging(false);
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startValue: value };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    const delta = side === "left" ? event.clientX - drag.startX : drag.startX - event.clientX;
    onChange(clamp(drag.startValue + delta, min, max));
  };

  return <div
    className={`resize-divider ${dragging ? "dragging" : ""}`}
    data-side={side}
    role="separator"
    aria-orientation="horizontal"
    aria-valuemin={min}
    aria-valuemax={max}
    aria-valuenow={value}
    onPointerDown={handlePointerDown}
    onPointerMove={handlePointerMove}
    onPointerUp={finish}
    onPointerCancel={finish}
  />;
}
