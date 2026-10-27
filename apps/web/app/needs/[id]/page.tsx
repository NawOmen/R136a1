"use client";
import { Icon } from "../../components/Icon";
import { formatDate } from "../../lib/dates";
import { russianMessage } from "../../lib/russianMessages";
import CommercialEstimate from "../../components/CommercialEstimate";

// Деталь потребности: характеристики, файлы, список предложений.
// Покупатель может выбрать предложение (POST /offers/{id}/select) —
// создаётся сделка, потребность переходит в статус matched.

import Link from "next/link";
import ProfileRevisionPanel from "../../components/ProfileRevisionPanel";
import NeedDraftEditor from "../../components/NeedDraftEditor";
import NeedRequirements from "../../components/NeedRequirements";
import SupplierBoard from "../../components/SupplierBoard";
import OrderExport from "../../components/OrderExport";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import {
  ApiError,
  Deal,
  DeliveryAddress,
  DEAL_STATUS_LABELS,
  formatCharacteristics,
  formatRub,
  formatUnits,
  itemUnit,
  marketplace,
  Need,
  NeedFeedItem,
  NEED_STATUS_LABELS,
  NEED_VISIBILITY_LABELS,
  Offer,
  OFFER_STATUS_LABELS,
  OptimizationVariant,
} from "../../lib/marketplace";
import { useMe } from "../../lib/useMe";

