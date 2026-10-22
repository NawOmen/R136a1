import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import "./design.css";
import localFont from "next/font/local";
import Link from "next/link";
import { AccountDrawer } from "./components/AccountDrawer";
import { RussianValidation } from "./components/RussianValidation";
import { SiteNavigation } from "./components/SiteNavigation";
import { LiquidAtmosphere } from "./components/LiquidAtmosphere";
import { PageSurface } from "./components/PageSurface";
import { Icon } from "./components/Icon";

const manrope = localFont({ src: "./fonts/Manrope-variable.ttf", display: "swap", variable: "--font-manrope", weight: "200 800" });

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export const metadata: Metadata = {
  title: "ПоРукам",
  description: "Маркетплейс для бизнеса коалиций покупателей и производителей",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: 'try{document.documentElement.dataset.theme=localStorage.getItem("porukam-theme")==="dark"?"dark":"light"}catch{}' }} /></head>
      <body className={manrope.variable}>
        <LiquidAtmosphere />
        <RussianValidation />
        <a className="skip-link" href="#main-content">К содержимому</a>
        <header className="site-header">
          <div className="container site-header__inner">
            <Link className="site-header__logo" href="/" aria-label="ПоРукам — на главную">
              <img src="/icon.png" alt="" width="36" height="36" />
              <span>ПоРукам</span>
            </Link>
            <SiteNavigation />
            <AccountDrawer />
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="container main"><PageSurface>{children}</PageSurface></main>
        <footer className="site-footer">
          <div className="container footer-grid">
            <Link className="site-header__logo" href="/"><img src="/icon.png" alt="" width="42" height="32" /><span>ПоРукам</span></Link>
            <nav className="footer-links" aria-label="Информация"><Link href="/info/contacts">Контакты</Link><Link href="/support">Поддержка</Link><Link href="/info/guide">Как начать</Link><Link href="/info/legal">Правила работы</Link></nav>
            <Link className="footer-contact" href="/support"><Icon name="mail" size={18} />Связаться с нами</Link>
            <details className="footer-more"><summary>Ещё</summary><nav><Link href="/catalog">Каталог товаров</Link><Link href="/seller/requests">Потребности бизнеса</Link><Link href="/ai-procurement">Закупки с ИИ</Link><Link href="/knowledge">Помощь с закупкой</Link><Link href="/info/about">О платформе</Link><Link href="/info/regulations">Регламенты</Link><Link href="/info/privacy">Конфиденциальность</Link><Link href="/info/news">Новости</Link></nav></details>
            <span className="footer-copyright">© ПоРукам</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
