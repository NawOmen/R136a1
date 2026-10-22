"use client";
import { productAvailability, startingPrice } from "../../lib/catalogPresentation";
import { formatDate } from "../../lib/dates";

import Link from "next/link";
import { russianMessage } from "../../lib/russianMessages";
import { ProductPlaceholder } from "../../components/ProductPlaceholder";
import { Icon } from "../../components/Icon";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { russianUnit, formatCharacteristics, formatRub, formatUnits, itemUnit, marketplace, primaryProductImage, PriceIndexPoint, ProductAdmissionChecklist, PublicProductDetail } from "../../lib/marketplace";

const verificationCopy = (text: string) => text.replace(/Проверено человеком/g, "Проверено").replace(/проверено человеком/g, "проверено");

export default function ProductDetailPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [product, setProduct] = useState<PublicProductDetail | null>(null);
  const [index, setIndex] = useState<PriceIndexPoint[]>([]);
  const [admission, setAdmission] = useState<ProductAdmissionChecklist | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [retry, setRetry] = useState(0);
  const [priceRetry, setPriceRetry] = useState(0);
  const [priceLoading, setPriceLoading] = useState(true);
  const [priceError, setPriceError] = useState(false);
  const [admissionError, setAdmissionError] = useState(false);
  const [admissionLoading, setAdmissionLoading] = useState(true);
  const [admissionRetry, setAdmissionRetry] = useState(0);

  useEffect(() => {
    if (!id) return;
    let active = true;
    setProduct(null); setError(null);
    marketplace.getProductDetail(id).then(item => { if (active) setProduct(item); })
      .catch(reason => { if (active) setError(reason instanceof Error ? russianMessage(reason.message) : "Не удалось загрузить товар."); });
    return () => { active = false; };
  }, [id, retry]);

  useEffect(() => {
    if (!product) return;
    let active = true;
    setIndex([]); setPriceLoading(true); setPriceError(false);
    marketplace.getPriceIndex(product.category, product.id).then(items => { if (active) setIndex(items); })
      .catch(() => { if (active) setPriceError(true); })
      .finally(() => { if (active) setPriceLoading(false); });
    return () => { active = false; };
  }, [product, priceRetry]);

  useEffect(() => {
    if (!id) return;
    let active = true;
    setAdmission(null); setAdmissionError(false); setAdmissionLoading(true);
    marketplace.getProductAdmission(id).then(item => { if (active) setAdmission(item); })
      .catch(() => { if (active) setAdmissionError(true); })
      .finally(() => { if (active) setAdmissionLoading(false); });
    return () => { active = false; };
  }, [id, admissionRetry]);

  if (error) return <div className="alert alert-error" role="alert">{error} <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRetry(value => value + 1)}>Повторить загрузку</button> <Link href="/catalog">В каталог</Link></div>;
  if (!product) return <div className="market-loading"><span /><p>Загружаем карточку товара...</p></div>;
  const photo = primaryProductImage(product.images);
  const availability = productAvailability(product);

  return <div className="product-page">
    <nav className="breadcrumbs" aria-label="Навигационная цепочка"><Link href="/catalog">Каталог</Link><span>›</span><Link href={`/catalog?q=${encodeURIComponent(product.category)}`}>{product.category}</Link><span>›</span><span>{product.name}</span></nav>
    <div className="product-detail product-detail--market">
      <section className="product-gallery">{photo ? <img className="product-hero" src={marketplace.productImageUrl(photo.id)} alt={product.name} /> : <div className="product-placeholder"><ProductPlaceholder /></div>}<div className="product-gallery__badges"><span className={`product-stock${availability.available ? " product-stock--available" : ""}`}>{availability.label === "Нет в наличии" && <Icon name="box" size={13} />}{availability.label}</span><span className="made-in-russia">ПРОИЗВЕДЕНО В РОССИИ</span></div></section>
      <section className="product-buybox"><span className="eyebrow">{product.category}{product.subcategory ? ` · ${product.subcategory}` : ""}</span><h1>{product.name}</h1><p className="product-characteristics">{formatCharacteristics(product.characteristics, product.category_profile)}</p>{product.quantity_conversion && <p>Содержимое подтверждено продавцом: 1 {russianUnit(product.quantity_conversion.from_unit)} = {product.quantity_conversion.factor} {russianUnit(product.quantity_conversion.to_unit)}. Заказ и цена — в {russianUnit(product.quantity_conversion.from_unit)}.</p>}<div className="product-price"><strong>от {formatRub(startingPrice(product).price, 12)}</strong><span>за {itemUnit(product.characteristics)}</span></div><div className="product-order-facts"><div><span>Минимальный заказ</span><b>От {formatUnits(product.moq_units, itemUnit(product.characteristics))}</b></div><div><span>Срок производства</span><b>от {product.lead_time_days} дней</b></div></div>{product.price_tiers.length > 0 && <div className="pricing"><span className="pricing-title">Оптовые цены</span>{product.price_tiers.map((tier) => <div key={tier.min_units}><span>От {formatUnits(tier.min_units, itemUnit(product.characteristics))}</span><b>{formatRub(tier.unit_price_rub, 12)} / {itemUnit(product.characteristics)}</b></div>)}</div>}<Link className="btn btn-primary product-main-action" href="/needs/new">Запросить условия</Link><p className="safe-note">Условия сделки подтверждаются обеими сторонами. Площадка не меняет цену автоматически.</p></section>
    </div>
    <section className="supplier-panel"><div className="supplier-mark">{product.producer.display_name.slice(0, 1)}</div><div><span className="eyebrow">Проверенный производитель</span><h2>{product.producer.display_name}</h2><p>{product.producer.region ?? "География производства уточняется"} · {product.producer.rating ? `★ ${product.producer.rating} · ${product.producer.reviews_count} отзывов` : "Новый поставщик без отзывов"}</p></div><Link className="btn btn-secondary" href={`/producers/${product.producer.company_id}`}>Профиль компании</Link></section>
    <div className="product-info-grid"><section className="card"><span className="eyebrow">Получение партии</span><h2>Доставка и ответственность</h2><p>Вес и объём фиксируются в сделке. Покупатель выбирает самовывоз, своего перевозчика или согласованную доставку продавца. «ПоРукам» помогает оформить процесс, но не оказывает транспортные услуги.</p></section><section className="card"><span className="eyebrow">Допуск товара</span><h2>Обязательные доказательства</h2>{admissionLoading ? <p className="hint" role="status">Загружаем требования к товару...</p> : admissionError ? <div className="alert alert-warning" role="alert">Не удалось загрузить сведения о допуске. <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAdmissionRetry(value => value + 1)}>Повторить проверку</button></div> : admission && admission.checklist.length > 0 ? <><p className="hint">Проверено у продавца: {verificationCopy(admission.state_label).toLowerCase()}.</p><ul className="company-list">{admission.checklist.map((item) => <li key={item.code}><div className="company-row"><div><div className="company-item__name">{item.title}</div><div className="company-meta">{item.legal_reference}</div><div className="company-meta">{item.buyer_note}</div>{item.scope_note && <div className="company-meta">Применимость: {item.scope_note}</div>}</div><span className={`badge ${item.state === "satisfied" ? "badge-verified" : "badge-rejected"}`}>{verificationCopy(item.state_label)}</span></div></li>)}</ul>{admission.advisories.map((text) => <p className="hint" key={text}>Уточните у продавца: {verificationCopy(text)}</p>)}<p className="hint">{verificationCopy(admission.note)}</p></> : <p className="hint">{admission?.supported === false ? verificationCopy(admission.summary) : "Для этой категории правила проверки документов ещё не настроены. Проверка компании не подтверждает соответствие товара."}</p>}</section><section className="card"><span className="eyebrow">Цены продавца</span><h2>История цены товара</h2><p className="hint">Последняя опубликованная цена дня для этой карточки с теми же характеристиками и минимальным заказом. Это цены предложений, а не совершённых продаж.</p>{priceLoading ? <p className="hint" role="status">Загружаем историю цен...</p> : priceError ? <div className="alert alert-warning" role="alert">История цен временно недоступна. <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPriceRetry(value => value + 1)}>Повторить загрузку истории</button></div> : index.length ? <div className="price-index">{index.map((point) => <div key={point.date}><span>{formatDate(point.date)}</span><b>{formatRub(point.average_unit_price_rub, 12)}</b><small>{point.offers_count} набл.</small></div>)}</div> : <p className="hint">История появится после изменения цен опубликованных товаров. История справочная и не является прогнозом.</p>}</section></div>
  </div>;
}
