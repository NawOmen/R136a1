import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Сборка B2B",
  description: "B2B-маркетплейс коалиций покупателей и производителей",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ru">
      <body>
        <header className="site-header">
          <div className="container site-header__inner">
            <span className="site-header__logo">Сборка B2B</span>
          </div>
        </header>
        <main className="container main">{children}</main>
      </body>
    </html>
  );
}
