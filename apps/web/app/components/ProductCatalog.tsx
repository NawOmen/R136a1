"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, AUTH_CHANGED_EVENT, getToken, MeResponse } from "../lib/api";
import { marketplace, Product } from "../lib/marketplace";
import { ProductCard } from "./ProductCard";
import { Icon, IconName } from "./Icon";
import { LiquidSurface } from "./LiquidSurface";

const allCategories = "Все категории";

export function ProductCatalog({ home = false }: { home?: boolean }) {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [category, setCategory] = useState(allCategories);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("popular");
  const [limit, setLimit] = useState(home ? 4 : 24);
  const [favorites, setFavorites] = useState<string[]>([]);
  useEffect(() => {
    const sync = () => { try { const value: unknown = JSON.parse(localStorage.getItem("porukam-product-favorites-v1") ?? "[]"); setFavorites(Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : []); } catch { setFavorites([]); } };
    sync(); window.addEventListener("storage", sync); return () => window.removeEventListener("storage", sync);
  }, []);
  const toggleFavorite = (id: string) => setFavorites(previous => {
    const next = previous.includes(id) ? previous.filter(value => value !== id) : [...previous, id];
    try { localStorage.setItem("porukam-product-favorites-v1", JSON.stringify(next)); } catch { /* Session-only favorites if storage is unavailable. */ }
    return next;
  });
  const generation = useRef(0);
  const load = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true); setError(null);
    try { const value = await marketplace.getCatalog("popular"); if (current === generation.current) setProducts(value); }
    catch (err) { if (current === generation.current) setError(err instanceof Error ? err.message : "Проверьте соединение и попробуйте ещё раз."); }
    finally { if (current === generation.current) setLoading(false); }
  }, []);
  useEffect(() => {
    setQuery(new URLSearchParams(window.location.search).get("q") ?? "");
    void load();
    return () => { generation.current++; };
  }, [load]);
  useEffect(() => {
    let current = 0;
    const sync = () => {
      const request = ++current, token = getToken();
      setMe(null);
      if (token) void api.me(token).then(value => { if (request === current) setMe(value); }).catch(() => {});
    };
    sync(); window.addEventListener(AUTH_CHANGED_EVENT, sync);
    return () => { current++; window.removeEventListener(AUTH_CHANGED_EVENT, sync); };
  }, []);
  const categories = useMemo(() => {
    const order = ["Упаковка и тара", "Сырьё и материалы", "Товары для бизнеса", "Оборудование", "Строительство"];
    return Array.from(new Set(products.map(product => product.category))).sort((a, b) => {
      const ar = order.includes(a) ? order.indexOf(a) : 99, br = order.includes(b) ? order.indexOf(b) : 99;
      return ar - br || a.localeCompare(b, "ru");
    });
  }, [products]);
  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ru");
    const result = products.filter(product => (category === allCategories || product.category === category) && (!normalized || `${product.name} ${product.category} ${product.subcategory ?? ""}`.toLocaleLowerCase("ru").includes(normalized)));
    if (sort === "name") return result.sort((a, b) => a.name.localeCompare(b.name, "ru"));
    // Preserve the server popularity order through search/category filtering.
    return result;
  }, [products, category, query, sort, home]);
  // Public GET /products admits only verified companies with sale permission (server admission.py).
  const admin = Boolean(me?.user.is_marketplace_admin);
  const chooseCategory = (value: string) => { setCategory(value); setLimit(24); };
  const company = me?.companies[0];

  const categoryIcons: Record<string, IconName> = { "Упаковка и тара": "package", "Сырьё и материалы": "metal", "Товары для бизнеса": "briefcase", "Оборудование": "chair", "Строительство": "bricks", "Продукты питания": "layers", "Электроника": "link" };
  return <div className={home ? "marketplace storefront" : "marketplace catalogue-page"}>
    {home ? <section className="storefront-hero" aria-labelledby="storefront-heading">
      <div className="storefront-warehouse" aria-hidden="true" />
      <div className="storefront-hero__copy"><h1 id="storefront-heading">Всё для вашего бизнеса</h1><p>Готовые товары. Прямой диалог с производителями.</p>
      <div className="storefront-hero__actions"><LiquidSurface as="div" variant="rail" className="liquid-action liquid-action--outline"><Link href={admin ? "/admin" : "/needs/new"}>{admin ? "Кабинет площадки" : "Разместить потребность"}<Icon name="arrow" size={19} /></Link></LiquidSurface><Link className="storefront-guide" href="/ai-procurement">Как это работает<Icon name="arrow" size={17} /></Link></div></div>
    </section> : <div className="marketplace-heading"><h1>Каталог товаров</h1>{!admin && <Link className="btn btn-outline-primary" href="/needs/new">Разместить потребность<Icon name="arrow" size={18} /></Link>}</div>}
    <div className="marketplace-layout">
      <aside className="catalog-categories" aria-label="Категории товаров">
        <h2 className="visually-hidden">Категории</h2>
        <nav>{[allCategories, ...categories].map(item => <button type="button" key={item} aria-label={item} className={item === category ? "active" : ""} aria-pressed={item === category} onClick={() => chooseCategory(item)}><Icon name={categoryIcons[item] ?? "grid"} size={29} /><span>{item === "Упаковка и тара" ? "Упаковка" : item}</span></button>)}</nav>
      </aside>
      <section className="catalog-results" aria-label="Предложения производителей">
        <div className="catalog-heading-row"><div className="catalog-title-group"><h2>Товары производителей</h2>{home && limit < visible.length && <button type="button" className="catalog-all" onClick={() => setLimit(value => value + 24)}>Показать ещё<Icon name="arrow" size={14} /></button>}</div>
          <div className="catalog-controls"><nav className="storefront-mode" aria-label="Для компаний">{admin ? <Link className="active" href="/admin">Администрирование</Link> : <><Link className="active" href="/catalog">Покупатель</Link><Link href={me ? "/seller/requests" : "/login"}>Производитель</Link></>}</nav><label className="catalog-sort"><span className="visually-hidden">Порядок</span><select aria-label="Порядок товаров" title={sort === "popular" ? "По числу закупок с подтверждённой приёмкой за вычетом полных возвратов" : "По алфавиту"} value={sort} onChange={event => { setSort(event.target.value); setLimit(home ? 4 : 24); }}><option value="popular">По популярности</option><option value="name">По названию</option></select></label></div>
        </div>
        <p className={loading || error ? "catalog-status" : "visually-hidden"} role="status">{loading ? "Загружаем товары…" : error ? "Каталог недоступен" : `${visible.length} предложений`}</p>
        {query && <p className="catalog-query">Поиск: «{query}» <a href={home ? "/" : "/catalog"}>Сбросить</a></p>}
        {loading ? <div className="product-grid" aria-busy="true" aria-label="Загрузка предложений">{[0, 1, 2, 3].map(i => <div className="product-skeleton" key={i}><span /><i /><i /></div>)}</div>
          : error ? <div className="empty-market" role="alert"><Icon name="box" size={28} /><div><b>Не удалось загрузить предложения</b><p>{error}</p></div><button type="button" className="btn btn-secondary" onClick={() => void load()}>Повторить</button></div>
          : visible.length ? <><div className="product-grid">{visible.slice(0, limit).map(product => <ProductCard key={product.id} headingLevel={2} product={product} manufacturerVerified favorite={favorites.includes(product.id)} onFavorite={() => toggleFavorite(product.id)} />)}</div>{!home && limit < visible.length && <button className="btn btn-secondary catalog-more" type="button" onClick={() => setLimit(value => value + 24)}>Показать ещё · осталось {visible.length - limit}</button>}</>
          : <div className="empty-market"><Icon name="search" size={28} /><div><b>{query || category !== allCategories ? "Подходящих товаров пока нет" : "Новые предложения появятся здесь"}</b><p>Измените поиск или опишите закупку для производителей.</p></div>{category !== allCategories && <button className="btn btn-secondary" type="button" onClick={() => chooseCategory(allCategories)}>Все категории</button>}{!admin && <Link href="/needs/new" className="btn btn-primary">Создать потребность</Link>}</div>}
      </section>
    </div>
    {home && !admin && <section className="storefront-request"><div className="storefront-request__symbol" aria-hidden="true"><Icon name="spark" size={31} /></div><h2>Не нашли нужный товар?</h2><LiquidSurface as="div" variant="rail" className="liquid-action liquid-action--primary"><Link href="/needs/new">Создать потребность<Icon name="arrow" size={18} /></Link></LiquidSurface></section>}
    {!home && <nav className="market-utilities" aria-label="Рабочие возможности">
      {me && <><Link href={admin ? "/admin" : company ? "/dashboard" : "/company/new"}><Icon name="building" />{admin ? "Администрирование" : company ? "Моя компания" : "Создать компанию"}<Icon name="arrow" size={16} /></Link>{!admin && <><Link href="/needs"><Icon name="layers" />Мои потребности<Icon name="arrow" size={16} /></Link><Link href="/notifications"><Icon name="spark" />Уведомления<Icon name="arrow" size={16} /></Link><Link href="/deals"><Icon name="box" />Сделки<Icon name="arrow" size={16} /></Link></>}</>}
      <Link href="/ai-procurement"><Icon name="link" />Закупки с ИИ<Icon name="arrow" size={16} /></Link><Link href="/knowledge"><Icon name="shield" />Помощь с закупкой<Icon name="arrow" size={16} /></Link>
    </nav>}
  </div>;
}
