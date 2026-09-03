import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import Link from "next/link";
import { AccountDrawer } from "./components/AccountDrawer";
import { SiteNavigation } from "./components/SiteNavigation";

export const metadata: Metadata = {
  title: "ПоРукам",
  description: "B2B-маркетплейс коалиций покупателей и производителей",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <body>
        <header className="site-header">
          <div className="container site-header__inner">
            <Link className="site-header__logo" href="/">ПоРукам</Link>
            <SiteNavigation />
            <AccountDrawer />
          </div>
        </header>
        <main className="container main">{children}</main>
        <footer className="site-footer">
          <div className="container footer-grid">
            <div><strong>ПоРукам</strong><br />B2B-маркетплейс российских компаний</div>
            <div><Link href="/info/about">О компании</Link><Link href="/info/news">Новости</Link><Link href="/info/contacts">Контакты</Link></div>
            <div><Link href="/info/guide">Инструкция</Link><Link href="/info/regulations">Регламенты</Link><Link href="/support">Поддержка</Link></div>
            <div><Link href="/info/legal">Пользовательское соглашение</Link><Link href="/info/privacy">Политика конфиденциальности</Link><span>© 2026 · Демопрототип</span></div>
          </div>
        </footer>
      </body>
    </html>
  );
}
