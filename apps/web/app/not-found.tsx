import Link from "next/link";

export default function NotFound() {
  return (
    <section className="route-state">
      <span className="eyebrow">Страница не найдена</span>
      <h1>По этому адресу ничего нет</h1>
      <p>Проверьте адрес или найдите нужный товар в каталоге.</p>
      <div className="route-state__actions">
        <Link className="btn btn-primary" href="/catalog">В каталог</Link>
        <Link className="btn btn-secondary" href="/">На главную</Link>
      </div>
    </section>
  );
}
