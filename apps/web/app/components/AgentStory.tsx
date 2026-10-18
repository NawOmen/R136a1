"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import styles from "./AgentStory.module.css";

const AgentWorld = dynamic(() => import("./AgentWorld"), { ssr: false });

const chapters = [
  { name: "Разрыв", title: "Производство есть. Спрос есть. Нужна связь.", text: "У производителя — возможности. У покупателя — задача. ПоРукам помогает им встретиться.", state: "Поиск", detail: "Возможности и запрос ещё не сопоставлены." },
  { name: "Подбор", title: "Два бизнеса. Один понятный запрос.", text: "ИИ разбирает требования покупателя и сопоставляет их с предложениями производителей.", state: "Сканирование", detail: "Материал, объём и сроки учитываются при подборе." },
  { name: "Согласование", title: "ИИ готовит. Стороны решают.", text: "Сравните условия и уточните детали. Обязательства возникают только после вашего подтверждения.", state: "Координация", detail: "При изменении условий потребуется повторная проверка." },
  { name: "Сотрудничество", title: "От отдельного запроса — к общей работе.", text: "Товары, производство и совместные закупки — в одном пространстве.", state: "Связь", detail: "Запрос → подбор → согласование сторонами." },
];

function Building({ office = false }: { office?: boolean }) {
  return <div className={`${styles.building} ${office ? styles.office : styles.factory}`}>
    <div className={styles.front}>{office ? <><span className={styles.windows}>▦ ▦<br />▦ ▦</span><span className={styles.door} /></> : <><span className={styles.gear}>⚙</span><span className={styles.gear}>⚙</span><div className={styles.belt}><i /><i /><i /></div></>}</div>
    <div className={styles.side} /><div className={styles.roof} />
    {!office && <div className={styles.chimney} />}
  </div>;
}

