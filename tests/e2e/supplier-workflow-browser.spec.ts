import { test, expect, type Page } from "@playwright/test";

const buyerId="10000000-0000-4000-8000-000000000001",sellerId="10000000-0000-4000-8000-000000000002",needId="10000000-0000-4000-8000-000000000003",requestId="10000000-0000-4000-8000-000000000004";
const sellerName="ООО «Синтетическая упаковка»";
const buyer={id:buyerId,display_name:"ООО «Синтетический покупатель»",full_name:"ООО «Синтетический покупатель»",country:"RU",legal_form:"ООО",verification_status:"verified",membership:{can_buy:true,can_sell:false,is_admin:true}};
const seller={...buyer,id:sellerId,display_name:sellerName,full_name:sellerName,membership:{can_buy:false,can_sell:true,is_admin:true}};
const need={id:needId,company_id:buyerId,category:"Упаковка и тара",subcategory:"Бумажные стаканы",status:"open_for_offers",visibility:"open_anonymized",revision:1,volume_units:100,budget_rub:"5000.00",deadline_date:"2026-11-20",valid_until:"2026-11-19",delivery_address_id:null,characteristics:{unit:"шт",material:"бумага"},files:[],requirements_evidence:null};
const draftText=`Здравствуйте, ${sellerName}! Просим КП на 100 бумажных стаканов. Укажите цену в рублях, НДС и срок поставки.`;

async function prepare(page: Page, options: {quote?:Record<string,unknown>; empty?:boolean; draftFailure?:boolean; sendFailure?:boolean; closed?:boolean}={}) {
  let row={id:requestId,need_id:needId,need_revision:1,buyer_company_id:buyerId,seller_company_id:sellerId,buyer_name:buyer.display_name,seller_name:sellerName,specification:{category:need.category,subcategory:need.subcategory,characteristics:need.characteristics,quantity:100,unit:"шт",deadline_date:need.deadline_date},status:"sent",revision:1,quoted_price_rub:null as string|null,price_basis:"unknown",lead_time_days:null as number|null,delivery_date:null as string|null,note:"",sent_at:"2026-10-26T01:00:00Z",updated_at:"2026-10-26T01:00:00Z"};
  let rows=options.empty?[]:[row]; const messages: unknown[]=[]; let sendAttempts=0;
  const updates: Record<string,unknown>[]=[];const sends: Record<string,unknown>[]=[];const removedPanelRequests: string[]=[];
  page.on("request",request=>{if(/\/(files|extract-reply)([/?]|$)/.test(new URL(request.url()).pathname))removedPanelRequests.push(request.url());});
  page.on("pageerror",error=>{throw error;});
  await page.addInitScript(()=>localStorage.setItem("token","synthetic-supplier-ui"));
  await page.route("**/api/**",route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname;
    let json:unknown=[];
    if(path.endsWith("/auth/me"))json={user:{id:"synthetic-user",first_name:"Тест",last_name:"Покупатель",account_status:"active"},companies:[buyer,seller]};
    else if(path.endsWith("/next-step"))json={title:"Потребности",description:"",href:"/needs"};
    else if(path.endsWith(`/needs/${needId}`))json={...need,visibility:options.closed?"closed":need.visibility};
    else if(path.endsWith("/needs/mine"))json=[need];
    else if(path.endsWith("/offers"))json=options.quote?[options.quote]:[];
    else if(path.endsWith(`/needs/${needId}/suppliers`))json=[{company_id:sellerId,company_name:sellerName,specialization:[need.category],relevant:true,products:["Бумажный стакан"]}];
    else if(path.endsWith("/suppliers"))json=[{company_id:sellerId,company_name:sellerName,specialization:[need.category],relevant:true,products:["Бумажный стакан"]}];
    else if(path.endsWith("/specification.csv"))return route.fulfill({contentType:"text/csv",headers:{"Content-Disposition":"attachment; filename=spec.csv"},body:"Категория;Количество\nУпаковка;100"});
    else if(path.endsWith("/supplier-requests")&&req.method()==="POST"){row={...row,status:"draft",sent_at:null as unknown as string};rows=[row];json=row;}
    else if(path.endsWith("/supplier-requests"))json=rows;
    else if(path.endsWith(`/supplier-requests/${requestId}`)&&req.method()==="PATCH"){
      const value=req.postDataJSON();updates.push(value);row={...row,...value,revision:row.revision+1};rows=[row];json=row;
    }
    else if(path.endsWith("/messages")&&req.method()==="POST"){
      const value=req.postDataJSON();sends.push(value);sendAttempts++;
      if(options.sendFailure&&sendAttempts===1)return route.fulfill({status:503,json:{detail:"Отправка временно недоступна. Повторите попытку."}});
      const message={id:`synthetic-message-${sendAttempts}`,author_company_id:value.company_id,message:value.message,created_at:"2026-10-26T02:00:00Z"};messages.push(message);row={...row,status:row.status==="draft"?"sent":value.company_id===sellerId&&row.status==="sent"?"replied":row.status,revision:row.revision+1};rows=[row];json=message;
    }
    else if(path.endsWith("/messages"))json=messages;
    else if(path.endsWith("/draft")){
      if(options.draftFailure)return route.fulfill({status:503,json:{detail:"Локальный ИИ недоступен. Напишите вручную или повторите попытку."}});
      json={text:draftText,request_revision:row.revision,warnings:["ИИ подготовил ответ без коммерческих обязательств."]};
    }
    return route.fulfill({json});
  });
  return {updates,sends,removedPanelRequests};
}

