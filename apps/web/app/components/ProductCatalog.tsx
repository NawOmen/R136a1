"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, AUTH_CHANGED_EVENT, getToken, MeResponse } from "../lib/api";
import { formatUnits, itemUnit, marketplace, Product } from "../lib/marketplace";
import { activeCatalogFilterCount, type CatalogFilterErrors, type CatalogFilters, type CatalogSort, emptyCatalogFilters, filterCatalog, readCatalogLocation, validateCatalogFilters, writeCatalogLocation } from "../lib/catalogFilters";
import { ProductCard } from "./ProductCard";
import { Icon, IconName } from "./Icon";
import { LiquidSurface } from "./LiquidSurface";

const allCategories = "Все категории";
const homePageSize = 10;
const catalogPageSize = 30;

export function ProductCatalog({ home = false }: { home?: boolean }) {
  const [products, setProducts] = useState<Product[]>([]);
  const [supplierNames, setSupplierNames] = useState<Record<string, string>>({});
  const supplierRequests = useRef(new Map<string, Promise<string | null>>());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [category, setCategory] = useState(allCategories);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<CatalogSort>("popular");
  const [filters, setFilters] = useState<CatalogFilters>(emptyCatalogFilters);
  const [draft, setDraft] = useState<CatalogFilters>(emptyCatalogFilters);
  const [filterErrors, setFilterErrors] = useState<CatalogFilterErrors>({});
  const filtersPanel = useRef<HTMLDetailsElement>(null);
  const [limit, setLimit] = useState(home ? homePageSize : catalogPageSize);
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
    const syncLocation = () => {
      const state = readCatalogLocation(home ? "" : window.location.search), checked = validateCatalogFilters(state.filters);
      setQuery(state.query); setCategory(state.category || allCategories); setSort(state.sort);
      setDraft(state.filters); setFilterErrors(checked.errors);
      setFilters(Object.keys(checked.errors).length ? emptyCatalogFilters : checked.filters);
      setLimit(home ? homePageSize : catalogPageSize);
      if (Object.keys(checked.errors).length && filtersPanel.current) filtersPanel.current.open = true;
    };
    syncLocation();
    window.addEventListener("popstate", syncLocation);
    void load();
    return () => { generation.current++; window.removeEventListener("popstate", syncLocation); };
  }, [load, home]);
  useEffect(() => {
    let active = true;
    const requests = Array.from(new Set(products.map(product => product.company_id))).map(async id => {
      let request = supplierRequests.current.get(id);
      if (!request) {
        request = marketplace.getProducer(id).then(value => value?.company_id === id && typeof value.display_name === "string" && value.display_name.trim() ? value.display_name : null).catch(() => null);
        supplierRequests.current.set(id, request);
      }
      return [id, await request] as const;
    });
    void Promise.all(requests).then(entries => { if (active) setSupplierNames(previous => ({ ...previous, ...Object.fromEntries(entries.filter((entry): entry is readonly [string, string] => entry[1] !== null)) })); });
    return () => { active = false; };
  }, [products]);
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
  const categoryProducts = useMemo(() => products.filter(product => category === allCategories || product.category === category), [products, category]);
  const subcategories = useMemo(() => Array.from(new Set(categoryProducts.map(product => product.subcategory).filter((value): value is string => Boolean(value)))).sort((a, b) => a.localeCompare(b, "ru")), [categoryProducts]);
  const units = useMemo(() => Array.from(new Set(categoryProducts.map(product => itemUnit(product.characteristics)))).sort((a, b) => a.localeCompare(b, "ru")), [categoryProducts]);
  const visible = useMemo(() => filterCatalog(products, category === allCategories ? "" : category, query, sort, filters), [products, category, query, sort, filters]);
  const activeFilters = activeCatalogFilterCount(filters);
  const updateLocation = (next: { category?: string; sort?: CatalogSort; filters?: CatalogFilters; query?: string } = {}) => {
    const selectedCategory = next.category ?? category;
    const search = writeCatalogLocation(window.location.search, { query: next.query ?? query, category: selectedCategory === allCategories ? "" : selectedCategory, sort: next.sort ?? sort, filters: next.filters ?? filters });
    const url = `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`;
    if (url !== `${window.location.pathname}${window.location.search}${window.location.hash}`) window.history.pushState(null, "", url);
  };
  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const checked = validateCatalogFilters(draft);
    setFilterErrors(checked.errors);
    if (Object.keys(checked.errors).length) {
      const first = Object.keys(checked.errors)[0];
      event.currentTarget.querySelector<HTMLInputElement>(`[name="${first}"]`)?.focus();
      return;
    }
    setFilters(checked.filters); setDraft(checked.filters); setLimit(home ? homePageSize : catalogPageSize);
    updateLocation({ filters: checked.filters });
  };
  const resetFilters = () => {
    setFilters(emptyCatalogFilters); setDraft(emptyCatalogFilters); setFilterErrors({}); setCategory(allCategories); setLimit(home ? homePageSize : catalogPageSize);
    updateLocation({ category: allCategories, filters: emptyCatalogFilters });
  };
  const setDraftField = <K extends keyof CatalogFilters>(field: K, value: CatalogFilters[K]) => setDraft(previous => ({ ...previous, [field]: value }));
  // Public GET /products admits only verified companies with sale permission (server admission.py).
  const admin = Boolean(me?.user.is_marketplace_admin);
  const chooseCategory = (value: string) => {
    const matching = products.filter(product => value === allCategories || product.category === value);
    const next = { ...filters, subcategory: matching.some(product => product.subcategory === filters.subcategory) ? filters.subcategory : "", unit: matching.some(product => itemUnit(product.characteristics) === filters.unit) ? filters.unit : "" };
    setCategory(value); setFilters(next); setDraft(next); setFilterErrors({}); setLimit(catalogPageSize);
    updateLocation({ category: value, filters: next });
  };
  const company = me?.companies[0];

  const categoryIcons: Record<string, IconName> = { "Упаковка и тара": "package", "Сырьё и материалы": "metal", "Товары для бизнеса": "briefcase", "Оборудование": "chair", "Строительство": "bricks", "Продукты питания": "layers", "Электроника": "link" };
  return <div className={home ? "marketplace storefront" : "marketplace catalogue-page"}>
    {home ? <section className="storefront-hero" aria-labelledby="storefront-heading">
      <div className="storefront-warehouse" aria-hidden="true" />
      <div className="storefront-hero__copy"><h1 id="storefront-heading" className="storefront-title"><span className="storefront-title__base">Всё для вашего бизнеса</span><span className="storefront-title__sheen" aria-hidden="true">Всё для вашего бизнеса</span></h1><p>От задачи до выбора поставщика: ИИ соберёт требования, подберёт производителей и поможет сравнить предложения.</p>
      <div className="storefront-hero__actions"><LiquidSurface as="div" variant="rail" className="liquid-action liquid-action--outline"><Link href={admin ? "/admin" : "/needs/new"}>{admin ? "Кабинет площадки" : "Закупить с ИИ"}<Icon name="arrow" size={19} /></Link></LiquidSurface><Link className="storefront-guide" href="/ai-procurement">Как это работает<Icon name="arrow" size={17} /></Link></div></div>
    </section> : <div className="marketplace-heading"><h1>Каталог товаров</h1>{!admin && <Link className="btn btn-outline-primary" href="/needs/new">Разместить потребность<Icon name="arrow" size={18} /></Link>}</div>}
    <div className={home ? "storefront-products" : "marketplace-layout"}>
      {!home && <aside className="catalog-categories" aria-label="Категории товаров">
        <h2 className="visually-hidden">Категории</h2>
        <nav>{[allCategories, ...categories].map(item => <button type="button" key={item} aria-label={item} className={item === category ? "active" : ""} aria-pressed={item === category} onClick={() => chooseCategory(item)}><Icon name={categoryIcons[item] ?? "grid"} size={29} /><span>{item === "Упаковка и тара" ? "Упаковка" : item}</span></button>)}</nav>
      </aside>}
      <section className="catalog-results" aria-label="Предложения производителей">
        <div className="catalog-heading-row"><div className="catalog-title-group"><h2>{home ? "Популярные товары" : "Товары производителей"}</h2>{home && <Link className="btn btn-secondary catalog-more" href="/catalog">Показать ещё<Icon name="arrow" size={18} /></Link>}</div>
          {!home && <div className="catalog-controls"><nav className="storefront-mode" aria-label="Для компаний">{admin ? <Link className="active" href="/admin">Администрирование</Link> : <><Link className="active" href="/catalog">Покупатель</Link><Link href={me ? "/seller/requests" : "/login"}>Производитель</Link></>}</nav><label className="catalog-sort"><span className="visually-hidden">Порядок</span><select aria-label="Порядок товаров" title={sort === "popular" ? "По числу закупок с подтверждённой приёмкой за вычетом полных возвратов" : undefined} value={sort} onChange={event => { const value = event.target.value as CatalogSort; setSort(value); setLimit(home ? homePageSize : catalogPageSize); updateLocation({ sort: value }); }}><option value="popular">По популярности</option><option value="name">По названию</option><option value="price-asc">Сначала дешевле</option><option value="price-desc">Сначала дороже</option><option value="lead-time">Быстрее производство</option><option value="moq">Меньше минимальный заказ</option></select></label></div>}
        </div>
        {!home && <details className="catalog-filters" ref={filtersPanel}>
          <summary><Icon name="sliders" size={18} /><span>Фильтры{activeFilters > 0 && <span className="catalog-filter-count">{activeFilters}</span>}</span><Icon name="arrow" className="catalog-filter-chevron" size={16} /></summary>
          <form className="catalog-filter-form" onSubmit={applyFilters} noValidate>
            <div className="catalog-filter-fields">
              <div className="field"><label htmlFor="catalog-price-from">Цена от, ₽</label><input type="text" id="catalog-price-from" name="priceFrom" inputMode="decimal" autoComplete="off" value={draft.priceFrom} onChange={event => setDraftField("priceFrom", event.target.value)} aria-invalid={Boolean(filterErrors.priceFrom)} aria-describedby={filterErrors.priceFrom ? "catalog-price-from-error" : undefined} />{filterErrors.priceFrom && <p id="catalog-price-from-error" className="catalog-filter-error" role="alert">{filterErrors.priceFrom}</p>}</div>
              <div className="field"><label htmlFor="catalog-price-to">Цена до, ₽</label><input type="text" id="catalog-price-to" name="priceTo" inputMode="decimal" autoComplete="off" value={draft.priceTo} onChange={event => setDraftField("priceTo", event.target.value)} aria-invalid={Boolean(filterErrors.priceTo)} aria-describedby={filterErrors.priceTo ? "catalog-price-to-error" : undefined} />{filterErrors.priceTo && <p id="catalog-price-to-error" className="catalog-filter-error" role="alert">{filterErrors.priceTo}</p>}</div>
              <div className="field"><label htmlFor="catalog-lead-days">Срок производства, до дней</label><input type="text" id="catalog-lead-days" name="leadDays" inputMode="numeric" autoComplete="off" value={draft.leadDays} onChange={event => setDraftField("leadDays", event.target.value)} aria-invalid={Boolean(filterErrors.leadDays)} aria-describedby={filterErrors.leadDays ? "catalog-lead-days-error" : undefined} />{filterErrors.leadDays && <p id="catalog-lead-days-error" className="catalog-filter-error" role="alert">{filterErrors.leadDays}</p>}</div>
              <div className="field"><label htmlFor="catalog-moq">Минимальный заказ, до единиц</label><input type="text" id="catalog-moq" name="moq" inputMode="numeric" autoComplete="off" value={draft.moq} onChange={event => setDraftField("moq", event.target.value)} aria-invalid={Boolean(filterErrors.moq)} aria-describedby={filterErrors.moq ? "catalog-moq-error" : undefined} />{filterErrors.moq && <p id="catalog-moq-error" className="catalog-filter-error" role="alert">{filterErrors.moq}</p>}</div>
              <div className="field"><label htmlFor="catalog-subcategory">Подкатегория</label><select id="catalog-subcategory" value={draft.subcategory} onChange={event => setDraftField("subcategory", event.target.value)}><option value="">Все подкатегории</option>{draft.subcategory && !subcategories.includes(draft.subcategory) && <option value={draft.subcategory}>{draft.subcategory}</option>}{subcategories.map(value => <option value={value} key={value}>{value}</option>)}</select></div>
              <div className="field"><label htmlFor="catalog-unit">Единица заказа</label><select id="catalog-unit" value={draft.unit} onChange={event => setDraftField("unit", event.target.value)}><option value="">Все единицы</option>{draft.unit && !units.includes(draft.unit) && <option value={draft.unit}>{draft.unit}</option>}{units.map(value => <option value={value} key={value}>{value}</option>)}</select></div>
            </div>
            <div className="catalog-filter-actions"><label className="catalog-stock-filter"><input type="checkbox" checked={draft.inStock} onChange={event => setDraftField("inStock", event.target.checked)} /><span>Только в наличии</span></label><button className="btn btn-primary" type="submit">Применить фильтры</button><button className="btn btn-secondary" type="button" onClick={resetFilters}>Очистить фильтры</button></div>
          </form>
        </details>}
        <p className={loading || error ? "catalog-status" : "visually-hidden"} role="status">{loading ? "Загружаем товары…" : error ? "Каталог недоступен" : formatUnits(visible.length, "предложение")}</p>
        {query && <p className="catalog-query">Поиск: «{query}» <button type="button" onClick={() => { setQuery(""); setLimit(home ? homePageSize : catalogPageSize); updateLocation({ query: "" }); }}>Сбросить поиск</button></p>}
        {loading ? <div className="product-grid" aria-busy="true" aria-label="Загрузка предложений">{Array.from({ length: homePageSize }, (_, i) => <div className="product-skeleton" key={i}><span /><i /><i /></div>)}</div>
          : error ? <div className="empty-market" role="alert"><Icon name="box" size={28} /><div><b>Не удалось загрузить предложения</b><p>{error}</p></div><button type="button" className="btn btn-secondary" onClick={() => void load()}>Повторить</button></div>
          : visible.length ? <><div className="product-grid">{visible.slice(0, limit).map((product, index) => <ProductCard key={product.id} headingLevel={2} product={product} supplier={supplierNames[product.company_id]} imageLoading={index < 5 ? "eager" : "lazy"} manufacturerVerified favorite={favorites.includes(product.id)} onFavorite={() => toggleFavorite(product.id)} />)}</div>{!home && limit < visible.length && <button className="btn btn-secondary catalog-more" type="button" onClick={() => setLimit(value => value + catalogPageSize)}>Показать ещё</button>}</>
          : <div className="empty-market"><Icon name="search" size={28} /><div><b>{query || activeFilters || category !== allCategories ? "Подходящих товаров пока нет" : "Новые предложения появятся здесь"}</b><p>Измените фильтры или поиск, либо опишите закупку для производителей.</p></div>{(activeFilters > 0 || category !== allCategories) && <button className="btn btn-secondary" type="button" onClick={resetFilters}>Сбросить ограничения</button>}{!admin && <Link href="/needs/new" className="btn btn-primary">Создать потребность</Link>}</div>}
      </section>
    </div>
    {home && !admin && <section className="storefront-request"><div className="storefront-request__symbol" aria-hidden="true"><Icon name="spark" size={31} /></div><h2>Не нашли нужный товар?</h2><LiquidSurface as="div" variant="rail" className="liquid-action liquid-action--primary"><Link href="/needs/new">Создать потребность<Icon name="arrow" size={18} /></Link></LiquidSurface></section>}
    {!home && <nav className="market-utilities" aria-label="Рабочие возможности">
      {me && <><Link href={admin ? "/admin" : company ? "/dashboard" : "/company/new"}><Icon name="building" />{admin ? "Администрирование" : company ? "Моя компания" : "Создать компанию"}<Icon name="arrow" size={16} /></Link>{!admin && <><Link href="/needs"><Icon name="layers" />Мои потребности<Icon name="arrow" size={16} /></Link><Link href="/deals"><Icon name="box" />Сделки<Icon name="arrow" size={16} /></Link></>}</>}
      <Link href="/ai-procurement"><Icon name="link" />Закупки с ИИ<Icon name="arrow" size={16} /></Link><Link href="/knowledge"><Icon name="shield" />Помощь с закупкой<Icon name="arrow" size={16} /></Link>
    </nav>}
  </div>;
}
