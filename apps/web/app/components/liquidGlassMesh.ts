/** Original, bounded WebGL glass mesh. No DOM capture, textures or dependencies. */
const vertex = `
precision highp float;
attribute vec2 a_uv;
uniform vec2 u_size, u_pointer;
uniform float u_variant, u_gutter;
varying vec2 v_uv;
varying vec3 v_normal;
void main() {
  v_uv = a_uv;
  vec2 p = a_uv * 2.0 - 1.0;
  float amplitude = u_variant < 0.5 ? 3.0 : 13.0;
  // A curved sheet, not a rotated DOM rectangle. Cross-curvature follows the hand.
  float z = amplitude * (u_pointer.x * p.x * p.x + u_pointer.y * p.y * p.y
    + 0.45 * (u_pointer.x - u_pointer.y) * p.x * p.y);
  vec2 slope = amplitude * vec2(2.0 * u_pointer.x * p.x + 0.45 * (u_pointer.x - u_pointer.y) * p.y,
    2.0 * u_pointer.y * p.y + 0.45 * (u_pointer.x - u_pointer.y) * p.x) / (u_size * 0.5);
  v_normal = normalize(vec3(-slope, 1.0));
  vec2 base = p * (u_size - 2.0 * u_gutter) / u_size;
  vec2 position = base + vec2(u_pointer.x, -u_pointer.y) * z / u_size;
  float perspective = 1.0 - z / 1500.0;
  vec2 displacement = (position / perspective - base) * u_size * 0.5;
  // Smoothly bound the projected motion inside a real guard band, including spring overshoot.
  // Unlike clamping the final vertex, this never creates a hard, stationary barrier.
  float limit = min(24.0, u_gutter - 6.0);
  displacement /= sqrt(vec2(1.0) + displacement * displacement / (limit * limit));
  gl_Position = vec4(base + displacement * 2.0 / u_size, z / 100.0, 1.0);
}`;

const fragment = `
precision highp float;
uniform vec2 u_size, u_pointer;
uniform float u_dark, u_variant, u_gutter;
uniform vec4 u_radii;
varying vec2 v_uv;
varying vec3 v_normal;
float outline(vec2 p, vec2 halfSize, float r) {
  vec2 q = abs(p) - halfSize + r;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
void main() {
  vec2 dimensions = u_size - 2.0 * u_gutter;
  vec2 p = (v_uv - 0.5) * dimensions;
  // CSS is the sole source of all four corners, including responsive asymmetry.
  float radius = p.y > 0.0 ? (p.x < 0.0 ? u_radii.x : u_radii.y) : (p.x < 0.0 ? u_radii.w : u_radii.z);
  radius = clamp(radius - 1.0, 1.0, min(dimensions.x, dimensions.y) * 0.5 - 1.0);
  float d = outline(p, dimensions * 0.5 - 1.0, radius);
  float coverage = 1.0 - smoothstep(-0.8, 0.8, d);
  if (coverage < 0.01) discard;
  vec2 gradient = normalize(vec2(
    outline(p + vec2(0.7,0.0), dimensions * 0.5 - 1.0, radius) - d,
    outline(p + vec2(0.0,0.7), dimensions * 0.5 - 1.0, radius) - d) + 0.0001);
  float bevel = exp(-abs(d + 3.0) / 4.2);
  vec3 normal = normalize(v_normal + vec3(gradient * bevel * 1.65, 0.0));
  vec3 light = normalize(vec3(-0.6 + u_pointer.x * 0.38, 0.85 + u_pointer.y * 0.2, 1.1));
  float shine = pow(max(dot(normal, light),0.0), 18.0);
  float fresnel = pow(1.0 - clamp(normal.z,0.0,1.0), 2.2);
  float lip = exp(-abs(d + 1.5) / 1.1);
  float caustic = exp(-abs(d + 9.0) / 2.0);
  float diagonal = u_variant > 1.5 ? v_uv.x * 0.7 + v_uv.y : v_uv.x * 0.25 - v_uv.y;
  // GLSL pow(x, 2.0) is undefined for negative x; Metal and ANGLE differ here.
  float reflectionDistance = (diagonal - (u_variant > 1.5 ? 0.85 : -0.28) - u_pointer.x * 0.11) / 0.12;
  float reflection = exp(-reflectionDistance * reflectionDistance);
  vec3 silver = mix(vec3(0.59,0.71,0.82),vec3(0.91,0.96,1.0),shine);
  vec3 color = mix(silver,vec3(1.0),clamp(lip * 0.8 + shine * 0.5,0.0,1.0));
  color = mix(color,vec3(0.30,0.46,0.63),caustic * 0.38);
  float alpha = lip * 0.72 + bevel * 0.24 + fresnel * 0.22 + shine * bevel * 0.42 + reflection * (0.13 - u_dark * 0.07);
  gl_FragColor = vec4(color, clamp(alpha,0.0,0.86) * coverage);
}`;

