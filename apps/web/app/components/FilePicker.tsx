"use client";

import type { InputHTMLAttributes } from "react";

/** Keep the native, keyboard-accessible input while localizing its visible control. */
export function FilePicker({ status, multiple, disabled, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { status?: string }) {
  return <div className="file-picker" data-disabled={Boolean(disabled)}>
    <label className="file-picker__control">
      <span>{multiple ? "Выбрать файлы" : "Выбрать файл"}</span>
      <input {...props} type="file" multiple={multiple} disabled={disabled} />
    </label>
    <span className="hint" aria-live="polite">{status ?? (multiple ? "Файлы не выбраны" : "Файл не выбран")}</span>
  </div>;
}
