import { useEffect, useRef, useState } from "react";
import type { PermissionMode, RuntimeState } from "../lib/protocol";

interface PermissionModeSelectorProps {
  mode: PermissionMode;
  runtimeState: RuntimeState;
  busy?: boolean;
  onChange: (mode: PermissionMode) => void;
}

const options: Array<{ mode: PermissionMode; description: string }> = [
  { mode: "normal", description: "写文件、Shell 和网络工具按策略请求审批" },
  { mode: "full-access", description: "跳过应用层审批，但仍受 Agent 阶段、工具参数和路径校验约束" }
];

export function PermissionModeSelector({ mode, runtimeState, busy = false, onChange }: PermissionModeSelectorProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const canEdit = runtimeState === "IDLE" && !busy;
  const label = mode === "normal" ? "Normal" : "Full Access";

  useEffect(() => {
    if (!canEdit) setOpen(false);
  }, [canEdit]);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return <div className="permission-mode-selector" ref={rootRef}>
    <button
      type="button"
      className={`permission-mode-button ${mode === "full-access" ? "full-access" : "normal"}`}
      aria-label={`权限模式：${label}`}
      aria-haspopup="menu"
      aria-expanded={open}
      title={canEdit ? undefined : "仅可在 IDLE 状态切换"}
      disabled={!canEdit}
      onClick={() => setOpen((value) => !value)}
    >
      {busy ? "切换中…" : label}
      <span aria-hidden="true">⌄</span>
    </button>
    {open && <div className="permission-mode-menu" role="menu">
      {options.map((option) => {
        const optionLabel = option.mode === "normal" ? "Normal" : "Full Access";
        return <button
          type="button"
          role="menuitem"
          key={option.mode}
          className={option.mode === mode ? "selected" : undefined}
          onClick={() => {
            setOpen(false);
            if (option.mode !== mode) onChange(option.mode);
          }}
        >
          <strong>{optionLabel}</strong>
          <small>{option.description}</small>
        </button>;
      })}
    </div>}
  </div>;
}