async function openBoard(page:Page){await page.goto(`/needs/${needId}/suppliers`);await page.getByRole('tab',{name:/Доска запросов/}).click();}
async function openCard(page:Page){await openBoard(page);await page.locator('.supplier-card__open').first().click();return page.getByRole('region',{name:'Работа с поставщиком'});}

test('closed need keeps its addressed chat open after sending and refreshing',async({page})=>{
  const state=await prepare(page,{empty:true,closed:true});
  await page.goto(`/needs/${needId}/suppliers`);
  await page.getByRole('button',{name:'Запросить КП',exact:true}).click();
  const workspace=page.getByRole('region',{name:'Работа с поставщиком'});
  await workspace.getByLabel('Запрос коммерческого предложения').fill('Просим КП на 100 стаканов.');
  await expect(workspace.getByRole('button',{name:'Отправить поставщику',exact:true})).toBeEnabled();
  await workspace.getByRole('button',{name:'Отправить поставщику',exact:true}).click();
  await expect(workspace.getByText('Сообщение отправлено.',{exact:true})).toBeVisible();
  await workspace.getByLabel('Ваше сообщение').fill('Уточните условия доставки.');
  await workspace.getByRole('button',{name:'Обновить',exact:true}).click();
  await expect(workspace.getByText('Переписка обновлена.',{exact:true})).toBeVisible();
  await expect(workspace.getByLabel('Ваше сообщение')).toHaveValue('Уточните условия доставки.');
  await expect(workspace.getByRole('heading',{name:'Чат',exact:true})).toBeVisible();
  expect(state.sends).toHaveLength(1);
});

test('supplier RFQ is addressed, editable and never sent by generation',async({page})=>{
  const state=await prepare(page,{empty:true});await openBoard(page);
  await page.getByLabel('Получатель запроса').selectOption(sellerId);await page.getByRole('button',{name:'Подготовить запрос',exact:true}).click();
  const workspace=page.getByRole('region',{name:'Работа с поставщиком'});
  await workspace.getByRole('button',{name:'Подготовить запрос с ИИ'}).click();
  const input=workspace.getByLabel('Запрос коммерческого предложения');await expect(input).toHaveValue(draftText);expect(state.sends).toHaveLength(0);
  await input.fill(draftText+' Уточните упаковку.');await workspace.getByRole('button',{name:'Отправить поставщику',exact:true}).click();
  await expect(workspace.getByText('Сообщение отправлено.',{exact:true})).toBeVisible();expect(state.sends).toHaveLength(1);expect(state.sends[0].human_approved).toBe(true);
});

