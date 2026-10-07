// Cleanmold — interface: malha escaneada com os alvos, lista de alvos, antes/depois e sólido de revolução.
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { computeBoundsTree, disposeBoundsTree, acceleratedRaycast } from 'three-mesh-bvh';

// seleção e clique acelerados (árvore de caixas por malha): sem isso, cada toque percorreria todos os triângulos
THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree;
THREE.Mesh.prototype.raycast = acceleratedRaycast;

const TOKEN = new URLSearchParams(location.search).get('t') || '';
const JANELA = Math.random().toString(36).slice(2, 12);          // cada janela dá o seu sinal: fechar uma não encerra a outra
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const SVGNS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, ...filhos) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? '' : v);
  }
  for (const f of filhos) if (f !== null && f !== undefined && f !== false) e.append(f);
  return e;
};
// troca o conteúdo de um elemento, ignorando o que for nulo (replaceChildren escreveria "null")
const por = (cx, ...filhos) => cx.replaceChildren(...filhos.filter((f) => f !== null && f !== undefined && f !== false));
const sv = (tag, attrs = {}, ...filhos) => {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'text') e.textContent = v; else e.setAttribute(k, v);
  }
  for (const f of filhos) if (f) e.append(f);
  return e;
};
// números para a tela: vírgula decimal, sinal de menos tipográfico e nunca "−0"
const br = (s) => (/^-[0.]*$/.test(s) ? s.slice(1) : s).replace('-', '−').replace('.', ',');
const num = (v, d = 2) => (v === null || v === undefined || !isFinite(v)) ? '—' : br(Number(v).toFixed(d));
const milhar = (v) => (v === null || v === undefined) ? '—' : Math.round(v).toLocaleString('pt-BR');
const semMovimento = matchMedia('(prefers-reduced-motion: reduce)').matches;

const MSG_PARADO = 'O Cleanmold foi encerrado ou não responde. Feche esta janela e abra o programa de novo.';
let semResposta = 0, parado = false, sinal = null;
function servidorParou() {
  if (parado) return;
  parado = true;
  if (sinal) clearInterval(sinal);
  S.ocupado = false; S.exportando = false;
  travar();
  $('#progresso').hidden = true;
  if (!S.r) $('#vazio').hidden = false;
  estado('erro', 'Cleanmold encerrado');
  toast(MSG_PARADO, true, 0);
}

async function api(caminho, corpo, bruto) {
  const op = { method: corpo !== undefined ? 'POST' : 'GET', headers: { 'X-Cleanmold': TOKEN } };
  if (corpo !== undefined) {
    if (corpo instanceof Blob) op.body = corpo;
    else { op.body = JSON.stringify(corpo); op.headers['Content-Type'] = 'application/json'; }
  }
  let r;
  try { r = await fetch(caminho, op); } catch (e) {
    if (++semResposta >= 3) servidorParou();              // três pedidos seguidos sem resposta: o programa não está mais lá
    throw new Error(MSG_PARADO);
  }
  semResposta = 0;
  if (!r.ok) {
    let msg = 'Falha (' + r.status + ')';
    try { msg = (await r.json()).erro || msg; } catch (e) { /* sem corpo */ }
    throw new Error(msg);
  }
  return bruto ? r.arrayBuffer() : r.json();
}

// ms = 0: fica até a pessoa fechar. Mensagens iguais não se empilham.
function toast(msg, erro = false, ms = 6000) {
  for (const o of $$('#toasts .toast')) if (o.dataset.msg === msg) { if (o.dataset.fixo) return; o.remove(); }
  const t = el('div', { class: 'toast' + (erro ? ' erro' : ''), role: erro ? 'alert' : null }, el('span', { text: msg }));
  t.dataset.msg = msg;
  if (!ms) t.dataset.fixo = '1';
  if (!ms || ms > 9000) t.append(el('button', { class: 'x', 'aria-label': 'Fechar', text: '×', onclick: () => t.remove() }));
  $('#toasts').append(t);
  if (ms) setTimeout(() => t.remove(), ms);
}

// ============================================================================
// visor 3D
// ============================================================================
const COR = {
  peca: new THREE.Color(0xb4b9c1), alvo: new THREE.Color(0x1fa368), alvoSel: new THREE.Color(0x0b6b41),
  fora: new THREE.Color(0xd9962b), solto: new THREE.Color(0x86c9a7), remendo: new THREE.Color(0x35c486), solido: 0x1fa368,
  selecao: new THREE.Color(0x2f6fde), furo: new THREE.Color(0xd92d20), furoSel: new THREE.Color(0xf59e0b), furoBorda: new THREE.Color(0x8a929c),
};
const LEVE_A_PARTIR = 350000;                 // acima disso, a vista em movimento usa a malha leve

function lerBlocos(buf) {
  const n = new DataView(buf).getUint32(0, true);
  const cab = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, n)));
  const base = 4 + n;
  const tipos = { V: Float32Array, I: Uint32Array, J: Uint32Array, M: Uint16Array, P: Float32Array, O: Uint32Array };
  const bloco = (nome) => {
    if (!cab.blocos[nome]) return null;
    const [off, qt] = cab.blocos[nome];
    const T = tipos[nome[0]];
    return new T(buf.slice(base + off, base + off + qt * T.BYTES_PER_ELEMENT));
  };
  return { cab, bloco };
}

class Visor {
  constructor(recipiente, tela) {
    this.rec = recipiente;
    this.r = new THREE.WebGLRenderer({ canvas: tela, antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
    this.r.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    this.cena = new THREE.Scene();
    this.cam = new THREE.PerspectiveCamera(26, 1, 1, 100000);
    this.cam.up.set(0, 0, 1);
    this.cam.position.set(600, -700, 500);
    this.ctl = new OrbitControls(this.cam, tela);
    this.ctl.enableDamping = !semMovimento; this.ctl.dampingFactor = 0.14;
    this.ctl.rotateSpeed = 0.9; this.ctl.zoomSpeed = 1.1;
    this.ctl.zoomToCursor = true;
    this.ctl.addEventListener('change', () => { this.planosDeCorte(); this.sujo = true; this.mexeu(); });
    this.ctl.addEventListener('start', () => { for (const o of $$('[data-cam]')) o.classList.remove('ativo'); this.mexeu(); });
    this.cena.add(new THREE.HemisphereLight(0xffffff, 0x8c929b, 1.2));
    const l1 = new THREE.DirectionalLight(0xffffff, 1.9); l1.position.set(-1, 1.4, 1.2);
    const l2 = new THREE.DirectionalLight(0xe4f5ec, 0.8); l2.position.set(1.2, -0.4, -0.8);
    this.cam.add(l1); this.cam.add(l2); this.cena.add(this.cam);        // a luz acompanha a câmera
    this.gMalha = new THREE.Group(); this.gSolido = new THREE.Group(); this.gFuros = new THREE.Group();
    this.cena.add(this.gSolido, this.gMalha, this.gFuros);
    // dois lados: escaneamento de um lado só é uma casca aberta, e o verso também precisa aparecer
    this.matMalha = new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide });
    this.matSolido = new THREE.MeshStandardMaterial({ color: COR.solido, metalness: 0.2, roughness: 0.5, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    this.centro = new THREE.Vector3(); this.raio = 100; this.sujo = true; this.anim = null;
    this.raycaster = new THREE.Raycaster(); this.raycaster.firstHitOnly = true;
    this.malhas = {};                                        // fase -> { geo, marcas, sel, cab, leve: { geo, marcas, sel } | null }
    this.movendo = false; this.tParar = null;
    // cursor do pincel: um anel deitado na superfície
    const pts = []; for (let k = 0; k <= 64; k++) { const a = k / 64 * Math.PI * 2; pts.push(new THREE.Vector3(Math.cos(a), Math.sin(a), 0)); }
    const gAnel = new THREE.BufferGeometry().setFromPoints(pts);
    this.anel = new THREE.Group();
    this.anel.add(new THREE.Line(gAnel, new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true })),
      new THREE.Line(gAnel, new THREE.LineBasicMaterial({ color: 0x1a1f25, depthTest: false, transparent: true })));
    this.anel.children[1].scale.setScalar(1.035);
    this.anel.renderOrder = 10; this.anel.visible = false; this.cena.add(this.anel);
    this.furos = null;
    tela.addEventListener('webglcontextlost', (ev) => ev.preventDefault());
    tela.addEventListener('webglcontextrestored', () => { this.sujo = true; });
    new ResizeObserver(() => this.redimensionar()).observe(recipiente);
    this.redimensionar();
    const laco = () => { requestAnimationFrame(laco); this.quadro(); };
    laco();
  }

  redimensionar() {
    const w = this.rec.clientWidth, h = this.rec.clientHeight;
    if (!w || !h) return;
    this.r.setSize(w, h, false);
    this.cam.aspect = w / h;
    this.cam.updateProjectionMatrix();
    this.sujo = true;
  }

  quadro() {
    if (!this.rec.clientWidth) return;
    if (this.anim) { this.passoAnim(); this.mexeu(); }
    if (this.ctl.update() || this.sujo) { this.sujo = false; this.r.render(this.cena, this.cam); }
  }

  // A vista está em movimento: enquanto gira, desloca ou aproxima, mostra a malha leve (poucos triângulos); parou,
  // volta a malha cheia. É o que mantém o giro solto com milhões de triângulos.
  mexeu() {
    if (!this.movendo) { this.movendo = true; this.montar(); }
    clearTimeout(this.tParar);
    this.tParar = setTimeout(() => { this.movendo = false; this.montar(); }, 170);
  }

  limpar(grupo) {
    for (const m of [...grupo.children]) { grupo.remove(m); if (m.geometry) m.geometry.dispose(); }
  }

  soltar(d) { if (!d) return; if (d.geo.boundsTree) d.geo.disposeBoundsTree(); d.geo.dispose(); if (d.leve) d.leve.geo.dispose(); }

  esquecer() {
    for (const d of Object.values(this.malhas)) this.soltar(d);
    this.malhas = {}; this.limpar0(); this.limpar(this.gSolido); this.esconderFuros(); this.fase = null; this.sujo = true;
  }

