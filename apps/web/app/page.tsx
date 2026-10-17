"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, AUTH_CHANGED_EVENT, getToken, MeResponse } from "./lib/api";
import { formatRub, formatUnits, itemUnit, marketplace, Product } from "./lib/marketplace";

function ProductShowcase({ products }: { products: Product[] }) {
  const featured: Product[] = [];
  const shownCategories = new Set<string>();
  for (const product of products) {
    if (!shownCategories.has(product.category)) {
      featured.push(product);
      shownCategories.add(product.category);
    }
    if (featured.length === 4) break;
  }
  for (const product of products) {
    if (featured.length === 4) break;
    if (!featured.some((item) => item.id === product.id)) featured.push(product);
  }
  return <section className="market-section">
    <div className="section-heading"><div><span className="eyebrow">Готовые предложения</span><h2>Товары российских производителей</h2></div><Link href="/catalog">Открыть весь каталог <span>→</span></Link></div>
    {products.length ? <div className="product-grid product-grid--showcase">{featured.map((product) => <Link className="market-product" href={`/catalog/${product.id}`} key={product.id}>
      <div className="market-product__visual">{product.images[0] ? <img src={marketplace.productImageUrl(product.images[0].id)} alt={product.name} /> : <span aria-hidden="true">{product.category.slice(0, 1)}</span>}<small>РОССИЯ</small></div>
      <div className="market-product__body"><strong className="market-price">{formatRub(product.price_rub, 12)}</strong><span className="market-muted">за {itemUnit(product.characteristics)} · минимальный заказ {formatUnits(product.moq_units, itemUnit(product.characteristics))}</span><h3>{product.name}</h3><span className="market-supplier">✓ Проверенный производитель</span><span className="market-product__cta">Подробнее</span></div>
    </Link>)}</div> : <div className="empty-market"><span aria-hidden="true">◫</span><div><b>Каталог готов к публикации</b><p>После добавления товаров здесь появятся актуальные предложения производителей.</p></div><Link className="btn btn-primary" href="/catalog">Перейти в каталог</Link></div>}
  </section>;
}

export default function HomePage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const router = useRouter();
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

  useEffect(() => { if (me) router.replace("/dashboard"); }, [me, router]);

  if (!ready) return <div className="market-loading"><span /><p>Открываем маркетплейс...</p></div>;

  if (me) return <div className="card"><h1>Продолжим работу</h1><p>Выберите компанию и задачу в личном кабинете.</p><Link href="/dashboard" className="btn btn-primary">Открыть кабинет</Link></div>;

  return <div className="market-home">
    <section className="market-hero"><div className="market-hero__content"><span className="eyebrow">Оптовый маркетплейс для бизнеса</span><h1>Товары и производство<br /><em>на ваших условиях</em></h1><p>Опишите, что нужно купить. ИИ подготовит запрос, а вы проверите условия и выберете производителя.</p><div className="actions"><Link href="/register" className="btn btn-primary">Начать закупку с ИИ</Link><Link href="/catalog" className="btn btn-secondary">Найти готовый товар</Link></div><div className="trust-row"><span>✓ Только российские компании</span><span>✓ Проверка производителей</span><span>✓ Цены в рублях</span></div></div><aside className="market-hero__panel"><span className="live-dot">Как проходит закупка</span><strong>1 → 2 → 3</strong><small>Запрос · условия · подтверждение</small><ol><li>Опишите товар и количество.</li><li>Проверьте запрос ИИ.</li><li>Сравните предложения.</li></ol><Link href="/ai-procurement">Подробнее о закупке →</Link></aside></section>
    {availableCategories.length > 0 && <nav className="category-rail" aria-label="Категории каталога">{availableCategories.map((category) => <Link href={`/catalog?q=${encodeURIComponent(category)}`} key={category}>{category}</Link>)}</nav>}
    <ProductShowcase products={products} />
    <section className="dual-market"><article><span className="dual-market__number">01</span><div><span className="eyebrow">Покупателям</span><h2>Не нашли товар — опубликуйте потребность</h2><p>Укажите объём, бюджет и требования. Производители предложат условия, а система найдёт совместимый спрос.</p><Link className="btn btn-outline-primary" href="/register">Создать запрос</Link></div></article><article><span className="dual-market__number">02</span><div><span className="eyebrow">Производителям</span><h2>Находите заказы под свои мощности</h2><p>Лента показывает реальный спрос и объясняет, почему запрос подходит вашему производству.</p><Link className="btn btn-outline-primary" href="/register">Стать поставщиком</Link></div></article></section>
    <section className="agent-banner"><div className="agent-mark">ИИ</div><div><span className="eyebrow">Закупки с ИИ-агентами</span><h2>Рутина автоматизируется, решение остаётся вашим</h2><p>ИИ собирает требования и объясняет подбор. Цена, мощность, резерв и статус сделки меняются только после подтверждения.</p></div><Link href="/ai-procurement" className="btn btn-primary">Узнать подробнее</Link></section>
  </div>;
}
