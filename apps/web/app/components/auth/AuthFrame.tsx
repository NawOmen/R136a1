"use client";

import { type ReactNode, useRef } from "react";
import { motion, useMotionValue, useReducedMotion, useSpring } from "motion/react";
import styles from "./AuthFrame.module.css";

export function AuthFrame({ children, registration = false }: { children: ReactNode; registration?: boolean }) {
  const reduced = useReducedMotion();
  const card = useRef<HTMLElement>(null);
  const x = useMotionValue(0), y = useMotionValue(0);
  const rotateX = useSpring(x, { stiffness: 120, damping: 26 });
  const rotateY = useSpring(y, { stiffness: 120, damping: 26 });
  return <div className={styles.stage}>
    <div className={styles.light} aria-hidden="true" />
    <motion.section ref={card} className={`${styles.card} ${registration ? styles.registration : ""}`} style={{ rotateX: reduced ? 0 : rotateX, rotateY: reduced ? 0 : rotateY }}
      onPointerMove={event => {
        if (event.currentTarget.contains(document.activeElement) || reduced || event.pointerType !== "mouse" || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
        const rect = event.currentTarget.getBoundingClientRect();
        x.set(-((event.clientY - rect.top) / rect.height - .5) * 3);
        y.set(((event.clientX - rect.left) / rect.width - .5) * 3);
      }} onPointerLeave={() => { x.set(0); y.set(0); }} onFocusCapture={() => { x.set(0); y.set(0); }}>
      <div className={styles.brand}><img src="/icon.png" width="29" height="29" alt="" /><span>ПоРукам</span></div>
      {children}
    </motion.section>
  </div>;
}

export function AuthSubmit({ submitting, text, pendingText }: { submitting: boolean; text: string; pendingText: string }) {
  return <button type="submit" className={styles.submit} disabled={submitting} aria-busy={submitting}>
    <span>{submitting ? pendingText : text}</span>
    <svg className={styles.door} data-opening={submitting} viewBox="0 0 76 48" width="76" height="48" fill="none" aria-hidden="true">
      <path d="M44 4h25v40H44z" fill="#677be0" stroke="#c4d7ff" strokeOpacity=".6" />
      <path className={styles.doorPanel} d="M44 4h25v40H44z" fill="#8ca8ff" stroke="#d9e4ff" strokeOpacity=".6" />
      <path d="M49 21v7" stroke="#f2f7ff" strokeWidth="2" strokeLinecap="round" />
      <g className={styles.person} stroke="#10294e" strokeWidth="2.2" strokeLinecap="round"><circle cx="22" cy="14" r="3" fill="#10294e" stroke="none"/><path d="M22 19v12m0-9-5 6m5-6 5 5m-5 4-4 10m4-10 4 10"/></g>
    </svg>
  </button>;
}
