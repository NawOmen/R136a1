"use client";

// Capability Passport (GET/PUT /companies/{id}/capability-passport).
// Массивы вводятся построчно (каждая строка = элемент), size_ranges — min/max.

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import { ApiError, marketplace } from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

function parseLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export default function SellerPassportPage() {
  const {
    loading,
    error: meError,
    available,
    company,
    companyId,
    setCompanyId,
  } = useCompanySelector("can_sell");

  const [technologies, setTechnologies] = useState("");
  const [equipment, setEquipment] = useState("");
  const [materials, setMaterials] = useState("");
  const [sizeMin, setSizeMin] = useState("");
  const [sizeMax, setSizeMax] = useState("");
  const [tolerances, setTolerances] = useState("");
  const [certifications, setCertifications] = useState("");
  const [minOrder, setMinOrder] = useState("");
  const [maxOrder, setMaxOrder] = useState("");
  const [deliveryRegions, setDeliveryRegions] = useState("");
  const [completedOrderTypes, setCompletedOrderTypes] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setLoaded(false);
    setError(null);
    marketplace
      .getCapabilityPassport(token, companyId)
      .then((passport) => {
        if (cancelled) return;
        setTechnologies(passport.technologies.join("\n"));
        setEquipment(passport.equipment.join("\n"));
        setMaterials(passport.materials.join("\n"));
        setTolerances(passport.tolerances ?? "");
        setCertifications(passport.certifications.join("\n"));
        setMinOrder(passport.min_order_units ? String(passport.min_order_units) : "");
        setMaxOrder(passport.max_order_units ? String(passport.max_order_units) : "");
        setDeliveryRegions(passport.delivery_regions.join("\n"));
        setCompletedOrderTypes(passport.completed_order_types.join("\n"));
        const firstRange = Object.entries(passport.size_ranges ?? {})[0];
        if (firstRange) {
          setSizeMin(String(firstRange[1][0]));
          setSizeMax(String(firstRange[1][1]));
        } else {
          setSizeMin("");
          setSizeMax("");
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          // Паспорт ещё не заполнен — оставляем пустую форму
        } else {
          setError(err instanceof ApiError ? err.message : "Не удалось загрузить паспорт.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company) return;

    const sizeRanges: Record<string, [number, number]> = {};
    const min = Number(sizeMin);
    const max = Number(sizeMax);
    if (sizeMin !== "" && sizeMax !== "" && !Number.isNaN(min) && !Number.isNaN(max)) {
      sizeRanges.cup_volume_ml = [min, max];
    }

    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await marketplace.updateCapabilityPassport(token, company.id, {
        technologies: parseLines(technologies),
        equipment: parseLines(equipment),
        materials: parseLines(materials),
        size_ranges: sizeRanges,
        tolerances: tolerances.trim(),
        certifications: parseLines(certifications),
        min_order_units: Number(minOrder) || 0,
        max_order_units: Number(maxOrder) || 0,
        delivery_regions: parseLines(deliveryRegions),
        completed_order_types: parseLines(completedOrderTypes),
      });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить паспорт.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (meError) {
    return (
      <div>
        <h1 className="page-title">Паспорт возможностей</h1>
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
        <h1 className="page-title">Паспорт возможностей</h1>
        <div className="alert alert-error">
          У вас нет компании с правом «Продаю». Создайте компанию и включите режим продажи.
        </div>
        <div className="actions">
          <Link href="/company/new" className="btn btn-primary">
            Создать компанию
          </Link>
          <Link href="/dashboard" className="btn btn-secondary">
            На главную
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Паспорт возможностей</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          На главную
        </Link>
      </div>
      <p className="subtitle">Возможности производства: технологии, оборудование, материалы</p>

      {available.length > 1 && (
        <div className="field">
          <label htmlFor="seller_company">Компания</label>
          <select id="seller_company" value={companyId} onChange={(event) => setCompanyId(event.target.value)}>
            {available.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
        </div>
      )}

      {saved && <div className="alert alert-success">Паспорт сохранён.</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {!loaded ? (
        <p className="hint">Загрузка паспорта...</p>
      ) : (
        <form className="card" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="technologies">
              Технологии<span className="opt">каждая строка — одна технология</span>
            </label>
            <textarea
              id="technologies"
              value={technologies}
              onChange={(event) => setTechnologies(event.target.value)}
              placeholder={"высечка бумажных стаканов"}
            />
          </div>
          <div className="field">
            <label htmlFor="equipment">
              Оборудование<span className="opt">каждая строка — единица</span>
            </label>
            <textarea
              id="equipment"
              value={equipment}
              onChange={(event) => setEquipment(event.target.value)}
              placeholder={"высекальный пресс"}
            />
          </div>
          <div className="field">
            <label htmlFor="materials">
              Материалы<span className="opt">каждая строка — материал</span>
            </label>
            <textarea
              id="materials"
              value={materials}
              onChange={(event) => setMaterials(event.target.value)}
              placeholder={"крафт-картон 260–320 г/м²"}
            />
          </div>
          <div className="char-row">
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="size_min">
                Размер: минимум, мл<span className="opt">например, 150</span>
              </label>
              <input
                id="size_min"
                type="number"
                min="0"
                value={sizeMin}
                onChange={(event) => setSizeMin(event.target.value)}
              />
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="size_max">
                Размер: максимум, мл<span className="opt">например, 600</span>
              </label>
              <input
                id="size_max"
                type="number"
                min="0"
                value={sizeMax}
                onChange={(event) => setSizeMax(event.target.value)}
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="tolerances">
              Допуски<span className="opt">необязательно</span>
            </label>
            <input
              id="tolerances"
              type="text"
              value={tolerances}
              onChange={(event) => setTolerances(event.target.value)}
              placeholder="Например, ±0,5 мм"
            />
          </div>
          <div className="field">
            <label htmlFor="certifications">
              Сертификации<span className="opt">каждая строка — документ</span>
            </label>
            <textarea
              id="certifications"
              value={certifications}
              onChange={(event) => setCertifications(event.target.value)}
              placeholder={"ТР ТС 005/2011"}
            />
          </div>
          <div className="char-row">
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="min_order">
                Минимальный заказ, шт.<span className="req">*</span>
              </label>
              <input
                id="min_order"
                type="number"
                min="0"
                value={minOrder}
                onChange={(event) => setMinOrder(event.target.value)}
                placeholder="Например, 20000"
                required
              />
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="max_order">
                Максимальный заказ, шт.<span className="req">*</span>
              </label>
              <input
                id="max_order"
                type="number"
                min="0"
                value={maxOrder}
                onChange={(event) => setMaxOrder(event.target.value)}
                placeholder="Например, 48000"
                required
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="delivery_regions">
              Регионы доставки<span className="opt">каждая строка — регион</span>
            </label>
            <textarea
              id="delivery_regions"
              value={deliveryRegions}
              onChange={(event) => setDeliveryRegions(event.target.value)}
              placeholder={"Центральный ФО"}
            />
          </div>
          <div className="field">
            <label htmlFor="completed_order_types">
              Типы выполненных заказов<span className="opt">каждая строка — тип</span>
            </label>
            <textarea
              id="completed_order_types"
              value={completedOrderTypes}
              onChange={(event) => setCompletedOrderTypes(event.target.value)}
              placeholder={"стаканы 300–450 мл"}
            />
          </div>
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Сохраняем..." : "Сохранить паспорт"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