export default function NeedDetailPage() {
  const params = useParams();
  const needId = typeof params.id === "string" ? params.id : "";
  const me = useMe();

  const [need, setNeed] = useState<Need | NeedFeedItem | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [deal, setDeal] = useState<Deal | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadRetry, setLoadRetry] = useState(0);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectingId, setSelectingId] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [variants, setVariants] = useState<OptimizationVariant[]>([]);
  const [preparingResilience, setPreparingResilience] = useState<string | null>(null);
  const [addresses, setAddresses] = useState<DeliveryAddress[]>([]);
  const [addressError, setAddressError] = useState(false);
  const [addressRetry, setAddressRetry] = useState(0);
  const [addressLoading, setAddressLoading] = useState(true);
  const ownedNeed = need && "company_id" in need ? need : null;
  const buyerCompany = me.companies.find((company) => company.id === ownedNeed?.company_id);
  const isBuyer = buyerCompany?.membership?.can_buy === true;

  useEffect(() => {
    const token = getToken();
    let active = true;
    setAddresses([]); setAddressError(false); setAddressLoading(true);
    if (token && isBuyer && ownedNeed) void marketplace.getAddresses(token, ownedNeed.company_id)
      .then(items => { if (active) setAddresses(items); })
      .catch(() => { if (active) setAddressError(true); })
      .finally(() => { if (active) setAddressLoading(false); });
    return () => { active = false; };
  }, [ownedNeed?.company_id, isBuyer, addressRetry]);

  useEffect(() => {
    const token = getToken();
    if (!token || !needId) return;
    let cancelled = false;
    setLoading(true); setError(null); setNotFound(false);
    setNeed(null); setOffers([]); setDeal(null); setVariants([]);
    Promise.all([marketplace.getNeed(token, needId), marketplace.getOffers(token, needId)])
      .then(([needData, offersData]) => {
        if (cancelled) return;
        setNeed(needData);
        setOffers(offersData);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить потребность.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [needId, loadRetry]);

  async function handleSelect(offer: Offer) {
    const token = getToken();
    if (!token || !need) return;
    if (
      !window.confirm(
        "Выбрать это предложение и заключить сделку? Остальные предложения будут отклонены.",
      )
    ) {
      return;
    }
    setSelectingId(offer.id);
    setError(null);
    // Стабильный ключ на ревизию КП: повтор после потерянного ответа
    // возвращает ту же сделку, а не новую.
    const storageKey = `offer-select-${offer.id}-v${offer.revision}`;
    let requestKey = window.sessionStorage.getItem(storageKey);
    if (!requestKey) {
      requestKey = crypto.randomUUID();
      window.sessionStorage.setItem(storageKey, requestKey);
    }
    try {
      const created = await marketplace.selectOffer(token, offer.id, offer.revision, requestKey);
      setDeal(created);
      const [needData, offersData] = await Promise.all([
        marketplace.getNeed(token, need.id),
        marketplace.getOffers(token, need.id),
      ]);
      setNeed(needData);
      setOffers(offersData);
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось выбрать предложение.");
    } finally {
      setSelectingId(null);
    }
  }

  async function handleDownload(fileId: string, fileName: string) {
    const token = getToken();
    if (!token) return;
    setDownloadingId(fileId);
    setError(null);
    try {
      const blob = await marketplace.downloadNeedFile(token, fileId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = fileName;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось скачать файл.");
    } finally {
      setDownloadingId(null);
    }
  }

  async function handlePublish() {
    const token = getToken();
    if (!token || !need) return;
    if (!window.confirm("Опубликовать потребность для производителей?")) return;
    setPublishing(true);
    setError(null);
    try {
      setNeed(await marketplace.publishNeed(token, need.id));
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось опубликовать потребность.");
    } finally {
      setPublishing(false);
    }
  }

  async function handleOptimize() {
    const token = getToken();
    if (!token || !need) return;
    setOptimizing(true);
    setError(null);
    try {
      setVariants(await marketplace.optimizeNeed(token, need.id));
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось рассчитать варианты.");
    } finally {
      setOptimizing(false);
    }
  }

  async function handlePrepareResilience(variant: OptimizationVariant) {
    const token = getToken();
    if (!token || !need) return;
    const priceThreshold = window.prompt("Допустимое увеличение цены, %:", "5");
    const delayThreshold = window.prompt("Допустимое увеличение срока, дней:", "2");
    if (priceThreshold === null || delayThreshold === null) return;
    const price = Number(priceThreshold);
    const delay = Number(delayThreshold);
    if (!Number.isFinite(price) || price < 0 || !Number.isInteger(delay) || delay < 0) {
      setError("Пороги должны быть неотрицательными числами, срок — целым числом дней.");
      return;
    }
    const autoReplace = window.confirm(
      "Разрешить автоматическую замену только после подтверждения резервов и только внутри этих порогов?",
    );
    setPreparingResilience(variant.id);
    setError(null);
    try {
      await marketplace.createResiliencePlan(token, need.id, variant.id, price, delay, autoReplace);
      window.location.href = "/resilience";
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось подготовить план устойчивости.");
    } finally {
      setPreparingResilience(null);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (error && !need) return <div><h1 className="page-title">Не удалось загрузить потребность</h1><div className="alert alert-error" role="alert">{error}</div><button type="button" className="btn btn-secondary" onClick={() => setLoadRetry(value => value + 1)}>Повторить загрузку</button></div>;

  if (notFound || !need) {
    return (
      <div>
        <h1 className="page-title">Потребность не найдена</h1>
        <Link href="/needs" className="btn btn-secondary">
          Мои потребности
        </Link>
      </div>
    );
  }

  const deliveryAddress = addresses.find(item => item.id === ownedNeed?.delivery_address_id);

  return (
    <div>
      <div className="need-heading">
        <h1 className="page-title">{need.category}</h1>
        {need.subcategory && <p className="hint">Подкатегория: {need.subcategory}</p>}
        <div className="actions">
          <span className={`badge badge-${need.status}`}>{NEED_STATUS_LABELS[need.status]}</span>
          <span className={`badge badge-${need.visibility}`}>{NEED_VISIBILITY_LABELS[need.visibility]}</span>
          <Link href="/needs" className="btn btn-secondary btn-sm">
            Мои потребности
          </Link>
          {isBuyer && ownedNeed && <OrderExport id={need.id} companyId={ownedNeed.company_id} specification />}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <section className="card need-summary" aria-label="Основное о закупке">
        <dl className="need-summary__facts">
          <div><dt>Количество</dt><dd>{formatUnits(need.volume_units, itemUnit(need.characteristics))}</dd></div>
          <div><dt>Бюджет</dt><dd>{ownedNeed ? formatRub(ownedNeed.budget_rub) : "Доступен покупателю"}</dd></div>
          <div><dt>Получить до</dt><dd>{formatDate(need.deadline_date)}</dd></div>
          <div><dt>Актуальна до</dt><dd>{formatDate(need.valid_until)}</dd></div>
        </dl>
        {isBuyer && ownedNeed && <p className="need-summary__address"><strong>Доставка: </strong>{deliveryAddress ? `${deliveryAddress.city}, ${deliveryAddress.address}` : addressLoading ? "Загружаем адрес…" : addressError ? "Не удалось загрузить адрес." : ownedNeed.delivery_address_id ? "Адрес не найден в адресах компании." : "Адрес не указан."}{addressError && <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAddressRetry(value => value + 1)}>Повторить</button>}</p>}
      </section>

      {ownedNeed?.no_match_reason && (
        <section className="need-match-note"><Icon name="search" size={24} /><div><h2>Подбираем подходящее производство</h2><p>{ownedNeed.no_match_reason}</p><Link href="/catalog">Посмотреть товары в каталоге →</Link></div></section>
      )}

      {ownedNeed?.matching_warnings?.map(warning => <p className="alert alert-warning" role="status" key={warning}>{warning}</p>)}

      {!isBuyer && !!need.requirement_decisions?.length && <section className="card"><h2>Уточнения покупателя</h2><p>В текущей версии покупатель разрешил противоречия в этих требованиях:</p>{need.requirement_decisions.map(item => <p key={item.field}>{formatCharacteristics({ [item.field]: item.confirmed_value }, need.category_profile)}</p>)}</section>}
      {isBuyer && ownedNeed && <details className="card need-disclosure"><summary>Требования, источники и история</summary><NeedRequirements key={`${need.id}:${need.revision}`} need={ownedNeed} addresses={addresses} /></details>}
      {isBuyer && ownedNeed && buyerCompany?.membership?.is_admin && ["open_for_offers", "waiting_for_match", "coalition_candidate", "awaiting_approvals"].includes(need.status) && (
        <details className="card need-disclosure"><summary>Изменить требования</summary><NeedDraftEditor key={`${need.id}:${need.revision}`} need={ownedNeed} onSaved={async value => { setNeed(value); const token = getToken(); if (token) setOffers(await marketplace.getOffers(token, value.id)); }} /></details>
      )}
      {isBuyer && ownedNeed && need.status === "draft" && (
        <section className="card">
          <h2>Черновик потребности</h2>
          {ownedNeed && buyerCompany?.membership?.is_admin && <NeedDraftEditor key={`${need.id}:${need.revision}`} need={ownedNeed} onSaved={setNeed} />}
          {ownedNeed && buyerCompany?.membership?.is_admin && <ProfileRevisionPanel kind="needs" id={need.id} revision={need.revision} draft={need.status === "draft"} onAdopted={async () => { const token = getToken(); if (token) setNeed(await marketplace.getNeed(token, need.id)); }} />}
          {buyerCompany?.verification_status === "verified" ? (
            <div className="actions">
              <button
                type="button"
                className="btn btn-success"
                disabled={publishing}
                onClick={() => void handlePublish()}
              >
                {publishing ? "Публикуем..." : "Опубликовать"}
              </button>
            </div>
          ) : (
            <p className="hint mode-hint">
              Черновик сохранён. Публикация станет доступна после проверки компании.
            </p>
          )}
        </section>
      )}

      {isBuyer && need.status === "matched" && !deal && <section className="card"><h2>Предложение выбрано</h2><p className="hint">Продолжите согласование получения и исполнение в заказах.</p><Link href="/deals" prefetch={false} className="btn btn-primary">Перейти к заказам</Link></section>}

      {deal && (
        <section className="card">
          <div className="company-row">
            <h2>Сделка заключена</h2>
            <span className="badge badge-created">{DEAL_STATUS_LABELS[deal.status]}</span>
          </div>
          <p className="hint mode-hint">
            Объём: {formatUnits(deal.units, itemUnit(need?.characteristics))} · Сумма: {formatRub(deal.total_price_rub)}
          </p>
          <CommercialEstimate value={deal.commercial_snapshot?.estimate} />
          <Link href={`/deals?deal=${deal.id}`} prefetch={false} className="btn btn-primary">Открыть заказ</Link>
        </section>
      )}

      <details className="card need-disclosure">
        <summary>Характеристики и файлы{ownedNeed?.files.length ? ` (${ownedNeed.files.length})` : ""}</summary>
        <dl className="company-details">
          <div>
            <dt>Характеристики</dt>
            <dd>{formatCharacteristics(need.characteristics, need.category_profile)}</dd>
          </div>
        </dl>

        <h2 style={{ marginTop: 8 }}>Файлы</h2>
        {!ownedNeed ? <p className="hint">Вложения доступны только компании-покупателю.</p> : ownedNeed.files.length === 0 ? (
          <p className="hint">Файлов нет.</p>
        ) : (
          <ul className="company-list">
            {ownedNeed.files.map((file) => (
              <li key={file.id} className="company-item">
                <span>
                  <span className="company-item__name">{file.file_name}</span>
                  <span className="company-meta">Прикреплённый файл</span>
                </span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={downloadingId === file.id}
                  onClick={() => void handleDownload(file.id, file.file_name)}
                >
                  {downloadingId === file.id ? "Скачиваем..." : "Скачать"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </details>

      <section className="card">
        <div className="company-row">
          <h2>{isBuyer ? "Предложения" : "Ваши предложения"} ({offers.length})</h2>
          {isBuyer && offers.length > 0 && need.status !== "matched" && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={optimizing}
              onClick={() => void handleOptimize()}
            >
              {optimizing ? "Считаем..." : "Рассчитать доступные варианты"}
            </button>
          )}
        </div>
        {offers.length === 0 ? (
          <p className="hint mode-hint">{isBuyer ? "Предложений пока нет." : "Вы ещё не отправляли предложения по этой потребности."}</p>
        ) : (
          <ul className="company-list">
            {offers.map((offer) => (
              <li key={offer.id} className="card"><CommercialEstimate value={offer.commercial_quote?.estimate} />
                <div className="company-row">
                  <div>
                    <div className="company-item__name">
                      Предложение #{offer.id.slice(0, 8)}
                    </div>
                    <div className="company-meta">
                      КП {offer.id} · Цена: {formatRub(offer.price_rub, 12)} · Объём: {formatUnits(offer.available_units, itemUnit(need.characteristics))} ·
                      минимальный заказ: {formatUnits(offer.moq_units, itemUnit(need.characteristics))} · Логистика: {formatRub(offer.delivery_cost_rub)} ·
                      Срок: {offer.lead_time_days} дн. · Действует до: {formatDate(offer.valid_until, "не ограничено")}
                    </div>
                  </div>
                  <span className={`badge badge-${offer.status}`}>
                    {OFFER_STATUS_LABELS[offer.status]}
                  </span>
                </div>
                {isBuyer &&
                  ["open_for_offers", "waiting_for_match", "coalition_candidate"].includes(
                    need.status,
                  ) &&
                  offer.status === "sent" && (
                  <div className="actions">
                    <button
                      type="button"
                      className="btn btn-success btn-sm"
                      disabled={selectingId === offer.id || !offer.commercial_quote?.estimate.complete}
                      onClick={() => void handleSelect(offer)}
                    >
                      {selectingId === offer.id ? "Заключаем сделку..." : "Выбрать предложение"}
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {isBuyer && ownedNeed && <SupplierBoard key={`${need.id}:${ownedNeed.company_id}`} needId={need.id} companyId={ownedNeed.company_id} needRevision={need.revision} canManage={buyerCompany?.membership?.is_admin === true} />}

      {variants.length > 0 && (
        <section className="card">
          <h2>Варианты закупки</h2>
          <p className="hint mode-hint">
            Объём распределяется программным расчётом, без решений ИИ.
          </p>
          <div className="market-grid">
            {variants.map((variant) => (
              <article className="card" key={variant.id}>
                <div className="company-row">
                  <strong>{variant.result.title}</strong>
                  <span className={`badge ${variant.result.feasible ? "badge-verified" : "badge-rejected"}`}>
                    {variant.result.feasible ? "Выполнимо" : "Нет варианта"}
                  </span>
                </div>
                {variant.result.comparison_basis && <p className="hint">{variant.result.comparison_basis.tax_basis === "no_vat" ? "Без НДС" : `Включая НДС ${variant.result.comparison_basis.vat_rate_pct}%`} · {variant.result.comparison_basis.delivery_method === "self_pickup" ? "Самовывоз" : "Доставка"}: {variant.result.comparison_basis.delivery_conditions}. Сравнение выполняется внутри этих условий.</p>}
                {variant.result.feasible ? (
                  <>
                    <p>
                      {formatUnits(variant.result.total_units, itemUnit(need.characteristics))} · {formatRub(variant.result.total_cost_rub)} ·
                      до {variant.result.max_lead_time_days} дн.
                    </p>
                    <ul className="evidence-list">
                      {variant.result.allocations.map((allocation) => (
                        <li key={allocation.company_id}>
                          Производитель #{allocation.company_id.slice(0, 8)}: {formatUnits(allocation.units, itemUnit(need.characteristics))} ·
                          {formatRub(allocation.total_cost_rub)}
                        </li>
                      ))}
                    </ul>
                    {variant.result.feasible && (
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={preparingResilience === variant.id}
                        onClick={() => void handlePrepareResilience(variant)}
                      >
                        {preparingResilience === variant.id
                          ? "Готовим резерв..."
                          : "Подготовить N-1 / N-2 и резерв"}
                      </button>
                    )}
                  </>
                ) : (
                  <p className="hint">{variant.result.reasons.join(" ")}</p>
                )}
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
