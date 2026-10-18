"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { Component, type ReactNode, useEffect, useMemo, useRef } from "react";
import { CatmullRomCurve3, Group, Mesh, Vector3, MathUtils } from "three";

function Block({ position, size, color, glass = false }: { position: [number, number, number]; size: [number, number, number]; color: string; glass?: boolean }) {
  return <mesh position={position} castShadow receiveShadow><boxGeometry args={size} /><meshPhysicalMaterial color={color} metalness={glass ? .2 : .65} roughness={glass ? .12 : .35} transparent={glass} opacity={glass ? .32 : 1} clearcoat={1} /></mesh>;
}

function Factory({ active, scale = 1, x = -3, z = 0 }: { active: boolean; scale?: number; x?: number; z?: number }) {
  const gears = useRef<Group>(null);
  useFrame((_, delta) => { if (active && gears.current) gears.current.rotation.z -= delta * .7; });
  return <group position={[x, 0, z]} scale={scale}>
    <Block position={[0, -.15, 0]} size={[2.8, .3, 2.4]} color="#1e475a" />
    <Block position={[0, 1, 0]} size={[2.3, 2, 1.8]} color={active ? "#6bd3f5" : "#64727e"} glass />
    <mesh position={[0,1,0]}><boxGeometry args={[2.31,2.01,1.81]}/><meshBasicMaterial color={active ? "#6cdfff" : "#657988"} wireframe transparent opacity={.35}/></mesh>
    <Block position={[.7, 2, -.45]} size={[.3, 2, .3]} color="#8db8c8" />
    <Block position={[0, .3, .2]} size={[1.9, .25, .9]} color="#122b39" />
    {Array.from({length: 6}, (_, i) => <mesh key={i} position={[-.75 + i * .3, .48, .2]} rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[.09,.09,.75,12]} /><meshStandardMaterial color="#829caa" metalness={.8} roughness={.25} /></mesh>)}
    <group ref={gears} position={[0, 1.2, .95]}><mesh><torusGeometry args={[.38,.1,8,24]} /><meshStandardMaterial color={active ? "#6ddfff" : "#6a7a84"} emissive={active ? "#176789" : "#000000"} emissiveIntensity={2} /></mesh>{Array.from({length: 8}, (_, i) => <group key={i} rotation={[0,0,i*Math.PI/4]}><Block position={[0,.45,0]} size={[.14,.2,.15]} color="#9dd9e7" /></group>)}</group>
    {[0,1,2].map(i => <mesh key={i} position={[-.8+i*.8, 2.04, .9]}><sphereGeometry args={[.035,8,8]} /><meshBasicMaterial color={active ? "#7de7ff" : "#5f6d76"} /></mesh>)}
  </group>;
}

function Office({ active, x = 3, z = 0, scale = 1 }: { active: boolean; x?: number; z?: number; scale?: number }) {
  const roof = useRef<Group>(null);
  useFrame((_,delta) => { if(roof.current) roof.current.rotation.z = MathUtils.damp(roof.current.rotation.z, active ? -.35 : 0, 3, delta); });
  return <group position={[x,0,z]} scale={scale}>
    <Block position={[0,-.15,0]} size={[2.8,.3,2.4]} color="#4c4b47" />
    <Block position={[0,.85,0]} size={[2,1.7,1.6]} color="#72858e" />
    <group ref={roof} position={[-1,1.8,0]}><Block position={[1,0,0]} size={[2.2,.16,1.8]} color="#b7c9ca" /></group>
    {[-.6,0,.6].map(x => [ .55,1.2].map(y => <mesh key={`${x}-${y}`} position={[x,y,.811]}><planeGeometry args={[.35,.36]} /><meshStandardMaterial color={active ? "#ffcf88" : "#263641"} emissive={active ? "#ffad42" : "#000000"} emissiveIntensity={active ? 1.8 : 0} /></mesh>))}
    <Block position={[0,.25,.84]} size={[.3,.5,.08]} color="#152733" />
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
    cameraTarget.set(pointer.x*.35,wide?9:5,wide?13:10);
    camera.position.lerp(cameraTarget,1-Math.exp(-delta*2));
    camera.lookAt(0,.8,0);
    if(scan.current){const size=(clock.elapsedTime*.5)%2.6;scan.current.scale.setScalar(size);}
  });
  return <>
    <EffectComposer multisampling={0}><Bloom luminanceThreshold={1.2} intensity={.65} mipmapBlur /></EffectComposer>
    <color attach="background" args={["#081621"]} /><fog attach="fog" args={["#081621",14,30]} />
    <ambientLight intensity={.8} /><directionalLight position={[3,8,5]} intensity={2.8} color="#b4eaff" castShadow shadow-mapSize={[1024,1024]} /><pointLight position={[-3,3,2]} color="#50cbff" intensity={12} distance={9} /><pointLight position={[3,3,2]} color="#ffc575" intensity={9} distance={8} />
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
