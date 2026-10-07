// Cleanmold — interface: malha escaneada com os alvos, lista de alvos e antes/depois da retirada.
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

const TOKEN = new URLSearchParams(location.search).get('t') || '';
const JANELA = Math.random().toString(36).slice(2, 12);          // cada janela dá o seu sinal: fechar uma não encerra a outra
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
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
  fora: new THREE.Color(0xd9962b), foraSel: new THREE.Color(0xa86708), solto: new THREE.Color(0x86c9a7), contorno: 0x0f7a4d,
};
const LEVE_A_PARTIR = 350000;                 // acima disso, a vista em movimento usa a malha leve

function lerBlocos(buf) {
  const n = new DataView(buf).getUint32(0, true);
  const cab = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, n)));
  const base = 4 + n;
  const tipos = { V: Float32Array, I: Uint32Array, M: Uint16Array, R: Uint8Array, S: Uint8Array, L: Float32Array };
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
    // A luz acompanha a câmera, de qualquer lado e com a peça em qualquer lugar do espaço: as duas luzes dirigidas e
    // os alvos delas são filhos da câmera, e o "céu" da luz ambiente aponta para o alto da tela (ver quadro()).
    this.ceu = new THREE.HemisphereLight(0xffffff, 0x8c929b, 1.2);
    this.cena.add(this.ceu);
    const l1 = new THREE.DirectionalLight(0xffffff, 1.9); l1.position.set(-1, 1.4, 1.2);
    const l2 = new THREE.DirectionalLight(0xe4f5ec, 0.8); l2.position.set(1.2, -0.4, -0.8);
    for (const l of [l1, l2]) { l.target.position.set(0, 0, 0); this.cam.add(l); this.cam.add(l.target); }
    this.cena.add(this.cam);
    this.gMalha = new THREE.Group(); this.gContorno = new THREE.Group();
    this.cena.add(this.gMalha, this.gContorno);
    // dois lados: escaneamento de um lado só é uma casca aberta, e pelo furo de um alvo se vê o verso da malha
    this.matMalha = new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    // o avesso da malha sai mais escuro: é o que faz um furo parecer furo (por ele se vê o lado de dentro da peça)
    this.matMalha.onBeforeCompile = (sh) => {
      sh.fragmentShader = sh.fragmentShader.replace('#include <dithering_fragment>', '#include <dithering_fragment>\n\tif ( ! gl_FrontFacing ) gl_FragColor.rgb *= vec3( 0.50, 0.54, 0.62 );');
    };
    this.matContorno = new THREE.LineBasicMaterial({ color: COR.contorno });
    this.centro = new THREE.Vector3(); this.raio = 100; this.sujo = true; this.anim = null;
    this.raycaster = new THREE.Raycaster();
    this.d = null;                                           // a malha na tela: { geo, marcas, cab, todos, depois, leve: {…} | null }
    this.fase = 'antes'; this.movendo = false; this.tParar = null;
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
    if (this.ctl.update() || this.sujo) {
      this.sujo = false;
      this.ceu.position.set(0, 1, 0).applyQuaternion(this.cam.quaternion);
      this.r.render(this.cena, this.cam);
    }
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

  esquecer() {
    if (this.d) { this.d.geo.dispose(); if (this.d.leve) this.d.leve.geo.dispose(); }
    this.d = null; this.malhaCheia = null;
    for (const m of [...this.gMalha.children]) this.gMalha.remove(m);
    this.limpar(this.gContorno); this.sujo = true;
  }

  geometria(buf) {
    const { cab, bloco } = lerBlocos(buf);
    const V = bloco('V');
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(V, 3));
    const todos = new THREE.BufferAttribute(bloco('I'), 1);
    geo.setIndex(todos);
    geo.computeVertexNormals();
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(V.length), 3));
    geo.computeBoundingSphere();
    return { geo, marcas: bloco('M') || new Uint16Array(V.length / 3), cab, todos, depois: null };
  }

  guardar(buf, bufLeve) {
    this.esquecer();
    const d = this.geometria(buf);
    d.leve = bufLeve ? this.geometria(bufLeve) : null;
    this.d = d;
    this.centro.copy(d.geo.boundingSphere.center); this.raio = d.geo.boundingSphere.radius;
    this.ctl.minDistance = this.raio * 0.004; this.ctl.maxDistance = this.raio * 30;
  }

  // O resultado da retirada: quais triângulos da tela saíram (um byte por triângulo, na malha cheia e na leve) e os
  // lados do contorno dos furos. A vista "depois" é a mesma malha, desenhada sem os triângulos que saíram.
  aplicarRetirada(R, S, L) {
    const d = this.d; if (!d) return;
    const filtrar = (x, saiu) => {
      if (!x) return;
      if (!saiu) { x.depois = null; return; }
      const I = x.todos.array, n = saiu.length;
      let k = 0;
      for (let t = 0; t < n; t++) if (!saiu[t]) k++;
      const J = new Uint32Array(3 * k);
      k = 0;
      for (let t = 0; t < n; t++) if (!saiu[t]) { J[k++] = I[3 * t]; J[k++] = I[3 * t + 1]; J[k++] = I[3 * t + 2]; }
      x.depois = new THREE.BufferAttribute(J, 1);
    };
    filtrar(d, R); filtrar(d.leve, S);
    this.limpar(this.gContorno);
    if (L && L.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(L, 3));
      this.gContorno.add(new THREE.LineSegments(geo, this.matContorno));
    }
    this.montar(true);
  }

  mostrar(fase) { this.fase = fase; this.gContorno.visible = fase === 'depois'; this.montar(true); }

  indice(x) { return this.fase === 'depois' && x.depois ? x.depois : x.todos; }

  // põe na cena a malha: a cheia parada, a leve em movimento; na vista "depois", sem os triângulos que saíram
  montar(forcar) {
    const d = this.d;
    const usarLeve = !!(d && d.leve && this.movendo && d.cab.triangulos > LEVE_A_PARTIR);
    const x = d ? (usarLeve ? d.leve : d) : null;
    const atual = this.gMalha.children[0];
    if (x) {
      const ind = this.indice(x);
      if (x.geo.index !== ind) { x.geo.setIndex(ind); forcar = true; }
    }
    if (!forcar && atual && x && atual.geometry === x.geo) return;
    if (!atual || !x || atual.geometry !== x.geo) {
      for (const m of [...this.gMalha.children]) this.gMalha.remove(m);
      if (x) this.gMalha.add(new THREE.Mesh(x.geo, this.matMalha));
    }
    this.sujo = true;
  }

  // cores: na vista "antes", cada alvo conforme marcado ou selecionado; na "depois", só a peça
  pintar(alvos, sel, apagarSoltos) {
    const m = this.d; if (!m) return;
    const tab = (cor) => [cor.r, cor.g, cor.b];
    const peca = tab(COR.peca), solto = tab(apagarSoltos ? COR.solto : COR.peca);
    const porAlvo = (alvos || []).map((x) => tab(x.marcado ? (x.i === sel ? COR.alvoSel : COR.alvo) : (x.i === sel ? COR.foraSel : COR.fora)));
    const antes = this.fase === 'antes';
    for (const d of [m, m.leve]) {
      if (!d) continue;
      const c = d.geo.getAttribute('color'), a = c.array, M = d.marcas;
      for (let k = 0; k < M.length; k++) {
        const v = M[k];
        let cor = peca;
        if (v === 1) { if (antes) cor = solto; } else if (v >= 2) { const ca = porAlvo[v - 2]; if (ca && (antes || !alvos[v - 2].retirado)) cor = ca; }
        a[3 * k] = cor[0]; a[3 * k + 1] = cor[1]; a[3 * k + 2] = cor[2];
      }
      c.needsUpdate = true;
    }
    this.sujo = true;
  }

  modoArrasto(nome) {
    const b = this.ctl.mouseButtons;
    b.LEFT = nome === 'mover' ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE; b.MIDDLE = THREE.MOUSE.DOLLY; b.RIGHT = THREE.MOUSE.PAN;
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
    let dir = new THREE.Vector3(...dirs[nome]);
    const cima = new THREE.Vector3(0, 0, 1);
    if (nome === 'iso' && this.frente) {
      // escaneamento de um lado só: a vista de abertura olha para o lado escaneado, não para o avesso da malha
      const f = this.frente;
      if (Math.abs(f.z) > 0.9) cima.set(0, 1, 0);
      const lado = new THREE.Vector3().crossVectors(cima, f).normalize();
      const alto = new THREE.Vector3().crossVectors(f, lado).normalize();
      dir = f.clone().addScaledVector(lado, 0.45).addScaledVector(alto, 0.4);
    }
    this.cam.up.copy(cima);
    this.irPara(dir, this.centro.clone(), this.raio, imediato);
  }

  // olha para um alvo: de lado e um pouco de cima em relação ao eixo dele
  olharAlvo(a) {
    const c = new THREE.Vector3(...a.centro), e = new THREE.Vector3(...a.eixo).normalize();
    const lado = new THREE.Vector3().crossVectors(e, Math.abs(e.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0)).normalize();
    const antes = this.fase === 'antes' || !a.retirado;      // um alvo que ficou é visto inteiro; um que saiu, pelo furo
    const dir = lado.multiplyScalar(0.8).addScaledVector(e, antes ? 0.75 : 1.3);
    const meio = c.clone().addScaledVector(e, antes ? a.altura * 0.4 : 0);
    this.irPara(dir, meio, antes ? Math.max(42, a.altura * 0.8) : 30, false, e);
  }

  // o que está debaixo do cursor: ponto e marca (0 = peça, 1 = lasca solta, 2 + i = alvo i)
  pegar(ev) {
    const d = this.d;
    if (!d) return null;
    const ind = this.indice(d);
    if (d.geo.index !== ind) d.geo.setIndex(ind);
    if (!this.malhaCheia || this.malhaCheia.geometry !== d.geo) this.malhaCheia = new THREE.Mesh(d.geo, this.matMalha);
    const b = this.r.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2(((ev.clientX - b.left) / b.width) * 2 - 1, -((ev.clientY - b.top) / b.height) * 2 + 1), this.cam);
    const hit = this.raycaster.intersectObject(this.malhaCheia, false)[0];
    if (!hit) return null;
    const M = d.marcas;
    return { ponto: [hit.point.x, hit.point.y, hit.point.z], marca: Math.max(M[hit.face.a], M[hit.face.b], M[hit.face.c]) };
  }
}