export function AgentStory() {
  const root = useRef<HTMLDivElement>(null);
  const scene = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(true);
  const [failed3D, setFailed3D] = useState(false);
  const [ready3D, setReady3D] = useState(false);
  const [interactive, setInteractive] = useState(false);
  const [chapter, setChapter] = useState(0);
  const [staticView, setStaticView] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [insight, setInsight] = useState<"factory" | "buyer" | "agent" | null>(null);

  useEffect(() => {
    setInteractive(true);
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(media.matches);
    sync(); media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (staticView || reduced) return;
    const sections = root.current?.querySelectorAll<HTMLElement>("[data-chapter]");
    if (!sections) return;
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) if (entry.isIntersecting) setChapter(Number((entry.target as HTMLElement).dataset.chapter));
    }, { rootMargin: window.matchMedia("(max-width: 650px)").matches ? "-65% 0px -5% 0px" : "-25% 0px -45% 0px", threshold: 0 });
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [staticView, reduced]);

  useEffect(() => {
    const element = scene.current;
    if (!element) return;
    let visible = false;
    const sync = () => setPaused(!visible || document.hidden);
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; sync(); });
    observer.observe(element);
    document.addEventListener("visibilitychange", sync);
    return () => { observer.disconnect(); document.removeEventListener("visibilitychange", sync); };
  }, []);

  const still = !interactive || staticView || reduced;
  const step = still ? 3 : chapter;
  const selectChapter = (index: number) => {
    setChapter(index);
    document.getElementById(`story-chapter-${index}`)?.scrollIntoView({ behavior: reduced ? "instant" : "smooth", block: "center" });
  };

  return <div ref={root} className={styles.story} data-still={still}>
    <header className={styles.intro}><span className="eyebrow">Как работает ПоРукам</span><h1>Между спросом<br />и производством — <em>связь.</em></h1><div className={styles.introBottom}><p>ИИ помогает найти друг друга.<br />Решение остаётся за компаниями.</p><Link href="/catalog" className="btn btn-secondary">Сразу в каталог →</Link></div></header>
    <div className={styles.toolbar}><span>История взаимодействия</span><button type="button" aria-pressed={staticView || reduced} disabled={reduced} onClick={() => setStaticView(!staticView)}>{reduced ? "Движение уменьшено в настройках" : staticView ? "Включить анимацию" : "Без анимации"}</button></div>
    <div className={styles.journey}>
      <div ref={scene} className={styles.visual} data-stage={step} data-paused={paused}>
        <div className={styles.horizon} aria-hidden="true" /><div className={styles.grid} aria-hidden="true" />
        <span className={styles.sceneCaption}>ПРОИЗВОДИТЕЛЬ ↔ ПОКУПАТЕЛЬ</span>
        <div className={styles.world} aria-hidden="true" style={{visibility: ready3D && !still && !failed3D ? "hidden" : "visible"}}>
          <div className={styles.islandLeft}><Building /></div><div className={styles.islandRight}><Building office /></div>
          <div className={styles.bridge}><i /><i /><i /><i /><i /><i /></div>
          <div className={styles.detour} />
          <span className={`${styles.agent} ${styles.central}`}>✧</span><span className={`${styles.agent} ${styles.supply}`}>✧</span><span className={`${styles.agent} ${styles.demand}`}>✧</span>
          <div className={styles.scan} /><div className={styles.satellites}><Building /><Building office /><Building /></div>
        </div>
        {!still && !failed3D && <div className={styles.webgl}><AgentWorld stage={step} paused={paused} onFailure={() => setFailed3D(true)} onReady={() => setReady3D(true)} /></div>}
        <button className={`${styles.hotspot} ${styles.factoryLabel}`} type="button" aria-expanded={insight === "factory"} onClick={() => setInsight(insight === "factory" ? null : "factory")}><small>01 / ПРЕДЛОЖЕНИЕ</small>Производитель <span>+</span></button>
        <button className={`${styles.hotspot} ${styles.buyerLabel}`} type="button" aria-expanded={insight === "buyer"} onClick={() => setInsight(insight === "buyer" ? null : "buyer")}><small>02 / ПОТРЕБНОСТЬ</small>Компания-покупатель <span>+</span></button>
        <button className={styles.agentLabel} type="button" aria-expanded={insight === "agent"} onClick={() => setInsight(insight === "agent" ? null : "agent")}>✧ ИИ-агенты · {chapters[step].state}</button>
        {insight && <div className={styles.insight} role="status">{insight === "factory" ? "Товары, параметры и доступные возможности производства." : insight === "buyer" ? "Требования, количество и срок закупки." : "Подготовка запроса и объяснение подбора. Подтверждают условия стороны."}<button type="button" aria-label="Закрыть пояснение" onClick={() => setInsight(null)}>×</button></div>}
        <div className={styles.sceneStatus}><span className={styles.dot} />{chapters[step].detail}</div>
      </div>
      <div className={styles.chapters}>{chapters.map((item, index) => <section key={item.name} id={`story-chapter-${index}`} data-chapter={index} className={styles.chapter}><span className={styles.number}>0{index + 1} / {item.name}</span><h2>{item.title}</h2><p>{item.text}</p>{index === 2 && <span className={styles.approval}>✓ Условия подтверждают обе стороны</span>}{index === 3 && <Link className="btn btn-primary" href="/register">Начать сотрудничество →</Link>}</section>)}</div>
    </div>
    {!still && <nav className={styles.steps} aria-label="Этапы взаимодействия">{chapters.map((item, index) => <button key={item.name} type="button" aria-current={chapter === index ? "step" : undefined} onClick={() => selectChapter(index)}><span>0{index + 1}</span>{" "}{item.name}</button>)}</nav>}
    <section className={styles.outro}><span className="eyebrow">Следующий шаг — ваш</span><h2>Найдите товар.<br />Или расскажите, что нужно.</h2><div className="actions"><Link href="/catalog" className="btn btn-secondary">Открыть каталог</Link><Link href="/register" className="btn btn-primary">Создать запрос →</Link></div><p>Только российские компании. Расчёты в рублях.</p></section>
  </div>;
}
