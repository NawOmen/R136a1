import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import Link from "next/link";
import { AccountDrawer } from "./components/AccountDrawer";
import { WorkflowGuide } from "./components/WorkflowGuide";
import { RussianValidation } from "./components/RussianValidation";
import { SiteNavigation } from "./components/SiteNavigation";

export const metadata: Metadata = {
  title: "ПоРукам",
  description: "Маркетплейс для бизнеса коалиций покупателей и производителей",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <body>
        <RussianValidation />
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
        <main className="container main"><WorkflowGuide />{children}</main>
        <footer className="site-footer">
          <div className="container footer-grid">
            <div className="footer-brand"><Link className="site-header__logo" href="/"><img src="/icon.png" alt="" width="34" height="34" /><span>ПоРукам</span></Link><p>Для проверенных российских покупателей и производителей.</p><span>© ПоРукам</span></div>
            <div><strong>Маркетплейс</strong><Link href="/catalog">Каталог товаров</Link><Link href="/seller/requests">Потребности бизнеса</Link><Link href="/ai-procurement">Закупки с ИИ</Link></div>
            <div><strong>Компаниям</strong><Link href="/info/about">О платформе</Link><Link href="/info/guide">Как начать</Link><Link href="/info/regulations">Регламенты</Link><Link href="/support">Поддержка</Link></div>
            <div><strong>Документы</strong><Link href="/info/legal">Правила работы</Link><Link href="/info/privacy">Конфиденциальность</Link><Link href="/info/contacts">Контакты</Link><Link href="/info/news">Новости</Link></div>
          </div>
        </footer>
      </body>
    </html>
  );
}
