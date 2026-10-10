"use client";

import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { MarketWatch, marketplace, PRODUCT_CATEGORIES } from "../lib/marketplace";

export default function SettingsPage() {
  const [theme,setTheme]=useState<"light"|"dark">("light");
  const [category,setCategory]=useState(PRODUCT_CATEGORIES[0]);
  const [watches,setWatches]=useState<MarketWatch[]>([]);
  const [error,setError]=useState<string|null>(null);
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [removingId,setRemovingId]=useState<string|null>(null);

  async function load() {
    const token=getToken();
    if(!token){setLoading(false);return;}
    setLoading(true);setError(null);
    try{setWatches(await marketplace.getMarketWatches(token));}
    catch(e){setError(e instanceof Error?e.message:"Не удалось загрузить подписки.");}
    finally{setLoading(false);}
  }

  useEffect(()=>{
    const saved=window.localStorage.getItem("porukam-theme")==="dark"?"dark":"light";
    setTheme(saved);
    void load();
  },[]);

  function changeTheme(value:"light"|"dark"){setTheme(value);document.documentElement.dataset.theme=value;window.localStorage.setItem("porukam-theme",value);}

  async function addWatch(){
    const token=getToken();if(!token)return;
    setSaving(true);setError(null);
    try{await marketplace.createMarketWatch(token,category);setWatches(await marketplace.getMarketWatches(token));}
    catch(e){setError(e instanceof Error?e.message:"Не удалось сохранить подписку.");}
    finally{setSaving(false);}
  }

  async function removeWatch(id:string){
    const token=getToken();if(!token)return;
    setRemovingId(id);setError(null);
    try{await marketplace.deleteMarketWatch(token,id);setWatches((current)=>current.filter((item)=>item.id!==id));}
    catch(e){setError(e instanceof Error?e.message:"Не удалось отключить подписку.");}
    finally{setRemovingId(null);}
  }

  return <div><h1>Настройки</h1>{error&&<div className="alert alert-error" role="alert">{error} <button type="button" className="btn btn-secondary btn-sm" onClick={()=>void load()}>Повторить загрузку</button></div>}<section className="card"><h2>Интерфейс</h2><div className="theme-choice"><button className={theme==="light"?"active":""} onClick={()=>changeTheme("light")}>☀ Светлая</button><button className={theme==="dark"?"active":""} onClick={()=>changeTheme("dark")}>☾ Тёмная</button></div><p className="hint">Язык интерфейса: русский.</p></section><section className="card"><h2>Изменения рынка</h2><p>Получайте уведомления, когда меняется спрос или предложение в выбранной категории.</p><div className="company-row"><select aria-label="Категория для подписки" value={category} onChange={(e)=>setCategory(e.target.value)}>{PRODUCT_CATEGORIES.map((item)=><option key={item}>{item}</option>)}</select><button className="btn btn-primary btn-sm" disabled={saving||watches.some((item)=>item.category===category)} onClick={()=>void addWatch()}>{saving?"Сохраняем...":"Следить"}</button></div>{loading?<p className="hint">Загружаем подписки...</p>:<ul className="company-list">{watches.map((watch)=><li className="company-row" key={watch.id}><span>{watch.category}</span><button className="btn btn-secondary btn-sm" disabled={removingId===watch.id} onClick={()=>void removeWatch(watch.id)}>{removingId===watch.id?"Отключаем...":"Отключить"}</button></li>)}</ul>}</section><section className="card"><h2>Двухфакторная аутентификация</h2><div className="alert alert-warning">Пока недоступна</div><p>Вход выполняется по паролю. Используйте отдельный сложный пароль и не передавайте его другим людям.</p></section></div>;
}