  geometria(buf) {
    const { cab, bloco } = lerBlocos(buf);
    const V = bloco('V');
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(V, 3));
    geo.setIndex(new THREE.BufferAttribute(bloco('I'), 1));
    geo.computeVertexNormals();
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(V.length), 3));
    geo.computeBoundingSphere();
    return { geo, marcas: bloco('M') || new Uint16Array(V.length / 3), sel: new Uint8Array(V.length / 3), cab };
  }

  guardar(fase, buf, bufLeve) {
    const d = this.geometria(buf);
    d.leve = bufLeve ? this.geometria(bufLeve) : null;
    this.soltar(this.malhas[fase]);
    this.malhas[fase] = d;
    if (fase === 'antes' || !this.malhas.antes) { this.centro.copy(d.geo.boundingSphere.center); this.raio = d.geo.boundingSphere.radius; this.limites(); }
  }

  limites() {
    this.ctl.minDistance = this.raio * 0.004; this.ctl.maxDistance = this.raio * 30;
  }

  dados() { return this.malhas[this.fase === 'solido' ? (this.malhas.depois ? 'depois' : 'antes') : this.fase]; }

  mostrar(fase) {
    this.fase = fase;
    this.gSolido.visible = fase === 'solido';
    this.opacidadeMalha(fase === 'solido' ? this.opSolido : 1);
    this.montar();
  }

  // põe na cena a malha da fase: a cheia parada, a leve em movimento
  montar() {
    const d = this.dados();
    const usarLeve = !!(d && d.leve && this.movendo && d.cab.triangulos > LEVE_A_PARTIR);
    const geo = d ? (usarLeve ? d.leve.geo : d.geo) : null;
    const atual = this.gMalha.children[0];
    if (atual && atual.geometry === geo) return;
    this.limpar0();
    if (geo) this.gMalha.add(new THREE.Mesh(geo, this.matMalha));
    this.sujo = true;
  }

  limpar0() { for (const m of [...this.gMalha.children]) this.gMalha.remove(m); }

  opacidadeMalha(v) {
    this.matMalha.opacity = v; this.matMalha.transparent = v < 0.995; this.matMalha.depthWrite = v > 0.9;
    this.gMalha.visible = v > 0.02; this.sujo = true;
  }

  carregarSolido(buf) {
    this.limpar(this.gSolido);
    if (!buf) return;
    const { bloco } = lerBlocos(buf);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(bloco('V'), 3));
    geo.setIndex(new THREE.BufferAttribute(bloco('I'), 1));
    geo.computeVertexNormals();
    this.gSolido.add(new THREE.Mesh(geo, this.matSolido));
    this.sujo = true;
  }

  // cores: "antes" pinta cada alvo conforme marcado/selecionado; "depois" pinta os remendos; por cima, a pintura do pincel
  pintar(fase, alvos, sel, apagarSoltos) {
    const m = this.malhas[fase]; if (!m) return;
    const tab = (cor) => [cor.r, cor.g, cor.b];
    const peca = tab(COR.peca), solto = tab(apagarSoltos ? COR.solto : COR.peca), rem = tab(COR.remendo), pin = tab(COR.selecao);
    const porAlvo = (alvos || []).map((x) => tab(x.i === sel ? COR.alvoSel : (x.marcado ? COR.alvo : COR.fora)));
    for (const d of [m, m.leve]) {
      if (!d) continue;
      const c = d.geo.getAttribute('color'), a = c.array, M = d.marcas, S_ = d.sel;
      for (let k = 0; k < M.length; k++) {
        const v = M[k];
        let cor = peca;
        if (S_[k]) cor = pin;
        else if (v === 65535) cor = rem;
        else if (fase === 'antes') { if (v === 1) cor = solto; else if (v >= 2) cor = porAlvo[v - 2] || peca; }
        else if (v === 1) cor = rem;
        a[3 * k] = cor[0]; a[3 * k + 1] = cor[1]; a[3 * k + 2] = cor[2];
      }
      c.needsUpdate = true;
    }
    this.sujo = true;
  }

  // ---------- pincel ----------
  aplicarSelecao(fase, ids, idsLeve) {
    const m = this.malhas[fase]; if (!m) return;
    m.sel.fill(0);
    if (ids) for (let k = 0; k < ids.length; k++) m.sel[ids[k]] = 1;
    if (m.leve) { m.leve.sel.fill(0); if (idsLeve) for (let k = 0; k < idsLeve.length; k++) m.leve.sel[idsLeve[k]] = 1; }
  }

  // árvore de caixas da malha cheia da fase (montada uma vez por malha)
  preparar(fase) {
    const m = this.malhas[fase];
    if (m && !m.geo.boundsTree) m.geo.computeBoundsTree({ maxLeafTris: 12 });
    return !!m;
  }

  // prévia da pincelada na tela (a seleção de verdade é feita no programa, na malha inteira, e volta em seguida)
  previa(fase, ponto, raio, modo, normal) {
    const m = this.malhas[fase]; if (!m || !m.geo.boundsTree) return;
    const esfera = new THREE.Sphere(ponto, raio), r2 = raio * raio;
    const idx = m.geo.index.array, cor = m.geo.getAttribute('color'), a = cor.array;
    const pin = COR.selecao, tmp = new THREE.Vector3(), nt = new THREE.Vector3();
    m.geo.boundsTree.shapecast({
      intersectsBounds: (caixa) => esfera.intersectsBox(caixa),
      intersectsTriangle: (tri, i, contido) => {
        if (!contido) { tri.getMidpoint(tmp); if (tmp.distanceToSquared(ponto) > r2) return false; }
        if (normal) { tri.getNormal(nt); if (nt.dot(normal) < -0.2) return false; }          // o outro lado de uma parede fina fica de fora
        if (!modo) return false;                       // despintar: a tela só atualiza quando o programa responde
        for (let k = 0; k < 3; k++) { const v = idx[3 * i + k]; a[3 * v] = pin.r; a[3 * v + 1] = pin.g; a[3 * v + 2] = pin.b; }
        return false;
      },
    });
    cor.needsUpdate = true; this.sujo = true;
  }

  cursor(ponto, normal, raio) {
    if (!ponto) { if (this.anel.visible) { this.anel.visible = false; this.sujo = true; } return; }
    this.anel.position.copy(ponto).addScaledVector(normal, Math.max(0.05, raio * 0.01));
    this.anel.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
    this.anel.scale.setScalar(raio);
    this.anel.visible = true; this.sujo = true;
  }

  modoArrasto(nome) {
    const b = this.ctl.mouseButtons;
    if (nome === 'pincel') { b.LEFT = -1; b.MIDDLE = THREE.MOUSE.PAN; b.RIGHT = THREE.MOUSE.ROTATE; }
    else { b.LEFT = nome === 'mover' ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE; b.MIDDLE = THREE.MOUSE.DOLLY; b.RIGHT = THREE.MOUSE.PAN; }
  }

  planosDeCorte() {
    const d = this.cam.position.distanceTo(this.ctl.target);
    const perto = Math.max(0.05, d / 400), longe = d + this.raio * 6;
    if (Math.abs(this.cam.near - perto) > perto * 0.2 || Math.abs(this.cam.far - longe) > longe * 0.2) { this.cam.near = perto; this.cam.far = longe; this.cam.updateProjectionMatrix(); }
  }

  irPara(dir, alvo, raio, imediato, cima) {
    const w = this.rec.clientWidth || 1, h = this.rec.clientHeight || 1;
    const folga = Math.min(1, w / h);
    const dist = Math.min(this.ctl.maxDistance, Math.max(this.ctl.minDistance, 1.2 * raio / Math.tan(THREE.MathUtils.degToRad(this.cam.fov / 2)) / folga));
    const pos = alvo.clone().addScaledVector(dir.clone().normalize(), dist);
    if (cima) this.cam.up.copy(cima);
    if (imediato || semMovimento || !this.rec.clientWidth) { this.anim = null; this.cam.position.copy(pos); this.ctl.target.copy(alvo); this.ctl.update(); this.planosDeCorte(); this.sujo = true; return; }
    this.anim = { t0: performance.now(), dur: 520, p0: this.cam.position.clone(), p1: pos, a0: this.ctl.target.clone(), a1: alvo.clone() };
  }

  passoAnim() {
    const a = this.anim; let k = Math.min(1, (performance.now() - a.t0) / a.dur);
    k = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    const alvo = a.a0.clone().lerp(a.a1, k);
    const v0 = a.p0.clone().sub(a.a0), v1 = a.p1.clone().sub(a.a1);
    const d = v0.length() + (v1.length() - v0.length()) * k;
    const dir = v0.normalize().lerp(v1.normalize(), k);
    if (dir.lengthSq() < 1e-6) dir.set(0, 1, 0);
    this.cam.position.copy(alvo).addScaledVector(dir.normalize(), d);
    this.ctl.target.copy(alvo); this.planosDeCorte(); this.sujo = true;
    if (k >= 1) this.anim = null;
  }

  vista(nome, imediato) {
    const dirs = { iso: [0.62, -0.62, 0.48], cima: [0.0001, -0.0002, 1], frente: [0, -1, 0.0001], lado: [1, 0, 0.0001] };
    this.cam.up.set(0, 0, 1);
    this.irPara(new THREE.Vector3(...dirs[nome]), this.centro.clone(), this.raio, imediato);
  }

  // olha para um alvo: de lado e um pouco de cima em relação ao eixo dele
  olharAlvo(a) {
    const c = new THREE.Vector3(...a.centro), e = new THREE.Vector3(...a.eixo).normalize();
    const lado = new THREE.Vector3().crossVectors(e, Math.abs(e.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0)).normalize();
    const dir = lado.multiplyScalar(0.8).addScaledVector(e, 0.75);
    const meio = c.clone().addScaledVector(e, this.fase === 'antes' ? a.altura * 0.4 : 2);
    this.irPara(dir, meio, this.fase === 'antes' ? Math.max(42, a.altura * 0.8) : 34, false, e);
  }

  // o que está debaixo do cursor: ponto, normal do triângulo e marca
  tocar(ev) {
    const d = this.dados();
    if (!d || !this.gMalha.visible) return null;
    if (!this.malhaCheia || this.malhaCheia.geometry !== d.geo) this.malhaCheia = new THREE.Mesh(d.geo, this.matMalha);
    const b = this.r.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2(((ev.clientX - b.left) / b.width) * 2 - 1, -((ev.clientY - b.top) / b.height) * 2 + 1), this.cam);
    const hit = this.raycaster.intersectObject(this.malhaCheia, false)[0];
    if (!hit) return null;
    const M = d.marcas;
    const marca = Math.max(M[hit.face.a], M[hit.face.b], M[hit.face.c]);
    const normal = hit.face.normal.clone();
    if (normal.dot(this.raycaster.ray.direction) > 0) normal.negate();        // verso de uma casca: normal para o lado de quem olha
    return { ponto: hit.point.clone(), normal, normalFace: hit.face.normal.clone(), marca: marca === 65535 ? 0 : marca };
  }

  pegar(ev) {
    const h = this.tocar(ev);
    return h ? { ponto: [h.ponto.x, h.ponto.y, h.ponto.z], marca: h.marca } : null;
  }

  // ---------- furos ----------
  esconderFuros() { this.limpar(this.gFuros); this.furos = null; this.sujo = true; }

  carregarFuros(buf) {
    this.limpar(this.gFuros);
    const { cab, bloco } = lerBlocos(buf);
    const P = bloco('P'), O = bloco('O');
    this.furos = { lista: cab.furos, P, O, sel: -1 };
    if (!P || !P.length) { this.sujo = true; return; }
    const n = P.length / 3;
    const seg = new Uint32Array(2 * n);
    let q = 0;
    for (let k = 0; k + 1 < O.length; k++) for (let i = O[k]; i < O[k + 1]; i++) { seg[q++] = i; seg[q++] = i + 1 < O[k + 1] ? i + 1 : O[k]; }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(P, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(P.length), 3));
    geo.setIndex(new THREE.BufferAttribute(seg, 1));
    this.gFuros.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, depthTest: false, transparent: true, opacity: 0.95 })));
    const pontos = new THREE.Points(geo, new THREE.PointsMaterial({ vertexColors: true, size: 3.5, sizeAttenuation: false, depthTest: false, transparent: true }));
    this.gFuros.add(pontos);
    this.gFuros.renderOrder = 5;
    this.corFuros(-1);
  }

  corFuros(sel) {
    const f = this.furos; if (!f || !this.gFuros.children.length) return;
    f.sel = sel;
    const c = this.gFuros.children[0].geometry.getAttribute('color'), a = c.array;
    for (let k = 0; k + 1 < f.O.length; k++) {
      const cor = k === sel ? COR.furoSel : (f.lista[k].borda ? COR.furoBorda : COR.furo);
      for (let i = f.O[k]; i < f.O[k + 1]; i++) { a[3 * i] = cor.r; a[3 * i + 1] = cor.g; a[3 * i + 2] = cor.b; }
    }
    c.needsUpdate = true; this.sujo = true;
  }

  // o contorno mais perto do cursor, em pixels na tela (ou -1)
  furoPerto(ev, maxPx = 14) {
    const f = this.furos; if (!f || !f.P.length) return -1;
    const b = this.r.domElement.getBoundingClientRect();
    const mx = ev.clientX - b.left, my = ev.clientY - b.top;
    const v = new THREE.Vector3();
    let melhor = -1, dm = maxPx * maxPx;
    for (let k = 0; k + 1 < f.O.length; k++) {
      for (let i = f.O[k]; i < f.O[k + 1]; i++) {
        v.set(f.P[3 * i], f.P[3 * i + 1], f.P[3 * i + 2]).project(this.cam);
        if (v.z > 1) continue;
        const dx = (v.x * 0.5 + 0.5) * b.width - mx, dy = (-v.y * 0.5 + 0.5) * b.height - my;
        const d2 = dx * dx + dy * dy;
        if (d2 < dm) { dm = d2; melhor = k; }
      }
    }
    return melhor;
  }

  olharFuro(f) {
    const c = new THREE.Vector3(...f.centro), n = new THREE.Vector3(...f.normal).normalize();
    const lado = new THREE.Vector3().crossVectors(n, Math.abs(n.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0)).normalize();
    this.irPara(n.clone().multiplyScalar(0.9).addScaledVector(lado, 0.45), c, Math.max(12, f.diametro * 1.1), false);
  }
}

// ============================================================================
// estado
// ============================================================================
const S = { r: null, fase: 'antes', sel: null, ferr: 'selecionar', ocupado: false, nLog: 0, log: [], versaoApp: '', versaoMalha: {},
  tarefa: 'analise', exportando: false, aba: 'alvos', pincel: { diam: 25, modo: 1 }, furos: null, furoSel: -1, nUltima: 0, fila: Promise.resolve() };
let visor = null;
try { visor = new Visor($('#area3d'), $('#tela')); visor.opSolido = 0.35; } catch (e) { visor = null; }

function estado(cls, texto) { $('#stPonto').className = cls; $('#stTexto').textContent = texto; }

// ---------- abrir e analisar ----------
async function abrirMalha() {
  if (S.ocupado) { toast('Espere terminar o que está em andamento.', true); return; }
  try {
    const r = await api('/api/abrir', {});
    if (r.cancelado) return;
    mostrarArquivo(r.nome, r.tamanho);
    decidirAbertura(r);
  } catch (e) { toast(e.message, true); }
}

async function enviarArquivo(arq) {
  try {
    mostrarProgresso('Copiando o arquivo', 0.03, arq.size > 5e7 ? 'Arquivo grande: a cópia leva alguns segundos.' : '');
    const r = await api('/api/enviar?nome=' + encodeURIComponent(arq.name), arq);
    mostrarArquivo(r.nome, r.tamanho);
    $('#progresso').hidden = true;
    if (!S.r) $('#vazio').hidden = false;
    decidirAbertura(r);
  } catch (e) { $('#progresso').hidden = true; if (!S.r) $('#vazio').hidden = false; toast(e.message, true); }
}

const gb = (b) => br((b / 1073741824).toFixed(1));

// Malha grande: antes de abrir, mostra quanto ela pede do computador e oferece otimizar na abertura.
function decidirAbertura(r) {
  const a = r.avaliacao;
  if (!a || !a.otimizar || !(a.grande || a.apertado)) { iniciar('analise', '/api/analisar', {}); return; }
  const n = a.triangulos || a.estimado;
  const linhas = [el('div', {}, el('b', { class: 'mono', text: r.nome }), ` tem ${a.triangulos ? '' : 'cerca de '}${milhar(n)} triângulos (${br((a.tamanho / 1048576).toFixed(0))} MB).`)];
  if (a.livre) linhas.push(el('div', { class: 'fraco', text: `Para abrir inteira o Cleanmold precisa de uns ${gb(a.precisa)} GB de memória; este computador tem ${gb(a.livre)} GB livres agora (de ${gb(a.total)} GB).` }));
  if (a.nao_cabe) linhas.push(el('div', { class: 'alerta', text: 'É malha demais para este computador, mesmo otimizando na abertura. Feche outros programas antes de continuar, ou exporte a malha do Control X com menos triângulos.' }));
  else if (a.apertado) linhas.push(el('div', { class: 'alerta', text: 'Abrir inteira deve encher a memória e travar o computador. Otimize ao abrir.' }));
  $('#grandeTexto').replaceChildren(...linhas);
  $('#grandeInteira').querySelector('small').textContent = a.apertado ? 'Não recomendado neste computador.' : '';
  $('input[name=grande][value=otimizar]').checked = true;
  $('#grandeTol').hidden = false;
  $('#mGrande').hidden = false;
}

function confirmarAbertura() {
  const otim = $('input[name=grande]:checked').value === 'otimizar';
  $('#mGrande').hidden = true;
  iniciar('analise', '/api/analisar', otim ? { otimizar: Number($('#grandeNivel').value) } : {});
}

function mostrarArquivo(nome, tamanho) {
  $('#topoArquivo').textContent = nome; S.arquivo = nome;
  $('#topoQuando').textContent = '';
  if (!S.r) por($('#cartaoMalha'), el('div', { class: 'mono', text: nome }), tamanho ? el('div', { class: 'fraco', text: br((tamanho / 1048576).toFixed(1)) + ' MB' }) : null);
  for (const b of $$('[data-arquivo]')) b.disabled = false;
}

