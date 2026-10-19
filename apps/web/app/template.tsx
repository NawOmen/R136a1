"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { animate, useReducedMotion } from "motion/react";

export default function PageTemplate({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (!root.current) return;
    if (reduced || window.matchMedia("(prefers-reduced-motion: reduce)").matches) { root.current.style.opacity = "1"; return; }
    // Opacity only: transforms would change the containing block of sticky scenes.
    const transition = animate(root.current, { opacity: [.72, 1] }, { duration: .32, ease: [.16, 1, .3, 1] });
    return () => transition.stop();
  }, [reduced]);
  return <div ref={root} className="page-transition">{children}</div>;
}
