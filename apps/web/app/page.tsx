"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, AUTH_CHANGED_EVENT, getToken, MeResponse } from "./lib/api";
import { formatRub, formatUnits, marketplace, Product } from "./lib/marketplace";

function ProductShowcase({ products }: { products: Product[] }) {
  return <section className="market-section">
    <div className="section-heading"><div><span className="eyebrow">Готовые предложения</span><h2>Товары российских производителей</h2></div><Link href="/catalog">Открыть весь каталог <span>→</span></Link></div>
    {products.length ? <div className="product-grid product-grid--showcase">{products.slice(0, 4).map((product) => <Link className="market-product" href={`/catalog/${product.id}`} key={product.id}>
      <div className="market-product__visual">{product.images[0] ? <img src={marketplace.productImageUrl(product.images[0].id)} alt={product.name} /> : <span aria-hidden="true">{product.category.slice(0, 1)}</span>}<small>РОССИЯ</small></div>
      <div className="market-product__body"><strong className="market-price">{formatRub(product.price_rub)}</strong><span className="market-muted">за единицу · MOQ {formatUnits(product.moq_units)}</span><h3>{product.name}</h3><span className="market-supplier">✓ Проверенный производитель</span><span className="market-product__cta">Подробнее</span></div>
    </Link>)}</div> : <div className="empty-market"><span aria-hidden="true">◫</span><div><b>Каталог готов к публикации</b><p>После добавления товаров здесь появятся актуальные предложения производителей.</p></div><Link className="btn btn-primary" href="/catalog">Перейти в каталог</Link></div>}
  </section>;
}

export default function HomePage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [ready, setReady] = useState(false);
  const availableCategories = Array.from(new Set(products.map((product) => product.category))).slice(0, 8);

  useEffect(() => {
    void marketplace.getCatalog().then(setProducts).catch(() => setProducts([]));
    const sync = () => {
      const token = getToken();
      if (!token) { setMe(null); setReady(true); return; }
      void api.me(token).then(setMe).catch(() => setMe(null)).finally(() => setReady(true));
    };
    sync(); window.addEventListener(AUTH_CHANGED_EVENT, sync);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, sync);
  }, []);

  if (!ready) return <div className="market-loading"><span /><p>Открываем маркетплейс...</p></div>;

  if (me) {
    const company = me.companies[0];
    return <div className="market-home">
      <section className="workspace-hero"><div><span className="eyebrow">Ваше рабочее пространство</span><h1>Добрый день, {me.user.first_name}</h1><p>{company ? `Компания «${company.display_name}» готова к работе.` : "Создайте компанию, чтобы публиковать товары и потребности."}</p></div><div className="actions"><Link href={company ? "/needs/new" : "/company/new"} className="btn btn-primary">+ {company ? "Новая потребность" : "Создать компанию"}</Link><Link href="/catalog" className="btn btn-secondary">Найти товар</Link></div></section>
      <section className="workspace-strip"><Link href="/needs"><span>01</span><div><b>Повторить закупку</b><small>Новый черновик за два действия</small></div><i>→</i></Link><Link href="/notifications"><span>02</span><div><b>Новые варианты</b><small>Спрос, предложения и коалиции</small></div><i>→</i></Link><Link href="/deals"><span>03</span><div><b>Активные сделки</b><small>Производство, отгрузка, получение</small></div><i>→</i></Link></section>
      <ProductShowcase products={products} />
      <section className="agent-banner"><div className="agent-mark">ИИ</div><div><span className="eyebrow">Агент покупателя</span><h2>Опишите закупку своими словами</h2><p>Агент уточнит характеристики, проверит противоречия и подготовит карточку потребности. Публикация — только после вашего подтверждения.</p></div><Link href="/needs/new" className="btn btn-primary">Начать закупку</Link></section>
    </div>;
  }

  return <div className="market-home">
    <section className="market-hero"><div className="market-hero__content"><span className="eyebrow">Оптовый маркетплейс для бизнеса</span><h1>Товары и производство<br /><em>на ваших условиях</em></h1><p>Покупайте готовые партии, размещайте запросы на производство и объединяйте объёмы с другими компаниями — с контролем человека на каждом критичном шаге.</p><div className="actions"><Link href="/catalog" className="btn btn-primary">Смотреть товары</Link><Link href="/register" className="btn btn-secondary">Разместить потребность</Link></div><div className="trust-row"><span>✓ Только российские компании</span><span>✓ Проверка производителей</span><span>✓ Цены в рублях</span></div></div><aside className="market-hero__panel"><span className="live-dot">Как проходит закупка</span><strong>1 → 2 → 3</strong><small>Запрос · условия · подтверждение</small><p>Укажите товар и объём, сравните предложения и подтвердите подходящие условия. Для разных категорий доступны свои характеристики и требования к документам.</p><Link href="/ai-procurement">Как работает объединение →</Link></aside></section>
    {availableCategories.length > 0 && <nav className="category-rail" aria-label="Категории каталога">{availableCategories.map((category) => <Link href={`/catalog?q=${encodeURIComponent(category)}`} key={category}>{category}</Link>)}</nav>}
    <ProductShowcase products={products} />
    <section className="dual-market"><article><span className="dual-market__number">01</span><div><span className="eyebrow">Покупателям</span><h2>Не нашли товар — опубликуйте потребность</h2><p>Укажите объём, бюджет и требования. Производители предложат условия, а система найдёт совместимый спрос.</p><Link className="btn btn-outline-primary" href="/register">Создать запрос</Link></div></article><article><span className="dual-market__number">02</span><div><span className="eyebrow">Производителям</span><h2>Находите заказы под свои мощности</h2><p>Лента показывает реальный спрос и объясняет, почему запрос подходит вашему производству.</p><Link className="btn btn-outline-primary" href="/register">Стать поставщиком</Link></div></article></section>
    <section className="agent-banner"><div className="agent-mark">ИИ</div><div><span className="eyebrow">Закупки с ИИ-агентами</span><h2>Рутина автоматизируется, решение остаётся вашим</h2><p>ИИ собирает требования и объясняет подбор. Цена, мощность, резерв и статус сделки меняются только после подтверждения.</p></div><Link href="/ai-procurement" className="btn btn-primary">Узнать подробнее</Link></section>
  </div>;
}
