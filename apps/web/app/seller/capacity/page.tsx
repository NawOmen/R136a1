"use client";
import { formatDate } from "../../lib/dates";

// Календарь мощностей (GET/PUT /companies/{id}/capacity).
// Таблица на ближайшие 30 дней для выбранного ресурса и единицы измерения.

import { russianMessage } from "../../lib/russianMessages";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { getToken } from "../../lib/api";
import { ApiError, CapacityEntry, formatUnits, marketplace } from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

const DAYS_COUNT = 30;

function formatDateKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

export default function SellerCapacityPage() {
  const {
    loading,
    error: meError,
    available,
    company,
    companyId,
    setCompanyId,
  } = useCompanySelector("can_sell");

  const dates = useMemo(() => {
    const today = new Date();
    return Array.from({ length: DAYS_COUNT }, (_, index) => formatDateKey(addDays(today, index)));
  }, []);

  const [reserved, setReserved] = useState<Record<string, number>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [allEntries, setAllEntries] = useState<CapacityEntry[]>([]);
  const [scopeCategory, setScopeCategory] = useState("");
  const [scopeUnit, setScopeUnit] = useState("шт");
  const [conversions, setConversions] = useState<NonNullable<CapacityEntry["category_conversions"]>>([]);
  const [conversionApproved, setConversionApproved] = useState(false);
  const [leafOptions, setLeafOptions] = useState<{id:string;label:string;units:string[]}[]>([]);
  const initialScope = useRef("");
  useEffect(() => {
    let active=true;
    marketplace.getCategoryRegistry().then(data => {if(active)setLeafOptions(data.groups.flatMap(group=>group.leaves.filter(leaf=>leaf.admission_state!=="unsupported").map(leaf=>({id:leaf.id,label:group.label+" / "+leaf.label,units:((leaf.technical_profile.passport.units as {allowed: string[]}).allowed)}))));})
      .catch(err=>{if(active)setError(err instanceof Error?russianMessage(err.message):"Не удалось загрузить категории.");});
    return ()=>{active=false;};
  }, []);
  const [loaded, setLoaded] = useState(false);
  const [loadedCompanyId, setLoadedCompanyId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setLoaded(false); setAllEntries([]); setSaved(false);
    setError(null);
    marketplace
      .getCapacity(token, companyId)
      .then((entries) => {
        if (cancelled) return;
        setAllEntries(entries);
        setLoadedCompanyId(companyId);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить мощности.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, dates]);

  useEffect(() => {
    if (!loaded || loadedCompanyId !== companyId || !leafOptions.length || initialScope.current === companyId) return;
    initialScope.current = companyId;
    const query = new URLSearchParams(window.location.search);
    const leaf = leafOptions.find(item => item.id === query.get("category"))
      ?? leafOptions.find(item => allEntries.some(entry => entry.category === item.id)) ?? leafOptions[0];
    const general = allEntries.find(entry => !entry.category);
    if (general) { setScopeCategory(""); setScopeUnit(general.unit); }
    else {
      setScopeCategory(leaf.id);
      const wanted = query.get("unit") ?? allEntries.find(entry => entry.category === leaf.id)?.unit ?? "шт";
      setScopeUnit(leaf.units.includes(wanted) ? wanted : leaf.units[0]);
    }
  }, [loaded, loadedCompanyId, leafOptions, allEntries, companyId]);

  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("company");
    if (wanted && available.some(item => item.id === wanted)) setCompanyId(wanted);
  }, [available]);

  useEffect(() => {
    const scoped = allEntries.filter(entry => entry.category === scopeCategory && entry.unit === scopeUnit);
    setValues(Object.fromEntries(scoped.filter(entry => dates.includes(entry.date)).map(entry => [entry.date, String(entry.available_units)])));
    setConversions(scoped[0]?.category_conversions ?? []); setConversionApproved(false);
    setReserved(Object.fromEntries(scoped.map(entry => [entry.date, entry.reserved_units ?? 0])));
  }, [allEntries, scopeCategory, scopeUnit, dates]);

  async function handleSave() {
    const token = getToken();
    if (!token || !company) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      if (!loaded || loadedCompanyId !== company.id) throw new Error("Дождитесь загрузки календаря выбранной компании.");
      const enteredUnit = scopeUnit.trim().toLowerCase().replace(/\.$/, "");
      const unit = ["штука", "штуки", "штук"].includes(enteredUnit) ? "шт" : enteredUnit;
      if (!unit || unit.length > 32) throw new Error("Укажите единицу измерения до 32 символов.");
      const leaf = leafOptions.find(item => item.id === scopeCategory);
      if (scopeCategory && !leaf) throw new Error("Выберите листовую подкатегорию ресурса.");
      if (leaf && !leaf.units.includes(unit)) throw new Error(`Для этой подкатегории допустимы единицы: ${leaf.units.join(", ")}.`);
      if (!scopeCategory && !conversions.length) throw new Error("Добавьте подкатегорию и коэффициент расхода общего ресурса.");
      const keys = conversions.map(item => `${item.category_id}:${item.order_unit}`);
      if (!scopeCategory && (new Set(keys).size !== keys.length || conversions.some(item =>
        !leafOptions.some(leaf => leaf.id === item.category_id && leaf.units.includes(item.order_unit)) ||
        !Number.isSafeInteger(item.resource_units_per_order_unit) || item.resource_units_per_order_unit < 1)))
        throw new Error("Проверьте подкатегории, единицы и целые положительные коэффициенты без повторов.");
      const entries = dates.filter(date => values[date]?.trim()).map((date) => ({
        date,
        category: scopeCategory,
        unit,
        available_units: Number(values[date] || 0),
        category_conversions: scopeCategory ? [] : conversions, conversions_approved: conversionApproved,
      }));
      if (!entries.length) throw new Error("Укажите мощность хотя бы на один день.");
      for (const entry of entries) {
        const declared = scopeCategory ? [{category_id:scopeCategory,order_unit:unit}] : conversions;
        const overlap = allEntries.some(old => old.date === entry.date && (old.category !== scopeCategory || old.unit !== unit) &&
          ((!old.category_conversions?.length && (!old.category || declared.some(next => next.category_id === old.category && next.order_unit === old.unit))) || (old.category_conversions ?? []).some(prior => declared.some(next => next.category_id === prior.category_id && next.order_unit === prior.order_unit))));
        if (overlap) throw new Error(`На ${formatDate(entry.date)} эта категория уже учитывается другим ресурсом. Выберите существующий ресурс и измените его мощность или коэффициенты.`);
      }
      if (entries.some(entry=>!Number.isSafeInteger(entry.available_units) || entry.available_units < 0)) throw new Error("Укажите целое количество единиц для каждого дня.");
      if(!scopeCategory && conversions.length && !conversionApproved) throw new Error("Проверьте и подтвердите коэффициенты для каждого дня календаря.");
      await marketplace.updateCapacity(token, company.id, entries);
      const updated = await marketplace.getCapacity(token, company.id);
      setScopeUnit(unit);
      setAllEntries(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? russianMessage(err.message) : "Не удалось сохранить мощности.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (meError) {
    return (
      <div>
        <h1 className="page-title">Мощности</h1>
        <div className="alert alert-error">{meError}</div>
        <Link href="/login" className="btn btn-secondary">
          На страницу входа
        </Link>
      </div>
    );
  }

  if (available.length === 0) {
    return (
      <div>
        <h1 className="page-title">Мощности</h1>
        <div className="alert alert-error">
          У вас нет компании с правом «Продаю». Создайте компанию и включите режим продажи.
        </div>
        <div className="actions">
          <Link href="/company/new" className="btn btn-primary">
            Создать компанию
          </Link>
          <Link href="/dashboard" className="btn btn-secondary">
            В личный кабинет
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Мощности</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          В личный кабинет
        </Link>
      </div>
      <p className="subtitle">Мощность производства по категориям и единицам измерения (ближайшие {DAYS_COUNT} дней)</p>

      {available.length > 1 && (
        <div className="field">
          <label htmlFor="seller_company">Компания</label>
          <select id="seller_company" value={companyId} disabled={saving} onChange={(event) => setCompanyId(event.target.value)}>
            {available.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
        </div>
      )}

      {saved && <div className="alert alert-success">Мощности сохранены.</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <div className="form-grid card capacity-settings">
        <div className="field"><label htmlFor="capacity-category">Категория ресурса</label><select id="capacity-category" value={scopeCategory} disabled={saving} onChange={event => { setScopeCategory(event.target.value);
          const leaf = leafOptions.find(item => item.id === event.target.value);
          if (leaf && !leaf.units.includes(scopeUnit)) setScopeUnit(leaf.units[0]);
          setSaved(false); }}><option value="">Общий ресурс с явными коэффициентами</option>{leafOptions.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></div>
        <div className="field"><label htmlFor="capacity-unit">Единица измерения</label>{scopeCategory ? <select id="capacity-unit" value={scopeUnit} disabled={saving} onChange={event => { setScopeUnit(event.target.value); setSaved(false); }}>{leafOptions.find(leaf => leaf.id === scopeCategory)?.units.map(unit => <option key={unit}>{unit}</option>)}</select> : <input id="capacity-unit" type="text" value={scopeUnit} maxLength={32} disabled={saving} onChange={event => { setScopeUnit(event.target.value); setSaved(false); setConversionApproved(false); }} />}</div>
        <p className="hint">Отдельный ресурс — одна подкатегория и единица. Общий — только с подтверждёнными коэффициентами. Каждый день учитывается отдельно, занятое — в единице ресурса.</p>
        <details className="text-details"><summary>Как вводить дробные объёмы</summary><div className="text-details__body"><p>Используйте меньшую единицу хранения: г, мм, см² или мл. Например, 2,5 кг = 2500 г; 0,5 часа ресурса = 30 минут.</p></div></details>
        {!scopeCategory && <div className="field capacity-settings__conversions"><h3>Расход общего ресурса</h3>
          {conversions.map((item,index)=><div key={index}>
            <label>Подкатегория<select aria-label="Подкатегория" value={item.category_id} disabled={saving} onChange={event=>{setConversions(previous=>previous.map((value,i)=>i===index?{...value,category_id:event.target.value,order_unit:leafOptions.find(leaf=>leaf.id===event.target.value)?.units[0] ?? "шт"}:value));setConversionApproved(false);}}><option value="">Выберите</option>{leafOptions.map(leaf=><option key={leaf.id} value={leaf.id}>{leaf.label}</option>)}</select></label>
            <label>Единица заказа<select aria-label="Единица заказа" value={item.order_unit} disabled={saving} onChange={event=>{setConversions(previous=>previous.map((value,i)=>i===index?{...value,order_unit:event.target.value}:value));setConversionApproved(false);}}>{leafOptions.find(leaf=>leaf.id===item.category_id)?.units.map(unit=><option key={unit}>{unit}</option>)}</select></label>
            <label>Расход {scopeUnit} на одну единицу заказа<input type="number" min={1} step={1} value={item.resource_units_per_order_unit} disabled={saving} onChange={event=>{setConversions(previous=>previous.map((value,i)=>i===index?{...value,resource_units_per_order_unit:Number(event.target.value)}:value));setConversionApproved(false);}} /></label>
            <button type="button" className="btn btn-secondary btn-sm" disabled={saving} onClick={()=>{setConversions(previous=>previous.filter((_,i)=>i!==index));setConversionApproved(false);}}>Удалить коэффициент</button>
          </div>)}
          <button type="button" className="btn btn-secondary btn-sm" disabled={saving} onClick={()=>{setConversions(previous=>[...previous,{category_id:leafOptions[0]?.id ?? "",order_unit:leafOptions[0]?.units[0] ?? "шт",resource_units_per_order_unit:1}]);setConversionApproved(false);}}>Добавить категорию</button>
          {!conversions.length && <p className="hint">Для общего ресурса добавьте нужную подкатегорию и единицу заказа, затем укажите расход ресурса и подтвердите коэффициенты.</p>}
          <p className="hint">Коэффициент — сколько единиц общего ресурса нужно на одну единицу заказа. Например, 2 минуты на 1 штуку: ресурс «мин», заказ «шт», коэффициент 2. Расход — целое число в меньшей единице, без округления. Коэффициенты действуют для всех показанных дней; условия прежних резервов сохраняются.</p>
          {!!conversions.length && <label><input type="checkbox" checked={conversionApproved} disabled={saving} onChange={event=>setConversionApproved(event.target.checked)} /> Коэффициенты и дни календаря проверены</label>}
        </div>}
      </div>

      <section className="card">
        {!loaded ? (
          <p className="hint">Загрузка календаря...</p>
        ) : (
          <>
            <div className="comparison-scroll" tabIndex={0} role="region" aria-label="Календарь мощностей, прокрутка по горизонтали">
            <table className="capacity-table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Всего, {scopeUnit}</th><th>Занято, {scopeUnit}</th><th>Свободно, {scopeUnit}</th>
                </tr>
              </thead>
              <tbody>
                {dates.map((date) => (
                  <tr key={date}>
                    <td>{formatDate(date)}</td>
                    <td>
                      <input
                        type="number"
                        min={reserved[date] ?? 0}
                        step="1"
                        aria-label={`Общая мощность на ${formatDate(date)}`}
                        value={values[date] ?? ""}
                        placeholder="0"
                        onChange={(event) =>
                          { setValues((current) => ({ ...current, [date]: event.target.value })); setSaved(false); }
                        }
                      />
                    </td><td>{reserved[date] ?? 0}</td><td>{Math.max(0, Number(values[date] || 0) - (reserved[date] ?? 0))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            <p className="hint mode-hint">
              Сохраняются только заполненные дни. Чтобы закрыть доступный объём, укажите 0. Например, {formatUnits(4800, scopeUnit)} — объём выбранного ресурса в этот день. Занятый объём включает заказы, удержания и уже выполненную работу. Уменьшить мощность ниже занятого объёма нельзя.
            </p>
            <div className="actions">
              <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void handleSave()}>
                {saving ? "Сохраняем..." : "Сохранить"}
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
