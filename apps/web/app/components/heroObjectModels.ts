import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import type { HeroObjectKind } from "./HeroObject";

/** Original procedural meshes inspired by the existing illustrations; no remote models/textures. */
export function createHeroModel(kind: HeroObjectKind) {
  const root = new THREE.Group();
  root.name = kind === "help" ? "procurement-help" : "business-link";
  const chrome = new THREE.MeshPhysicalMaterial({ color: 0xd9e9ff, metalness: .94, roughness: .14, clearcoat: 1, clearcoatRoughness: .1, envMapIntensity: 1.45 });
  const blue = new THREE.MeshPhysicalMaterial({ color: 0x123d80, metalness: .35, roughness: .24, clearcoat: 1, envMapIntensity: .8 });
  const ice = new THREE.MeshPhysicalMaterial({ color: 0x8cbafa, metalness: .5, roughness: .12, clearcoat: 1, iridescence: .45, iridescenceIOR: 1.3, envMapIntensity: 1.65 });
  const ivory = new THREE.MeshPhysicalMaterial({ color: 0xf8f3e7, metalness: .08, roughness: .3, clearcoat: .65 });

  const box = (parent: THREE.Group, name: string, dimensions: [number, number, number], position: [number, number, number], material: THREE.Material, radius = .055) => {
    const mesh = new THREE.Mesh(new RoundedBoxGeometry(...dimensions, 3, radius), material);
    mesh.name = name; mesh.position.set(...position); parent.add(mesh); return mesh;
  };
  const tube = (parent: THREE.Group, name: string, points: THREE.Vector3[], radius: number, material: THREE.Material) => {
    const curve = new THREE.CatmullRomCurve3(points);
    const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 24, radius, 8, false), material);
    mesh.name = name; parent.add(mesh); return mesh;
  };

  if (kind === "procurement") {
    // A continuous three-lobed ribbon, with glass faces and a narrow polished edge.
    class KnotCurve extends THREE.Curve<THREE.Vector3> {
      constructor() { super(); }
      getPoint(t: number, target = new THREE.Vector3()) {
        const u = t * Math.PI * 2, radius = 1 + .28 * Math.cos(3 * u);
        return target.set(radius * Math.cos(2 * u), radius * Math.sin(2 * u), .48 * Math.sin(3 * u));
      }
    }
    const curve = new KnotCurve(), segments = 256, radial = 32;
    const frames = curve.computeFrenetFrames(segments, true);
    const positions: number[] = [], colors: number[] = [], glassIndices: number[] = [], edgeIndices: number[] = [];
    const geometry = new THREE.BufferGeometry();
    const pearl = new THREE.Color(0xe7f4ff), sapphire = new THREE.Color(0x83b0e2), tint = new THREE.Color();
    for (let i = 0; i <= segments; i++) {
      const u = i / segments * Math.PI * 2, p = curve.getPoint(i / segments), twist = u + .4;
      const normal = frames.normals[i], binormal = frames.binormals[i];
      tint.copy(pearl).lerp(sapphire, .22 + .2 * Math.sin(u - .7));
      for (let j = 0; j <= radial; j++) {
        const angle = j / radial * Math.PI * 2;
        const x = .32 * Math.cos(angle), y = .125 * Math.sin(angle);
        const a = x * Math.cos(twist) - y * Math.sin(twist), b = x * Math.sin(twist) + y * Math.cos(twist);
        positions.push(p.x + normal.x * a + binormal.x * b, p.y + normal.y * a + binormal.y * b, p.z + normal.z * a + binormal.z * b);
        colors.push(tint.r, tint.g, tint.b);
      }
    }
    for (let i = 0; i < segments; i++) {
      for (let j = 0; j < radial; j++) {
        const a = i * (radial + 1) + j, b = a + radial + 1;
        const indices = Math.abs(Math.cos((j + .5) / radial * Math.PI * 2)) > .96 ? edgeIndices : glassIndices;
        indices.push(a, a + 1, b, b, a + 1, b + 1);
      }
    }
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    geometry.setIndex([...glassIndices, ...edgeIndices]);
    geometry.addGroup(0, glassIndices.length, 0);
    geometry.addGroup(glassIndices.length, edgeIndices.length, 1);
    geometry.computeVertexNormals();
    const normals = geometry.getAttribute("normal"), average = new THREE.Vector3();
    const joinNormals = (a: number, b: number) => {
      average.set(normals.getX(a) + normals.getX(b), normals.getY(a) + normals.getY(b), normals.getZ(a) + normals.getZ(b)).normalize();
      normals.setXYZ(a, average.x, average.y, average.z); normals.setXYZ(b, average.x, average.y, average.z);
    };
    for (let i = 0; i <= segments; i++) joinNormals(i * (radial + 1), i * (radial + 1) + radial);
    for (let j = 0; j <= radial; j++) joinNormals(j, segments * (radial + 1) + j);
    const glass = new THREE.MeshPhysicalMaterial({ color: 0xffffff, vertexColors: true, metalness: 0,
      roughness: .075, transmission: .58, thickness: .52, ior: 1.48, dispersion: .12,
      attenuationColor: 0x9acbff, attenuationDistance: 2.4, clearcoat: 1, clearcoatRoughness: .045,
      iridescence: .22, iridescenceThicknessRange: [140, 300], envMapIntensity: 1.5 });
    const edge = new THREE.MeshPhysicalMaterial({ color: 0xe9f3ff, metalness: 1, roughness: .1, clearcoat: 1, envMapIntensity: 1.3 });
    const ribbon = new THREE.Mesh(geometry, [glass, edge]);
    ribbon.name = "sculpted-glass-knot"; root.add(ribbon);
    root.rotation.set(-.22, .38, -.18);
  } else {
    const clipboard = new THREE.Group(); clipboard.name = "clipboard";
    clipboard.position.set(-.43, .12, -.22); clipboard.rotation.set(-.04, .14, .075); root.add(clipboard);
    box(clipboard, "chrome-rim", [1.55, 2.1, .16], [0, 0, 0], chrome, .1);
    box(clipboard, "blue-shell", [1.48, 2.03, .18], [0, 0, 0], ice, .09);
    box(clipboard, "ivory-paper", [1.31, 1.8, .05], [0, -.035, .115], ivory, .065);
    box(clipboard, "clip-base", [.66, .2, .095], [0, .91, .18], chrome);
    const clip = new THREE.Mesh(new THREE.TorusGeometry(.135, .055, 12, 36), chrome);
    clip.name = "clip-eye"; clip.position.set(0, 1.065, .17); clipboard.add(clip);
    for (let row = 0; row < 3; row++) {
      const y = .46 - row * .5;
      box(clipboard, `check-rim-${row}`, [.27, .28, .045], [-.43, y, .165], chrome, .04);
      box(clipboard, `check-face-${row}`, [.235, .245, .05], [-.43, y, .18], ivory, .035);
      tube(clipboard, `check-${row}`, [new THREE.Vector3(-.51, y, .22), new THREE.Vector3(-.45, y - .06, .22), new THREE.Vector3(-.35, y + .07, .22)], .024, blue);
      box(clipboard, `line-${row}`, [.62, .055, .035], [.14, y + .045, .165], blue, .025);
      box(clipboard, `short-line-${row}`, [.44, .045, .035], [.05, y - .07, .165], blue, .02);
    }
    const parcel = new THREE.Group(); parcel.name = "parcel";
    parcel.position.set(.48, -.64, .64); parcel.rotation.set(.06, -.38, .025); root.add(parcel);
    box(parcel, "parcel-body", [1.23, .96, .94], [0, 0, 0], ivory, .075);
    // An exposed front bezel; a closed outer chrome box would hide the cream body entirely.
    box(parcel, "parcel-rim", [1.21, .94, .025], [0, 0, .472], chrome, .012);
    box(parcel, "parcel-front", [1.17, .9, .035], [0, 0, .481], ivory, .017);
    box(parcel, "parcel-tape-top", [.25, .024, .87], [0, .478, .01], blue, .01);
    const tape = new THREE.Shape();
    tape.moveTo(-.125, .46); tape.lineTo(.125, .46); tape.lineTo(.125, -.06);
    tape.lineTo(0, .02); tape.lineTo(-.125, -.06); tape.closePath();
    const tapeMesh = new THREE.Mesh(new THREE.ExtrudeGeometry(tape, { depth: .025, bevelEnabled: true, bevelSegments: 2, steps: 1, bevelSize: .009, bevelThickness: .009 }), blue);
    tapeMesh.name = "parcel-tape-front"; tapeMesh.position.z = .507; parcel.add(tapeMesh);

    const bubble = new THREE.Group(); bubble.name = "support-message";
    bubble.position.set(.9, .62, .1); bubble.rotation.set(.04, -.17, -.12); root.add(bubble);
    const outline = new THREE.Shape();
    outline.moveTo(-.35, -.25); outline.quadraticCurveTo(-.49, -.25, -.49, -.1);
    outline.lineTo(-.49, .22); outline.quadraticCurveTo(-.49, .37, -.34, .37);
    outline.lineTo(.34, .37); outline.quadraticCurveTo(.49, .37, .49, .22);
    outline.lineTo(.49, -.1); outline.quadraticCurveTo(.49, -.25, .34, -.25);
    outline.lineTo(.25, -.25); outline.lineTo(.22, -.43); outline.lineTo(.02, -.25); outline.closePath();
    for (const [name, scale, depth, material] of [["bubble-rim", 1.06, .12, chrome], ["bubble-face", 1, .145, ice]] as const) {
      const mesh = new THREE.Mesh(new THREE.ExtrudeGeometry(outline, { depth, bevelEnabled: true, bevelSegments: 3, steps: 1, bevelSize: .04, bevelThickness: .04, curveSegments: 12 }), material);
      mesh.name = name; mesh.scale.set(scale, scale, 1); bubble.add(mesh);
    }
    const pearl = new THREE.SphereGeometry(.06, 16, 12);
    for (let i = 0; i < 3; i++) {
      const dot = new THREE.Mesh(pearl, ivory); dot.name = `message-dot-${i}`; dot.position.set((i - 1) * .22, .045, .23); bubble.add(dot);
    }
    root.rotation.set(.16, -.3, -.06);
  }
  return root;
}
