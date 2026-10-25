"use client";
import { useEffect, useRef, useState } from "react";
import { getToken } from "../lib/api";
import { marketplace, DeliveryAddress } from "../lib/marketplace";
import { Icon } from "./Icon";

export function AddressDialog({ companyId, addresses, busy, onSave, onClose }: { companyId: string; addresses: DeliveryAddress[]; busy: boolean; onSave: (value: { address: string; city: string; region: string }) => Promise<boolean>; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [address, setAddress] = useState(""), [city, setCity] = useState(""), [region, setRegion] = useState("");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [lookup, setLookup] = useState("");
  const [suggestions, setSuggestions] = useState<Awaited<ReturnType<typeof marketplace.getAddressSuggestions>>>([]);
  const [lookupError, setLookupError] = useState("");
  const [searching, setSearching] = useState(false);
  useEffect(() => {
    setSuggestions([]); setLookupError("");
    if (lookup.trim().length < 3) { setSearching(false); return; }
    let active = true; setSearching(true);
    const timer = setTimeout(() => {
      const token = getToken(); if (!token) return;
      void marketplace.getAddressSuggestions(token, companyId, lookup).then(items => { if (active) setSuggestions(items); })
        .catch(() => { if (active) setLookupError("Подсказки недоступны. Заполните адрес ниже или проверьте на карте."); })
        .finally(() => { if (active) setSearching(false); });
    }, 400);
    return () => { active = false; clearTimeout(timer); };
  }, [lookup, companyId]);
  useEffect(() => { const el = dialog.current; el?.showModal(); return () => el?.close(); }, []);
  return <dialog ref={dialog} className="address-dialog" onCancel={e => { if (busy) e.preventDefault(); else onClose(); }} onClick={e => { if (e.target === e.currentTarget && !busy) onClose(); }}><div className="address-dialog__body">
    <div className="company-row"><div><p className="hint">Доставка по России</p><h2>Куда доставить заказ?</h2></div><button type="button" className="icon-button" aria-label="Закрыть выбор адреса" disabled={busy} onClick={onClose}><Icon name="close" /></button></div>
    <form onSubmit={async e => { e.preventDefault(); setError(""); if (!/\d/.test(address)) { setError("Укажите номер дома или строения."); return; } if (await onSave({ address: address.trim(), city: city.trim(), region: region.trim() })) onClose(); else setError("Не удалось сохранить адрес. Проверьте права компании и повторите."); }}>
      <div className="field"><label htmlFor="address-lookup">Поиск адреса</label><input id="address-lookup" placeholder="Начните с города и улицы" value={lookup} onChange={e=>setLookup(e.target.value)} maxLength={250} autoComplete="off" /><p className="hint">Для подсказок введённый адрес передаётся в ДаДата. Можно сразу заполнить поля вручную.</p>{searching && <p role="status" className="hint">Ищем адрес…</p>}{lookupError && <p role="status" className="hint">{lookupError}</p>}<div className="address-suggestions">{suggestions.map(item=><button type="button" key={item.label} onClick={()=>{setAddress(item.address);setCity(item.city ?? "");setRegion(item.region ?? "");setSuggestions([]);}}>{item.label}{!item.house && " · уточните дом"}</button>)}</div></div>
      {addresses.length > 0 && <div className="field"><label htmlFor="address-search">Найти среди адресов компании</label><input id="address-search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Город или улица" /><div className="address-suggestions">{addresses.filter(a=>`${a.city} ${a.address}`.toLowerCase().includes(search.toLowerCase())).slice(0,5).map(a=><button type="button" key={a.id} onClick={()=>{setAddress(a.address);setCity(a.city);setRegion(a.region);}}>{a.city}, {a.address}</button>)}</div></div>}
      <div className="need-form-grid"><div className="field"><label htmlFor="address-region">Регион</label><input id="address-region" autoComplete="address-level1" required minLength={2} maxLength={120} value={region} onChange={e=>setRegion(e.target.value)} placeholder="Новосибирская область" /></div><div className="field"><label htmlFor="address-city">Город или населённый пункт</label><input id="address-city" autoComplete="address-level2" required minLength={2} maxLength={120} value={city} onChange={e=>setCity(e.target.value)} placeholder="Новосибирск" /></div></div>
      <div className="field"><label htmlFor="address-street">Улица, дом, строение</label><input id="address-street" autoComplete="street-address" required minLength={5} maxLength={500} value={address} onChange={e=>setAddress(e.target.value)} placeholder="Улица, номер дома и склад" /></div>
      <a className="address-map-link" href={`https://yandex.ru/maps/?text=${encodeURIComponent(["Россия",region,city,address].filter(Boolean).join(", "))}`} target="_blank" rel="noreferrer"><Icon name="search" />Найти и проверить на карте<Icon name="arrow" /></a><p className="hint">Карта откроется в новой вкладке. Проверьте дом и внесите адрес в поля выше.</p>
      {error && <p className="alert alert-error" role="alert">{error}</p>}<div className="actions"><button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить адрес"}</button><button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>Отмена</button></div>
    </form></div></dialog>;
}
