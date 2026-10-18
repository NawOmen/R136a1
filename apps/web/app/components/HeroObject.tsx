"use client";

import { useEffect, useRef } from "react";

export type HeroObjectKind = "procurement" | "help";

/** Matching model poster for first paint/static mode; live geometry takes over in the same pose. */
export function HeroObject({ kind }: { kind: HeroObjectKind }) {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = host.current, surface = canvas.current;
    if (!element || !surface) return;
    const motion = matchMedia("(prefers-reduced-motion: no-preference) and (hover: hover) and (pointer: fine)");
    const dense = matchMedia("(prefers-reduced-transparency: reduce)");
    const forced = matchMedia("(forced-colors: active)");
    let generation = 0, visible = false, lost = false;
    let dispose: (() => void) | undefined;
    const refresh = () => {
      const ticket = ++generation;
      dispose?.(); dispose = undefined;
      delete surface.dataset.ready;
      if (!visible || document.hidden || lost || !motion.matches || dense.matches || forced.matches) return;
      // Three.js and model code never enter the initial/main catalogue bundle.
      void import("./heroObjectScene").then(({ createHeroObjectScene }) => {
        if (ticket !== generation) return;
        try { dispose = createHeroObjectScene(element, surface, kind); }
        catch (error) { delete surface.dataset.ready; console.warn("Не удалось отрисовать 3D-иллюстрацию", error); }
      }).catch(() => { /* Network/chunk failure keeps the matching model poster. */ });
    };
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting === visible) return;
      visible = entry.isIntersecting; refresh();
    });
    observer.observe(element);
    const contextLost = (event: Event) => { event.preventDefault(); lost = true; refresh(); };
    const contextRestored = () => { lost = false; refresh(); };
    surface.addEventListener("webglcontextlost", contextLost);
    surface.addEventListener("webglcontextrestored", contextRestored);
    document.addEventListener("visibilitychange", refresh);
    for (const query of [motion, dense, forced]) query.addEventListener("change", refresh);
    return () => {
      generation++; observer.disconnect(); dispose?.();
      surface.removeEventListener("webglcontextlost", contextLost);
      surface.removeEventListener("webglcontextrestored", contextRestored);
      document.removeEventListener("visibilitychange", refresh);
      for (const query of [motion, dense, forced]) query.removeEventListener("change", refresh);
    };
  }, [kind]);

  return <div className="guidance-art" aria-hidden="true">
    <div className={`hero-object hero-object--${kind}`} ref={host}>
      <canvas className="hero-object__canvas" ref={canvas} />
      <div className="hero-object__poster" />
    </div>
  </div>;
}