const pctDe = (log, re, de, ate) => { let f = 0; for (const l of log) { const m = re.exec(l); if (m) f = Math.max(f, de + Number(m[1]) / 100 * (ate - de)); } return f; };
const TAREFAS = {
  analise: { titulo: 'Procurando os alvos', fracao: (log) => {
    let f = 0.04;
    const otim = log.some((l) => /^Otimizando a malha/.test(l));
    for (const l of log) {
      if (/^Lendo/.test(l)) f = Math.max(f, 0.05);
      if (/triângulos$/.test(l)) f = Math.max(f, otim ? 0.12 : 0.25);
      if (/pontos de amostra/.test(l)) f = Math.max(f, otim ? 0.66 : 0.42);
      if (otim) {
        const m = /Otimizando a malha… (\d+)%/.exec(l); if (m) f = Math.max(f, 0.12 + Number(m[1]) / 100 * 0.34);
        const e = /Acertando as emendas… (\d+)%/.exec(l); if (e) f = Math.max(f, 0.46 + Number(e[1]) / 100 * 0.08);
        if (/Medindo o desvio/.test(l)) f = Math.max(f, 0.55);
        if (/^Malha otimizada/.test(l)) f = Math.max(f, 0.6);
        continue;
      }
      const m = /Procurando pés.*?(\d+)%/.exec(l); if (m) f = Math.max(f, 0.45 + Number(m[1]) / 100 * 0.2);
      if (/Conferindo esferas/.test(l)) f = Math.max(f, 0.7);
      if (/alvos encontrados/.test(l)) f = Math.max(f, 0.82);
      if (/Indexando/.test(l)) f = Math.max(f, 0.86);
      if (/Preparando a vista/.test(l)) f = Math.max(f, 0.92);
    }
    return Math.min(f, 0.98);
  } },
  limpeza: { titulo: 'Retirando os alvos', fracao: (log) => {
    let f = 0.04;
    for (const l of log) {
      if (/Indexando/.test(l)) f = Math.max(f, 0.1);
      const m = /Retirando alvos… (\d+)%/.exec(l); if (m) f = Math.max(f, 0.12 + Number(m[1]) / 100 * 0.6);
      if (/^Malha limpa/.test(l)) f = Math.max(f, 0.78);
      if (/Preparando a vista/.test(l)) f = Math.max(f, 0.84);
    }
    return Math.min(f, 0.98);
  } },
  otimizar: { titulo: 'Otimizando a malha', fracao: (log) => {
    let f = Math.max(0.03, pctDe(log, /Otimizando a malha… (\d+)%/, 0.03, 0.6), pctDe(log, /Acertando as emendas… (\d+)%/, 0.6, 0.72));
    for (const l of log) {
      if (/Medindo o desvio/.test(l)) f = Math.max(f, 0.74);
      if (/^Malha otimizada/.test(l)) f = Math.max(f, 0.8);
      if (/Procurando os alvos na malha nova/.test(l)) f = Math.max(f, 0.82);
      if (/Preparando a vista/.test(l)) f = Math.max(f, 0.93);
    }
    return Math.min(f, 0.98);
  } },
  // tarefas curtas: em vez da barra de progresso, um aviso pequeno no canto do modelo
  edicao: { titulo: 'Editando a malha', leve: true },
  furos: { titulo: 'Furos', leve: true },
  reparo: { titulo: 'Examinando a malha', leve: true },
  desfazer: { titulo: 'Desfazendo', leve: true },
  solido: { titulo: 'Reconhecendo as formas da peça', fracao: (log) => {
    let f = 0.05;
    for (const l of log) {
      if (/Procurando o eixo/.test(l)) f = Math.max(f, 0.15);
      if (/Cortando a malha/.test(l)) f = Math.max(f, 0.45);
      if (/Ajustando retas/.test(l)) f = Math.max(f, 0.85);
    }
    return Math.min(f, 0.98);
  } },
};

async function iniciar(tarefa, rota, corpo) {
  try {
    S.nLog = tarefa === 'analise' ? 0 : (await api('/api/estado?desde=999999')).n_log;
    await api(rota, corpo);
    S.tarefa = tarefa; S.log = [];
    acompanhar();
  } catch (e) {
    $('#progresso').hidden = true;
    if (!S.r) $('#vazio').hidden = false;
    $('#ocupadinho').hidden = true;
    if (!parado) estadoParado();
    toast(e.message, true, 9000);
  }
}

function estadoParado() {
  if (S.exportando) estado('andando', 'Gerando arquivos');
  else if (S.falha) estado('erro', S.r ? `A análise de ${S.falha.arquivo} falhou — na tela continua ${S.r.arquivo}` : 'A análise falhou');
  else if (S.r && S.r.limpo) estado('ok', 'Limpeza concluída');
  else if (S.r) estado('ok', S.r.alvos.length + (S.r.alvos.length === 1 ? ' alvo encontrado' : ' alvos encontrados'));
  else estado('', 'Pronto para abrir uma malha');
}

function travar() {
  $('.dir').inert = true; $('.esq').inert = true;
  for (const b of $$('[data-precisa], [data-arquivo], [data-precisa-saida], [data-desfazer], [data-ferr], [data-acao=abrir], #btPrincipal')) b.disabled = true;
  $('#barraPincel').inert = true;
  for (const f of $$('.fundo')) f.hidden = true;
}

function ocupar(sim) {
  S.ocupado = sim;
  $('.dir').inert = sim; $('#secOpcoes').inert = sim; $('#secIdent').inert = sim; $('#barraPincel').inert = sim;
  if (sim && visor) visor.cursor(null);
  atualizarBotoes();
}

function atualizarBotoes() {
  const tem = !!S.r, oc = S.ocupado;
  for (const b of $$('[data-precisa]')) b.disabled = oc || !tem;
  for (const b of $$('[data-precisa-saida]')) b.disabled = oc || !tem || !(S.r.limpo || S.r.editada);
  for (const b of $$('[data-desfazer]')) {
    b.disabled = oc || !tem || !S.r.desfazer;
    const t = tem && S.r.desfazer ? 'Desfazer ' + S.r.desfazer : 'Desfazer';
    if (b.classList.contains('icone')) { b.title = t + ' (Ctrl+Z)'; b.setAttribute('aria-label', t); } else b.textContent = t;
  }
  $('[data-ferr=manual]').disabled = oc || !tem || S.r.limpo;
  $('[data-ferr=pincel]').disabled = oc || !tem;
  for (const b of $$('[data-fase]')) b.disabled = !tem || (b.dataset.fase === 'depois' && !S.r.limpo);
  const p = $('#btPrincipal');
  if (!tem) { p.textContent = 'Retirar alvos'; p.disabled = true; return; }
  const n = S.r.alvos.filter((a) => a.marcado).length;
  if (S.r.limpo && !mudou()) { p.textContent = 'Gerar arquivos'; p.disabled = oc; p.dataset.oque = 'exportar'; }
  else if (!S.r.limpo && !n && !S.r.soltos && S.r.editada) { p.textContent = 'Gerar arquivos'; p.disabled = oc; p.dataset.oque = 'exportar'; }
  else { p.textContent = S.r.limpo ? 'Retirar de novo' : (n ? `Retirar ${n} ${n === 1 ? 'alvo' : 'alvos'}` : 'Retirar pedaços soltos'); p.disabled = oc || (!n && !S.r.soltos); p.dataset.oque = 'limpar'; }
}

// a seleção (ou as opções) mudou depois da última limpeza?
function mudou() {
  if (!S.r || !S.r.limpo) return false;
  if (S.r.alvos.some((a) => a.marcado !== a.retirado)) return true;
  const o = lerOpcoes(false);
  return !o || Math.abs(o.margem - S.r.opcoes.margem) > 1e-9 || Math.abs(o.alcance - S.r.opcoes.alcance) > 1e-9 || o.remover_soltos !== S.r.opcoes.remover_soltos;
}

function mostrarFalha(falha) {
  S.falha = falha || null;
  const cx = $('#vazioErro');
  cx.hidden = !falha || !!S.r;
  if (!falha) return;
  cx.replaceChildren(el('b', { text: `A análise de ${falha.arquivo} falhou.` }), el('span', { text: falha.erro }));
  if (!S.r) $('#vazio').hidden = false;
  estadoParado();
}

function mostrarProgresso(titulo, fracao, nota) {
  $('#vazio').hidden = true;
  $('#progresso').hidden = false;
  $('#progTitulo').textContent = titulo;
  $('#progPct').textContent = (fracao * 100).toFixed(0) + ' %';
  $('#progBarra').style.width = (fracao * 100).toFixed(0) + '%';
  $('#progNota').textContent = nota || '';
  estado('andando', titulo + ' ' + (fracao * 100).toFixed(0) + ' %');
}

function acompanhar() {
  ocupar(true);
  if (S.tarefa === 'analise') mostrarFalha(null);
  const T = TAREFAS[S.tarefa];
  const mostrar = (nota) => {
    if (T.leve) { $('#ocupadinho').hidden = false; $('#ocupTexto').textContent = nota || T.titulo + '…'; estado('andando', nota || T.titulo); }
    else mostrarProgresso(T.titulo, T.fracao(S.log), nota);
  };
  const passo = async () => {
    let e;
    try { e = await api('/api/estado?desde=' + S.nLog); } catch (x) { if (!parado) setTimeout(passo, 1500); return; }
    S.log.push(...e.log); S.nLog = e.n_log;
    mostrar(S.log.length ? S.log[S.log.length - 1] : '');
    if (e.ocupado) { setTimeout(passo, T.leve ? 250 : 500); return; }
    $('#progresso').hidden = true; $('#ocupadinho').hidden = true;
    if (e.erro) {
      if (!S.r && e.tem_resultado) try { await carregarResultado(true); } catch (x) { /* fica só o aviso */ }
      ocupar(false);
      if (S.tarefa === 'analise') mostrarFalha(e.falha || { arquivo: S.arquivo || 'a malha', erro: e.erro });
      else { estadoParado(); toast(e.erro, true, 0); }
      if (!S.r) $('#vazio').hidden = false;
      return;
    }
    try { await carregarResultado(S.tarefa === 'analise'); } catch (x) {
      if (parado) return;
      S.ocupado = false; travar();
      estado('erro', 'Não consegui carregar o resultado');
      toast('O trabalho terminou, mas não consegui carregar o resultado (' + x.message + '). Feche esta janela e abra o Cleanmold de novo.', true, 0);
      return;
    }
    ocupar(false);
    if (S.tarefa === 'limpeza') trocarFase('depois');
    if (S.tarefa === 'solido') trocarFase('solido');
    if (S.tarefa === 'analise' && S.r.fase_edicao === 'depois') trocarFase('depois');
  };
  mostrar('');
  passo();
}

async function carregarResultado(novaPeca) {
  const r = await api('/api/resultado');
  await aplicarResultado(r, novaPeca);
}

async function buscarMalha(fase) {
  const v = S.r.versoes ? S.r.versoes[fase] : S.r.versao;
  if (!visor || S.versaoMalha[fase] === v) return false;
  const cheia = await api('/api/malha.bin?fase=' + fase, undefined, true);
  // a malha leve só existe para malhas grandes: o cabeçalho da cheia diz quantos triângulos a malha de verdade tem
  const n = new DataView(cheia).getUint32(0, true);
  const cab = JSON.parse(new TextDecoder().decode(new Uint8Array(cheia, 4, n)));
  let leve = null;
  if (cab.originais > 300000) try { leve = await api('/api/malha.bin?nivel=leve&fase=' + fase, undefined, true); } catch (e) { leve = null; }
  visor.guardar(fase, cheia, leve);
  S.versaoMalha[fase] = v;
  return true;
}

async function buscarSelecao() {
  if (!visor || !S.r) return;
  if (!S.r.selecao) { for (const f of ['antes', 'depois']) visor.aplicarSelecao(f, null, null); return; }
  try {
    const { cab, bloco } = lerBlocos(await api('/api/selecao.bin', undefined, true));
    visor.aplicarSelecao(cab.fase, bloco('I'), bloco('J'));
  } catch (e) { /* sem seleção na tela: o programa continua com a dele */ }
}

async function buscarFuros() {
  if (!visor || !S.r) return;
  if (!S.r.furos_prontos) { visor.esconderFuros(); S.furos = null; S.furoSel = -1; return; }
  try {
    visor.carregarFuros(await api('/api/furos.bin', undefined, true));
    S.furos = visor.furos.lista; S.furoSel = -1;
    visor.gFuros.visible = S.aba === 'malha' && S.fase === S.r.fase_edicao;
  } catch (e) { visor.esconderFuros(); S.furos = null; }
}

async function aplicarResultado(r, novaPeca) {
  const antes = S.r;
  S.r = r;
  if (novaPeca) {
    S.sel = null; S.falha = null; S.fase = 'antes'; S.versaoMalha = {}; S.versaoSolido = -1; S.furos = null; S.furoSel = -1;
    if (visor) visor.esquecer();
    $('#expPasta').value = r.pasta || '';
    $('#idPeca').value = r.ident.peca || ''; $('#idResp').value = r.ident.responsavel || '';
    $('#vazioErro').hidden = true; $('#expResultado').hidden = true;
    if (S.ferr !== 'selecionar' && S.ferr !== 'mover') escolherFerramenta('selecionar');
  }
  if (novaPeca || !antes) { $('#opMargem').value = br(String(r.opcoes.margem)); $('#opAlcance').value = br(String(r.opcoes.alcance)); $('#opSoltos').checked = r.opcoes.remover_soltos; }
  $('#vazio').hidden = true;
  for (const s of ['#secResumo', '#secOpcoes', '#secIdent']) $(s).hidden = false;
  $('#topoArquivo').textContent = r.arquivo;
  $('#topoQuando').textContent = r.analisado_em ? '· analisado em ' + r.analisado_em : '';
  if (S.sel !== null && !r.alvos[S.sel]) S.sel = null;
  if (visor) {
    try {
      await buscarMalha('antes');
      if (r.limpo) await buscarMalha('depois');
      if (r.solido && r.solido.tipo && S.versaoSolido !== r.versao) { visor.carregarSolido(await api('/api/solido.bin', undefined, true)); S.versaoSolido = r.versao; }
      if (!r.solido || !r.solido.tipo) visor.carregarSolido(null);
      await buscarSelecao();
      await buscarFuros();
    } catch (e) { toast('Não consegui carregar a malha para a tela: ' + e.message, true); }
    if (S.fase === 'depois' && !r.limpo) S.fase = 'antes';
    visor.mostrar(S.fase);
    if (S.ferr === 'pincel') { if (S.fase !== r.fase_edicao) escolherFerramenta('selecionar'); else visor.preparar(S.fase); }
    if (novaPeca) { visor.vista('iso', true); for (const o of $$('[data-cam]')) o.classList.toggle('ativo', o.dataset.cam === 'iso'); }
  }
  if (!S.ocupado) ocupar(false);
  estadoParado();
  desenharTudo();
  // o que a última edição fez
  if (r.ultima && r.ultima.n !== S.nUltima) {
    S.nUltima = r.ultima.n;
    const av = r.ultima.avisos || [];
    if (!novaPeca || r.ultima.tipo === 'otimizar') toast(r.ultima.texto + (av.length ? '\nConferir: ' + av.join('; ') + '.' : ''), av.length > 0, av.length ? 0 : 9000);
  }
}

