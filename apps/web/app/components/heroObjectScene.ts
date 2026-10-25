import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { createHeroModel } from "./heroObjectModels";
import type { HeroObjectKind } from "./HeroObject";

/** One bounded, on-demand renderer; pointer tracking never touches the surrounding hero. */
export function createHeroObjectScene(host: HTMLElement, canvas: HTMLCanvasElement, kind: HeroObjectKind) {
  const context = canvas.getContext("webgl2", { alpha: true, antialias: true, powerPreference: "low-power" });
  if (!context) return;
  const renderer = new THREE.WebGLRenderer({ canvas, context, alpha: true, antialias: true });
  const scene = new THREE.Scene(), pivot = new THREE.Group();
  const camera = new THREE.PerspectiveCamera(32, 1, .1, 30);
  let environment: THREE.WebGLRenderTarget | undefined;
  let frame = 0, previousTime = 0, disposed = false;
  let targetX = 0, targetY = 0, targetZ = 0;
  let resize: ResizeObserver | undefined, theme: MutationObserver | undefined;
  const key = new THREE.DirectionalLight(0xffffff, 2);
  const fill = new THREE.HemisphereLight(0xe5f1ff, 0x35527c, .9);
  const rim = new THREE.DirectionalLight(0x78afff, 1.5);

  function dispose() {
    disposed = true; cancelAnimationFrame(frame); frame = 0;
    resize?.disconnect(); theme?.disconnect();
    host.removeEventListener("pointermove", move);
    host.removeEventListener("pointerleave", reset);
    host.removeEventListener("pointercancel", reset);
    window.removeEventListener("blur", reset);
    const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>();
    scene.traverse(object => {
      if (object instanceof THREE.Mesh) {
        geometries.add(object.geometry);
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) materials.add(material);
      }
    });
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
    environment?.dispose(); renderer.dispose(); scene.clear();
    delete canvas.dataset.ready;
  }
  function schedule() {
    if (!frame && !disposed) { previousTime = performance.now(); frame = requestAnimationFrame(draw); }
  }
  function draw(time: number) {
    frame = 0;
    if (disposed) return;
    // Exponential smoothing is stable at any dt; capping it makes low-FPS return drag on.
    const dt = Math.max(0, (time - previousTime) / 1000);
    previousTime = time;
    const ease = 1 - Math.exp(-dt / .095);
    pivot.rotation.x += (targetX - pivot.rotation.x) * ease;
    pivot.rotation.y += (targetY - pivot.rotation.y) * ease;
    pivot.rotation.z += (targetZ - pivot.rotation.z) * ease;
    const settled = Math.max(Math.abs(targetX - pivot.rotation.x), Math.abs(targetY - pivot.rotation.y), Math.abs(targetZ - pivot.rotation.z)) < .0005;
    if (settled) pivot.rotation.set(targetX, targetY, targetZ);
    renderer.render(scene, camera);
    if (!settled) frame = requestAnimationFrame(draw);
  }
  function move(event: PointerEvent) {
    if (event.pointerType !== "mouse" && event.pointerType !== "pen") return;
    const box = host.getBoundingClientRect();
    const x = THREE.MathUtils.clamp((event.clientX - box.left) / box.width * 2 - 1, -1, 1);
    const y = THREE.MathUtils.clamp((event.clientY - box.top) / box.height * 2 - 1, -1, 1);
    targetX = y * .32; targetY = x * .6; targetZ = -x * .07;
    schedule();
  }
  function reset() { targetX = targetY = targetZ = 0; schedule(); }

  try {
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    const room = new RoomEnvironment(), generator = new THREE.PMREMGenerator(renderer);
    if (kind === "procurement") {
      // Long softboxes make continuous reflections on the ribbon, with navy negative fill.
      room.dispose(); room.clear();
      room.background = new THREE.Color(0x1a2943);
      const softbox = (color: number, strength: number, size: [number, number, number], position: [number, number, number]) => {
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(strength) }));
        mesh.position.set(...position); mesh.lookAt(0, 0, 0); room.add(mesh);
      };
      softbox(0xffffff, 7, [3, 7, .05], [-4, 3, 5]);
      softbox(0xeaf5ff, 4, [1.4, 6, .05], [4, 1, 2]);
      softbox(0x729eff, 2, [5, 1.2, .05], [0, -3, 3]);
      softbox(0xd7d9ff, 3, [1.5, 5, .05], [-2, 0, -4]);
      renderer.transmissionResolutionScale = .75;
    }
    try { environment = generator.fromScene(room, .04); }
    finally { room.dispose(); generator.dispose(); }
    scene.environment = environment.texture;
    const model = createHeroModel(kind);
    const bounds = new THREE.Box3().setFromObject(model), sphere = bounds.getBoundingSphere(new THREE.Sphere());
    // The rotated AABB greatly overestimates curved objects; fit their actual vertices instead.
    const vertex = new THREE.Vector3(); let radius = 0;
    model.traverse(object => {
      if (!(object instanceof THREE.Mesh)) return;
      const positions = object.geometry.getAttribute("position");
      for (let i = 0; i < positions.count; i++) {
        vertex.fromBufferAttribute(positions, i).applyMatrix4(object.matrixWorld);
        radius = Math.max(radius, vertex.distanceTo(sphere.center));
      }
    });
    sphere.radius = radius;
    model.position.sub(sphere.center);
    pivot.add(model); scene.add(pivot);
    // Fit a bounding sphere, including every rotated side, with an actual clear guard band.
    camera.position.z = sphere.radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.08;
    camera.far = camera.position.z + sphere.radius * 3;
    camera.updateProjectionMatrix();
    key.position.set(-3, 5, 6); rim.position.set(3, 1, -2);
    scene.add(key, fill, rim);
    const setTheme = () => {
      const dark = document.documentElement.dataset.theme === "dark";
      renderer.toneMappingExposure = dark ? .95 : 1.02;
      fill.intensity = dark ? .65 : .9;
      schedule();
    };
    resize = new ResizeObserver(() => {
      const width = Math.max(1, host.clientWidth), height = Math.max(1, host.clientHeight);
      renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.6, 640 / Math.max(width, height)));
      renderer.setSize(width, height, false);
      camera.aspect = width / height; camera.updateProjectionMatrix(); schedule();
    });
    resize.observe(host);
    theme = new MutationObserver(setTheme);
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    host.addEventListener("pointermove", move, { passive: true });
    host.addEventListener("pointerleave", reset, { passive: true });
    host.addEventListener("pointercancel", reset, { passive: true });
    window.addEventListener("blur", reset);
    setTheme();
    renderer.setSize(Math.max(1, host.clientWidth), Math.max(1, host.clientHeight), false);
    renderer.render(scene, camera);
    canvas.dataset.ready = "true";
    return dispose;
  } catch (error) { dispose(); throw error; }
}
