"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, AUTH_CHANGED_EVENT, getToken, MeResponse } from "./lib/api";

const purchases = [["Бумажные стаканы 400 мл", "55 000 шт.", "Москва"], ["Гофрокороба для доставки", "12 000 шт.", "Казань"], ["ПЭТ-бутылки 1 л", "28 000 шт.", "Тула"]];

export default function HomePage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const sync = () => { const token = getToken(); if (!token) { setMe(null); setReady(true); return; } void api.me(token).then(setMe).catch(() => setMe(null)).finally(() => setReady(true)); };
    sync(); window.addEventListener(AUTH_CHANGED_EVENT, sync); return () => window.removeEventListener(AUTH_CHANGED_EVENT, sync);
  }, []);

  if (!ready) return <p className="hint">Загрузка рабочего пространства...</p>;

  if (me) {
    const company = me.companies[0];
    return <div className="landing"><section className="hero authenticated-hero"><span className="eyebrow">Рабочее пространство</span><h1>Здравствуйте, {me.user.first_name}. Что закупаем сегодня?</h1><p>{company ? `Работаем от компании «${company.display_name}».` : "Создайте компанию, чтобы публиковать потребности и предложения."} Следующий шаг всегда под вашим контролем.</p><div className="actions"><Link href={company ? "/needs/new" : "/company/new"} className="btn btn-primary">{company ? "Создать потребность" : "Создать компанию"}</Link><Link href="/catalog" className="btn btn-secondary">Найти готовый товар</Link></div></section>
      <section className="journey-grid"><Link className="journey-card" href="/needs"><span>01</span><b>Повторить прошлую закупку</b><small>Создать черновик из сохранённой потребности</small></Link><Link className="journey-card" href="/notifications"><span>02</span><b>Проверить новые варианты</b><small>Изменения спроса, предложения и коалиций</small></Link><Link className="journey-card" href="/deals"><span>03</span><b>Продолжить сделку</b><small>Переписка, доставка и контрольные точки</small></Link></section>
      <section className="promo"><div><span className="eyebrow">Ваш следующий шаг</span><h2>Опишите задачу голосом или текстом</h2><p>Помощник соберёт требования и покажет, почему подходят найденные производители.</p></div><Link href="/needs/new" className="btn btn-primary">Начать закупку</Link></section></div>;
  }

  return <div className="landing"><section className="hero"><span className="eyebrow">Российский B2B-маркетплейс</span><h1>Закупка, в которой спрос сам находит производство</h1><p>ПоРукам превращает запрос компании в карточку потребности, находит производителей и объединяет совместимые объёмы только при подтверждённой выгоде.</p><div className="actions"><Link href="/register" className="btn btn-primary">Начать бесплатно</Link><Link href="/catalog" className="btn btn-secondary">Смотреть товары</Link></div></section>
    <section className="landing-grid"><article className="feature"><b>Малый опт становится доступнее</b><p>Кофейням не нужно в одиночку покупать партию, рассчитанную на крупную сеть.</p></article><article className="feature"><b>Производитель видит реальный спрос</b><p>Открытые потребности помогают загрузить свободные мощности.</p></article><article className="feature"><b>Человек сохраняет контроль</b><p>ИИ готовит варианты, но цена, резерв и сделка меняются только после подтверждения.</p></article></section>
    <section className="card"><div className="company-row"><div><h2>Недавние покупки</h2><p className="hint">Синтетические данные демонстрационного контура</p></div><Link href="/catalog">Весь каталог →</Link></div><div className="purchase-grid">{purchases.map(([name, volume, city]) => <article key={name}><b>{name}</b><span>{volume}</span><small>{city}</small></article>)}</div></section>
    <section className="promo"><div><span className="eyebrow">Выгодное предложение</span><h2>Объедините 5 000 стаканов с другими покупателями</h2><p>Демосценарий достигает минимальной партии 50 000 шт. с расчётом логистики и требований.</p></div><Link href="/ai-procurement" className="btn btn-primary">Как работают ИИ-агенты</Link></section></div>;
}
