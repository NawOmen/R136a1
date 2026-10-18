import { useId } from "react";
import styles from "./AgentIllustration.module.css";

function Box({x,y,w,d,h,color="#527e95",top="#8eb6c7",side="#2c5268"}:{x:number;y:number;w:number;d:number;h:number;color?:string;top?:string;side?:string}) {
  return <g transform={`translate(${x} ${y})`} stroke="#b6eaff" strokeOpacity=".2" strokeWidth=".7" strokeLinejoin="round">
    <path d={`M ${-d} ${d*.45} L ${w-d} ${(w+d)*.45} V ${(w+d)*.45-h} L ${-d} ${d*.45-h} Z`} fill={color}/>
    <path d={`M ${w} ${w*.45} L ${w-d} ${(w+d)*.45} V ${(w+d)*.45-h} L ${w} ${w*.45-h} Z`} fill={side}/>
    <path d={`M 0 ${-h} L ${w} ${w*.45-h} L ${w-d} ${(w+d)*.45-h} L ${-d} ${d*.45-h} Z`} fill={top}/>
  </g>;
}
function Plant(){return <g>
  <Box x={245} y={330} w={220} d={140} h={20} color="#2f5269" top="#54798b"/>
  <Box x={247} y={300} w={167} d={100} h={122} color="#345d77" top="#89bccd" side="#203f56"/>
  {[0,1,2].map(i=><g key={i}><Box x={245+i*48} y={183+i*21.6} w={45} d={100} h={17} color="#46718a" top="#bbd7df"/>
    <Box x={246+i*48} y={177+i*21.6} w={30} d={80} h={5} color="#203b50" top="#3d819c"/>
  </g>)}
  {[0,1,2,3,4,5].map(i=><path key={i} d={`M ${155+i*25} ${259+i*11.25} v-45 l18 8 v45 Z`} fill="#72c6e5" fillOpacity=".5" stroke="#a5e7fa" strokeOpacity=".3"/>)}
  <Box x={233} y={315} w={166} d={28} h={17} color="#233c4d" top="#86a9b7"/>
  {Array.from({length:13},(_,i)=><path key={i} d={`M ${211+i*12} ${307+i*5.4} l25 -11`} stroke="#c3dce5" strokeWidth="3"/>)}
  <g className={styles.conveyor}>{[0,1,2].map(i=><Box key={i} x={231+i*51} y={302+i*23} w={22} d={19} h={23} color="#bb9971" top="#e5c69c" side="#8b7055"/>)}</g>
  {[0,1].map(i=><g key={i} transform={`translate(${365+i*35} ${248+i*16})`}><path d="M-10 0 V-124 H10 V0" fill="#9ebfc9" stroke="#c5e6eb"/><ellipse cy="-124" rx="10" ry="5" fill="#d9edf0"/><path d="M-10 -20 H10 M-10 -82 H10" stroke="#577c91" strokeWidth="3"/></g>)}
  <Box x={130} y={332} w={49} d={40} h={48} color="#395f77" top="#7a9eae"/>
  <g transform="translate(130 300)"><circle r="15" fill="#1d3a50" stroke="#94cfdf" strokeWidth="3"/><g className={styles.fan}>{[0,1,2,3].map(i=><path key={i} transform={`rotate(${i*90})`} d="M-3 0 L-6 -12 Q5 -15 4 -3 Z" fill="#7cb9ce"/>)}</g></g>
  <Box x={402} y={390} w={39} d={22} h={31} color="#d8aa61" top="#f8d28c" side="#9d793e"/>
  <Box x={400} y={362} w={22} d={20} h={20} color="#254c61" top="#95bdc9"/>
  <circle cx="398" cy="397" r="8" fill="#142b3c"/><circle cx="423" cy="407" r="8" fill="#142b3c"/>
</g>}
function Office(){return <g>
  <Box x={740} y={330} w={170} d={155} h={20} color="#354858" top="#788c94"/>
  <Box x={737} y={302} w={115} d={95} h={178} color="#9db5bf" top="#d2e2e6" side="#4c7084"/>
  {[0,1,2].map(f=><g key={f}>
    <Box x={737} y={177+f*56} w={121} d={99} h={7} color="#b3cbd5" top="#e4eff2" side="#7995a6"/>
    {[0,1,2,3].map(i=><path key={i} d={`M ${646+i*23} ${153+f*56+i*10.35} l17 7.65 v34 l-17 -7.65 Z`} fill="#f9d69c" stroke="#44647a" strokeWidth="2"/>)}
    {[0,1,2].map(i=><path key={i} d={`M ${839-i*28} ${181+f*56+i*12.6} l-21 9.45 v34 l21 -9.45 Z`} fill="#cba76e" stroke="#44647a" strokeWidth="2"/>)}
  </g>)}
  <g className={styles.roof}><Box x={737} y={121} w={129} d={106} h={12} color="#b6ced6" top="#e2edf0" side="#7c9daf"/>
    <Box x={749} y={105} w={43} d={31} h={20} color="#72919f" top="#b2ccd5"/>
    {[0,1,2].map(i=><path key={i} d={`M ${691+i*30} ${92+i*13.5} l23 10.35 l-32 14.4 l-23 -10.35 Z`} fill="#254c67" stroke="#74b3ce"/>)}</g>
  <Box x={705} y={331} w={42} d={22} h={6} top="#c9dce2"/>
  <Box x={708} y={325} w={39} d={20} h={6} top="#d8e7eb"/>
  <Box x={711} y={317} w={35} d={18} h={6} top="#e4eef0"/>
  <Box x={713} y={284} w={38} d={25} h={8} top="#b3d4df"/>
  <Box x={850} y={404} w={39} d={22} h={13} color="#5e8ea8" top="#9dc7d7"/>
  <Box x={850} y={391} w={23} d={20} h={13} color="#36596b" top="#b0d4e2"/>
  <circle cx="843" cy="412" r="6" fill="#172e3b"/><circle cx="868" cy="423" r="6" fill="#172e3b"/>
</g>}
function Tree({x,y}:{x:number;y:number}){return <g transform={`translate(${x} ${y})`}><ellipse cy="11" rx="22" ry="9" fill="#091b28" opacity=".5"/><path d="M0 7 V-28" stroke="#73918a" strokeWidth="5"/><path d="M0 -73 L23 -46 L20 -22 L0 -12 L-23 -26 L-22 -51 Z" fill="#377e77"/><path d="M0 -73 L23 -46 L20 -22 L0 -12 Z" fill="#215858"/><path d="M0 -73 L-22 -51 L0 -40 L23 -46 Z" fill="#6aa398"/></g>}
export function AgentIllustration({stage}:{stage:number}) {
  const id=useId().replace(/:/g,"");
  return <svg className={styles.illustration} data-stage={stage} viewBox="0 0 1000 650" aria-hidden="true">
    <defs><radialGradient id={`${id}-glow`}><stop stopColor="#55d9ff" stopOpacity=".18"/><stop offset="1" stopColor="#55d9ff" stopOpacity="0"/></radialGradient><linearGradient id={`${id}-road`}><stop stopColor="#60cfff"/><stop offset="1" stopColor="#9eecd1"/></linearGradient></defs>
    <ellipse cx="500" cy="350" rx="490" ry="260" fill={`url(#${id}-glow)`}/>
    <g className={styles.network} opacity=".3"><path d="M120 150 L500 300 L880 150 M190 500 L500 300 L880 500" fill="none" stroke="#649cb3" strokeDasharray="5 8"/>
      <g transform="translate(110 90) scale(.24)"><Plant/></g><g transform="translate(650 60) scale(.24)"><Office/></g><g transform="translate(130 410) scale(.22)"><Plant/></g></g>
    <ellipse cx="281" cy="402" rx="190" ry="52" fill="#020e19" opacity=".5"/>
    <ellipse cx="753" cy="402" rx="180" ry="52" fill="#020e19" opacity=".5"/>
    <g className={styles.plant}><Plant/><Tree x={162} y={385}/></g><g className={styles.office}><Office/><Tree x={615} y={366}/><Tree x={900} y={361}/></g>
    <g className={styles.routes}><path d="M423 368 C490 334 560 332 630 355" fill="none" stroke="#163f56" strokeWidth="30"/><path d="M423 365 C490 331 560 329 630 352" fill="none" stroke={`url(#${id}-road)`} strokeWidth="2"/>
      <path className={styles.flow} d="M423 365 C490 331 560 329 630 352" fill="none" stroke="#c9f8ff" strokeWidth="7" strokeDasharray="1 37" strokeLinecap="round"/>
      <path className={styles.alternate} d="M435 350 C460 240 590 240 622 338" fill="none" stroke="#95dfbc" strokeWidth="1.5" strokeDasharray="4 5"/></g>
    <g className={styles.scanning}><ellipse cx="510" cy="325" rx="145" ry="65" fill="none" stroke="#6edaff" strokeWidth="1"/><ellipse cx="510" cy="325" rx="195" ry="88" fill="none" stroke="#6edaff" strokeWidth=".6" opacity=".35"/></g>
    {[0,1,2].map((i)=><g className={`${styles.agent} ${styles[`agent${i}`]}`} key={i} transform={`translate(${i===0?505:i===1?280:760} ${i===0?190:112})`}><circle r="32" fill={`url(#${id}-glow)`}/><path d="M0 -16 L12 0 L0 19 L-12 0Z" fill={i===2?"#ffd6a1":"#9feaff"}/><path d="M0 -16 L0 19 L-12 0Z" fill={i===2?"#b98c57":"#368fac"}/><ellipse cy="23" rx="22" ry="7" stroke={i===2?"#ffd6a1":"#9feaff"} strokeWidth=".8" fill="none" opacity=".5"/></g>)}
  </svg>;
}
