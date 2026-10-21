"use client";

import { ReactNode, useEffect, useRef } from "react";
import { createGlassMesh } from "./liquidGlassMesh";

type Material = "rail" | "help" | "procurement";

/** Only the decorative shell bends. Links, text and hit targets never move. */
export function LiquidSurface({ as: Tag = "section", variant, className, children, "aria-label": label }: {
  as?: "section" | "header" | "aside" | "div";
  variant: Material;
  className: string;
  children: ReactNode;
  "aria-label"?: string;
}) {
  const host = useRef<HTMLElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = host.current, plate = canvas.current;
    if (!element || !plate) return;
    const motion = matchMedia("(prefers-reduced-motion: no-preference) and (hover: hover) and (pointer: fine)");
    const dense = matchMedia("(prefers-reduced-transparency: reduce)");
    const forced = matchMedia("(forced-colors: active)");
    let dispose: (() => void) | undefined;
    const resetTilt = () => { element.style.removeProperty("--glass-tilt-x"); element.style.removeProperty("--glass-tilt-y"); };
    const tilt = (event: PointerEvent) => {
      if (!element.dataset.glassFallback || !motion.matches || dense.matches || forced.matches || event.pointerType !== "mouse") return;
      const box = element.getBoundingClientRect();
      if (!box.width || !box.height) return;
      const x = Math.max(-1, Math.min(1, (event.clientX - box.left) / box.width * 2 - 1));
      const y = Math.max(-1, Math.min(1, (event.clientY - box.top) / box.height * 2 - 1));
      element.style.setProperty("--glass-tilt-x", `${-y * 1.2}deg`);
      element.style.setProperty("--glass-tilt-y", `${x * 1.2}deg`);
    };
    const refresh = () => {
      dispose?.(); dispose = undefined;
      resetTilt(); delete element.dataset.glassFallback;
      if (motion.matches && !dense.matches && !forced.matches) dispose = createGlassMesh(element, plate, variant);
    };
    refresh();
    element.addEventListener("pointermove", tilt); element.addEventListener("pointerleave", resetTilt); element.addEventListener("pointercancel", resetTilt); window.addEventListener("blur", resetTilt);
    plate.addEventListener("webglcontextrestored", refresh);
    for (const query of [motion, dense, forced]) query.addEventListener("change", refresh);
    return () => { dispose?.(); resetTilt(); element.removeEventListener("pointermove", tilt); element.removeEventListener("pointerleave", resetTilt); element.removeEventListener("pointercancel", resetTilt); window.removeEventListener("blur", resetTilt); plate.removeEventListener("webglcontextrestored", refresh); for (const query of [motion, dense, forced]) query.removeEventListener("change", refresh); };
  }, [variant]);
  return <Tag ref={(node: HTMLElement | null) => { host.current = node; }} className={`${className} liquid-surface liquid-surface--${variant}`} aria-label={label}>
    <span className="liquid-surface__material" aria-hidden="true" />
    <canvas className="liquid-surface__mesh" ref={canvas} aria-hidden="true" />
    {children}
  </Tag>;
}