// ---------- desenho ----------
function desenharTudo() {
  desenharEsquerda(); desenharDireita(); pintar(); desenharLegenda(); atualizarBotoes(); atualizarPincel();
  for (const b of $$('[data-fase]')) b.classList.toggle('ativa', b.dataset.fase === S.fase);
  $('#grpOpacidade').hidden = S.fase !== 'solido';
  $('#stVersao').textContent = 'Cleanmold ' + S.versaoApp;
  if (visor && S.r) visor.gFuros.visible = !!S.furos && S.aba === 'malha' && S.fase === S.r.fase_edicao;
}

function pintar() {
  if (!visor || !S.r) return;
  const soltos = $('#opSoltos').checked;
  visor.pintar('antes', S.r.alvos, S.sel, soltos);
  if (S.r.limpo) visor.pintar('depois', null, null, soltos);
}

function desenharLegenda() {
  const cx = $('#legendaCores');
  cx.hidden = !S.r;
  if (!S.r) return;
  const item = (cor, texto) => el('span', {}, el('i', { style: 'background:' + cor }), texto);
  const pin = S.r.selecao ? item('#2f6fde', 'pintado com o pincel') : null;
  const furo = S.furos && S.aba === 'malha' && S.fase === S.r.fase_edicao ? item('#d92d20', 'contorno aberto (furo)') : null;
  if (S.fase === 'antes') por(cx, S.r.alvos.some((a) => a.marcado) ? item('#1fa368', 'alvo marcado para retirar') : null,
    S.r.alvos.some((a) => !a.marcado) ? item('#d9962b', 'alvo desmarcado') : null,
    $('#opSoltos').checked && S.r.soltos ? item('#86c9a7', 'pedaço solto (será apagado)') : null,
    S.r.editada ? item('#35c486', 'remendo') : null, pin, furo, item('#b4b9c1', 'peça'));
  else if (S.fase === 'depois') por(cx, item('#35c486', 'remendo (superfície reconstruída)'), pin, furo, item('#b4b9c1', 'peça escaneada'));
  else por(cx, item('#1fa368', 'peça de revolução reconhecida'), item('#b4b9c1', 'malha escaneada (transparente)'));
}

function contar() {
  const r = S.r, a = r.alvos;
  const sit = a.map(situacao);
  return { marcados: a.filter((x) => x.marcado).length, retirados: a.filter((x) => x.retirado).length,
    ok: sit.filter((s) => s.cls === 'ok').length, conferir: sit.filter((s) => s.cls === 'lim' || s.cls === 'fora').length,
    duvidosos: a.filter((x) => !x.seguro).length };
}

function situacao(a) {
  if (!S.r.limpo || !a.retirado) return a.marcado ? { cls: 'neutro', t: 'a retirar' } : { cls: 'neutro', t: 'fica' };
  if (!a.preenchido) return { cls: 'fora', t: 'furo aberto' };
  if (a.aviso || (a.degrau || 0) > 0.8) return { cls: 'lim', t: 'conferir' };
  return { cls: 'ok', t: 'fechado' };
}

function desenharEsquerda() {
  const r = S.r; if (!r) return;
  const [lo, hi] = r.caixa;
  const reduzida = r.original && r.triangulos_atual < 0.97 * r.original.triangulos;
  por($('#cartaoMalha'), el('div', { class: 'mono', text: r.arquivo }),
    el('div', { class: 'fraco', text: milhar(r.triangulos_atual) + ' triângulos' + (reduzida ? ` (aberta com ${milhar(r.original.triangulos)})` : '') }),
    el('div', { class: 'fraco', text: `${num(hi[0] - lo[0], 0)} × ${num(hi[1] - lo[1], 0)} × ${num(hi[2] - lo[2], 0)} mm · aresta ${num(r.aresta, 2)} mm` }),
    r.triangulos_atual > 3000000 ? el('button', { class: 'bt-texto', style: 'justify-self:start;margin-top:4px', text: 'Otimizar a malha', onclick: () => abrirAba('malha') }) : null);
  const c = contar();
  const n = (rot, v, cls) => el('div', { class: 'num ' + (cls || '') }, rot, el('b', { text: String(v) }));
  $('#resumoNums').replaceChildren(
    n('Alvos encontrados', r.alvos.length, 'destaque'), n('Pedaços soltos', r.soltos),
    r.limpo ? n('Fechados sem ressalva', c.ok) : n('Marcados', c.marcados),
    r.limpo ? n('A conferir', c.conferir, c.conferir ? 'atencao' : '') : n('Confiança baixa', c.duvidosos, c.duvidosos ? 'atencao' : ''));
  $('#stConta').textContent = r.limpo ? `malha limpa: ${milhar(r.triangulos_limpa)} triângulos` : (r.editada ? `malha de trabalho: ${milhar(r.triangulos_atual)} triângulos` : '');
}

function desenharDireita() {
  const r = S.r;
  $('#dirVazio').hidden = !!r; $('#abasDir').hidden = !r;
  $('#dirCheio').hidden = !r || S.aba !== 'alvos'; $('#dirMalha').hidden = !r || S.aba !== 'malha';
  if (!r) return;
  for (const b of $$('[data-aba]')) { b.classList.toggle('ativa', b.dataset.aba === S.aba); if (b.dataset.aba === 'alvos') b.textContent = S.fase === 'solido' ? 'Sólido' : 'Alvos'; }
  if (S.aba === 'malha') return desenharMalha();
  if (S.fase === 'solido') return desenharSolido();
  const cx = $('#dirCheio');
  const c = contar();
  const partes = [el('div', { class: 'lista-topo' }, el('div', { class: 't', text: 'Alvos' }),
    el('span', { class: 'chip', text: r.alvos.length + (r.alvos.length === 1 ? ' encontrado' : ' encontrados') }))];
  // o que fazer agora
  if (!r.limpo) {
    partes.push(el('div', { class: 'caixa-acao' }, el('div', { class: 'forte', text: `${c.marcados} ${c.marcados === 1 ? 'alvo marcado' : 'alvos marcados'} para retirar` }),
      el('div', { text: (r.soltos ? `${r.soltos} pedaços soltos (esferas, dodecaedros e lascas que o escaneamento separou) também saem. ` : '') +
        'Confira no modelo: o que está em verde sai, o que está em laranja fica.' }),
      el('button', { class: 'bt primario', text: 'Retirar e fechar os furos', onclick: limpar })));
  } else if (mudou()) {
    partes.push(el('div', { class: 'caixa-acao' }, el('div', { class: 'forte', text: 'A seleção ou o recorte mudaram' }),
      el('div', { text: 'A malha limpa na tela ainda é a da limpeza anterior.' }), el('button', { class: 'bt primario', text: 'Retirar de novo', onclick: limpar })));
  } else {
    partes.push(el('div', { class: 'caixa-acao' }, el('div', { class: 'forte', text: `${c.retirados} ${c.retirados === 1 ? 'alvo retirado' : 'alvos retirados'}: ${c.ok} fechados sem ressalva` + (c.conferir ? `, ${c.conferir} a conferir` : '') }),
      el('div', { text: c.conferir ? 'Os marcados com “conferir” tinham rebarba do escaneamento, ressalto ou parede junto ao pé: olhe o remendo antes de medir em cima dele.' : 'Todos os furos assentaram na superfície de referência.' }),
      el('button', { class: 'bt primario', text: 'Gerar arquivos', onclick: () => abrirExportar() })));
  }
  if (!r.alvos.length) partes.push(el('div', { class: 'caixa-nota', text: 'Nenhum alvo foi reconhecido nesta malha. Se há alvos, use a ferramenta de indicar à mão (o alvo com a mira, na barra de cima) e clique no pé de cada um.' }));
  // tabela
  const todos = r.alvos.length && r.alvos.every((a) => a.marcado);
  const tb = el('div', { class: 'alvos' }, el('div', { class: 'al-cab' },
    el('input', { type: 'checkbox', checked: todos, 'aria-label': 'Marcar todos', onchange: (ev) => marcarVarios(() => ev.target.checked) }),
    el('span', { text: 'Nº' }), el('span', { text: 'Tipo' }), el('span', { text: 'Conf.' }), el('span', { style: 'text-align:right', text: 'Situação' })));
  for (const a of r.alvos) {
    const s = situacao(a);
    const linha = el('div', { class: 'al-linha' + (a.i === S.sel ? ' sel' : ''), 'data-i': a.i, onclick: (ev) => { if (ev.target.tagName !== 'INPUT' && !ev.target.closest('.al-det')) selecionar(a.i, true); } },
      el('input', { type: 'checkbox', checked: a.marcado, 'aria-label': 'Retirar o alvo ' + (a.i + 1), onchange: (ev) => marcar(a.i, ev.target.checked) }),
      el('span', { class: 'n', text: String(a.i + 1) }),
      el('span', { class: 'tp' }, a.nome, a.deformado ? el('small', { text: ' · pé amassado' }) : null),
      el('span', { class: 'cf' + (a.seguro ? '' : ' baixa'), text: a.manual ? '—' : (a.confianca * 100).toFixed(0) + ' %' }),
      el('span', { class: 'st' }, el('span', { class: 'sit ' + s.cls, text: s.t })));
    if (a.i === S.sel) {
      const det = el('div', { class: 'al-det' });
      det.append(el('span', {}, 'Pé em ', el('span', { class: 'mono', text: a.centro.map((v) => num(v, 1)).join('; ') }), ' mm · Ø ', el('span', { class: 'mono', text: num(2 * a.raio, 1) }), ' mm'));
      if (a.soltos) det.append(el('span', { text: `${a.soltos} ${a.soltos === 1 ? 'pedaço solto pertence' : 'pedaços soltos pertencem'} a este alvo.` }));
      if (!a.seguro) det.append(el('span', { class: 'obs', text: 'Confiança baixa: o padrão do pé saiu pouco nítido. Confira no modelo e marque se for alvo.' }));
      if (a.retirado) {
        if (a.referencia) det.append(el('span', {}, 'Remendo sobre ', el('span', { class: 'mono', text: a.referencia }),
          a.sigma != null ? ` · ruído da referência ${num(a.sigma, 3)} mm` : '', a.area ? ` · ${num(a.area, 0)} mm²` : ''));
        if (a.arestas) det.append(el('span', { text: `A aresta viva ao lado do alvo foi refeita (${a.arestas} ${a.arestas === 1 ? 'parede' : 'paredes'}).` }));
        if ((a.degrau || 0) > 0.8) det.append(el('span', { class: 'obs', text: `O contorno do furo fica até ${num(a.degrau, 1)} mm fora da referência.` }));
        if (a.aviso) det.append(el('span', { class: 'obs', text: a.aviso.charAt(0).toUpperCase() + a.aviso.slice(1) + '.' }));
      }
      const ac = el('div', { class: 'acoes' }, el('button', { class: 'bt-texto', text: 'Ver no modelo', onclick: () => selecionar(a.i, true) }));
      if (a.manual) ac.append(el('button', { class: 'bt-texto', text: 'Apagar da lista', onclick: () => esquecer(a.i) }));
      det.append(ac);
      linha.append(det);
    }
    tb.append(linha);
  }
  if (r.alvos.length) partes.push(tb);
  if (r.soltos_sem_alvo && !r.limpo) partes.push(el('p', { class: 'fraco', text: `${r.soltos_sem_alvo} pedaços soltos não estão perto de nenhum alvo (lascas e ruído do escaneamento).` + ($('#opSoltos').checked ? ' Também serão apagados.' : '') }));
  cx.replaceChildren(...partes);
}

// ---------- seleção ----------
function selecionar(i, moverCamera) {
  S.sel = i; S.aba = 'alvos';
  if (S.fase === 'solido') trocarFase(S.r.limpo ? 'depois' : 'antes'); else { desenharDireita(); pintar(); }
  const linha = $(`.al-linha[data-i="${i}"]`);
  if (linha) linha.scrollIntoView({ block: 'nearest' });
  if (moverCamera && visor && S.r.alvos[i]) { visor.olharAlvo(S.r.alvos[i]); for (const o of $$('[data-cam]')) o.classList.remove('ativo'); }
}

function marcar(i, sim) { S.r.alvos[i].marcado = sim; desenharTudo(); }
function marcarVarios(fn) { for (const a of S.r.alvos) a.marcado = !!fn(a); desenharTudo(); }

function trocarFase(f) {
  if (!S.r || (f === 'depois' && !S.r.limpo)) return;
  const antes = S.fase;
  S.fase = f;
  if (f === 'solido') S.aba = 'alvos';
  if (S.ferr === 'pincel' && f !== S.r.fase_edicao) escolherFerramenta('selecionar');
  if (S.ferr === 'manual' && f !== 'antes') escolherFerramenta('selecionar');
  if (visor) {
    visor.mostrar(f);
    if (f === 'solido' && antes !== 'solido') { visor.vista('iso'); for (const o of $$('[data-cam]')) o.classList.toggle('ativo', o.dataset.cam === 'iso'); }
  }
  desenharTudo();
}

function abrirAba(nome) {
  S.aba = nome;
  if (nome === 'malha' && S.r && S.fase !== S.r.fase_edicao) trocarFase(S.r.fase_edicao); else desenharTudo();
}

function lerOpcoes(avisar = true) {
  const ler = (id, nome, lo, hi) => {
    const v = Number(String($(id).value).trim().replace(',', '.'));
    if (!(v >= lo && v <= hi)) { if (avisar) toast(`${nome}: informe um valor entre ${br(String(lo))} e ${br(String(hi))} mm.`, true); return null; }
    return v;
  };
  const margem = ler('#opMargem', 'Margem', 0, 10), alcance = ler('#opAlcance', 'Alcance', 2, 30);
  if (margem === null || alcance === null) return null;
  return { margem, alcance, remover_soltos: $('#opSoltos').checked };
}

async function limpar() {
  if (!S.r || S.ocupado) return;
  const opcoes = lerOpcoes(); if (!opcoes) return;
  const escolha = S.r.alvos.filter((a) => a.marcado).map((a) => a.i);
  if (!escolha.length && !(opcoes.remover_soltos && S.r.soltos)) { toast('Marque pelo menos um alvo para retirar.', true); return; }
  await iniciar('limpeza', '/api/limpar', { escolha, opcoes });
}

