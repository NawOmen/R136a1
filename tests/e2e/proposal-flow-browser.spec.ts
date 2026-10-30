import {expect,test,type Page} from '@playwright/test';
import {readFileSync} from 'node:fs';
const registry=JSON.parse(readFileSync(require.resolve('../../services/marketplace/app/category_registry.json'),'utf8'));
const leaf=registry.groups.find((g:{label:string})=>g.label==='Строительство').leaves.find((l:{label:string})=>l.label==='Крепёж');
const buyer='60000000-0000-4000-8000-000000000001',seller='60000000-0000-4000-8000-000000000002',needId='60000000-0000-4000-8000-000000000003',dealId='60000000-0000-4000-8000-000000000004',requestId='60000000-0000-4000-8000-000000000005';
const need={id:needId,company_id:buyer,category:'Строительство',subcategory:'Крепёж',revision:1,characteristics:{unit:'шт'},volume_units:20000,budget_rub:'100000',deadline_date:'2026-11-29',valid_until:'2026-11-29',status:'waiting_for_match',visibility:'open_anonymized',files:[],delivery_address_id:null};
const request={id:requestId,need_id:needId,need_revision:1,buyer_company_id:buyer,seller_company_id:seller,buyer_name:'Синтетический покупатель',seller_name:'Синтетический поставщик',specification:{category:'Строительство',subcategory:'Крепёж',quantity:20000,unit:'шт',deadline_date:need.deadline_date,characteristics:{unit:'шт'}},status:'draft',revision:1,quoted_price_rub:null,price_basis:'unknown',note:''};
const totals={ordered_units:20000,shipped_units:0,unshipped_units:20000,received_units:0,accepted_units:0,returned_units:0,cancelled_units:0,net_units:0,open_units:20000};
async function prepare(page:Page,role:'buyer'|'seller'='buyer'){
 const writes:{path:string;body:Record<string,any>}[]=[];
 const state={deal_id:dealId,line_id:'line',revision:5,terms_version:1,status:'created',totals,dispatch:null,commercial:{seller_total_rub:'96000',seller_delivery_rub:'0',external_carrier_rub:null},destination:'Москва, Складская, 1',logistics:null,stages:{},batches:[],disputes:[],requests:[],proposals:[],history:[],completed:false,rating_rule:'Отзыв доступен после подтверждённого исполнения.',messages:[{id:'m1',company_id:seller,terms_version:1,note:'Подготовим заказ к отгрузке.\nУсловия доставки согласованы в КП.',attachments:[]},{id:'m2',company_id:buyer,terms_version:1,note:'Подтверждаем адрес получения в Москве.',attachments:[]}]};
 await page.addInitScript(()=>localStorage.setItem('token','synthetic-proposal-flow'));
 page.on('pageerror',error=>{throw error;});
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname;
  if(req.method()!=='GET') writes.push({path,body:req.postDataJSON()});
  if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'synthetic',first_name:'Тест',last_name:'Сценарий',account_status:'active'},companies:[{id:role==='buyer'?buyer:seller,display_name:'Синтетическая компания',membership:{can_buy:role==='buyer',can_sell:role==='seller',is_admin:true}}]}});
  if(path.endsWith('/categories/profiles'))return route.fulfill({json:registry});
  if(path.endsWith('/capacity'))return route.fulfill({json:req.method()==='PUT'?req.postDataJSON().entries:[]});
  if(path.endsWith('/notifications'))return route.fulfill({json:[]});
  if(path.endsWith(`/needs/${needId}`))return route.fulfill({json:need});
  if(path.endsWith(`/needs/${needId}/offers`))return route.fulfill({json:[{id:'quote',company_id:seller,revision:1,status:'sent',price_rub:'4.80',available_units:20000,moq_units:1000,lead_time_days:2,commercial_quote:{estimate:{complete:false,terms:{tax_basis:'no_vat',delivery_conditions:null},lines:[],missing:['Не подтверждено место получения товара'],known_total_rub:'96000'}}}]});
  if(path.endsWith('/supplier-requests')&&req.method()==='GET')return route.fulfill({json:[]});
  if(path.endsWith(`/needs/${needId}/supplier-requests`)&&req.method()==='POST')return route.fulfill({status:201,json:request});
  if(path.endsWith('/deals/mine'))return route.fulfill({json:[{id:dealId,need_id:needId,buyer_company_id:buyer,seller_company_id:seller,units:20000,total_price_rub:'96000',status:'created',commercial_snapshot:null}]});
  if(path.endsWith('/fulfillment')){
   if(req.method()==='POST'){const body=req.postDataJSON();state.messages.push({id:'m3',company_id:role==='buyer'?buyer:seller,terms_version:1,note:body.payload.note,attachments:[]});state.revision++;}
   return route.fulfill({json:state});
  }
  if(path.endsWith('/execution'))return route.fulfill({json:{...totals,events:[],financials:{unit_price_rub:'4.80',net_goods_revenue_rub:'0',attributable_expenses_rub:null},unit_cost_rub:null,cost_history:[]}});
  return route.fulfill({json:[]});
 });
 return {writes,state};
}

