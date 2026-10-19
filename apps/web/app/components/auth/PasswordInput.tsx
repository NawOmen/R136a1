"use client";

import { type InputHTMLAttributes, useState } from "react";
import styles from "./AuthFrame.module.css";

export function PasswordInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  return <div className={styles.password}><input {...props} type={visible ? "text" : "password"} />
    <button type="button" onClick={() => setVisible(!visible)} aria-label={visible ? "Скрыть пароль" : "Показать пароль"} aria-pressed={visible} aria-controls={props.id}>
      <svg width="21" height="21" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" stroke="currentColor" strokeWidth="1.6"/><circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6"/>{visible && <path d="m4 3 16 18" stroke="currentColor" strokeWidth="1.6"/>}</svg>
    </button>
  </div>;
}
