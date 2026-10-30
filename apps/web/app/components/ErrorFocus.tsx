"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

/** Bring errors from a user's action into view, including an unchanged repeat. */
export default function ErrorFocus() {
  const pathname = usePathname();
  useEffect(() => {
    const main = document.getElementById("main-content");
    if (!main) return;
    let armed = false;
    let frame = 0;
    let alive = true;
    const reveal = () => {
      if (!alive || !armed) return;
      const target = Array.from(main.querySelectorAll<HTMLElement>('.alert-error,[role="alert"]'))
        .find(node => node.textContent?.trim() && node.getClientRects().length && !node.closest('[hidden],[aria-hidden="true"]'));
      if (!target) return;
      armed = false;
      target.classList.add("alert", "alert-error", "error-focus-target");
      target.setAttribute("role", "alert");
      target.tabIndex = -1;
      const header = document.querySelector(".site-header")?.getBoundingClientRect();
      target.style.scrollMarginTop = `${Math.max(0, header?.bottom ?? 0) + 20}px`;
      target.focus({ preventScroll: true });
      target.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => { frame = requestAnimationFrame(reveal); });
    };
    const action = (event: Event) => {
      if (!(event.target instanceof Element)) return;
      const button = event.target.closest("button,input[type=submit]");
      if (event.type === "click" && (!button || button.matches(":disabled") || button.hasAttribute("aria-expanded"))) return;
      armed = true;
      schedule();
    };
    const observer = new MutationObserver(schedule);
    observer.observe(main, { childList: true, subtree: true, characterData: true });
    main.addEventListener("click", action, true);
    main.addEventListener("submit", action, true);
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      main.removeEventListener("click", action, true);
      main.removeEventListener("submit", action, true);
    };
  }, [pathname]);
  return null;
}