// ============================================================================
// estado
// ============================================================================
const S = { r: null, fase: 'antes', sel: null, ferr: 'selecionar', ocupado: false, nLog: 0, log: [], versaoApp: '', versaoMalha: -1, versaoLimpa: -1,
  tarefa: 'analise', exportando: false };
let visor = null;
try { visor = new Visor($('#area3d'), $('#tela')); } catch (e) { visor = null; }

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
    mostrarProgresso('Copiando o arquivo', 0.03, arq.size > 5e7 ? 'Arquivo grande: a cópia leva alguns segundos. Pelo botão Abrir malha não há cópia.' : '');
    const r = await api('/api/enviar?nome=' + encodeURIComponent(arq.name), arq);
    mostrarArquivo(r.nome, r.tamanho);
    $('#progresso').hidden = true;
    if (!S.r) $('#vazio').hidden = false;
    decidirAbertura(r);
  } catch (e) { $('#progresso').hidden = true; if (!S.r) $('#vazio').hidden = false; toast(e.message, true); }
}

const gb = (b) => br((b / 1073741824).toFixed(1));

// Só pergunta quando a conta diz que a malha não cabe folgada na memória livre.
function decidirAbertura(r) {
  const a = r.avaliacao;
  if (a && a.apertado && a.livre) {
    const n = a.triangulos || a.estimado;
    if (!confirm(`${r.nome} tem ${a.triangulos ? '' : 'cerca de '}${milhar(n)} triângulos.\n\nPara abrir, o Cleanmold precisa de uns ${gb(a.precisa)} GB de memória, e este computador tem ${gb(a.livre)} GB livres agora (de ${gb(a.total)} GB).\n\nFeche outros programas antes de continuar. Abrir assim mesmo?`)) return;
  }
  iniciar('analise', '/api/analisar', {});
}