// ---------- alvo indicado à mão ----------
function escolherFerramenta(nome) {
  if ((nome === 'manual' || nome === 'pincel') && (!S.r || S.ocupado)) return;
  if (nome === 'manual' && S.r.limpo) { toast('Os alvos já foram retirados. Para tirar mais alguma coisa, use o pincel.', true); return; }
  S.ferr = nome;
  for (const b of $$('[data-ferr]')) b.classList.toggle('ativo', b.dataset.ferr === nome);
  if (visor) { visor.modoArrasto(nome); if (nome !== 'pincel') visor.cursor(null); }
  $('#dicaManual').hidden = nome !== 'manual';
  $('#barraPincel').hidden = nome !== 'pincel';
  $('#tela').style.cursor = nome === 'manual' ? 'crosshair' : (nome === 'mover' ? 'grab' : '');
  $('#tela').classList.toggle('tela-pincel', nome === 'pincel');
  if (nome === 'manual' && S.fase !== 'antes') trocarFase('antes');
  if (nome === 'pincel') {
    if (S.fase !== S.r.fase_edicao) trocarFase(S.r.fase_edicao);
    atualizarPincel();
    // a árvore de seleção da malha na tela é montada na primeira vez (uma fração de segundo em malha grande)
    if (visor) { estado('andando', 'Preparando o pincel'); setTimeout(() => { visor.preparar(S.fase); estadoParado(); }, 30); }
  }
  if (S.r && S.aba === 'malha') desenharMalha();
}

// ---------- pincel ----------
const DIAM_MIN = 1, DIAM_MAX = 200;
const deslParaDiam = (v) => DIAM_MIN * Math.pow(DIAM_MAX / DIAM_MIN, v / 100);
const diamParaDesl = (d) => 100 * Math.log(d / DIAM_MIN) / Math.log(DIAM_MAX / DIAM_MIN);

function definirDiametro(d, origem) {
  d = Math.min(DIAM_MAX, Math.max(DIAM_MIN, d));
  S.pincel.diam = d;
  if (origem !== 'texto') $('#pinDiam').value = br(d >= 10 ? d.toFixed(0) : d.toFixed(1));
  if (origem !== 'desl') $('#pinDesl').value = String(diamParaDesl(d));
  try { localStorage.setItem('cleanmold.pincel', String(d)); } catch (e) { /* sem armazenamento */ }
}

function atualizarPincel() {
  const sel = S.r && S.r.selecao;
  $('#pinConta').textContent = sel ? `${milhar(sel.triangulos)} triângulos · ${num(sel.area, 0)} mm²` : 'nada pintado';
  for (const b of $$('[data-edit], [data-sel]')) b.disabled = !sel || S.ocupado;
  for (const b of $$('[data-pin]')) b.classList.toggle('ativo', Number(b.dataset.pin) === S.pincel.modo);
}

function aplicarSelecaoBin(buf) {
  const { cab, bloco } = lerBlocos(buf);
  S.r.selecao = cab.selecao;
  if (visor) { visor.aplicarSelecao(cab.fase, bloco('I'), bloco('J')); }
  pintar(); atualizarPincel(); desenharLegenda();
}

// as pinceladas vão para o programa em fila, na ordem em que foram dadas
function enviarPinceladas(pts) {
  S.fila = S.fila.then(async () => {
    try { aplicarSelecaoBin(await api('/api/pincel', { fase: S.r.fase_edicao, pinceladas: pts }, true)); }
    catch (e) { toast(e.message, true); await buscarSelecao(); pintar(); }
  });
  return S.fila;
}

async function mudarSelecao(acao) {
  if (!S.r || S.ocupado) return;
  await S.fila;
  try { aplicarSelecaoBin(await api('/api/selecao', { acao }, true)); } catch (e) { toast(e.message, true); }
}

async function editar(acao) {
  if (!S.r || S.ocupado) return;
  await S.fila;
  if (!S.r.selecao) { toast('Nada pintado. Arraste o pincel sobre a malha primeiro.', true); return; }
  await iniciar('edicao', '/api/editar', { fase: S.r.fase_edicao, acao, forca: Number($('#pinForca').value) });
}

async function desfazer() {
  if (!S.r || S.ocupado || !S.r.desfazer) return;
  await S.fila;
  await iniciar('desfazer', '/api/desfazer', {});
}

// ---------- malha e reparo ----------
function lerNumero(seletor, nome, lo, hi) {
  const v = Number(String($(seletor).value).trim().replace(',', '.'));
  if (!(v >= lo && v <= hi)) { toast(`${nome}: informe um valor entre ${br(String(lo))} e ${br(String(hi))}.`, true); return null; }
  return v;
}

async function otimizarMalha() {
  if (!S.r || S.ocupado) return;
  let tol = Number($('#otNivel').value);
  if (!tol) { tol = lerNumero('#otTol', 'Tolerância (mm)', 0.001, 1); if (tol === null) return; }
  await iniciar('otimizar', '/api/otimizar', { fase: S.r.fase_edicao, tolerancia: tol });
}

async function procurarFuros() {
  if (!S.r || S.ocupado) return;
  await iniciar('furos', '/api/furos', { fase: S.r.fase_edicao, acao: 'listar' });
}

async function fecharFuros(ids) {
  if (!S.r || S.ocupado) return;
  if (ids) {
    const f = S.furos && S.furos[ids[0]];
    if (f && f.borda && !confirm(`Este contorno tem ${num(f.diametro, 0)} mm e parece ser a borda da peça, não um furo. Fechar assim mesmo?`)) return;
    await iniciar('furos', '/api/furos', { fase: S.r.fase_edicao, acao: 'fechar', ids });
    return;
  }
  const ate = lerNumero('#fuAte', 'Diâmetro (mm)', 0.1, 2000); if (ate === null) return;
  try { localStorage.setItem('cleanmold.furos', String(ate)); } catch (e) { /* sem armazenamento */ }
  await iniciar('furos', '/api/furos', { fase: S.r.fase_edicao, acao: 'fechar', ate });
}

function escolherFuro(i, olhar) {
  S.furoSel = i;
  if (visor) { visor.corFuros(i); if (olhar && S.furos[i]) visor.olharFuro(S.furos[i]); }
  desenharMalha();
  const linha = $(`.fu-linha[data-i="${i}"]`);
  if (linha) linha.scrollIntoView({ block: 'nearest' });
}

async function examinar() {
  if (!S.r || S.ocupado) return;
  await iniciar('reparo', '/api/reparo', { fase: S.r.fase_edicao, acao: 'diagnostico' });
}

async function reparar() {
  if (!S.r || S.ocupado) return;
  const furos = $('#rpFuros').checked;
  let ate = null;
  if (furos) { ate = lerNumero('#rpAte', 'Diâmetro dos furos (mm)', 0.1, 2000); if (ate === null) return; }
  await iniciar('reparo', '/api/reparo', { fase: S.r.fase_edicao, acao: 'reparar', soltos: $('#rpSoltos').checked, nao_variedade: $('#rpLascas').checked,
    orientar: $('#rpVirados').checked, furos, furos_ate: ate });
}

function desenharMalha() {
  const r = S.r, cx = $('#dirMalha');
  if (!r) return;
  const guardado = {};
  for (const id of ['otNivel', 'otTol', 'fuAte', 'rpAte']) { const c = $('#' + id); if (c) guardado[id] = c.value; }
  for (const id of ['rpSoltos', 'rpLascas', 'rpVirados', 'rpFuros']) { const c = $('#' + id); if (c) guardado[id] = c.checked; }
  const val = (id, padrao) => (id in guardado ? guardado[id] : padrao);
  const mb = (b) => br((b / 1048576).toFixed(b > 104857600 ? 0 : 1)) + ' MB';
  const partes = [];
  // ---- malha de trabalho
  const medidas = el('div', { class: 'medidas' },
    el('span', { class: 'k', text: 'Triângulos agora' }), el('span', { class: 'v', text: milhar(r.triangulos_atual) }),
    el('span', { class: 'k', text: 'Como foi aberta' }), el('span', { class: 'v', text: milhar(r.original.triangulos) }),
    el('span', { class: 'k', text: 'Arquivo STL desta malha' }), el('span', { class: 'v', text: mb(r.tamanho_stl) }),
    el('span', { class: 'k', text: 'Arquivo aberto' }), el('span', { class: 'v', text: mb(r.original.tamanho) }));
  partes.push(el('div', { class: 'bloco' },
    el('h3', {}, 'Malha de trabalho', el('span', { class: 'chip', text: r.fase_edicao === 'depois' ? 'já sem os alvos' : 'ainda com os alvos' })),
    el('p', { text: r.fase_edicao === 'depois' ? 'As ferramentas abaixo mexem na malha limpa (vista Depois).' : 'As ferramentas abaixo mexem na malha como foi aberta (vista Antes). Depois de retirar os alvos, passam a mexer na malha limpa.' }),
    medidas,
    r.desfazer ? el('div', { class: 'linha' }, el('button', { class: 'bt', text: 'Desfazer ' + r.desfazer, onclick: desfazer })) : null));
  // ---- otimizar
  const o = r.otimizacao;
  const niveis = r.niveis || { fiel: 0.02, equilibrado: 0.05, leve: 0.1 };
  const sel = el('select', { id: 'otNivel', 'aria-label': 'Tolerância', onchange: () => { $('#otTol').hidden = $('#otNivel').value !== '0'; } },
    el('option', { value: String(niveis.fiel), text: `Fiel · ${br(String(niveis.fiel))} mm` }),
    el('option', { value: String(niveis.equilibrado), text: `Equilibrado · ${br(String(niveis.equilibrado))} mm` }),
    el('option', { value: String(niveis.leve), text: `Leve · ${br(niveis.leve.toFixed(2))} mm` }),
    el('option', { value: '0', text: 'Outra tolerância…' }));
  sel.value = val('otNivel', String(niveis.equilibrado));
  const outra = el('input', { type: 'text', id: 'otTol', inputmode: 'decimal', value: val('otTol', '0,05'), 'aria-label': 'Tolerância em milímetros', hidden: sel.value !== '0' });
  partes.push(el('div', { class: 'bloco' }, el('h3', { text: 'Otimizar: menos triângulos, mesma forma' }),
    el('p', { text: 'Onde a peça é lisa, muitos triângulos pequenos viram poucos grandes; onde há raio, canto ou ressalto, eles ficam. A tolerância é o quanto a malha nova pode se afastar da original; o desvio que resultou é medido e mostrado. A borda da malha e o contorno dos furos não são mexidos.' }),
    r.otimizar_disponivel ? el('div', { class: 'linha' }, sel, outra, el('button', { class: 'bt primario', text: 'Otimizar', onclick: otimizarMalha })) :
      el('div', { class: 'res av', text: 'A biblioteca de redução de malha não está instalada: rode de novo o instalador do Cleanmold.' }),
    o ? el('div', { class: 'res' }, `Última otimização: ${milhar(o.antes)} → ${milhar(o.depois)} triângulos (${num(100 * (1 - o.depois / o.antes), 0)} % a menos), tolerância ${num(o.tolerancia, 2)} mm.`,
      o.desvio ? ` Desvio medido em ${milhar(o.desvio.pontos)} pontos: médio ${num(o.desvio.medio, 3)} mm, 99 % abaixo de ${num(o.desvio.p99, 3)} mm, máximo ${num(o.desvio.maximo, 3)} mm.` : ' O desvio não pôde ser medido.') : null,
    r.fase_edicao === 'antes' && r.alvos.length ? el('p', { text: 'Otimizar antes de retirar os alvos é o caminho mais rápido: a procura é refeita na malha nova e leva segundos.' }) : null));
  // ---- pincel
  partes.push(el('div', { class: 'bloco' }, el('h3', { text: 'Pincel: retirar, preencher ou alisar uma região' }),
    el('p', { text: 'Escolha o diâmetro, arraste sobre a malha e use uma das ações. Para tirar um alvo que a procura não achou: um toque no pé dele, com o pincel um pouco maior que o pé, e “Retirar e preencher” — o corpo do alvo, que fica pendurado, sai junto. Para fechar um vazio: pinte por cima da beirada dele e use “Preencher o vazio”.' }),
    el('div', { class: 'linha' }, el('button', { class: 'bt', text: S.ferr === 'pincel' ? 'Pincel aberto' : 'Abrir o pincel', disabled: S.ferr === 'pincel', onclick: () => escolherFerramenta('pincel') }))));
  // ---- furos
  const fu = [el('h3', {}, 'Furos', S.furos ? el('span', { class: 'chip', text: S.furos.length + (S.furos.length === 1 ? ' contorno aberto' : ' contornos abertos') }) : null),
    el('p', { text: 'Cada furo é fechado continuando a superfície que está em volta dele: plano, cilindro, esfera, cone ou superfície suave; se o furo passa por uma aresta viva, a aresta é refeita. Quando nenhuma dessas formas explica a vizinhança (a ponta de uma palheta, um vazio entre as duas faces de uma parede fina), o furo é fechado com a superfície mais lisa que continua as bordas, e fica marcado para conferir.' })];
  if (!S.furos) fu.push(el('div', { class: 'linha' }, el('button', { class: 'bt', text: 'Procurar furos', onclick: procurarFuros })));
  else if (!S.furos.length) fu.push(el('div', { class: 'res', text: 'A malha não tem contornos abertos: é uma superfície fechada.' }));
  else {
    let ate = '10'; try { ate = localStorage.getItem('cleanmold.furos') || '10'; } catch (e) { /* padrão */ }
    const nAte = (v) => S.furos.filter((f) => f.diametro <= v).length;
    const campo = el('input', { type: 'text', id: 'fuAte', inputmode: 'decimal', value: val('fuAte', br(ate)), 'aria-label': 'Diâmetro máximo em milímetros' });
    const conta = el('span', { class: 'fraco' });
    const recontar = () => { const v = Number(String(campo.value).replace(',', '.')); conta.textContent = v > 0 ? `${nAte(v)} de ${S.furos.length}` : ''; };
    campo.addEventListener('input', recontar); recontar();
    fu.push(el('div', { class: 'linha' }, 'Fechar todos até Ø', campo, 'mm', el('button', { class: 'bt primario', text: 'Fechar', onclick: () => fecharFuros(null) }), conta));
    const lista = el('div', { class: 'furos' });
    const mostra = [...S.furos].sort((a, b) => b.perimetro - a.perimetro).slice(0, 80);
    for (const f of mostra) {
      lista.append(el('div', { class: 'fu-linha' + (f.i === S.furoSel ? ' sel' : '') + (f.borda ? ' borda' : ''), 'data-i': f.i, onclick: (ev) => { if (ev.target.tagName !== 'BUTTON') escolherFuro(f.i, true); } },
        el('span', { class: 'n', text: String(f.i + 1) }),
        el('span', { text: f.borda ? 'borda da peça' : (f.diametro < 3 ? 'furo miúdo' : 'furo') }),
        el('span', { class: 'd', text: `Ø ${num(f.diametro, 1)} · ${num(f.perimetro, 0)} mm` }),
        el('button', { class: 'bt-texto', text: 'Fechar', onclick: () => fecharFuros([f.i]) })));
    }
    fu.push(lista);
    if (S.furos.length > mostra.length) fu.push(el('p', { text: `Na lista, os ${mostra.length} maiores. Os outros ${S.furos.length - mostra.length} aparecem no modelo (em vermelho): clique em um para escolher.` }));
    fu.push(el('p', { text: 'Clique numa linha (ou num contorno vermelho no modelo) para ver o furo. O contorno maior costuma ser a borda de um escaneamento de um lado só, não um furo.' }));
    fu.push(el('div', { class: 'linha' }, el('button', { class: 'bt-texto', text: 'Procurar de novo', onclick: procurarFuros })));
  }
  partes.push(el('div', { class: 'bloco' }, ...fu));
  // ---- exame e reparo
  const d = r.diag;
  const rp = [el('h3', { text: 'Exame e reparo automático' })];
  if (!d) rp.push(el('p', { text: 'Conta o que a malha tem de errado: pedaços soltos, arestas com três ou mais triângulos, triângulos virados, furos.' }),
    el('div', { class: 'linha' }, el('button', { class: 'bt', text: 'Examinar a malha', onclick: examinar })));
  else {
    const linha = (k, v, ruim) => [el('span', { class: 'k', text: k }), el('span', { class: 'v ' + (ruim ? 'ruim' : (ruim === false ? 'bom' : '')), text: v })];
    rp.push(el('div', { class: 'medidas' },
      ...linha('Pedaços soltos pequenos', `${milhar(d.soltos)}` + (d.soltos ? ` (${milhar(d.soltos_triangulos)} triângulos)` : ''), d.soltos > 0),
      ...linha('Arestas com três ou mais triângulos', milhar(d.nao_variedade), d.nao_variedade > 0),
      ...linha('Triângulos virados em relação aos vizinhos', milhar(d.invertidos), d.invertidos > 0),
      ...linha('Contornos abertos (furos e bordas)', milhar(d.furos) + (d.furos ? `, ${milhar(d.furos_ate_10)} até Ø 10 mm` : ''), d.furos > 0 ? undefined : false),
      ...linha('Triângulos muito finos', milhar(d.finos)),
      ...linha('Superfície', d.fechada ? 'fechada' : 'aberta', d.fechada ? false : undefined)));
    const marca = (id, texto, padrao) => el('label', { class: 'marcar' }, el('input', { type: 'checkbox', id, checked: val(id, padrao) }), texto);
    rp.push(marca('rpSoltos', 'Apagar os pedaços soltos pequenos', d.soltos > 0), marca('rpLascas', 'Tirar as lascas das arestas com três ou mais triângulos', d.nao_variedade > 0),
      marca('rpVirados', 'Desvirar os triângulos virados', d.invertidos > 0),
      el('div', { class: 'linha' }, marca('rpFuros', 'Fechar os furos até Ø', false), el('input', { type: 'text', id: 'rpAte', inputmode: 'decimal', value: val('rpAte', '5'), 'aria-label': 'Diâmetro máximo dos furos em milímetros' }), 'mm'),
      el('div', { class: 'linha' }, el('button', { class: 'bt primario', text: 'Reparar', onclick: reparar }), el('button', { class: 'bt-texto', text: 'Examinar de novo', onclick: examinar })));
    if (r.fase_edicao === 'antes' && r.alvos.length && d.soltos) rp.push(el('p', { text: 'Os pedaços soltos incluem partes dos alvos que o escaneamento separou. Retirar os alvos já apaga esses pedaços.' }));
  }
  partes.push(el('div', { class: 'bloco' }, ...rp));
  // ---- histórico
  if (r.edicoes.length) partes.push(el('div', { class: 'bloco' }, el('h3', { text: 'O que já foi feito nesta malha' }),
    el('ol', { class: 'historico' }, ...r.edicoes.map((e) => el('li', {}, e.texto, e.avisos && e.avisos.length ? el('small', { text: 'Conferir: ' + e.avisos.join('; ') + '.' }) : null)))));
  const topo = cx.parentElement.scrollTop;
  cx.replaceChildren(...partes);
  cx.parentElement.scrollTop = topo;
}

