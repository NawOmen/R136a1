"use client";

import "./globals.css";

export default function GlobalError() {
  return (
    <html lang="ru">
      <body>
        <title>Не удалось открыть страницу — ПоРукам</title>
        <main className="container main">
          <section className="route-state" role="alert">
            <span className="eyebrow">ПоРукам</span>
            <h1>Не удалось открыть страницу</h1>
            <p>Перезагрузите страницу, чтобы продолжить работу.</p>
            <div className="route-state__actions">
              <button className="btn btn-primary" onClick={() => window.location.reload()}>Перезагрузить страницу</button>
              <a className="btn btn-secondary" href="/">На главную</a>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
