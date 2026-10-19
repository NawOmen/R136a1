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
function Warehouse({x,y}:{x:number;y:number}) {return <g transform={`translate(${x} ${y})`}>
  <Box x={0} y={0} w={240} d={115} h={12} color="#29495b" top="#5c7887"/>
  <Box x={3} y={-15} w={222} d={100} h={95} color="#527f94" top="#bdd1d8" side="#2e566d"/>
  <Box x={3} y={-110} w={230} d={105} h={9} color="#8aabb8" top="#c9dde2"/>
  {[0,1,2,3].map(i=><g key={i}><path d={`M ${-79+i*50} ${-67+i*22.5} l35 15.75 v54 l-35 -15.75 Z`} fill="#203f53" stroke="#91becd"/>
    {[0,1,2,3].map(j=><path key={j} d={`M ${-77+i*50} ${-57+i*22.5+j*12} l31 13.95`} stroke="#517a90"/>)}
    <Box x={-66+i*50} y={-8+i*22.5} w={36} d={25} h={10} top="#768e99"/>
    <path d={`M ${-73+i*50} ${-76+i*22.5} l22 9.9`} stroke="#a2edcc" strokeWidth="3"/>
  </g>)}
  {[0,1,2,3].map(i=><Box key={i} x={8+i*45} y={-113+i*20.25} w={31} d={65} h={3} color="#254e66" top="#3d7791"/>)}
</g>}
function Truck({x,y}:{x:number;y:number}) {return <g transform={`translate(${x} ${y})`}>
  <Box x={0} y={0} w={60} d={29} h={38} color="#a7c1cb" top="#d7e6e9" side="#678d9f"/>
  <Box x={63} y={28} w={24} d={29} h={25} color="#4e91b0" top="#90c9dc"/>
  <path d="M41 19 l18 8 v-13 l-18 -8Z" fill="#21465c"/>
  {[0,1,2].map(i=><circle key={i} cx={-13+i*32} cy={17+i*14.4} r="7" fill="#102a3b" stroke="#6e93a3" strokeWidth="2"/>)}
</g>}
export function AgentIllustration({stage}:{stage:number}) {
  const id=useId().replace(/:/g,"");
  return <svg className={styles.illustration} data-stage={stage} viewBox="0 0 1600 850" aria-hidden="true">
    <defs><radialGradient id={`${id}-glow`}><stop stopColor="#55d9ff" stopOpacity=".18"/><stop offset="1" stopColor="#55d9ff" stopOpacity="0"/></radialGradient><linearGradient id={`${id}-road`}><stop stopColor="#60cfff"/><stop offset="1" stopColor="#9eecd1"/></linearGradient><filter id={`${id}-shadow`} x="-30%" y="-30%" width="160%" height="180%"><feDropShadow dx="0" dy="14" stdDeviation="11" floodColor="#020c14" floodOpacity=".4"/></filter></defs>
    <ellipse cx="800" cy="430" rx="790" ry="390" fill={`url(#${id}-glow)`}/>
    <path d="M100 440 L740 160 L1510 495 L865 790 Z" fill="#132d3e" stroke="#2a5269" strokeWidth="2"/>
    <path d="M180 528 L788 260 L1430 542 M385 660 L1010 385" fill="none" stroke="#294858" strokeWidth="35" strokeLinejoin="round"/>
    <path d="M180 528 L788 260 L1430 542 M385 660 L1010 385" fill="none" stroke="#7999a8" strokeWidth="1.5" strokeDasharray="12 14"/>
    <g className={styles.network}><g transform="translate(400 80) scale(.58)"><Plant/></g><g transform="translate(820 90) scale(.46)"><Office/></g></g>
    <Warehouse x={415} y={260}/><Warehouse x={690} y={380}/>
    <g className={styles.plant} filter={`url(#${id}-shadow)`} transform="translate(75 140)"><Plant/><Tree x={124} y={390}/></g>
    <g className={styles.office} filter={`url(#${id}-shadow)`} transform="translate(565 115)"><Office/><Tree x={606} y={383}/><Tree x={905} y={360}/></g>
    <Truck x={326} y={336}/><Truck x={609} y={461}/><Truck x={1075} y={613}/>
    {[0,1,2,3,4].map(i=><g key={i}><Tree x={173+i*89} y={581+i*38}/><Tree x={1063+i*62} y={336+i*27}/></g>)}
    {[0,1,2,3,4,5].map(i=><Box key={i} x={256+i%3*34} y={574+Math.floor(i/3)*35+i%3*15.3} w={25} d={23} h={27} color="#b8956c" top="#e1bf93" side="#8b7051"/>)}
    {[0,1,2,3,4,5].map(i=><g key={i} transform={`translate(${615+i*97} ${714-i*43})`}><path d="M0 0 v-58 l-16 -7" fill="none" stroke="#769dac" strokeWidth="3"/><path d="M-21 -65 l14 6" stroke="#b6eafa" strokeWidth="5"/></g>)}
    <g className={styles.routes}><path d="M492 500 C675 595 875 594 1192 458" fill="none" stroke="#163f56" strokeWidth="22"/><path d="M492 500 C675 595 875 594 1192 458" fill="none" stroke={`url(#${id}-road)`} strokeWidth="2"/>
      <path className={styles.flow} d="M492 500 C675 595 875 594 1192 458" fill="none" stroke="#c9f8ff" strokeWidth="6" strokeDasharray="1 48" strokeLinecap="round"/>
      <path className={styles.alternate} d="M492 500 C600 330 990 270 1192 458" fill="none" stroke="#95dfbc" strokeWidth="1.5" strokeDasharray="4 7"/></g>
    <g className={styles.requestPacket}>
      <rect x="-40" y="-35" width="80" height="70" rx="9" fill="#e8f4f9" stroke="#9bdbf0" strokeWidth="2"/>
      <path d="M-23 -18h31M-23 -6h46M-23 6h35" stroke="#3d7b98" strokeWidth="4" strokeLinecap="round"/>
      <circle cx="22" cy="19" r="7" fill="#4b9bb6"/>
    </g>
    <g className={styles.agreement} transform="translate(860 420)">
      <rect x="-78" y="-50" width="156" height="100" rx="12" fill="#e7f1f5" stroke="#a2cfdf" strokeWidth="2"/>
      <path d="M-48 -26h96" stroke="#45758b" strokeWidth="4"/>
      <circle cx="-37" cy="8" r="14" fill="#225d78"/><circle cx="37" cy="8" r="14" fill="#79613d"/>
      <path d="m-43 8 4 4 9-10m61 6 4 4 9-10" stroke="#dcfff0" strokeWidth="3" fill="none"/>
      <path d="M-15 8h30" stroke="#6e98a9" strokeWidth="2"/>
    </g>
    <g className={styles.shipment}>
      <ellipse cx="0" cy="16" rx="42" ry="12" fill="#020b12" opacity=".45"/>
      <Truck x={0} y={0}/>
    </g>
    <g className={styles.arrival} transform="translate(1192 458)"><circle r="28" fill="#7fe3b1" fillOpacity=".12" stroke="#8ceac2" strokeWidth="2"/><path d="m-12 0 8 8 17-20" fill="none" stroke="#b8f5d7" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"/></g>
    <g className={styles.scanning}><ellipse cx="800" cy="475" rx="300" ry="135" fill="none" stroke="#6edaff" strokeWidth="1"/><ellipse cx="800" cy="475" rx="390" ry="175" fill="none" stroke="#6edaff" strokeWidth=".6" opacity=".35"/></g>
    {[0,1,2].map((i)=><g className={`${styles.agent} ${styles[`agent${i}`]}`} key={i} transform={`translate(${i===0?800:i===1?355:1320} ${i===0?265:200})`}><circle r="48" fill={`url(#${id}-glow)`}/><path d="M0 -23 L18 0 L0 28 L-18 0Z" fill={i===2?"#ffd6a1":"#9feaff"}/><path d="M0 -23 L0 28 L-18 0Z" fill={i===2?"#b98c57":"#368fac"}/><ellipse cy="33" rx="32" ry="10" stroke={i===2?"#ffd6a1":"#9feaff"} strokeWidth=".8" fill="none" opacity=".5"/></g>)}
  </svg>;
}