async function alvoManual(ponto) {
  const d = Number(String($('#manDiam').value).replace(',', '.'));
  if (!(d >= 2 && d <= 120)) { toast('Ø do recorte: informe um valor entre 2 e 120 mm.', true); return; }
  try {
    estado('andando', 'Acrescentando o alvo');
    const marcados = new Map(S.r.alvos.map((a) => [a.i, a.marcado]));
    const r = await api('/api/manual', { ponto, diametro: d });
    for (const a of r.alvos) if (marcados.has(a.i)) a.marcado = marcados.get(a.i);
    await aplicarResultado(r, false);
    S.sel = r.novo; desenharTudo();
    toast(`Alvo ${r.novo + 1} acrescentado à lista. Clique em outro pé ou em Terminar.`);
  } catch (e) { estadoParado(); toast(e.message, true); }
}

async function esquecer(i) {
  try {
    const marcados = S.r.alvos.filter((a) => a.i !== i).map((a) => a.marcado);
    const r = await api('/api/esquecer', { i });
    r.alvos.forEach((a, k) => { a.marcado = marcados[k]; });
    S.sel = null;
    await aplicarResultado(r, false);
  } catch (e) { toast(e.message, true); }
}

// ---------- sólido ----------
function desenharSolido() {
  const r = S.r, s = r.solido, cx = $('#dirCheio');
  const partes = [el('div', { class: 'lista-topo' }, el('div', { class: 't', text: 'Sólido para o SolidWorks' }))];
  const opcoes = () => el('div', { class: 'grade-sol' },
    el('label', { class: 'campo' }, 'Arredondar as cotas para', el('select', { id: 'solArred' },
      ...[['0.001', '0,001 mm'], ['0.01', '0,01 mm'], ['0.05', '0,05 mm'], ['0.1', '0,1 mm'], ['0.5', '0,5 mm'], ['1', '1 mm']].map(([v, t]) =>
        el('option', { value: v, text: t, selected: (s && s.passo_cota ? String(s.passo_cota) : '0.01') === v })))),
    el('label', { class: 'campo' }, 'Ignorar detalhes menores que (mm)', el('input', { type: 'text', id: 'solDet', inputmode: 'decimal', value: br(String(s && s.detalhe != null ? s.detalhe : 1)) })));
  if (!s || !s.tipo) {
    partes.push(el('div', { class: 'caixa-acao' }, el('div', { class: 'forte', text: 'Peça de revolução' }),
      el('div', { text: 'O Cleanmold procura o eixo de revolução da peça, tira o perfil (retas e arcos) e monta a peça como o SolidWorks montaria: um esboço cotado e uma revolução. Serve para eixo, bucha, flange, anel, tampa. Peça prismática ou de forma livre não tem árvore automática.' }),
      opcoes(), el('button', { class: 'bt primario', text: r.limpo ? 'Reconhecer a peça' : 'Reconhecer a peça (malha ainda com alvos)', onclick: reconhecer })));
    if (s && s.erro) partes.push(el('div', { class: 'caixa-nota' }, el('b', { text: 'Não é peça de revolução. ' }), s.erro));
    if (!r.limpo) partes.push(el('p', { class: 'fraco', text: 'Retire os alvos antes: com eles na malha, o perfil sai com ressaltos falsos.' }));
    cx.replaceChildren(...partes);
    return;
  }
  const oque = s.solido ? 'Sólido de revolução' : (s.setor ? `Superfície de revolução, setor de ${num(s.setor, 0)}°` : 'Superfície de revolução (perfil aberto)');
  partes.push(el('div', { class: 'resumo' }, el('span', { class: 'chip', text: oque }),
    el('span', { class: 'sit ' + (s.cobertura > 0.9 ? 'ok' : (s.cobertura > 0.6 ? 'lim' : 'fora')), text: `explica ${num(100 * s.cobertura, 0)} % da malha` }),
    s.rms != null ? el('span', { class: 'fraco', text: `desvio médio ${num(s.rms, 2)} mm` }) : null));
  if (s.cobertura < 0.9) partes.push(el('div', { class: 'caixa-nota', text: `Só ${num(100 * s.cobertura, 0)} % da superfície da malha é de revolução em torno deste eixo. O que não é (palhetas, nervuras, rasgos, furos fora do eixo, dentes) não entra no sólido: modele por cima no SolidWorks.` }));
  if (!s.solido) partes.push(el('div', { class: 'caixa-nota', text: (s.setor ? 'A malha cobre só um setor da volta' : 'O perfil não fecha (a malha é de um lado só da peça)') + ': o que sai é a superfície de revolução, não um corpo fechado. No SolidWorks, complete o perfil no esboço e troque a revolução por um ressalto.' }));
  if (!s.da_limpa) partes.push(el('div', { class: 'caixa-nota', text: 'Este reconhecimento foi feito com os alvos ainda na malha. Retire os alvos e reconheça de novo.' }));
  // árvore
  const nl = s.entidades.filter((e) => e.tipo === 'linha' && e.forma !== 'eixo').length, na = s.entidades.filter((e) => e.tipo === 'arco').length;
  partes.push(el('div', { class: 'rotulo', text: 'Árvore que a macro constrói' }),
    el('div', { class: 'arvore' },
      el('div', { class: 'no' }, el('i', { text: '1' }), el('div', {}, el('b', { text: 'Perfil (esboço no Plano Frontal)' }),
        el('small', { text: `${nl} ${nl === 1 ? 'reta' : 'retas'}` + (na ? ` e ${na} ${na === 1 ? 'arco' : 'arcos'}` : '') + `, com ${s.cotas.length} cotas. Eixo de revolução = eixo X; origem na primeira face.` }))),
      el('div', { class: 'no' }, el('i', { text: '2' }), el('div', {}, el('b', { text: s.solido ? 'Revolução (ressalto/base), 360°' : `Revolução (superfície), ${s.setor ? num(s.setor, 0) + '°' : '360°'}` }),
        el('small', { text: `Comprimento ${num(s.comprimento, 2)} mm · Ø máximo ${num(2 * s.raio_max, 2)} mm` })))));
  // perfil
  partes.push(el('div', { class: 'rotulo', text: 'Perfil (raio × posição no eixo)' }), desenharPerfil(s));
  // cotas
  const tb = el('div', { class: 'cotas' }, el('div', { class: 'ct-cab' }, el('span', { text: 'Cota' }), el('span', { style: 'text-align:right', text: 'Valor' }), el('span', { text: 'Onde' })));
  for (const c of s.cotas) tb.append(el('div', { class: 'ct-linha' }, el('span', { class: 's', text: c.nome }),
    el('span', { class: 'v', text: c.tipo === 'cone' ? num(c.valor, 2) + '°' : num(c.valor, decimais(s.passo_cota)) + ' mm' }), el('span', { class: 'd', title: c.texto, text: c.texto.replace(/\./g, ',') })));
  partes.push(el('div', { class: 'rotulo', text: 'Cotas' }), tb);
  partes.push(el('div', { class: 'caixa-acao' }, el('div', { class: 'forte', text: 'Refazer com outro arredondamento' }), opcoes(),
    el('div', { style: 'display:flex;gap:8px' }, el('button', { class: 'bt', text: 'Reconhecer de novo', onclick: reconhecer }),
      r.limpo ? el('button', { class: 'bt primario', text: 'Gerar STEP e macro', onclick: () => abrirExportar(['step', 'macro']) }) : null)));
  partes.push(el('p', { class: 'fraco', text: 'Um arquivo STEP nunca leva árvore de projeto: abre como corpo importado. A árvore editável vem da macro (Ferramentas > Macro > Executar no SolidWorks), que cria o esboço cotado e a revolução dentro do próprio SolidWorks.' }));
  cx.replaceChildren(...partes);
}

const decimais = (p) => (p >= 1 ? 0 : p >= 0.1 ? 1 : p >= 0.01 ? 2 : 3);

function desenharPerfil(s) {
  const svg = sv('svg', { id: 'perfilSvg', role: 'img', 'aria-label': 'Perfil da peça de revolução' });
  const todos = [s.entidades, ...s.outros];
  let x0 = Infinity, x1 = -Infinity, y1 = 0;
  for (const g of todos) for (const e of g) for (const p of [e.p0, e.p1]) { x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }
  // num anel grande o perfil fica longe do eixo: a janela acompanha o perfil, e o eixo só aparece se couber
  let y0 = Infinity;
  for (const g of todos) for (const e of g) for (const p of [e.p0, e.p1]) y0 = Math.min(y0, p[1]);
  const longe = y0 > 1.5 * Math.max(x1 - x0, y1 - y0);
  if (!longe) y0 = 0;
  const tam = Math.max(x1 - x0, y1 - y0);
  const m = tam * 0.06 + 1;
  svg.setAttribute('viewBox', `${x0 - m} ${-y1 - m} ${x1 - x0 + 2 * m} ${y1 - y0 + 2 * m}`);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  const esp = tam / 260;
  if (!longe) svg.append(sv('line', { x1: x0 - m, y1: 0, x2: x1 + m, y2: 0, stroke: '#b91c1c', 'stroke-width': esp * 0.7, 'stroke-dasharray': `${esp * 8} ${esp * 3} ${esp * 1.5} ${esp * 3}` }));
  else svg.append(sv('text', { x: x0 - m * 0.6, y: -y0 + m * 0.7, 'font-size': esp * 9, fill: '#5a6470', text: `eixo a ${Math.round(y0)} mm ↓` }));
  todos.forEach((g, k) => {
    let d = '';
    g.forEach((e, j) => {
      if (j === 0 || Math.hypot(e.p0[0] - g[j - 1].p1[0], e.p0[1] - g[j - 1].p1[1]) > 1e-6) d += `M${e.p0[0]} ${-e.p0[1]}`;
      if (e.tipo === 'linha') d += `L${e.p1[0]} ${-e.p1[1]}`;
      else d += `A${e.r} ${e.r} 0 0 ${e.sentido > 0 ? 0 : 1} ${e.p1[0]} ${-e.p1[1]}`;
    });
    svg.append(sv('path', { d, fill: k === 0 && s.fechado ? '#e8f5ee' : 'none', stroke: k === 0 ? '#0f7a4d' : '#8a929c', 'stroke-width': esp * (k === 0 ? 1.6 : 1), 'stroke-linejoin': 'round' }));
  });
  return svg;
}