test('buyer sees the blocking reason and opens an addressed request without sending it',async({page})=>{
 const state=await prepare(page);await page.goto(`/needs/${needId}`);
 await expect(page.getByText('Выбор пока недоступен',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Выбрать предложение',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'Запросить условия у продавца',exact:true}).click();
 await expect(page).toHaveURL(new RegExp(`request=${requestId}`));
 expect(state.writes).toHaveLength(1);
 expect(state.writes[0].body).toMatchObject({seller_company_id:seller,company_id:buyer,expected_need_revision:1});
});

test('capacity links select a leaf and an allowed unit and save only filled days',async({page})=>{
 const state=await prepare(page,'seller');await page.goto(`/seller/capacity?category=${leaf.id}&company=${seller}&unit=шт`);
 await expect(page.locator('#capacity-category')).toHaveValue(leaf.id);
 await expect(page.locator('select#capacity-unit')).toHaveValue('шт');
 await page.getByRole('spinbutton',{name:/Общая мощность на/}).first().fill('20000');
 await page.getByRole('button',{name:'Сохранить',exact:true}).click();
 await expect(page.getByText('Мощности сохранены.',{exact:true})).toBeVisible();
 expect(state.writes[0].body.entries).toHaveLength(1);
 expect(state.writes[0].body.entries[0]).toMatchObject({category:leaf.id,unit:'шт',available_units:20000});
});

test('shared capacity explains coefficients and requires explicit approval',async({page})=>{
 const state=await prepare(page,'seller');await page.goto('/seller/capacity');
 await expect(page.locator('#capacity-category')).not.toHaveValue('');
 await page.locator('#capacity-category').selectOption('');await page.locator('#capacity-unit').fill('мин');
 await page.getByRole('spinbutton',{name:/Общая мощность на/}).first().fill('100');
 await page.getByRole('button',{name:'Добавить категорию',exact:true}).click();
 await page.getByLabel('Подкатегория',{exact:true}).selectOption(leaf.id);
 await page.getByLabel('Расход мин на одну единицу заказа',{exact:true}).fill('2');
 await expect(page.getByText(/2 минуты на 1 штуку/)).toBeVisible();
 await page.getByRole('button',{name:'Сохранить',exact:true}).click();
 await expect(page.locator('main .alert-error')).toContainText('подтвердите коэффициенты');
 expect(state.writes).toHaveLength(0);
 await page.getByRole('checkbox',{name:'Коэффициенты и дни календаря проверены',exact:true}).check();
 await page.getByRole('button',{name:'Сохранить',exact:true}).click();
 await expect(page.getByText('Мощности сохранены.',{exact:true})).toBeVisible();
 expect(state.writes[0].body.entries[0]).toMatchObject({category:'',unit:'мин',conversions_approved:true,category_conversions:[{category_id:leaf.id,order_unit:'шт',resource_units_per_order_unit:2}]});
});

for(const role of ['buyer','seller'] as const)test(`deal chat and operations stay aligned and preserve approvals for ${role}`,async({page},info)=>{
 const state=await prepare(page,role);await page.goto(`/deals?deal=${dealId}#deal-chat`);
 const log=page.getByRole('log',{name:'Сообщения сделки'});await expect(log.locator('.deal-message')).toHaveCount(2);
 await expect(log.locator('.deal-message--own')).toHaveCount(1);
 await expect(page.getByRole('button',{name:'Отправить сообщение',exact:true})).toBeDisabled();
 await page.getByLabel('Сообщение',{exact:true}).fill('Уточняем время передачи товара.');
 await page.getByRole('checkbox',{name:'Подтверждаю отправку в эту сделку',exact:true}).check();
 await page.getByRole('button',{name:'Отправить сообщение',exact:true}).click();
 await expect(log.locator('.deal-message')).toHaveCount(3);
 expect(state.writes[0].body).toMatchObject({action:'message',human_approved:true,expected_revision:5,terms_version:1});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.evaluate(()=>scrollTo(0,0));
 await page.screenshot({path:info.outputPath(`deal-${role}.png`),fullPage:true,animations:'disabled'});
 await page.evaluate(()=>document.documentElement.dataset.theme='dark');
 await page.screenshot({path:info.outputPath(`deal-${role}-dark.png`),fullPage:true,animations:'disabled'});
});


test('changing company reloads its own capacity scope before saving',async({page})=>{
 const other='60000000-0000-4000-8000-000000000006';
 const furniture=registry.groups.find((group:{label:string})=>group.label==='Товары для бизнеса').leaves[0];
 const state=await prepare(page,'seller');
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'synthetic',first_name:'Тест',last_name:'Сценарий',account_status:'active'},companies:[seller,other].map(id=>({id,display_name:id===seller?'Первая компания':'Вторая компания',membership:{can_buy:false,can_sell:true,is_admin:true}}))}});
  if(path.endsWith('/capacity')&&route.request().method()==='GET')return route.fulfill({json:[{date:new Date().toLocaleDateString('en-CA'),category:path.includes(other)?furniture.id:leaf.id,unit:'шт',available_units:20000,category_conversions:[]}]});
  return route.fallback();
 });
 await page.goto('/seller/capacity');
 await expect(page.locator('#capacity-category')).toHaveValue(leaf.id);
 await page.getByLabel('Компания',{exact:true}).selectOption(other);
 await expect(page.locator('#capacity-category')).toHaveValue(furniture.id);
 await page.getByRole('button',{name:'Сохранить',exact:true}).click();
 await expect(page.getByText('Мощности сохранены.',{exact:true})).toBeVisible();
 expect(state.writes[0].path).toContain(other);
 expect(state.writes[0].body.entries[0]).toMatchObject({category:furniture.id,unit:'шт'});
});
