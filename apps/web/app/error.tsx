"use client";

import Link from "next/link";

export default function ErrorPage({ retry }: { retry: () => void }) {
  return (
    <section className="route-state" role="alert">
      <span className="eyebrow">ПоРукам</span>
      <h1>Не удалось открыть страницу</h1>
      <p>Повторите загрузку. Если ошибка повторится, вернитесь в каталог или обратитесь в поддержку.</p>
      <div className="route-state__actions">
        <button className="btn btn-primary" onClick={retry}>Попробовать снова</button>
        <Link className="btn btn-secondary" href="/catalog">В каталог</Link>
        <Link href="/support">Поддержка</Link>
      </div>
    </section>
  );
}