async function reconhecer() {
  if (S.ocupado) return;
  const det = Number(String(($('#solDet') || { value: '1' }).value).replace(',', '.'));
  if (!(det >= 0 && det <= 20)) { toast('Menor detalhe: informe um valor entre 0 e 20 mm.', true); return; }
  await iniciar('solido', '/api/solido', { arredondar: Number(($('#solArred') || { value: '0.01' }).value), detalhe: det });
}

// ---------- textos ----------
function abrirTexto(titulo, conteudo) { $('#tTexto').textContent = titulo; $('#textoCorpo').replaceChildren(conteudo); $('#mTexto').hidden = false; }

function ajuda() {
  const c = el('div', { class: 'ajuda-texto' });
  c.innerHTML = `
    <h3>Do escaneamento à malha limpa</h3>
    <ul><li>Exporte a <b>malha</b> do Control X ou do Design X em STL (também PLY, OBJ ou OFF), em milímetros, com os alvos como saíram do escaneamento.</li>
    <li>Em <b>Abrir malha</b>, escolha o arquivo. A procura dos alvos começa sozinha. Em malha de milhões de triângulos, o Cleanmold pergunta antes se é para otimizar ao abrir.</li>
    <li>Na lista à direita, cada alvo tem uma <b>confiança</b>. Os de confiança alta já vêm marcados. Clique numa linha para ver o alvo no modelo.</li>
    <li><b>Retirar e fechar os furos</b> recorta cada alvo e fecha o furo continuando a superfície em volta. Use <b>Antes</b> e <b>Depois</b>, na barra de cima, para comparar.</li>
    <li>Em <b>Gerar arquivos</b>, marque o que precisa: malha limpa, relatório, sólido.</li></ul>
    <h3>O que o Cleanmold entende por alvo</h3>
    <ul><li>Um <b>pé cilíndrico</b> de diâmetro conhecido (a base magnética, Ø 18,8 mm no peão e Ø 14,9 mm no dado com base) em pé sobre a peça, e acima dele o corpo do alvo: pescoço, esfera, dodecaedro.</li>
    <li>O corpo pode vir amassado, torto, com caroços ou partido em <b>pedaços soltos</b>: o que decide é o pé e o perfil logo acima dele. Quando o pé também saiu amassado, o alvo é achado pela esfera ou pelo dodecaedro e aparece como “pé amassado”.</li>
    <li>Pedaços soltos pequenos (esferas, dodecaedros e lascas que o escaneamento separou da peça) são apagados junto, a menos que você desmarque <b>Apagar pedaços soltos</b>.</li></ul>
    <h3>Quando faltar ou sobrar um alvo</h3>
    <ul><li><b>Sobrou</b> (não é alvo): desmarque a linha. Fica em laranja no modelo e não é tocado.</li>
    <li><b>Faltou</b>: use a ferramenta com a mira, na barra de cima, informe o diâmetro do recorte e clique no pé do alvo. Ele entra na lista como “Indicado à mão”.</li></ul>
    <h3>Como o furo é fechado</h3>
    <ul><li>A superfície da peça em volta do pé é ajustada a um <b>plano</b>, <b>cilindro</b>, <b>esfera</b>, <b>cone</b> ou <b>superfície curva suave</b> (o mais simples que explicar a vizinhança). O remendo é gerado sobre esse ajuste e emendado no contorno do furo.</li>
    <li>Se o pé estava na beirada e o furo desce por uma parede, a <b>aresta viva</b> entre a face de cima e a parede é refeita.</li>
    <li>Se o alvo estava na <b>borda da malha</b>, a borda é refeita em linha reta naquele trecho.</li>
    <li><b>Margem</b>: quanto o recorte entra na superfície limpa. <b>Alcance</b>: até onde, em volta do pé, rebarbas grudadas nele são recortadas quando não terminam sozinhas.</li></ul>
    <h3>Malha grande e otimização</h3>
    <ul><li>Ao abrir uma malha de milhões de triângulos, o Cleanmold mostra quanto ela pede de memória e oferece <b>otimizar ao abrir</b>. Otimizar junta triângulos onde a peça é lisa e mantém os detalhes; a tolerância (0,02, 0,05 ou 0,10 mm) é o quanto a malha nova pode se afastar da original, e o desvio que resultou é <b>medido</b> e mostrado.</li>
    <li>Também dá para otimizar depois, na aba <b>Malha e reparo</b>. O arquivo STL sai menor na mesma proporção; em PLY sai menor ainda.</li></ul>
    <h3>Pincel, furos e reparo</h3>
    <ul><li><b>Pincel</b> (barra de cima, ou Malha &gt; Pincel de seleção): escolha o diâmetro e arraste sobre a malha. Com o botão direito a vista gira; com o do meio, desloca. Shift despinta; [ e ] mudam o diâmetro.</li>
    <li><b>Retirar e preencher</b> apaga o que está pintado, e o que ficar pendurado no corte, e fecha o furo seguindo a superfície em volta. Para um alvo que a procura não achou, um toque no pé dele com o pincel um pouco maior que o pé resolve.</li>
    <li><b>Preencher o vazio</b>: pinte por cima da beirada de um furo, ou de um entalhe na borda da malha, e o vazio é fechado.</li>
    <li><b>Alisar</b> tira ruído (leve), ondulações (médio) ou refaz a região como continuação lisa do que está em volta (refazer liso).</li>
    <li><b>Furos</b>, na aba Malha e reparo: lista os contornos abertos, fecha um por um ou todos até um diâmetro.</li>
    <li><b>Exame e reparo</b>: conta pedaços soltos, arestas com três ou mais triângulos e triângulos virados, e corrige o que você marcar.</li>
    <li><b>Desfazer</b> (Ctrl+Z) volta a última operação.</li></ul>
    <h3>O que conferir antes de confiar</h3>
    <ul><li>O remendo é uma <b>reconstrução</b>: a superfície debaixo do alvo não foi escaneada. Em superfície lisa o erro fica na ordem do ruído da malha; onde havia ressalto, cordão de solda ou rebarba passando por baixo do alvo, o remendo alisa.</li>
    <li>Situação <b>conferir</b>: o contorno do furo não assentou todo na referência. Olhe esses remendos no modelo antes de medir em cima deles.</li></ul>
    <h3>Sólido para o SolidWorks</h3>
    <ul><li>Na aba <b>Sólido</b>, o Cleanmold reconhece <b>peça de revolução</b>: acha o eixo, tira o perfil em retas e arcos e arredonda as cotas como você escolher.</li>
    <li>O <b>STEP</b> sai com um corpo só e abre como peça (não como montagem), mas nenhum STEP leva árvore de projeto.</li>
    <li>A árvore editável vem da <b>macro</b> (.swb): no SolidWorks, Ferramentas &gt; Macro &gt; Executar. Ela cria o esboço do perfil com relações e cotas e a revolução. Dois cliques na revolução ou no esboço mostram as cotas para editar.</li>
    <li>O que não é de revolução (palhetas, rasgos, furos fora do eixo) fica de fora e precisa ser modelado por cima.</li></ul>`;
  abrirTexto('Como usar', c);
}

function sobre() {
  const c = el('div', { class: 'ajuda-texto' });
  c.append(el('p', {}, el('b', { text: 'Cleanmold ' + S.versaoApp }), ' · retira os alvos de escaneamento da malha e fecha os furos pela superfície vizinha. Da mesma família do Enmold.'),
    el('p', { text: 'Tudo roda neste computador. A malha, a análise e os arquivos não são enviados pela internet.' }),
    el('p', { text: 'A malha limpa é apoio de engenharia. Os remendos são reconstruções: medidas tomadas em cima deles devem ser confirmadas na peça.' }),
    el('p', { class: 'fraco', text: 'Usa three.js e three-mesh-bvh (MIT), pyfqmr (MIT) e as fontes IBM Plex (OFL).' }));
  abrirTexto('Sobre o Cleanmold', c);
}

async function registro() {
  let txt;
  try { txt = (await api('/api/estado?desde=0')).log.join('\n') || 'Sem registro.'; } catch (x) { txt = x.message; }
  abrirTexto('Registro', el('pre', { class: 'registro', text: txt }));
}

// ---------- gerar arquivos ----------
function abrirExportar(pedir) {
  const r = S.r; if (!r) return;
  if (!Array.isArray(pedir)) pedir = null;
  if (!r.limpo && !r.editada) { toast('Retire os alvos antes de gerar os arquivos.', true); return; }
  if (mudou()) { toast('A seleção mudou depois da última limpeza. Use “Retirar de novo” antes de gerar os arquivos.', true, 9000); return; }
  const comAlvos = !r.limpo && r.alvos.length > 0;
  $('#expNomeMalha').textContent = r.limpo ? 'Malha limpa' : (comAlvos ? 'Malha de trabalho (ainda com os alvos)' : 'Malha de trabalho');
  $('#expTamanho').textContent = `${milhar(r.triangulos_atual)} triângulos · cerca de ${br((r.tamanho_stl / 1048576).toFixed(0))} MB em STL` + (comAlvos ? ' · os alvos ainda não foram retirados' : '');
  if (!$('#expPasta').value) $('#expPasta').value = r.pasta || '';
  const temSolido = !!(r.solido && r.solido.tipo && r.solido.da_limpa);
  if (!S.exportando) {
    let marcados = ['stl', 'pdf'];
    try { marcados = JSON.parse(localStorage.getItem('cleanmold.itens') || '["stl","pdf"]'); } catch (e) { /* padrão */ }
    if (pedir) marcados = [...new Set([...marcados, ...pedir])];
    for (const c of $$('#expItens input')) c.checked = marcados.includes(c.value) && (temSolido || !['step', 'macro'].includes(c.value));
    $('#expResultado').hidden = true;
  }
  for (const id of ['#itStep', '#itMacro']) {
    $(id).classList.toggle('inativo', !temSolido);
    $(id).querySelector('small').textContent = temSolido ? '' : (r.solido && r.solido.erro ? 'Esta peça não foi reconhecida como de revolução.' : 'Antes, reconheça a peça na aba Sólido.');
    if (!temSolido) $(id).querySelector('input').checked = false;
  }
  $('#mExportar').hidden = false;
}

async function gerar() {
  const itens = $$('#expItens input:checked').map((c) => c.value);
  try { localStorage.setItem('cleanmold.itens', JSON.stringify(itens)); } catch (e) { /* sem armazenamento */ }
  const cx = $('#expResultado');
  if ($('#btGerar').disabled) return;
  $('#btGerar').disabled = true;
  try {
    await api('/api/exportar', { itens, pasta: $('#expPasta').value.trim(), peca: $('#idPeca').value, responsavel: $('#idResp').value });
  } catch (e) { $('#btGerar').disabled = false; cx.hidden = false; cx.replaceChildren(el('div', { class: 'falha', text: e.message })); return; }
  acompanharGeracao();
}

function acompanharGeracao() {
  const cx = $('#expResultado');
  $('#btGerar').disabled = true; S.exportando = true;
  cx.hidden = false; cx.replaceChildren(el('div', { class: 'fraco', text: 'Gerando…' }));
  estado('andando', 'Gerando arquivos');
  let n0 = null;
  const fim = (erro, x) => {
    $('#btGerar').disabled = false; S.exportando = false;
    if (!parado) estadoParado();
    if (erro) cx.replaceChildren(el('div', { class: 'falha', text: erro })); else mostrarExportados(x);
    if (!$('#mExportar').hidden) return;
    const nf = x ? Object.keys(x.falhas || {}).length : 0, na = x ? Object.keys(x.arquivos).length : 0;
    if (erro) toast('Os arquivos não foram gerados: ' + erro, true, 0);
    else toast(`${na} ${na === 1 ? 'arquivo gerado' : 'arquivos gerados'} em ${x.pasta}.` + (nf ? ` ${nf} ${nf === 1 ? 'falhou' : 'falharam'}: veja em Gerar arquivos.` : ''), nf > 0, nf ? 0 : 9000);
  };
  const passo = async () => {
    let e;
    try { e = await api('/api/estado?desde=' + (n0 === null ? 999999 : n0)); } catch (x) { if (parado) fim(MSG_PARADO); else setTimeout(passo, 1200); return; }
    const ultima = (n0 !== null && e.log.length) ? e.log[e.log.length - 1] : null;
    n0 = e.n_log;
    if (e.ocupado) { if (ultima) cx.replaceChildren(el('div', { class: 'fraco', text: ultima })); setTimeout(passo, 600); return; }
    fim(e.erro, e.export);
  };
  setTimeout(passo, 300);
}

function mostrarExportados(x) {
  const cx = $('#expResultado'); cx.replaceChildren();
  if (!x) return;
  const nomes = { stl: 'Malha limpa (STL)', ply: 'Malha limpa (PLY)', pdf: 'Relatório (PDF)', html: 'Relatório (HTML)', csv: 'Planilha (CSV)', step: 'Sólido (STEP)', dxf: 'Perfil (DXF)', macro: 'Macro do SolidWorks' };
  const mostrar = (cam) => api('/api/mostrar', { caminho: cam }).catch((e) => toast(e.message, true));
  for (const [k, cam] of Object.entries(x.arquivos)) {
    cx.append(el('div', { class: 'arq' }, el('span', {}, nomes[k] + ' · ', el('span', { class: 'mono', text: cam.split(/[\\/]/).pop() })),
      ['stl', 'ply', 'step', 'macro', 'dxf'].includes(k) ? null : el('button', { class: 'bt-texto', type: 'button', text: 'Abrir', onclick: () => mostrar(cam) })));
  }
  for (const [k, msg] of Object.entries(x.falhas || {})) {
    cx.append(el('div', { class: 'falha', text: `${nomes[k]} não foi gerado: ${msg}.` + (k === 'pdf' ? ' Marque "Relatório em HTML", abra o arquivo e use Imprimir > Salvar como PDF.' : '') }));
  }
  if (Object.keys(x.arquivos).length) cx.append(el('button', { class: 'bt-texto', type: 'button', style: 'justify-self:start', text: 'Abrir a pasta', onclick: () => mostrar(x.pasta) }));
}

