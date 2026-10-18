"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { Component, type ReactNode, useEffect, useMemo, useRef } from "react";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { CatmullRomCurve3, Group, Mesh, Vector3, MathUtils } from "three";

function Block({ position, size, color, glass = false }: { position: [number, number, number]; size: [number, number, number]; color: string; glass?: boolean }) {
  const geometry = useMemo(() => new RoundedBoxGeometry(size[0], size[1], size[2], 2, Math.min(...size) * .12), [size[0], size[1], size[2]]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <mesh position={position} geometry={geometry} castShadow receiveShadow><meshPhysicalMaterial color={color} metalness={glass ? .1 : .35} roughness={glass ? .08 : .4} transparent={glass} opacity={glass ? .2 : 1} clearcoat={1} /></mesh>;
}

function Fan({ active, position }: { active:boolean; position:[number,number,number] }) {
  const rotor = useRef<Group>(null);
  useFrame((_,delta)=>{if(active&&rotor.current)rotor.current.rotation.z-=delta*2;});
  return <group position={position}><mesh><torusGeometry args={[.22,.035,8,28]}/><meshStandardMaterial color="#8faab7" metalness={.8} roughness={.25}/></mesh><group ref={rotor}>{[0,1,2,3].map(i=><group key={i} rotation={[0,0,i*Math.PI/2]}><Block position={[0,.1,0]} size={[.075,.22,.04]} color="#b9d4dd"/></group>)}</group></group>;
}

function Tree({x,z}:{x:number;z:number}) {
  return <group position={[x,0,z]}><Block position={[0,.2,0]} size={[.07,.4,.07]} color="#77877b"/><mesh position={[0,.6,0]} castShadow><icosahedronGeometry args={[.32,1]}/><meshStandardMaterial color="#276c63" roughness={.8}/></mesh><Block position={[0,.025,0]} size={[.45,.05,.45]} color="#4b7077"/></group>;
}

function Factory({ active, scale = 1, x = -3, z = 0 }: { active: boolean; scale?: number; x?: number; z?: number }) {
  const belt=useRef<Group>(null);
  useFrame(({clock})=>{if(active&&belt.current)belt.current.position.x=Math.sin(clock.elapsedTime)*.12;});
  return <group position={[x, 0, z]} scale={scale}>
    <Block position={[0,-.2,0]} size={[3.8,.4,3.5]} color="#203c50"/>
    <Block position={[0,.02,0]} size={[3.65,.08,3.35]} color="#56717d"/>
    <Block position={[-.25,.85,-.35]} size={[2.6,1.7,2]} color="#6fb4cc" glass/>
    {[-1.55,-.25,1.05].map((v,i)=><group key={v}>
      <Block position={[v,.85,-1.35]} size={[.07,1.75,.07]} color="#85bdcf"/>
      <Block position={[v,.85,.65]} size={[.07,1.75,.07]} color="#85bdcf"/>
      <group position={[-1.1+i*.8,1.76,-.35]} rotation={[0,0,-.1]}><Block position={[0,0,0]} size={[.78,.12,2.1]} color="#a3c0cc"/><Block position={[0,.08,0]} size={[.55,.025,1.7]} color="#28536b"/></group>
    </group>)}
    {[0,1].map(i=><group key={i} position={[-.8+i*1.05,.1,-.4]}><Block position={[0,.35,0]} size={[.65,.7,.65]} color="#2c718d"/><Block position={[0,.75,0]} size={[.45,.14,.45]} color="#a9bec5"/><Fan active={active} position={[0,.47,.34]}/></group>)}
    <Block position={[-.25,.25,.9]} size={[2.8,.25,.65]} color="#172e3b"/>
    {Array.from({length:12},(_,i)=><mesh key={i} position={[-1.5+i*.23,.42,.9]} rotation={[Math.PI/2,0,0]}><cylinderGeometry args={[.075,.075,.6,12]}/><meshStandardMaterial color="#98b2bd" metalness={.8} roughness={.2}/></mesh>)}
    <group ref={belt}>{[0,1,2].map(i=><Block key={i} position={[-1+i*.8,.62,.9]} size={[.34,.32,.35]} color="#c6a77d"/>)}</group>
    {[0,1].map(i=><group key={i} position={[1.25,0,-.65+i*.65]}><mesh position={[0,1.1,0]} castShadow><cylinderGeometry args={[.17,.23,2.2,24]}/><meshStandardMaterial color="#b8cbd0" metalness={.8} roughness={.24}/></mesh><mesh position={[0,2.15,0]}><torusGeometry args={[.18,.035,8,24]}/><meshStandardMaterial color="#d5e3e5"/></mesh></group>)}
    <Block position={[-.4,.36,-1.62]} size={[1.4,.65,.5]} color="#355a70"/>
    {[-.9,-.4,.1].map(v=><Block key={v} position={[v,.4,-1.89]} size={[.35,.42,.04]} color="#19384b"/>)}
    <Block position={[1.25,.35,1.1]} size={[.55,.55,.9]} color="#f0be6e"/>
    <Block position={[1.25,.7,.9]} size={[.45,.3,.4]} color="#273e49"/>
    {[.9,1.6].map(v=><mesh key={v} position={[v,.18,1.15]} rotation={[0,0,Math.PI/2]}><cylinderGeometry args={[.16,.16,.1,16]}/><meshStandardMaterial color="#17242d"/></mesh>)}
    <Tree x={-1.5} z={-1.5}/>
    <mesh position={[0,.08,1.6]} rotation={[-Math.PI/2,0,0]}><planeGeometry args={[2.5,.025]}/><meshBasicMaterial color="#8de9fa"/></mesh>
  </group>;
}

function Office({ active, x = 3, z = 0, scale = 1 }: { active: boolean; x?: number; z?: number; scale?: number }) {
  const roof = useRef<Group>(null);
  useFrame((_,delta)=>{if(roof.current)roof.current.position.y=MathUtils.damp(roof.current.position.y,active?2.38:2.1,3,delta);});
  return <group position={[x,0,z]} scale={scale}>
    <Block position={[0,-.2,0]} size={[3.8,.4,3.5]} color="#3e4b56"/>
    <Block position={[0,.02,0]} size={[3.65,.08,3.35]} color="#7a858a"/>
    <Block position={[0,1,-.2]} size={[2.15,2,1.9]} color="#b1c1c9"/>
    {Array.from({length:3},(_,floor)=><group key={floor}>
      <Block position={[0,.15+floor*.62,-.2]} size={[2.4,.1,2.1]} color="#d0dadd"/>
      {[-.77,-.25,.27,.79].map(v=><group key={v}>
        <mesh position={[v,.46+floor*.62,.762]}><planeGeometry args={[.38,.43]}/><meshStandardMaterial color={active?"#f6cf95":"#253d4a"} emissive={active?"#c7873b":"#000000"} emissiveIntensity={active?.6:0} metalness={.3} roughness={.18}/></mesh>
        <Block position={[v,.46+floor*.62,.79]} size={[.025,.43,.025]} color="#6c8d9b"/>
      </group>)}
      {[-.7,0,.7].map(v=><mesh key={v} position={[1.083,.46+floor*.62,v-.2]} rotation={[0,Math.PI/2,0]}><planeGeometry args={[.45,.43]}/><meshStandardMaterial color={active?"#d9ad70":"#253d4a"} emissive={active?"#a06f36":"#000000"} emissiveIntensity={.4}/></mesh>)}
    </group>)}
    <group ref={roof} position={[0,2.1,-.2]}><Block position={[0,0,0]} size={[2.45,.15,2.2]} color="#d3dfe2"/><Block position={[0,.18,-.2]} size={[.8,.3,.6]} color="#667e8a"/>{[-.25,.25].map(v=><mesh key={v} position={[v,.34,-.2]} rotation={[-Math.PI/2,0,0]}><circleGeometry args={[.14,20]}/><meshStandardMaterial color="#233e50"/></mesh>)}</group>
    <Block position={[0,.35,.82]} size={[.5,.65,.08]} color="#375c71"/>
    <Block position={[0,.76,1]} size={[.85,.08,.65]} color="#c0d9e1"/>
    {[0,1,2].map(i=><Block key={i} position={[0,.06+i*.04,1.15-i*.12]} size={[.85,.06,.2]} color="#a6b6bc"/>)}
    <Tree x={-1.4} z={.9}/><Tree x={1.4} z={-1.3}/>
    <Block position={[1.35,.18,1.15]} size={[.55,.3,.8]} color="#587e9c"/>
    <Block position={[1.35,.38,1.1]} size={[.45,.2,.4]} color="#284450"/>
    <mesh position={[-1.4,.25,-.6]}><cylinderGeometry args={[.15,.2,.4,16]}/><meshStandardMaterial color="#436578"/></mesh>
  </group>;
}

function Route({ stage }: { stage: number }) {
  const bridge = useRef<Group>(null);
  const detour = useMemo(() => new CatmullRomCurve3([new Vector3(-1.6,.5,0),new Vector3(-.7,1.25,-1.3),new Vector3(.8,1.2,-1.2),new Vector3(1.6,.5,0)]), []);
  const curve = useMemo(() => new CatmullRomCurve3([new Vector3(-2,.4,0),new Vector3(-.8,.6,-.5),new Vector3(.6,.6,-.5),new Vector3(2,.4,0)]), []);
  useFrame((_,delta) => { if(bridge.current) bridge.current.scale.x = MathUtils.damp(bridge.current.scale.x,stage >= 2 ? 1 : .001,4,delta); });
  return <group ref={bridge} scale={[.001,1,1]}>
    <mesh><tubeGeometry args={[curve,48,.06,8,false]} /><meshStandardMaterial color="#65d5ff" emissive="#239fd3" emissiveIntensity={2} /></mesh>
    <mesh visible={stage===2}><tubeGeometry args={[detour,40,.025,6,false]} /><meshBasicMaterial color="#7be5ae" /></mesh>
    <mesh position={[0,.1,0]}><boxGeometry args={[4,.08,.65]} /><meshStandardMaterial color="#2a657f" transparent opacity={.45} metalness={.8} roughness={.15} /></mesh>
    {Array.from({length: 7},(_,i)=><Cargo key={i} offset={i/7} curve={curve} />)}
  </group>;
}

function Cargo({ offset, curve }: {offset:number;curve:CatmullRomCurve3}) {
  const mesh = useRef<Mesh>(null);
  useFrame(({clock})=>{ if(mesh.current) mesh.current.position.copy(curve.getPoint((clock.elapsedTime*.12+offset)%1)); });
  return <mesh ref={mesh}><octahedronGeometry args={[.1]} /><meshStandardMaterial color="#c2f6ff" emissive="#5bdeff" emissiveIntensity={3} /></mesh>;
}

function Agent({ index, stage }: {index:number;stage:number}) {
  const group = useRef<Group>(null);
  useFrame(({clock},delta)=>{
    if(!group.current)return;
    const t=clock.elapsedTime;
    const intercept=stage===2&&index===1;
    const x=index===0?0:index===1?-2.6:2.6;
    const targetX=intercept?-.9+Math.sin(t*1.8)*.8:x+Math.sin(t*.6+index)*.25;
    group.current.position.x=MathUtils.damp(group.current.position.x,targetX,3,delta);
    group.current.position.y=2.8+Math.sin(t*.9+index)*.25-(intercept?.8:0);
    group.current.rotation.y+=delta*.45;
  });
  const color=index===2?"#ffd394":"#73deff";
  return <group ref={group} visible={index===0||stage>0}><mesh><octahedronGeometry args={[.22]} /><meshStandardMaterial color={color} emissive={color} emissiveIntensity={2.4} metalness={.4} roughness={.2} /></mesh><mesh rotation={[Math.PI/2,0,0]}><torusGeometry args={[.36,.012,8,40]} /><meshBasicMaterial color={color} transparent opacity={.5} /></mesh></group>;
}

function World({ stage }: {stage:number}) {
  const scan = useRef<Mesh>(null);
  const cameraTarget = useMemo(() => new Vector3(), []);
  useFrame(({camera,clock,pointer},delta)=>{
    const wide=stage===3;
    cameraTarget.set(1.8+pointer.x*.6,wide?10:6,wide?15:11);
    camera.position.lerp(cameraTarget,1-Math.exp(-delta*2));
    camera.lookAt(0,.65,0);
    if(scan.current){const size=(clock.elapsedTime*.5)%2.6;scan.current.scale.setScalar(size);}
  });
  return <>
    <EffectComposer multisampling={0}><Bloom luminanceThreshold={1.2} intensity={.35} mipmapBlur /></EffectComposer>
    <color attach="background" args={["#081621"]} /><fog attach="fog" args={["#081621",14,30]} />
    <ambientLight intensity={1.1} /><directionalLight position={[3,8,5]} intensity={3.5} color="#b4eaff" castShadow shadow-mapSize={[1024,1024]} /><pointLight position={[-3,5,2]} color="#50cbff" intensity={12} distance={9} /><pointLight position={[3,5,2]} color="#ffc575" intensity={9} distance={8} />
    <mesh rotation={[-Math.PI/2,0,0]} position={[0,-.34,0]} receiveShadow><planeGeometry args={[60,60]} /><meshStandardMaterial color="#0b1d2b" roughness={.32} metalness={.6} /></mesh>
    <gridHelper args={[30,30,"#21495e","#142f42"]} position={[0,-.32,0]} />
    <Factory active={stage>0}/><Office active={stage>0}/><Route stage={stage}/>
    {[0,1,2].map(index=><Agent key={index} index={index} stage={stage}/>)}
    <mesh ref={scan} rotation={[-Math.PI/2,0,0]} position={[0,.1,0]} visible={stage===1}><ringGeometry args={[1.9,1.93,64]} /><meshBasicMaterial color="#73deff" transparent opacity={.45} /></mesh>
    {stage===3&&<group>{Array.from({length:12},(_,i)=><mesh key={i} position={[Math.cos(i*2.4)*5,1.8+(i%3)*.4,Math.sin(i*2.4)*3-1]}><octahedronGeometry args={[.07]}/><meshBasicMaterial color={i%2 ? "#79dfff" : "#ffcf88"}/></mesh>)}</group>}
    {stage===3&&<><Factory active scale={.45} x={-4.5} z={-3}/><Factory active scale={.35} x={-1.5} z={-4}/><Office active scale={.5} x={3} z={-3.5}/><Office active scale={.35} x={5} z={-2.5}/></>}
  </>;
}

class SceneBoundary extends Component<{children:ReactNode;onFailure:()=>void},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(){this.props.onFailure();}
  render(){return this.state.failed?null:this.props.children;}
}

function Unavailable({ onFailure }: { onFailure: () => void }) {
  useEffect(() => { onFailure(); }, [onFailure]);
  return null;
}

export default function AgentWorld({stage,paused,onFailure,onReady}:{stage:number;paused:boolean;onFailure:()=>void;onReady:()=>void}) {
  return <SceneBoundary onFailure={onFailure}><Canvas aria-hidden="true" shadows dpr={[1,1.5]} frameloop={paused?"never":"always"} camera={{position:[0,5,10],fov:44}} gl={{antialias:true,alpha:false,powerPreference:"high-performance"}} onCreated={({gl})=>{onReady();gl.domElement.addEventListener("webglcontextlost",onFailure,{once:true});}} fallback={<Unavailable onFailure={onFailure} />}><World stage={stage}/></Canvas></SceneBoundary>;
}