test('buyer and seller exchange the RFQ, reply and follow-up only through chat',async({page})=>{
  const state=await prepare(page,{empty:true});await openBoard(page);
  await page.getByLabel('Получатель запроса').selectOption(sellerId);
  await page.getByRole('button',{name:'Подготовить запрос',exact:true}).click();
  const workspace=page.getByRole('region',{name:'Работа с поставщиком'});
  await expect(workspace.getByRole('button',{name:'Я отправил запрос вне платформы',exact:true})).toHaveCount(0);
  await workspace.getByLabel('Запрос коммерческого предложения').fill('Пришлите КП: 100 бумажных стаканов, доставка в Москву.');
  await workspace.getByRole('button',{name:'Отправить поставщику',exact:true}).click();
  await expect(workspace.getByText('Сообщение отправлено.',{exact:true})).toBeVisible();
  await expect(workspace.getByRole('heading',{name:'Ответ поставщика',exact:true})).toHaveCount(0);
  await expect(workspace.getByLabel('Цена из ответа, ₽')).toHaveCount(0);
  await expect(workspace.getByLabel('Файл ответа поставщика')).toHaveCount(0);

  await page.goto('/seller/inquiries');
  const reply='Цена 4 ₽ за штуку, всего 400 ₽. Поставка в Москву за 5 дней.';
  await workspace.getByLabel('Ваше сообщение').fill(reply);
  await workspace.getByRole('button',{name:'Отправить покупателю',exact:true}).click();
  await expect(workspace.getByText('Сообщение отправлено.',{exact:true})).toBeVisible();

  await openCard(page);
  await expect(workspace.getByText(reply,{exact:true})).toBeVisible();
  await expect(page.getByRole('region',{name:'Получен ответ',exact:true}).locator('.supplier-card')).toHaveCount(1);
  await workspace.getByLabel('Ваше сообщение').fill('Уточните, входит ли доставка в указанную сумму.');
  await workspace.getByRole('button',{name:'Отправить поставщику',exact:true}).click();
  await expect(workspace.getByText('Сообщение отправлено.',{exact:true})).toBeVisible();
  await page.reload();
  await page.getByRole('tab',{name:/Доска запросов/}).click();
  await page.locator('.supplier-card__open').first().click();
  await expect(workspace.locator('.supplier-message')).toHaveCount(3);
  await expect(workspace.getByText(reply,{exact:true})).toBeVisible();
  await expect(page.getByRole('region',{name:'Получен ответ',exact:true}).locator('.supplier-card')).toHaveCount(1);
  expect(state.sends.map(item=>item.company_id)).toEqual([buyerId,sellerId,buyerId]);
  expect(state.updates).toHaveLength(0);
  expect(state.removedPanelRequests).toHaveLength(0);
});

test('board can be moved with keyboard without creating a deal',async({page})=>{
  const state=await prepare(page);await openBoard(page);
  await page.getByLabel(`Этап: ${sellerName}`).selectOption('selected');
  await expect(page.getByRole('region',{name:'Выбрано',exact:true}).locator('.supplier-card')).toHaveCount(1);
  expect(state.updates.at(-1)?.status).toBe('selected');expect(state.updates.at(-1)?.expected_revision).toBe(1);
});

test('AI failure keeps message and failed send retries with the same key',async({page})=>{
  const state=await prepare(page,{draftFailure:true,sendFailure:true});const workspace=await openCard(page);const input=workspace.getByLabel('Ваше сообщение');
  await input.fill('Уточните, пожалуйста, срок поставки.');await workspace.getByRole('button',{name:'Помочь с ответом'}).click();
  await expect(workspace.getByRole('alert')).toContainText('Локальный ИИ недоступен');await expect(input).toHaveValue('Уточните, пожалуйста, срок поставки.');
  await workspace.getByRole('button',{name:'Отправить поставщику',exact:true}).click();await expect(workspace.getByRole('alert')).toContainText('Отправка временно недоступна');await expect(input).toHaveValue('Уточните, пожалуйста, срок поставки.');
  await workspace.getByRole('button',{name:'Отправить поставщику',exact:true}).click();await expect(input).toHaveValue('');expect(state.sends).toHaveLength(2);expect(state.sends[0].request_key).toBe(state.sends[1].request_key);
});

test('seller can draft and send a reply and cannot see private buyer quote fields',async({page})=>{
  const state=await prepare(page);await page.goto('/seller/inquiries');const workspace=page.getByRole('region',{name:'Работа с поставщиком'});
  await workspace.getByRole('button',{name:'Помочь с ответом'}).click();await expect(workspace.getByLabel('Ваше сообщение')).toHaveValue(draftText);
  await expect(workspace.getByText('ИИ подготовил ответ без коммерческих обязательств.',{exact:true})).toBeVisible();
  await workspace.getByRole('button',{name:'Отправить покупателю',exact:true}).click();await expect(workspace.getByText('Сообщение отправлено.',{exact:true})).toBeVisible();expect(state.sends[0].company_id).toBe(sellerId);
  await expect(workspace.getByLabel('Цена из ответа, ₽')).toHaveCount(0);await expect(workspace.getByLabel('Файл ответа поставщика')).toHaveCount(0);
});