// ============================================================================
// ligações
// ============================================================================
const ACOES = {
  abrir: abrirMalha, exportar: () => abrirExportar(), registro, ajuda, sobre, limpar,
  'marcar-todos': () => marcarVarios(() => true), 'marcar-seguros': () => marcarVarios((a) => a.seguro), desmarcar: () => marcarVarios(() => false),
  manual: () => escolherFerramenta('manual'), pincel: () => escolherFerramenta('pincel'), desfazer,
  otimizar: () => abrirAba('malha'),
  furos: () => { abrirAba('malha'); if (!S.furos) procurarFuros(); },
  examinar: () => { abrirAba('malha'); if (!S.r.diag) examinar(); },
  solido: () => { trocarFase('solido'); if (!S.r.solido || !S.r.solido.tipo) reconhecer(); },
  reanalisar: () => {
    if (S.ocupado) { toast('Espere terminar o que está em andamento.', true); return; }
    if (S.r && S.r.limpo && !confirm('Procurar de novo descarta a retirada dos alvos já feita e o que foi reparado depois dela (dá para desfazer). Continuar?')) return;
    iniciar('analise', '/api/analisar', {});
  },
};
function fecharMenus() {
  for (const m of $$('.menu-caixa')) m.hidden = true;
  for (const b of $$('.menu > button')) b.setAttribute('aria-expanded', 'false');
}
for (const b of $$('.menu > button')) {
  const alternar = (ev) => {
    ev.stopPropagation();
    const cx = b.parentElement.querySelector('.menu-caixa'), estava = !cx.hidden;
    fecharMenus(); cx.hidden = estava; b.setAttribute('aria-expanded', String(!estava));
  };
  b.addEventListener('click', alternar);
  b.addEventListener('mouseenter', (ev) => { if ($$('.menu-caixa').some((m) => !m.hidden) && b.getAttribute('aria-expanded') !== 'true') alternar(ev); });
}
for (const b of $$('[data-precisa], [data-arquivo], [data-precisa-saida], [data-desfazer]')) b.disabled = true;
for (const b of $$('[data-acao]')) b.addEventListener('click', () => { fecharMenus(); ACOES[b.dataset.acao](); });
$('#btPrincipal').addEventListener('click', () => { if ($('#btPrincipal').dataset.oque === 'exportar') abrirExportar(); else limpar(); });
for (const c of [$('#idPeca'), $('#idResp')]) c.addEventListener('change', () => api('/api/ident', { peca: $('#idPeca').value, responsavel: $('#idResp').value }).catch(() => {}));
for (const c of [$('#opMargem'), $('#opAlcance'), $('#opSoltos')]) c.addEventListener('change', () => { if (S.r) desenharTudo(); });
document.addEventListener('click', (ev) => { if (!ev.target.closest('.menu')) fecharMenus(); });
document.addEventListener('keydown', (ev) => {
  const digitando = /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
  if ((ev.ctrlKey || ev.metaKey) && !ev.shiftKey && ev.key.toLowerCase() === 'z' && !digitando) { ev.preventDefault(); desfazer(); return; }
  if (S.ferr === 'pincel' && !digitando && (ev.key === '[' || ev.key === ']')) { definirDiametro(S.pincel.diam * (ev.key === ']' ? 1.15 : 1 / 1.15)); return; }
  if (ev.key !== 'Escape') return;
  const aberto = $$('.fundo').some((f) => !f.hidden) || $$('.menu-caixa').some((m) => !m.hidden);
  fecharMenus(); for (const f of $$('.fundo')) f.hidden = true;
  if (!aberto && (S.ferr === 'manual' || S.ferr === 'pincel')) escolherFerramenta('selecionar');
});
for (const b of $$('[data-fechar]')) b.addEventListener('click', () => { b.closest('.fundo').hidden = true; });
for (const f of $$('.fundo')) f.addEventListener('mousedown', (ev) => { if (ev.target === f) f.hidden = true; });

$('#btGerar').addEventListener('click', gerar);
$('#btPasta').addEventListener('click', async () => {
  try { const r = await api('/api/pasta', { pasta: $('#expPasta').value }); if (r.pasta) $('#expPasta').value = r.pasta; } catch (e) { toast(e.message, true); }
});
for (const b of $$('[data-fase]')) b.addEventListener('click', () => trocarFase(b.dataset.fase));
for (const b of $$('[data-aba]')) b.addEventListener('click', () => abrirAba(b.dataset.aba));
$('#btGrande').addEventListener('click', confirmarAbertura);
for (const c of $$('input[name=grande]')) c.addEventListener('change', () => { $('#grandeTol').hidden = $('input[name=grande]:checked').value !== 'otimizar'; });
$('#btDesfazer').addEventListener('click', desfazer);
// barra do pincel
$('#pinSair').addEventListener('click', () => escolherFerramenta('selecionar'));
$('#pinDesl').addEventListener('input', (ev) => definirDiametro(deslParaDiam(Number(ev.target.value)), 'desl'));
$('#pinDiam').addEventListener('change', (ev) => { const v = Number(String(ev.target.value).replace(',', '.')); if (v > 0) definirDiametro(v); else definirDiametro(S.pincel.diam); });
for (const b of $$('[data-pin]')) b.addEventListener('click', () => { S.pincel.modo = Number(b.dataset.pin); atualizarPincel(); });
for (const b of $$('[data-edit]')) b.addEventListener('click', () => editar(b.dataset.edit));
for (const b of $$('[data-sel]')) b.addEventListener('click', () => mudarSelecao(b.dataset.sel));
{ let d = 25; try { d = Number(localStorage.getItem('cleanmold.pincel')) || 25; } catch (e) { /* padrão */ } definirDiametro(d); }
for (const b of $$('[data-ferr]')) b.addEventListener('click', () => escolherFerramenta(b.dataset.ferr));
$('#manSair').addEventListener('click', () => escolherFerramenta('selecionar'));
$('#btAjustar').addEventListener('click', () => { if (visor) { visor.vista('iso'); for (const o of $$('[data-cam]')) o.classList.toggle('ativo', o.dataset.cam === 'iso'); } });
for (const b of $$('[data-cam]')) b.addEventListener('click', () => {
  for (const o of $$('[data-cam]')) o.classList.toggle('ativo', o === b);
  if (visor) visor.vista(b.dataset.cam);
});
$('#opMalha').addEventListener('input', (ev) => { if (visor) { visor.opSolido = Number(ev.target.value) / 100; if (S.fase === 'solido') visor.opacidadeMalha(visor.opSolido); } });

// clique no modelo (sem confundir com arrastar) e pincel
{
  let ini = null, pintando = null;
  const tela = $('#tela');
  const raio = () => S.pincel.diam / 2;
  const carimbar = (h) => {
    const p = pintando;
    if (p.ult && p.ult.distanceTo(h.ponto) < raio() * 0.3) return;
    p.ult = h.ponto.clone();
    p.pts.push([h.ponto.x, h.ponto.y, h.ponto.z, raio(), p.modo]);
    visor.previa(S.fase, h.ponto, raio(), p.modo, h.normalFace);
  };
  tela.addEventListener('pointerdown', (ev) => {
    ini = { x: ev.clientX, y: ev.clientY, b: ev.button };
    if (S.ferr !== 'pincel' || ev.button !== 0 || !visor || !S.r || S.ocupado || S.fase !== S.r.fase_edicao) return;
    const h = visor.tocar(ev);
    if (!h) return;
    try { tela.setPointerCapture(ev.pointerId); } catch (e) { /* sem captura */ }
    pintando = { modo: ev.shiftKey ? 0 : S.pincel.modo, pts: [], ult: null };
    carimbar(h);
  });
  tela.addEventListener('pointermove', (ev) => {
    if (S.ferr !== 'pincel' || !visor || !S.r || S.ocupado) return;
    if (ev.buttons & 6) { visor.cursor(null); return; }                // girando ou deslocando a vista
    const h = visor.tocar(ev);
    visor.cursor(h ? h.ponto : null, h ? h.normal : null, raio());
    if (pintando && h && (ev.buttons & 1)) carimbar(h);
  });
  const soltar = () => { if (!pintando) return; const p = pintando; pintando = null; if (p.pts.length) enviarPinceladas(p.pts); };
  tela.addEventListener('pointerup', (ev) => {
    if (pintando) { soltar(); return; }
    if (!ini || ini.b !== 0 || Math.hypot(ev.clientX - ini.x, ev.clientY - ini.y) > 4 || !visor || !S.r || S.ferr === 'mover' || S.ferr === 'pincel' || S.ocupado) return;
    // contorno de furo perto do clique (com o painel de reparo aberto)
    if (S.furos && visor.gFuros.visible) { const k = visor.furoPerto(ev); if (k >= 0) { escolherFuro(k, false); return; } }
    const p = visor.pegar(ev);
    if (!p) return;
    if (S.ferr === 'manual') { alvoManual(p.ponto); return; }
    if (S.fase === 'antes' && p.marca >= 2) { if (S.aba !== 'alvos') S.aba = 'alvos'; selecionar(p.marca - 2, false); }
    else if (S.fase !== 'antes') {
      // depois/sólido: o alvo mais próximo do ponto clicado, se o clique foi perto de um remendo
      let melhor = null, dm = 30;
      for (const a of S.r.alvos) { const d = Math.hypot(a.centro[0] - p.ponto[0], a.centro[1] - p.ponto[1], a.centro[2] - p.ponto[2]); if (d < dm) { dm = d; melhor = a.i; } }
      if (melhor !== null && S.fase === 'depois' && S.aba === 'alvos') selecionar(melhor, false);
    }
  });
  tela.addEventListener('pointercancel', soltar);
  tela.addEventListener('pointerleave', () => { if (visor && !pintando) visor.cursor(null); });
  // Ctrl + roda: diâmetro do pincel (sem Ctrl, a roda aproxima a vista)
  tela.addEventListener('wheel', (ev) => {
    if (S.ferr !== 'pincel' || !ev.ctrlKey) return;
    ev.preventDefault(); ev.stopImmediatePropagation();
    definirDiametro(S.pincel.diam * (ev.deltaY < 0 ? 1.12 : 1 / 1.12));
  }, { capture: true, passive: false });
}

// arrastar e soltar
{
  let n = 0;
  const temArquivo = (ev) => ev.dataTransfer && [...ev.dataTransfer.types].includes('Files');
  addEventListener('dragenter', (ev) => { if (temArquivo(ev)) { n++; $('#soltar').hidden = false; ev.preventDefault(); } });
  addEventListener('dragover', (ev) => { if (temArquivo(ev)) ev.preventDefault(); });
  addEventListener('dragleave', () => { n = Math.max(0, n - 1); if (!n) $('#soltar').hidden = true; });
  addEventListener('drop', (ev) => {
    ev.preventDefault(); n = 0; $('#soltar').hidden = true;
    const arq = ev.dataTransfer && ev.dataTransfer.files[0];
    if (!arq) return;
    if (!/\.(stl|ply|obj|off)$/i.test(arq.name)) { toast('Use um arquivo de malha: STL, PLY, OBJ ou OFF.', true); return; }
    if (S.ocupado) { toast('Espere terminar o que está em andamento.', true); return; }
    if (S.exportando) { toast('Espere os arquivos terminarem de ser gerados.', true); return; }
    if (parado) { toast(MSG_PARADO, true, 0); return; }
    enviarArquivo(arq);
  });
}

// o programa encerra quando a janela fecha
const pingar = () => { if (!parado) api('/api/ping?j=' + JANELA, {}).catch(() => {}); };
sinal = setInterval(pingar, 15000);
pingar();
document.addEventListener('visibilitychange', () => { if (!document.hidden) pingar(); });
addEventListener('focus', pingar);
addEventListener('pagehide', () => { navigator.sendBeacon('/api/fechar?t=' + encodeURIComponent(TOKEN) + '&j=' + JANELA); });

// início (ou retomada, se a janela foi recarregada)
(async () => {
  try {
    const e = await api('/api/estado?desde=0');
    S.versaoApp = e.versao_app;
    $('#stVersao').textContent = 'Cleanmold ' + e.versao_app;
    if (!visor) toast('O modelo 3D não pôde ser iniciado neste computador (aceleração gráfica indisponível). A lista de alvos e os arquivos funcionam normalmente.', true, 0);
    if (e.nome) mostrarArquivo(e.nome);
    if (e.ocupado) {
      S.tarefa = /analisando/.test(e.ocupado) ? 'analise' : /retirando/.test(e.ocupado) ? 'limpeza' : /reconhecendo/.test(e.ocupado) ? 'solido'
        : /otimizando/.test(e.ocupado) ? 'otimizar' : /editando/.test(e.ocupado) ? 'edicao' : /furos/.test(e.ocupado) ? 'furos'
        : /examinando|reparando/.test(e.ocupado) ? 'reparo' : /desfazendo/.test(e.ocupado) ? 'desfazer' : null;
      if (e.tem_resultado && S.tarefa !== 'analise') await carregarResultado(true);
      if (S.tarefa) { S.log = e.log; S.nLog = e.n_log; acompanhar(); return; }
      if (e.tem_resultado) acompanharGeracao();
      return;
    }
    if (e.tem_resultado) await carregarResultado(true);
    if (e.falha) mostrarFalha(e.falha);
  } catch (x) {
    if (parado || x.message === MSG_PARADO) servidorParou();
    else { estado('erro', 'Erro ao abrir'); toast(x.message + '\nFeche esta janela e abra o Cleanmold de novo.', true, 0); }
  }
})();

// para inspeção e testes automáticos
window.cleanmold = { S, visor, selecionar, marcar, trocarFase, escolherFerramenta, limpar, reconhecer, abrirExportar, abrirAba, editar, desfazer,
  otimizarMalha, procurarFuros, fecharFuros, examinar, reparar, enviarPinceladas, definirDiametro,
  abrirCaminho: async (caminho, otimizar) => { const r = await api('/api/abrir', { caminho }); mostrarArquivo(r.nome, r.tamanho); await iniciar('analise', '/api/analisar', otimizar ? { otimizar } : {}); return r; },
  abrirPerguntando: async (caminho) => { const r = await api('/api/abrir', { caminho }); mostrarArquivo(r.nome, r.tamanho); decidirAbertura(r); return r; } };
