export default function Loading() {
  return (
    <section className="route-state" aria-busy="true">
      <p role="status">Загружаем страницу…</p>
      <p>Это может занять несколько секунд.</p>
    </section>
  );
}