type Material = "rail" | "help" | "procurement";

/** Check the real framebuffer, not just successful shader compilation. */
function intactFrame(gl: WebGLRenderingContext, variant: Material, width: number, height: number, gutter: number) {
  const pixel = new Uint8Array(4);
  const alpha = (x: number, y: number) => {
    gl.readPixels(Math.round((gutter + (width - 2 * gutter) * x) / width * gl.drawingBufferWidth),
      Math.round((gutter + (height - 2 * gutter) * y) / height * gl.drawingBufferHeight), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
    return pixel[3];
  };
  // The interior is translucent in both themes. The opaque cyan slabs in the
  // reported Safari captures violate this bound; a lost/empty frame also fails.
  for (const x of [.25, .5, .75]) for (const y of variant === "rail" ? [.5] : [.25, .5, .75]) {
    if (alpha(x, y) > 96) return false;
  }
  const reflectionY = variant === "procurement" ? .5 : .405;
  return alpha(.5, reflectionY) > 5 && gl.getError() === gl.NO_ERROR;
}

/** Original glass renderer for action and guidance shells; categories use CSS only. */
export function createGlassMesh(host: HTMLElement, canvas: HTMLCanvasElement, variant: Material) {
  const gl = canvas.getContext("webgl", { alpha: true, antialias: false, depth: false, stencil: false, premultipliedAlpha: false, powerPreference: "low-power" });
  if (!gl) return;
  // Pixel-space distances and their gradients need full float precision. If the
  // GPU cannot supply it, keep the CSS material rather than draw corrupt glass.
  const precision = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT);
  if (!precision || precision.precision < 16 || precision.rangeMax < 62) { host.dataset.glassFallback = "precision"; return; }
  let gutter = 8;
  const shaders: WebGLShader[] = [];
  const compile = (type: number, source: string) => {
    const shader = gl.createShader(type);
    if (!shader) throw new Error("shader");
    shaders.push(shader); gl.shaderSource(shader, source); gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error("compile");
    return shader;
  };
  const program = gl.createProgram(), buffer = gl.createBuffer();
  let frame = 0, disposed = false, visible = true, lost = false, width = 0, height = 0, previous = 0;
  let verified = false, cleanup: (() => void) | undefined;
  let x = 0, y = 0, vx = 0, vy = 0, tx = 0, ty = 0;
  const release = () => {
    // A lost context has already invalidated its resources. Deleting old handles
    // after restoration contaminates the new context's error state.
    if (lost) return;
    if (buffer) gl.deleteBuffer(buffer); if (program) gl.deleteProgram(program); for (const shader of shaders) gl.deleteShader(shader);
  };
  try {
    if (!program || !buffer) throw new Error("allocation");
    gl.attachShader(program, compile(gl.VERTEX_SHADER, vertex)); gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragment)); gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("link");
  } catch { release(); return; }
  const points: number[] = [];
  const columns = 64, rows = variant === "rail" ? 8 : 24;
  for (let j = 0; j < rows; j++) for (let i = 0; i < columns; i++) {
    const a = i / columns, b = j / rows, c = (i + 1) / columns, d = (j + 1) / rows;
    points.push(a,b,c,b,a,d,a,d,c,b,c,d);
  }
  gl.useProgram(program); gl.bindBuffer(gl.ARRAY_BUFFER, buffer); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(points), gl.STATIC_DRAW);
  const attribute = gl.getAttribLocation(program!, "a_uv"); gl.enableVertexAttribArray(attribute); gl.vertexAttribPointer(attribute, 2, gl.FLOAT, false, 0, 0);
  const corners = gl.getUniformLocation(program!, "u_radii"), guardBand = gl.getUniformLocation(program!, "u_gutter");
  const size = gl.getUniformLocation(program!, "u_size"), pointer = gl.getUniformLocation(program!, "u_pointer"), dark = gl.getUniformLocation(program!, "u_dark");
  gl.uniform1f(gl.getUniformLocation(program!, "u_variant"), variant === "rail" ? 0 : variant === "help" ? 1 : 2);
  const request = () => { if (!frame && !disposed && !lost && visible && !document.hidden && width > 0 && height > 0) frame = requestAnimationFrame(draw); };
  const draw = (time: number) => {
    frame = 0;
    const dt = previous ? Math.min((time - previous) / 1000, 0.032) : 1 / 60; previous = time;
    // Mass 1 / stiffness 100 / damping 10; runs only until the bounded spring rests.
    vx += ((tx - x) * 100 - vx * 10) * dt; vy += ((ty - y) * 100 - vy * 10) * dt;
    x += vx * dt; y += vy * dt;
    const moving = Math.abs(tx-x) + Math.abs(ty-y) + Math.abs(vx) + Math.abs(vy) > 0.002;
    if (!moving) { x = tx; y = ty; vx = vy = 0; previous = 0; }
    gl.viewport(0,0,canvas.width,canvas.height);
    gl.uniform2f(size,width,height); gl.uniform2f(pointer,x,-y);
    gl.uniform1f(dark,document.documentElement.dataset.theme === "dark" ? 1 : 0);
    gl.clearColor(0,0,0,0); gl.clear(gl.COLOR_BUFFER_BIT); gl.drawArrays(gl.TRIANGLES,0,points.length / 2);
    if (!verified) {
      if (!intactFrame(gl, variant, width, height, gutter)) {
        cleanup?.(); host.dataset.glassFallback = "invalid-frame"; return;
      }
      verified = true; delete host.dataset.glassFallback;
    }
    if (!canvas.dataset.ready) { canvas.dataset.ready = "true"; host.dataset.meshReady = "true"; }
    if (moving) request();
  };
  const reset = () => { tx = ty = 0; request(); };
  const move = (event: PointerEvent) => {
    if (event.pointerType !== "mouse") return;
    const box = host.getBoundingClientRect();
    tx = Math.max(-1,Math.min(1,(event.clientX - box.left) / box.width * 2 - 1));
    ty = Math.max(-1,Math.min(1,(event.clientY - box.top) / box.height * 2 - 1)); request();
  };
  const pause = () => {
    cancelAnimationFrame(frame); frame = 0; previous = 0; x = y = tx = ty = vx = vy = 0;
    if (!document.hidden) request();
  };
  const resize = new ResizeObserver(() => {
    const box = host.getBoundingClientRect();
    gutter = Math.max(8,Math.min(32,box.left,window.innerWidth - box.right));
    host.style.setProperty("--glass-gutter",`${gutter}px`); gl.uniform1f(guardBand,gutter);
    width = box.width + gutter * 2; height = box.height + gutter * 2;
    const scale = Math.min(1,1100 / width,600 / height);
    canvas.width = Math.max(1,Math.round(width * scale)); canvas.height = Math.max(1,Math.round(height * scale));
    const style = getComputedStyle(host);
    gl.uniform4f(corners,parseFloat(style.borderTopLeftRadius),parseFloat(style.borderTopRightRadius),parseFloat(style.borderBottomRightRadius),parseFloat(style.borderBottomLeftRadius)); request();
  });
  const intersection = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; if (!visible) pause(); else request(); });
  const theme = new MutationObserver(request);
  const contextLost = (event: Event) => { event.preventDefault(); lost = true; cancelAnimationFrame(frame); frame = 0; delete canvas.dataset.ready; delete host.dataset.meshReady; };
  host.addEventListener("pointermove",move); host.addEventListener("pointerleave",reset); host.addEventListener("pointercancel",reset);
  canvas.addEventListener("webglcontextlost",contextLost); window.addEventListener("blur",pause); document.addEventListener("visibilitychange",pause);
  resize.observe(host); intersection.observe(host); theme.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
  cleanup = () => {
    disposed = true; cancelAnimationFrame(frame); resize.disconnect(); intersection.disconnect(); theme.disconnect();
    host.removeEventListener("pointermove",move); host.removeEventListener("pointerleave",reset); host.removeEventListener("pointercancel",reset);
    canvas.removeEventListener("webglcontextlost",contextLost); window.removeEventListener("blur",pause); document.removeEventListener("visibilitychange",pause);
    delete canvas.dataset.ready; delete host.dataset.meshReady; host.style.removeProperty("--glass-gutter"); release();
  };
  return cleanup;
}