function mostrarArquivo(nome, tamanho) {
  $('#topoArquivo').textContent = nome; S.arquivo = nome;
  $('#topoQuando').textContent = '';
  if (!S.r) por($('#cartaoMalha'), el('div', { class: 'mono', text: nome }), tamanho ? el('div', { class: 'fraco', text: br((tamanho / 1048576).toFixed(1)) + ' MB' }) : null);
}

const TAREFAS = {
  analise: { titulo: 'Procurando os alvos', fracao: (log) => {
    let f = 0.04;
    for (const l of log) {
      if (/^Lendo/.test(l)) f = Math.max(f, 0.05);
      if (/triângulos$/.test(l)) f = Math.max(f, 0.3);
      if (/pontos de amostra/.test(l)) f = Math.max(f, 0.5);
      const m = /Procurando pés.*?(\d+)%/.exec(l); if (m) f = Math.max(f, 0.52 + Number(m[1]) / 100 * 0.2);
      if (/Conferindo esferas/.test(l)) f = Math.max(f, 0.74);
      if (/alvos encontrados/.test(l)) f = Math.max(f, 0.8);
      if (/Indexando/.test(l)) f = Math.max(f, 0.82);
      if (/Preparando a vista/.test(l)) f = Math.max(f, 0.88);
    }
    return Math.min(f, 0.98);
  } },
  limpeza: { titulo: 'Retirando os alvos', fracao: (log) => {
    let f = 0.04;
    for (const l of log) {
      const m = /Retirando alvos… (\d+)%/.exec(l); if (m) f = Math.max(f, 0.06 + Number(m[1]) / 100 * 0.8);
      if (/^Malha limpa/.test(l)) f = Math.max(f, 0.9);
      if (/Preparando a vista/.test(l)) f = Math.max(f, 0.9);
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
    if (!parado) estadoParado();
    toast(e.message, true, 9000);
  }
}

function estadoParado() {
  if (S.exportando) estado('andando', 'Gravando a malha limpa');
  else if (S.falha) estado('erro', S.r ? `A análise de ${S.falha.arquivo} falhou — na tela continua ${S.r.arquivo}` : 'A análise falhou');
  else if (S.r && S.r.limpo) estado('ok', 'Alvos retirados');
  else if (S.r) estado('ok', S.r.alvos.length + (S.r.alvos.length === 1 ? ' alvo encontrado' : ' alvos encontrados'));
  else estado('', 'Pronto para abrir uma malha');
}

function travar() {
  $('.dir').inert = true; $('.esq').inert = true;
  for (const b of $$('[data-precisa], [data-precisa-saida], [data-desfazer], [data-ferr], [data-acao=abrir], #btPrincipal')) b.disabled = true;
  for (const f of $$('.fundo')) f.hidden = true;
}

function ocupar(sim) {
  S.ocupado = sim;
  $('.dir').inert = sim; $('#secOpcoes').inert = sim;
  atualizarBotoes();
}

function atualizarBotoes() {
  const tem = !!S.r, oc = S.ocupado;
  for (const b of $$('[data-precisa]')) b.disabled = oc || !tem;
  for (const b of $$('[data-precisa-saida]')) b.disabled = oc || !tem || !S.r.limpo;
  for (const b of $$('[data-desfazer]')) b.disabled = oc || !tem || !S.r.limpo;
  $('[data-ferr=manual]').disabled = oc || !tem;
  for (const b of $$('[data-fase]')) b.disabled = !tem || (b.dataset.fase === 'depois' && !S.r.limpo);
  const p = $('#btPrincipal');
  if (!tem) { p.textContent = 'Retirar alvos'; p.disabled = true; return; }
  const n = S.r.alvos.filter((a) => a.marcado).length;
  if (S.r.limpo && !mudou()) { p.textContent = 'Salvar a malha limpa'; p.disabled = oc; p.dataset.oque = 'exportar'; }
  else { p.textContent = S.r.limpo ? 'Retirar de novo' : (n ? `Retirar ${n} ${n === 1 ? 'alvo' : 'alvos'}` : 'Apagar as lascas soltas'); p.disabled = oc || (!n && !lascas()); p.dataset.oque = 'limpar'; }
}

// lascas soltas que sairiam com as opções de agora
const lascas = () => ($('#opSoltos').checked && S.r ? S.r.soltos_sem_alvo : 0);

// a seleção (ou as opções) mudou depois da última retirada?
function mudou() {
  if (!S.r || !S.r.limpo) return false;
  if (S.r.alvos.some((a) => a.marcado !== a.tentado)) return true;
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
  const passo = async () => {
    let e;
    try { e = await api('/api/estado?desde=' + S.nLog); } catch (x) { if (!parado) setTimeout(passo, 1500); return; }
    S.log.push(...e.log); S.nLog = e.n_log;
    mostrarProgresso(T.titulo, T.fracao(S.log), S.log.length ? S.log[S.log.length - 1] : '');
    if (e.ocupado) { setTimeout(passo, 500); return; }
    if (e.erro) {
      $('#progresso').hidden = true;
      if (!S.r && e.tem_resultado) try { await carregarResultado(true); } catch (x) { /* fica só o aviso */ }
      ocupar(false);
      if (S.tarefa === 'analise') mostrarFalha(e.falha || { arquivo: S.arquivo || 'a malha', erro: e.erro });
      else { estadoParado(); toast(e.erro, true, 0); }
      if (!S.r) $('#vazio').hidden = false;
      return;
    }
    try { await carregarResultado(S.tarefa === 'analise'); } catch (x) {
      $('#progresso').hidden = true;
      if (parado) return;
      S.ocupado = false; travar();
      estado('erro', 'Não consegui carregar o resultado');
      toast('O trabalho terminou, mas não consegui carregar o resultado (' + x.message + '). Feche esta janela e abra o Cleanmold de novo.', true, 0);
      return;
    }
    $('#progresso').hidden = true;
    ocupar(false);
    if (S.tarefa === 'limpeza') { trocarFase('depois'); avisarRetirada(); }
  };
  mostrarProgresso(T.titulo, T.fracao(S.log), '');
  passo();
}

function avisarRetirada() {
  const c = contar();
  if (c.conferir) toast(`${c.conferir} ${c.conferir === 1 ? 'alvo ficou' : 'alvos ficaram'} para conferir: veja na lista.`, true, 0);
}

async function carregarResultado(novaPeca) {
  const r = await api('/api/resultado');
  await aplicarResultado(r, novaPeca);
}

async function buscarMalha() {
  if (!visor) return;
  const r = S.r;
  if (S.versaoMalha !== r.versoes.alvos) {
    const cheia = await api('/api/malha.bin', undefined, true);
    // a malha leve só existe para malhas grandes: o cabeçalho da cheia diz quantos triângulos ela tem
    const n = new DataView(cheia).getUint32(0, true);
    const cab = JSON.parse(new TextDecoder().decode(new Uint8Array(cheia, 4, n)));
    let leve = null;
    if (cab.triangulos > 300000) try { leve = await api('/api/malha.bin?nivel=leve', undefined, true); } catch (e) { leve = null; }
    visor.guardar(cheia, leve);
    S.versaoMalha = r.versoes.alvos; S.versaoLimpa = -1;
  }
  if (S.versaoLimpa !== r.versoes.limpa) {
    if (r.limpo) { const { bloco } = lerBlocos(await api('/api/retirada.bin', undefined, true)); visor.aplicarRetirada(bloco('R'), bloco('S'), bloco('L')); }
    else visor.aplicarRetirada(null, null, null);
    S.versaoLimpa = r.versoes.limpa;
  }
}

async function aplicarResultado(r, novaPeca) {
  const antes = S.r;
  S.r = r;
  if (novaPeca) {
    S.sel = null; S.falha = null; S.fase = 'antes'; S.versaoMalha = -1; S.versaoLimpa = -1;
    if (visor) visor.esquecer();
    $('#expPasta').value = r.pasta || '';
    $('#vazioErro').hidden = true; $('#expResultado').hidden = true;
    if (S.ferr !== 'selecionar' && S.ferr !== 'mover') escolherFerramenta('selecionar');
  }
  if (novaPeca || !antes) { $('#opMargem').value = br(String(r.opcoes.margem)); $('#opAlcance').value = br(String(r.opcoes.alcance)); $('#opSoltos').checked = r.opcoes.remover_soltos; }
  $('#vazio').hidden = true;
  for (const s of ['#secResumo', '#secOpcoes']) $(s).hidden = false;
  $('#topoArquivo').textContent = r.arquivo;
  $('#topoQuando').textContent = r.analisado_em ? '· aberta em ' + r.analisado_em : '';
  if (S.sel !== null && !r.alvos[S.sel]) S.sel = null;
  if (S.fase === 'depois' && !r.limpo) S.fase = 'antes';
  if (visor) {
    try { await buscarMalha(); } catch (e) { toast('Não consegui carregar a malha para a tela: ' + e.message, true); }
    visor.frente = r.frente ? new THREE.Vector3(...r.frente) : null;
    visor.mostrar(S.fase);
    if (novaPeca) { visor.vista('iso', true); for (const o of $$('[data-cam]')) o.classList.toggle('ativo', o.dataset.cam === 'iso'); }
  }
  if (!S.ocupado) ocupar(false);
  estadoParado();
  desenharTudo();
}

// ---------- desenho ----------
function desenharTudo() {
  desenharEsquerda(); desenharDireita(); pintar(); desenharLegenda(); atualizarBotoes();
  for (const b of $$('[data-fase]')) b.classList.toggle('ativa', b.dataset.fase === S.fase);
  $('#stVersao').textContent = 'Cleanmold ' + S.versaoApp;
}

function pintar() {
  if (visor && S.r) visor.pintar(S.r.alvos, S.sel, $('#opSoltos').checked);
}

function desenharLegenda() {
  const cx = $('#legendaCores');
  cx.hidden = !S.r;
  if (!S.r) return;
  const item = (cor, texto) => el('span', {}, el('i', { style: 'background:' + cor }), texto);
  if (S.fase === 'antes') por(cx, S.r.alvos.some((a) => a.marcado) ? item('#1fa368', 'alvo marcado para retirar') : null,
    S.r.alvos.some((a) => !a.marcado) ? item('#d9962b', 'alvo desmarcado (fica)') : null,
    lascas() ? item('#86c9a7', 'lasca solta (será apagada)') : null, item('#b4b9c1', 'peça'));
  else por(cx, item('#0f7a4d', 'contorno do furo de cada alvo'), S.r.alvos.some((a) => !a.retirado) ? item('#d9962b', 'alvo que ficou') : null, item('#b4b9c1', 'peça (não foi tocada)'));
}

function contar() {
  const a = S.r.alvos;
  const sit = a.map(situacao);
  return { marcados: a.filter((x) => x.marcado).length, retirados: a.filter((x) => x.retirado).length,
    ok: sit.filter((s) => s.cls === 'ok').length, conferir: sit.filter((s) => s.cls === 'lim' || s.cls === 'fora').length,
    duvidosos: a.filter((x) => !x.seguro).length };
}

function situacao(a) {
  if (!S.r.limpo) return a.marcado ? { cls: 'neutro', t: 'a retirar' } : { cls: 'neutro', t: 'fica' };
  if (!a.tentado) return { cls: 'neutro', t: 'ficou' };
  if (!a.retirado) return { cls: 'fora', t: 'não saiu' };
  if (a.aviso) return { cls: 'lim', t: 'conferir' };
  return { cls: 'ok', t: 'retirado' };
}

const mb = (b) => br((b / 1048576).toFixed(b > 104857600 ? 0 : 1)) + ' MB';

function desenharEsquerda() {
  const r = S.r; if (!r) return;
  const [lo, hi] = r.caixa;
  por($('#cartaoMalha'), el('div', { class: 'mono', text: r.arquivo }),
    el('div', { class: 'fraco', text: milhar(r.triangulos) + ' triângulos · ' + mb(r.tamanho) }),
    el('div', { class: 'fraco', text: `${num(hi[0] - lo[0], 0)} × ${num(hi[1] - lo[1], 0)} × ${num(hi[2] - lo[2], 0)} mm · aresta ${num(r.aresta, 2)} mm` }));
  const c = contar();
  const n = (rot, v, cls) => el('div', { class: 'num ' + (cls || '') }, rot, el('b', { text: String(v) }));
  $('#resumoNums').replaceChildren(
    n('Alvos encontrados', r.alvos.length, 'destaque'), n('Pedaços soltos', r.soltos),
    r.limpo ? n('Retirados', c.retirados) : n('Marcados', c.marcados),
    r.limpo ? n('A conferir', c.conferir, c.conferir ? 'atencao' : '') : n('Confiança baixa', c.duvidosos, c.duvidosos ? 'atencao' : ''));
  $('#stConta').textContent = r.limpo ? `malha limpa: ${milhar(r.triangulos_limpa)} triângulos (${milhar(r.triangulos - r.triangulos_limpa)} a menos)` : '';
}

function desenharDireita() {
  const r = S.r;
  $('#dirVazio').hidden = !!r; $('#dirCheio').hidden = !r;
  if (!r) return;
  const cx = $('#dirCheio');
  const c = contar();
  const partes = [el('div', { class: 'lista-topo' }, el('div', { class: 't', text: 'Alvos' }),
    el('span', { class: 'chip', text: r.alvos.length + (r.alvos.length === 1 ? ' encontrado' : ' encontrados') }))];
  // o que fazer agora
  if (!r.limpo) {
    const lk = lascas();
    partes.push(el('div', { class: 'caixa-acao' }, el('div', { class: 'forte', text: `${c.marcados} ${c.marcados === 1 ? 'alvo marcado' : 'alvos marcados'} para retirar` }),
      el('div', { text: 'Confira no modelo: o que está em verde sai, o que está em laranja fica. No lugar de cada pé fica um furo; o resto da malha não é tocado.' +
        (lk ? ` ${lk} ${lk === 1 ? 'lasca solta' : 'lascas soltas'} do escaneamento também ${lk === 1 ? 'sai' : 'saem'}.` : '') }),
      el('button', { class: 'bt primario', text: c.marcados ? 'Retirar os alvos' : 'Apagar as lascas soltas', disabled: !c.marcados && !lk, onclick: limpar })));
  } else if (mudou()) {
    partes.push(el('div', { class: 'caixa-acao' }, el('div', { class: 'forte', text: 'A seleção ou o recorte mudaram' }),
      el('div', { text: 'A malha limpa na tela ainda é a da retirada anterior.' }), el('button', { class: 'bt primario', text: 'Retirar de novo', onclick: limpar })));
  } else {
    partes.push(el('div', { class: 'caixa-acao' }, el('div', { class: 'forte', text: `${c.retirados} ${c.retirados === 1 ? 'alvo retirado' : 'alvos retirados'}` + (c.conferir ? `, ${c.conferir} a conferir` : '') }),
      el('div', { text: `Saíram ${milhar(r.triangulos - r.triangulos_limpa)} triângulos; os outros ${milhar(r.triangulos_limpa)} são os da malha aberta, sem alteração. ` +
        (c.conferir ? 'Olhe no modelo os marcados com “conferir” antes de salvar.' : 'Compare Antes e Depois na barra de cima.') }),
      el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, el('button', { class: 'bt primario', text: 'Salvar a malha limpa', onclick: () => abrirExportar() }),
        el('button', { class: 'bt', text: 'Desfazer a retirada', onclick: desfazer }))));
  }
  if (!r.alvos.length) partes.push(el('div', { class: 'caixa-nota', text: 'Nenhum alvo foi reconhecido nesta malha. Se há alvos, use a ferramenta de indicar à mão (a mira, na barra de cima) e clique no pé de cada um.' }));
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
      if (a.soltos) det.append(el('span', { text: `${a.soltos} ${a.soltos === 1 ? 'pedaço solto pertence' : 'pedaços soltos pertencem'} a este alvo e ${a.soltos === 1 ? 'sai' : 'saem'} com ele.` }));
      if (!a.seguro) det.append(el('span', { class: 'obs', text: 'Confiança baixa: o padrão do pé saiu pouco nítido. Confira no modelo e marque se for alvo.' }));
      if (r.limpo && a.tentado) {
        if (a.retirado) det.append(el('span', {}, 'Furo de Ø ', el('span', { class: 'mono', text: num(a.diametro, 1) }), ' mm · ', el('span', { class: 'mono', text: milhar(a.removidos) }), ' triângulos retirados',
          a.referencia ? ' · peça em volta: ' + a.referencia : ''));
        if (a.nota) det.append(el('span', { text: a.nota.charAt(0).toUpperCase() + a.nota.slice(1) + '.' }));
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
  if (r.soltos_sem_alvo && !r.limpo) partes.push(el('p', { class: 'fraco', text: `${r.soltos_sem_alvo} ${r.soltos_sem_alvo === 1 ? 'pedaço solto não está' : 'pedaços soltos não estão'} perto de nenhum alvo (lascas e ruído do escaneamento).` + ($('#opSoltos').checked ? ' Também serão apagados.' : ' Ficam na malha.') }));
  const topo = cx.parentElement.scrollTop;
  cx.replaceChildren(...partes);
  cx.parentElement.scrollTop = topo;
}

// ---------- seleção ----------
function selecionar(i, moverCamera) {
  S.sel = i;
  desenharDireita(); pintar();
  const linha = $(`.al-linha[data-i="${i}"]`);
  if (linha) linha.scrollIntoView({ block: 'nearest' });
  if (moverCamera && visor && S.r.alvos[i]) { visor.olharAlvo(S.r.alvos[i]); for (const o of $$('[data-cam]')) o.classList.remove('ativo'); }
}

function marcar(i, sim) { S.r.alvos[i].marcado = sim; desenharTudo(); }
function marcarVarios(fn) { for (const a of S.r.alvos) a.marcado = !!fn(a); desenharTudo(); }

function trocarFase(f) {
  if (!S.r || (f === 'depois' && !S.r.limpo)) return;
  S.fase = f;
  if (S.ferr === 'manual' && f !== 'antes') escolherFerramenta('selecionar');
  if (visor) visor.mostrar(f);
  desenharTudo();
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
  if (!escolha.length && !lascas()) { toast('Marque pelo menos um alvo para retirar.', true); return; }
  if (S.ferr === 'manual') escolherFerramenta('selecionar');
  await iniciar('limpeza', '/api/limpar', { escolha, opcoes });
}

// a retirada é só a lista dos triângulos que saem: desfazer é imediato
async function desfazer() {
  if (!S.r || S.ocupado || !S.r.limpo) return;
  try {
    const marcados = S.r.alvos.map((a) => a.marcado);
    const r = await api('/api/desfazer', {});
    r.alvos.forEach((a, k) => { a.marcado = marcados[k]; });
    S.fase = 'antes';
    await aplicarResultado(r, false);
  } catch (e) { toast(e.message, true); }
}

// ---------- alvo indicado à mão ----------
function escolherFerramenta(nome) {
  if (nome === 'manual' && (!S.r || S.ocupado)) return;
  S.ferr = nome;
  for (const b of $$('[data-ferr]')) b.classList.toggle('ativo', b.dataset.ferr === nome);
  if (visor) visor.modoArrasto(nome);
  $('#dicaManual').hidden = nome !== 'manual';
  $('#tela').style.cursor = nome === 'manual' ? 'crosshair' : (nome === 'mover' ? 'grab' : '');
  if (nome === 'manual' && S.fase !== 'antes') trocarFase('antes');
}

async function alvoManual(ponto) {
  const d = Number(String($('#manDiam').value).replace(',', '.'));
  if (!(d >= 2 && d <= 120)) { toast('Ø do pé: informe um valor entre 2 e 120 mm.', true); return; }
  try {
    estado('andando', 'Acrescentando o alvo');
    const marcados = new Map(S.r.alvos.map((a) => [a.i, a.marcado]));
    const r = await api('/api/manual', { ponto, diametro: d });
    for (const a of r.alvos) if (marcados.has(a.i)) a.marcado = marcados.get(a.i);
    S.fase = 'antes';
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
    S.sel = null; S.fase = 'antes';
    await aplicarResultado(r, false);
  } catch (e) { toast(e.message, true); }
}

// ---------- textos ----------
function abrirTexto(titulo, conteudo) { $('#tTexto').textContent = titulo; $('#textoCorpo').replaceChildren(conteudo); $('#mTexto').hidden = false; }

function ajuda() {
  const c = el('div', { class: 'ajuda-texto' });
  c.innerHTML = `
    <h3>Do escaneamento à malha limpa</h3>
    <ul><li>Exporte a <b>malha</b> do Control X ou do Design X em STL (também PLY, OBJ ou OFF), em milímetros, com os alvos como saíram do escaneamento. Não reduza a malha antes: o Cleanmold abre a malha inteira.</li>
    <li>Em <b>Abrir malha</b>, escolha o arquivo. A procura dos alvos começa sozinha.</li>
    <li>Na lista à direita, cada alvo tem uma <b>confiança</b>. Os de confiança alta já vêm marcados. Clique numa linha para ver o alvo no modelo.</li>
    <li><b>Retirar os alvos</b> recorta cada alvo marcado rente à peça. Use <b>Antes</b> e <b>Depois</b>, na barra de cima, para comparar; em Depois, o contorno de cada furo aparece em verde.</li>
    <li><b>Salvar a malha limpa</b> grava o STL (ou o PLY) ao lado da malha aberta, com “_limpa” no nome. O arquivo aberto não é alterado.</li></ul>
    <h3>O que o Cleanmold faz, e o que não faz</h3>
    <ul><li>Ele <b>só retira</b>. No lugar de cada pé fica um <b>furo aberto</b>, um pouco maior que o pé (a margem). Fechar os furos é trabalho do Design X.</li>
    <li>Nenhum triângulo é criado, movido ou reduzido. A malha limpa são os triângulos da malha aberta, menos os dos alvos: o que não é alvo sai idêntico ao que entrou.</li>
    <li><b>Desfazer a retirada</b> é imediato, e dá para retirar de novo com outra seleção ou outra margem quantas vezes quiser.</li></ul>
    <h3>O que o Cleanmold entende por alvo</h3>
    <ul><li>Um <b>pé cilíndrico</b> de diâmetro conhecido (a base magnética, Ø 18,8 mm no peão e Ø 14,9 mm no dado com base) em pé sobre a peça, e acima dele o corpo do alvo: pescoço, esfera, dodecaedro.</li>
    <li>O corpo pode vir amassado, torto, com caroços ou partido em <b>pedaços soltos</b>: o que decide é o pé e o perfil logo acima dele. Quando o pé também saiu amassado, o alvo é achado pela esfera ou pelo dodecaedro e aparece como “pé amassado”.</li>
    <li>Os pedaços soltos de um alvo saem com ele. As outras lascas soltas do escaneamento saem também, a menos que você desmarque <b>Apagar também as lascas soltas</b>.</li></ul>
    <h3>Quando faltar ou sobrar um alvo</h3>
    <ul><li><b>Sobrou</b> (não é alvo): desmarque a linha. Fica em laranja no modelo e não é tocado, nem os pedaços soltos dele.</li>
    <li><b>Faltou</b>: use a ferramenta com a mira, na barra de cima, informe o diâmetro do pé e clique em qualquer ponto do pé do alvo. Ele entra na lista como “Indicado à mão”.</li></ul>
    <h3>Como o corte é feito</h3>
    <ul><li>A superfície da peça em volta do pé é ajustada a um <b>plano</b>, <b>cilindro</b>, <b>esfera</b>, <b>cone</b> ou <b>superfície curva suave</b>. Sai o que está acima dessa superfície e ligado ao pé: o pé, as rebarbas grudadas nele e o corpo do alvo.</li>
    <li>Outra parte da peça que passe perto do alvo (a palheta vizinha, uma parede em frente) não tem ligação com o pé e não é tocada.</li>
    <li><b>Margem</b>: quanto o furo passa do pé, para o contorno cair em superfície limpa. <b>Alcance</b>: até onde, em volta do pé, rebarbas grudadas nele são recortadas quando não terminam sozinhas.</li></ul>
    <h3>Situação de cada alvo depois da retirada</h3>
    <ul><li><b>Retirado</b>: saiu inteiro e o furo ficou com um contorno só.</li>
    <li><b>Conferir</b>: o corpo do alvo estava grudado em outra parte da peça por uma rebarba do escaneamento, e pode ter sobrado um toco dela. Olhe no modelo.</li>
    <li><b>Não saiu</b>: não havia superfície da peça em volta para servir de referência. A malha ali ficou como estava.</li></ul>
    <h3>Malha grande</h3>
    <ul><li>A malha é aberta inteira, sem redução. A vista 3D mostra uma versão leve enquanto gira e a completa quando para; em volta dos alvos, todos os triângulos aparecem sempre.</li>
    <li>Se a conta indicar que a malha não cabe folgada na memória livre do computador, o Cleanmold avisa antes de abrir.</li>
    <li>O <b>PLY</b> grava a mesma malha em menos da metade do tamanho do STL.</li></ul>`;
  abrirTexto('Como usar', c);
}

function sobre() {
  const c = el('div', { class: 'ajuda-texto' });
  c.append(el('p', {}, el('b', { text: 'Cleanmold ' + S.versaoApp }), ' · retira os alvos de escaneamento da malha e deixa o furo no lugar de cada um. Da mesma família do Enmold.'),
    el('p', { text: 'Tudo roda neste computador. A malha e os arquivos não são enviados pela internet.' }),
    el('p', { text: 'O que não é alvo sai do Cleanmold idêntico ao que entrou: nenhum triângulo é criado, movido ou reduzido.' }),
    el('p', { class: 'fraco', text: 'Usa three.js (MIT) e as fontes IBM Plex (OFL).' }));
  abrirTexto('Sobre o Cleanmold', c);
}

async function registro() {
  let txt;
  try { txt = (await api('/api/estado?desde=0')).log.join('\n') || 'Sem registro.'; } catch (x) { txt = x.message; }
  abrirTexto('Registro', el('pre', { class: 'registro', text: txt }));
}

// ---------- salvar a malha limpa ----------
function abrirExportar() {
  const r = S.r; if (!r) return;
  if (!r.limpo) { toast('Retire os alvos antes de salvar a malha limpa.', true); return; }
  if (mudou()) { toast('A seleção mudou depois da última retirada. Use “Retirar de novo” antes de salvar.', true, 9000); return; }
  $('#expStl').textContent = `${milhar(r.triangulos_limpa)} triângulos · ${mb(r.tamanho_stl)}`;
  $('#expPly').textContent = `${milhar(r.triangulos_limpa)} triângulos · cerca de ${mb(r.tamanho_ply)}`;
  if (!$('#expPasta').value) $('#expPasta').value = r.pasta || '';
  if (!S.exportando) {
    let marcados = ['stl'];
    try { marcados = JSON.parse(localStorage.getItem('cleanmold.formatos') || '["stl"]'); } catch (e) { /* padrão */ }
    if (!marcados.length) marcados = ['stl'];
    for (const c of $$('#expItens input')) c.checked = marcados.includes(c.value);
    $('#expResultado').hidden = true;
  }
  $('#mExportar').hidden = false;
}

async function gerar() {
  const itens = $$('#expItens input:checked').map((c) => c.value);
  try { localStorage.setItem('cleanmold.formatos', JSON.stringify(itens)); } catch (e) { /* sem armazenamento */ }
  const cx = $('#expResultado');
  if ($('#btGerar').disabled) return;
  $('#btGerar').disabled = true;
  try {
    await api('/api/exportar', { itens, pasta: $('#expPasta').value.trim() });
  } catch (e) { $('#btGerar').disabled = false; cx.hidden = false; cx.replaceChildren(el('div', { class: 'falha', text: e.message })); return; }
  acompanharGeracao();
}

function acompanharGeracao() {
  const cx = $('#expResultado');
  $('#btGerar').disabled = true; S.exportando = true;
  cx.hidden = false; cx.replaceChildren(el('div', { class: 'fraco', text: 'Gravando…' }));
  estado('andando', 'Gravando a malha limpa');
  let n0 = null;
  const fim = (erro, x) => {
    $('#btGerar').disabled = false; S.exportando = false;
    if (!parado) estadoParado();
    if (erro) cx.replaceChildren(el('div', { class: 'falha', text: erro })); else mostrarExportados(x);
    if (!$('#mExportar').hidden) return;
    const nf = x ? Object.keys(x.falhas || {}).length : 0, na = x ? Object.keys(x.arquivos).length : 0;
    if (erro) toast('A malha limpa não foi gravada: ' + erro, true, 0);
    else toast(`${na} ${na === 1 ? 'arquivo gravado' : 'arquivos gravados'} em ${x.pasta}.` + (nf ? ` ${nf} ${nf === 1 ? 'falhou' : 'falharam'}: veja em Salvar a malha limpa.` : ''), nf > 0, nf ? 0 : 9000);
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
  const nomes = { stl: 'Malha limpa (STL)', ply: 'Malha limpa (PLY)' };
  for (const [k, cam] of Object.entries(x.arquivos)) cx.append(el('div', { class: 'arq' }, el('span', {}, nomes[k] + ' · ', el('span', { class: 'mono', text: cam.split(/[\\/]/).pop() }))));
  for (const [k, msg] of Object.entries(x.falhas || {})) cx.append(el('div', { class: 'falha', text: `${nomes[k]} não foi gravado: ${msg}.` }));
  if (Object.keys(x.arquivos).length) cx.append(el('button', { class: 'bt-texto', type: 'button', style: 'justify-self:start', text: 'Abrir a pasta',
    onclick: () => api('/api/mostrar', { caminho: x.pasta }).catch((e) => toast(e.message, true)) }));
}

// ============================================================================
// ligações
// ============================================================================
const ACOES = {
  abrir: abrirMalha, exportar: () => abrirExportar(), registro, ajuda, sobre, limpar, desfazer,
  'marcar-todos': () => marcarVarios(() => true), 'marcar-seguros': () => marcarVarios((a) => a.seguro), desmarcar: () => marcarVarios(() => false),
  manual: () => escolherFerramenta('manual'),
  reanalisar: () => {
    if (S.ocupado) { toast('Espere terminar o que está em andamento.', true); return; }
    if (S.r && S.r.limpo && !confirm('Procurar de novo desfaz a retirada dos alvos já feita. Continuar?')) return;
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
for (const b of $$('[data-precisa], [data-precisa-saida], [data-desfazer]')) b.disabled = true;
for (const b of $$('[data-acao]')) b.addEventListener('click', () => { fecharMenus(); ACOES[b.dataset.acao](); });
$('#btPrincipal').addEventListener('click', () => { if ($('#btPrincipal').dataset.oque === 'exportar') abrirExportar(); else limpar(); });
for (const c of [$('#opMargem'), $('#opAlcance'), $('#opSoltos')]) c.addEventListener('change', () => { if (S.r) desenharTudo(); });
document.addEventListener('click', (ev) => { if (!ev.target.closest('.menu')) fecharMenus(); });
document.addEventListener('keydown', (ev) => {
  const digitando = /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
  if ((ev.ctrlKey || ev.metaKey) && !ev.shiftKey && ev.key.toLowerCase() === 'z' && !digitando) { ev.preventDefault(); desfazer(); return; }
  if (ev.key !== 'Escape') return;
  const aberto = $$('.fundo').some((f) => !f.hidden) || $$('.menu-caixa').some((m) => !m.hidden);
  fecharMenus(); for (const f of $$('.fundo')) f.hidden = true;
  if (!aberto && S.ferr === 'manual') escolherFerramenta('selecionar');
});
for (const b of $$('[data-fechar]')) b.addEventListener('click', () => { b.closest('.fundo').hidden = true; });
for (const f of $$('.fundo')) f.addEventListener('mousedown', (ev) => { if (ev.target === f) f.hidden = true; });

$('#btGerar').addEventListener('click', gerar);
$('#btPasta').addEventListener('click', async () => {
  try { const r = await api('/api/pasta', { pasta: $('#expPasta').value }); if (r.pasta) $('#expPasta').value = r.pasta; } catch (e) { toast(e.message, true); }
});
for (const b of $$('[data-fase]')) b.addEventListener('click', () => trocarFase(b.dataset.fase));
for (const b of $$('[data-ferr]')) b.addEventListener('click', () => escolherFerramenta(b.dataset.ferr));
$('#manSair').addEventListener('click', () => escolherFerramenta('selecionar'));
$('#btAjustar').addEventListener('click', () => { if (visor) { visor.vista('iso'); for (const o of $$('[data-cam]')) o.classList.toggle('ativo', o.dataset.cam === 'iso'); } });
for (const b of $$('[data-cam]')) b.addEventListener('click', () => {
  for (const o of $$('[data-cam]')) o.classList.toggle('ativo', o === b);
  if (visor) visor.vista(b.dataset.cam);
});

// clique no modelo (sem confundir com arrastar)
{
  let ini = null;
  const tela = $('#tela');
  tela.addEventListener('pointerdown', (ev) => { ini = { x: ev.clientX, y: ev.clientY, b: ev.button }; });
  tela.addEventListener('pointerup', (ev) => {
    if (!ini || ini.b !== 0 || Math.hypot(ev.clientX - ini.x, ev.clientY - ini.y) > 4 || !visor || !S.r || S.ferr === 'mover' || S.ocupado) return;
    const p = visor.pegar(ev);
    if (!p) return;
    if (S.ferr === 'manual') { alvoManual(p.ponto); return; }
    if (p.marca >= 2) { selecionar(p.marca - 2, false); return; }
    if (S.fase === 'depois') {
      // o alvo saiu: o clique perto do furo dele seleciona a linha
      let melhor = null, dm = 25;
      for (const a of S.r.alvos) { const d = Math.hypot(a.centro[0] - p.ponto[0], a.centro[1] - p.ponto[1], a.centro[2] - p.ponto[2]); if (d < dm) { dm = d; melhor = a.i; } }
      if (melhor !== null) selecionar(melhor, false);
    }
  });
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
    if (!visor) toast('O modelo 3D não pôde ser iniciado neste computador (aceleração gráfica indisponível). A lista de alvos e a gravação da malha limpa funcionam normalmente.', true, 0);
    if (e.nome) mostrarArquivo(e.nome);
    if (e.ocupado) {
      S.tarefa = /analisando/.test(e.ocupado) ? 'analise' : /retirando/.test(e.ocupado) ? 'limpeza' : null;
      if (e.tem_resultado && S.tarefa !== 'analise') await carregarResultado(true);
      if (S.tarefa) { S.log = e.log; S.nLog = e.n_log; acompanhar(); return; }
      if (e.tem_resultado) acompanharGeracao();
      return;
    }
    if (e.tem_resultado) { await carregarResultado(true); if (S.r.limpo) trocarFase('depois'); }
    if (e.falha) mostrarFalha(e.falha);
  } catch (x) {
    if (parado || x.message === MSG_PARADO) servidorParou();
    else { estado('erro', 'Erro ao abrir'); toast(x.message + '\nFeche esta janela e abra o Cleanmold de novo.', true, 0); }
  }
})();

// para inspeção e testes automáticos
window.cleanmold = { S, visor, selecionar, marcar, trocarFase, escolherFerramenta, limpar, desfazer, abrirExportar, alvoManual,
  abrirCaminho: async (caminho) => { const r = await api('/api/abrir', { caminho }); mostrarArquivo(r.nome, r.tamanho); await iniciar('analise', '/api/analisar', {}); return r; } };
