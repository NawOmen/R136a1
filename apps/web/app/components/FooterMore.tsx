"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

export function FooterMore() {
  const pathname = usePathname();
  const details = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (details.current) details.current.open = false; }, [pathname]);
  useEffect(() => {
    const close = (event: Event) => {
      if (details.current && (!details.current.contains(event.target as Node) || (event instanceof KeyboardEvent && event.key === "Escape"))) details.current.open = false;
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); };
  }, []);
  return <details ref={details} className="footer-more"><summary>Ещё</summary><nav onClick={event => { if ((event.target as HTMLElement).closest("a") && details.current) details.current.open = false; }}><Link href="/catalog">Каталог товаров</Link><Link href="/seller/requests">Потребности бизнеса</Link><Link href="/ai-procurement">Закупки с ИИ</Link><Link href="/knowledge">Помощь с закупкой</Link><Link href="/info/about">О платформе</Link><Link href="/info/regulations">Регламенты</Link><Link href="/info/privacy">Конфиденциальность</Link><Link href="/info/news">Новости</Link></nav></details>;
}
