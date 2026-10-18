"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

export function PageSurface({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const market = pathname === "/" || pathname === "/catalog";
  const guidance = pathname === "/knowledge" || pathname === "/ai-procurement";
  return <div className={guidance ? "page-surface guidance-surface" : market ? "page-surface market-surface" : "page-surface work-surface"}>{children}</div>;
}
