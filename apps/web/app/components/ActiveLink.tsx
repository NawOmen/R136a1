"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export function ActiveLink({ href, paths = [href], children, prefetch }: { href: string; paths?: string[]; children: ReactNode; prefetch?: boolean }) {
  const pathname = usePathname();
  const active = paths.some((path) => pathname === path || pathname.startsWith(`${path}/`));
  return <Link href={href} prefetch={prefetch} className={active ? "active" : undefined} aria-current={active ? "page" : undefined}>{children}</Link>;
}