test('specification download and responsive light/dark board remain usable',async({page},testInfo)=>{
  await prepare(page);
  // Скачивание спецификации живёт в карточке потребности, доска запросов — на странице подбора.
  await page.goto(`/needs/${needId}`);
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'Скачать спецификацию',exact:true}).click();expect((await download).suggestedFilename()).toContain('specification');
  const workspace=await openCard(page);
  for(const theme of ['light','dark']){
    await page.evaluate(t=>{document.documentElement.dataset.theme=t;},theme);
    await workspace.scrollIntoViewIfNeeded();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await expect(workspace.getByLabel('Ваше сообщение')).toBeVisible();
    if(['desktop-chromium','iphone-webkit'].includes(testInfo.project.name)){
      await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
      await workspace.screenshot({path:`output/procurement-qa/${testInfo.project.name}-${theme}.png`,style:".site-header,.skip-link{visibility:hidden!important}"});
      await page.locator(".supplier-board").screenshot({path:`output/procurement-qa/${testInfo.project.name}-${theme}-board.png`,style:".site-header,.skip-link{visibility:hidden!important}"});
    }
  }
});

test('desktop board drag moves a supplier card smoothly',async({page,isMobile})=>{
  test.skip(isMobile,'На touch используется доступный выбор этапа');
  await prepare(page);await openBoard(page);
  await page.locator('.supplier-card').dragTo(page.getByRole('region',{name:'Получен ответ',exact:true}));
  await expect(page.getByRole('region',{name:'Получен ответ',exact:true}).locator('.supplier-card')).toHaveCount(1);
});


test('matched need keeps the next step to orders after reload', async ({page}, testInfo) => {
  await prepare(page);
  await page.route(url => url.pathname.includes("/api/") && url.pathname.endsWith(`/needs/${needId}`), route => route.fulfill({json:{...need,status:'matched'}}));
  await page.goto(`/needs/${needId}`);
  await expect(page.getByRole('heading',{name:'Предложение выбрано',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Перейти к заказам',exact:true})).toHaveAttribute('href','/deals');
  // Complete initial navigation/prefetch before testing persistence across reload.
  await page.waitForLoadState('networkidle');
  if (['desktop-chromium','iphone-webkit'].includes(testInfo.project.name)) await page.locator('section.card').filter({has:page.getByRole('heading',{name:'Предложение выбрано',exact:true})}).screenshot({path:`output/procurement-qa/final-next-step-${testInfo.project.name}.png`,style:'.site-header,.skip-link{visibility:hidden!important}'});
  await page.reload();
  await expect(page.getByRole('link',{name:'Перейти к заказам',exact:true})).toBeVisible();
});


for(const stale of [false,true])test(`supplier totals use the frozen quote and never recalculate stale terms: ${stale}`,async({page})=>{
 const quote={id:'quote',company_id:sellerId,status:'sent',revision:2,price_rub:'12',available_units:100,moq_units:10,lead_time_days:2,
  price_tiers:[{min_units:100,unit_price_rub:'9.50'}],commercial_quote:{schema_version:1,need:{id:needId,revision:stale?0:1,units:100},offer:{id:'quote',revision:2},
   estimate:{units:100,unit_price_rub:'9.50',complete:true,lines:[{code:'goods',amount_rub:'950.00',conditional:false}],missing:[],total_rub:'950.00',known_total_rub:'950.00',terms:{tax_basis:'no_vat'}}}};
 await prepare(page,{quote});await page.goto(`/needs/${needId}/suppliers`);
 const tile=page.locator('.supplier-tile');
 if(stale){await expect(tile.locator('.supplier-tile__total')).toHaveCount(0);await expect(tile).toContainText('Условия КП требуют обновления');}
 else {await expect(tile.locator('.supplier-tile__price strong')).toHaveText('9,5 ₽');await expect(tile.locator('.supplier-tile__total strong')).toHaveText('950 ₽');}
});
