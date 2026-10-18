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
    const refresh = () => {
      dispose?.(); dispose = undefined;
      if (motion.matches && !dense.matches && !forced.matches) dispose = createGlassMesh(element, plate, variant);
    };
    refresh();
    plate.addEventListener("webglcontextrestored", refresh);
    for (const query of [motion, dense, forced]) query.addEventListener("change", refresh);
    return () => { dispose?.(); plate.removeEventListener("webglcontextrestored", refresh); for (const query of [motion, dense, forced]) query.removeEventListener("change", refresh); };
  }, [variant]);
  return <Tag ref={(node: HTMLElement | null) => { host.current = node; }} className={`${className} liquid-surface liquid-surface--${variant}`} aria-label={label}>
    <span className="liquid-surface__material" aria-hidden="true" />
    <canvas className="liquid-surface__mesh" ref={canvas} aria-hidden="true" />
    {children}
  </Tag>;
}
