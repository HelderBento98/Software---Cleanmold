// Cleanmold — interface: malha escaneada com os alvos, lista de alvos, antes/depois e sólido de revolução.
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

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
};

function lerBlocos(buf) {
  const n = new DataView(buf).getUint32(0, true);
  const cab = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, n)));
  const base = 4 + n;
  const tipos = { V: Float32Array, I: Uint32Array, M: Uint16Array };
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
    this.r = new THREE.WebGLRenderer({ canvas: tela, antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.r.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    this.cena = new THREE.Scene();
    this.cam = new THREE.PerspectiveCamera(26, 1, 1, 100000);
    this.cam.up.set(0, 0, 1);
    this.cam.position.set(600, -700, 500);
    this.ctl = new OrbitControls(this.cam, tela);
    this.ctl.enableDamping = !semMovimento; this.ctl.dampingFactor = 0.12;
    this.ctl.addEventListener('change', () => { this.planosDeCorte(); this.sujo = true; });
    this.ctl.addEventListener('start', () => { for (const o of $$('[data-cam]')) o.classList.remove('ativo'); });
    this.cena.add(new THREE.HemisphereLight(0xffffff, 0x8c929b, 1.2));
    const l1 = new THREE.DirectionalLight(0xffffff, 1.9); l1.position.set(-1, 1.4, 1.2);
    const l2 = new THREE.DirectionalLight(0xe4f5ec, 0.8); l2.position.set(1.2, -0.4, -0.8);
    this.cam.add(l1); this.cam.add(l2); this.cena.add(this.cam);        // a luz acompanha a câmera
    this.gMalha = new THREE.Group(); this.gSolido = new THREE.Group();
    this.cena.add(this.gSolido, this.gMalha);
    // dois lados: escaneamento de um lado só é uma casca aberta, e o verso também precisa aparecer
    this.matMalha = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.15, roughness: 0.6, side: THREE.DoubleSide });
    this.matSolido = new THREE.MeshStandardMaterial({ color: COR.solido, metalness: 0.2, roughness: 0.5, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    this.centro = new THREE.Vector3(); this.raio = 100; this.sujo = true; this.anim = null;
    this.raycaster = new THREE.Raycaster();
    this.malhas = {};                                        // fase -> { geo, marcas }
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
    if (this.anim) this.passoAnim();
    if (this.ctl.update() || this.sujo) { this.sujo = false; this.r.render(this.cena, this.cam); }
  }

  limpar(grupo) {
    for (const m of [...grupo.children]) { grupo.remove(m); if (m.geometry) m.geometry.dispose(); }
  }

  esquecer() { this.malhas = {}; this.limpar(this.gMalha); this.limpar(this.gSolido); this.fase = null; this.sujo = true; }

  guardar(fase, buf) {
    const { cab, bloco } = lerBlocos(buf);
    const V = bloco('V');
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(V, 3));
    geo.setIndex(new THREE.BufferAttribute(bloco('I'), 1));
    geo.computeVertexNormals();
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(V.length), 3));
    geo.computeBoundingSphere();
    if (this.malhas[fase]) this.malhas[fase].geo.dispose();
    this.malhas[fase] = { geo, marcas: bloco('M') || new Uint16Array(V.length / 3), cab };
    if (fase === 'antes') { this.centro.copy(geo.boundingSphere.center); this.raio = geo.boundingSphere.radius; this.limites(); }
  }

  limites() {
    this.ctl.minDistance = this.raio * 0.01; this.ctl.maxDistance = this.raio * 30;
  }

  mostrar(fase) {
    const m = this.malhas[fase === 'solido' ? (this.malhas.depois ? 'depois' : 'antes') : fase];
    this.limpar0();
    if (m) { this.gMalha.add(new THREE.Mesh(m.geo, this.matMalha)); }
    this.fase = fase;
    this.gSolido.visible = fase === 'solido';
    this.opacidadeMalha(fase === 'solido' ? this.opSolido : 1);
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

  // cores: "antes" pinta cada alvo conforme marcado/selecionado; "depois" pinta os remendos
  pintar(fase, alvos, sel, apagarSoltos) {
    const m = this.malhas[fase]; if (!m) return;
    const c = m.geo.getAttribute('color'), a = c.array, M = m.marcas;
    const tab = (cor) => [cor.r, cor.g, cor.b];
    const peca = tab(COR.peca), solto = tab(apagarSoltos ? COR.solto : COR.peca), rem = tab(COR.remendo);
    const porAlvo = (alvos || []).map((x) => tab(x.i === sel ? COR.alvoSel : (x.marcado ? COR.alvo : COR.fora)));
    for (let k = 0; k < M.length; k++) {
      const v = M[k];
      let cor = peca;
      if (fase === 'antes') { if (v === 1) cor = solto; else if (v >= 2) cor = porAlvo[v - 2] || peca; }
      else if (v === 1) cor = rem;
      a[3 * k] = cor[0]; a[3 * k + 1] = cor[1]; a[3 * k + 2] = cor[2];
    }
    c.needsUpdate = true; this.sujo = true;
  }

  modoArrasto(mover) { this.ctl.mouseButtons.LEFT = mover ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE; }

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

  pegar(ev) {
    const m = this.gMalha.children[0];
    if (!m || !this.gMalha.visible) return null;
    const b = this.r.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2(((ev.clientX - b.left) / b.width) * 2 - 1, -((ev.clientY - b.top) / b.height) * 2 + 1), this.cam);
    const hit = this.raycaster.intersectObject(m, false)[0];
    if (!hit) return null;
    const dados = this.malhas[this.fase === 'solido' ? (this.malhas.depois ? 'depois' : 'antes') : this.fase];
    const M = dados ? dados.marcas : null;
    const marca = M ? Math.max(M[hit.face.a], M[hit.face.b], M[hit.face.c]) : 0;
    return { ponto: [hit.point.x, hit.point.y, hit.point.z], marca };
  }
}

// ============================================================================
// estado
// ============================================================================
const S = { r: null, fase: 'antes', sel: null, ferr: 'selecionar', ocupado: false, nLog: 0, log: [], versaoApp: '', versaoMalha: {},
  tarefa: 'analise', exportando: false };
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
    await iniciar('analise', '/api/analisar', {});
  } catch (e) { toast(e.message, true); }
}

async function enviarArquivo(arq) {
  try {
    mostrarProgresso('Copiando o arquivo', 0.03, arq.size > 5e7 ? 'Arquivo grande: a cópia leva alguns segundos.' : '');
    const r = await api('/api/enviar?nome=' + encodeURIComponent(arq.name), arq);
    mostrarArquivo(r.nome, r.tamanho);
    await iniciar('analise', '/api/analisar', {});
  } catch (e) { $('#progresso').hidden = true; if (!S.r) $('#vazio').hidden = false; toast(e.message, true); }
}

function mostrarArquivo(nome, tamanho) {
  $('#topoArquivo').textContent = nome; S.arquivo = nome;
  $('#topoQuando').textContent = '';
  if (!S.r) $('#cartaoMalha').replaceChildren(el('div', { class: 'mono', text: nome }), tamanho ? el('div', { class: 'fraco', text: br((tamanho / 1048576).toFixed(1)) + ' MB' }) : null);
  for (const b of $$('[data-arquivo]')) b.disabled = false;
}

const TAREFAS = {
  analise: { titulo: 'Procurando os alvos', fracao: (log) => {
    let f = 0.04;
    for (const l of log) {
      if (/^Lendo/.test(l)) f = Math.max(f, 0.06);
      if (/triângulos$/.test(l)) f = Math.max(f, 0.25);
      if (/pontos de amostra/.test(l)) f = Math.max(f, 0.42);
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
  for (const b of $$('[data-precisa], [data-arquivo], [data-precisa-limpa], [data-acao=abrir], #btPrincipal')) b.disabled = true;
  for (const f of $$('.fundo')) f.hidden = true;
}

function ocupar(sim) {
  S.ocupado = sim;
  $('.dir').inert = sim; $('#secOpcoes').inert = sim; $('#secIdent').inert = sim;
  atualizarBotoes();
}

function atualizarBotoes() {
  const tem = !!S.r, oc = S.ocupado;
  for (const b of $$('[data-precisa]')) b.disabled = oc || !tem;
  for (const b of $$('[data-precisa-limpa]')) b.disabled = oc || !tem || !S.r.limpo;
  $('[data-ferr=manual]').disabled = oc || !tem;
  for (const b of $$('[data-fase]')) b.disabled = !tem || (b.dataset.fase === 'depois' && !S.r.limpo);
  const p = $('#btPrincipal');
  if (!tem) { p.textContent = 'Retirar alvos'; p.disabled = true; return; }
  const n = S.r.alvos.filter((a) => a.marcado).length;
  if (S.r.limpo && !mudou()) { p.textContent = 'Gerar arquivos'; p.disabled = oc; p.dataset.oque = 'exportar'; }
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
  const passo = async () => {
    let e;
    try { e = await api('/api/estado?desde=' + S.nLog); } catch (x) { if (!parado) setTimeout(passo, 1500); return; }
    S.log.push(...e.log); S.nLog = e.n_log;
    mostrarProgresso(T.titulo, T.fracao(S.log), S.log.length ? S.log[S.log.length - 1] : '');
    if (e.ocupado) { setTimeout(passo, 500); return; }
    $('#progresso').hidden = true;
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
  };
  mostrarProgresso(T.titulo, 0.03);
  passo();
}

async function carregarResultado(novaPeca) {
  const r = await api('/api/resultado');
  await aplicarResultado(r, novaPeca);
}

async function buscarMalha(fase) {
  if (!visor || S.versaoMalha[fase] === S.r.versao) return;
  visor.guardar(fase, await api('/api/malha.bin?fase=' + fase, undefined, true));
  S.versaoMalha[fase] = S.r.versao;
}

async function aplicarResultado(r, novaPeca) {
  const antes = S.r;
  S.r = r;
  if (novaPeca) {
    S.sel = null; S.falha = null; S.fase = 'antes'; S.versaoMalha = {}; S.versaoSolido = -1;
    if (visor) visor.esquecer();
    $('#expPasta').value = r.pasta || '';
    $('#idPeca').value = r.ident.peca || ''; $('#idResp').value = r.ident.responsavel || '';
    $('#vazioErro').hidden = true; $('#expResultado').hidden = true;
  }
  if (novaPeca || !antes) { $('#opMargem').value = br(String(r.opcoes.margem)); $('#opAlcance').value = br(String(r.opcoes.alcance)); $('#opSoltos').checked = r.opcoes.remover_soltos; }
  $('#vazio').hidden = true;
  for (const s of ['#secResumo', '#secOpcoes', '#secIdent']) $(s).hidden = false;
  $('#topoArquivo').textContent = r.arquivo;
  $('#topoQuando').textContent = r.analisado_em ? '· analisado em ' + r.analisado_em : '';
  if (visor) {
    try {
      await buscarMalha('antes');
      if (r.limpo) await buscarMalha('depois');
      if (r.solido && r.solido.tipo && S.versaoSolido !== r.versao) { visor.carregarSolido(await api('/api/solido.bin', undefined, true)); S.versaoSolido = r.versao; }
      if (!r.solido || !r.solido.tipo) visor.carregarSolido(null);
    } catch (e) { toast('Não consegui carregar a malha para a tela: ' + e.message, true); }
    if (S.fase === 'depois' && !r.limpo) S.fase = 'antes';
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
  $('#grpOpacidade').hidden = S.fase !== 'solido';
  $('#stVersao').textContent = 'Cleanmold ' + S.versaoApp;
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
  if (S.fase === 'antes') cx.replaceChildren(item('#1fa368', 'alvo marcado para retirar'), item('#d9962b', 'alvo desmarcado'),
    $('#opSoltos').checked ? item('#86c9a7', 'pedaço solto (será apagado)') : null, item('#b4b9c1', 'peça'));
  else if (S.fase === 'depois') cx.replaceChildren(item('#35c486', 'remendo (superfície reconstruída)'), item('#b4b9c1', 'peça escaneada'));
  else cx.replaceChildren(item('#1fa368', 'peça de revolução reconhecida'), item('#b4b9c1', 'malha escaneada (transparente)'));
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
  $('#cartaoMalha').replaceChildren(el('div', { class: 'mono', text: r.arquivo }),
    el('div', { class: 'fraco', text: milhar(r.triangulos) + ' triângulos' }),
    el('div', { class: 'fraco', text: `${num(hi[0] - lo[0], 0)} × ${num(hi[1] - lo[1], 0)} × ${num(hi[2] - lo[2], 0)} mm · aresta ${num(r.aresta, 2)} mm` }));
  const c = contar();
  const n = (rot, v, cls) => el('div', { class: 'num ' + (cls || '') }, rot, el('b', { text: String(v) }));
  $('#resumoNums').replaceChildren(
    n('Alvos encontrados', r.alvos.length, 'destaque'), n('Pedaços soltos', r.soltos),
    r.limpo ? n('Fechados sem ressalva', c.ok) : n('Marcados', c.marcados),
    r.limpo ? n('A conferir', c.conferir, c.conferir ? 'atencao' : '') : n('Confiança baixa', c.duvidosos, c.duvidosos ? 'atencao' : ''));
  $('#stConta').textContent = r.limpo ? `malha limpa: ${milhar(r.triangulos_limpa)} triângulos` : '';
}

function desenharDireita() {
  const r = S.r;
  $('#dirVazio').hidden = !!r; $('#dirCheio').hidden = !r;
  if (!r) return;
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
  S.sel = i;
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
  if (visor) {
    visor.mostrar(f);
    if (f === 'solido' && antes !== 'solido') { visor.vista('iso'); for (const o of $$('[data-cam]')) o.classList.toggle('ativo', o.dataset.cam === 'iso'); }
  }
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
  if (!escolha.length && !(opcoes.remover_soltos && S.r.soltos)) { toast('Marque pelo menos um alvo para retirar.', true); return; }
  await iniciar('limpeza', '/api/limpar', { escolha, opcoes });
}

// ---------- alvo indicado à mão ----------
function escolherFerramenta(nome) {
  if (nome === 'manual' && (!S.r || S.ocupado)) return;
  S.ferr = nome;
  for (const b of $$('[data-ferr]')) b.classList.toggle('ativo', b.dataset.ferr === nome);
  if (visor) visor.modoArrasto(nome === 'mover');
  $('#dicaManual').hidden = nome !== 'manual';
  $('#tela').style.cursor = nome === 'manual' ? 'crosshair' : (nome === 'mover' ? 'grab' : '');
  if (nome === 'manual' && S.fase !== 'antes') trocarFase('antes');
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
    <li>Em <b>Abrir malha</b>, escolha o arquivo. A procura dos alvos começa sozinha. Malhas de milhões de triângulos levam de meio minuto a alguns minutos.</li>
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
    el('p', { class: 'fraco', text: 'Usa three.js (MIT) e as fontes IBM Plex (OFL).' }));
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
  if (!r.limpo) { toast('Retire os alvos antes de gerar os arquivos.', true); return; }
  if (mudou()) { toast('A seleção mudou depois da última limpeza. Use “Retirar de novo” antes de gerar os arquivos.', true, 9000); return; }
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
  manual: () => escolherFerramenta('manual'),
  solido: () => { trocarFase('solido'); if (!S.r.solido || !S.r.solido.tipo) reconhecer(); },
  reanalisar: () => {
    if (S.ocupado) { toast('Espere terminar o que está em andamento.', true); return; }
    if (S.r && S.r.alvos.some((a) => a.manual) && !confirm('Procurar de novo apaga os alvos indicados à mão. Continuar?')) return;
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
for (const b of $$('[data-precisa], [data-arquivo], [data-precisa-limpa]')) b.disabled = true;
for (const b of $$('[data-acao]')) b.addEventListener('click', () => { fecharMenus(); ACOES[b.dataset.acao](); });
$('#btPrincipal').addEventListener('click', () => { if ($('#btPrincipal').dataset.oque === 'exportar') abrirExportar(); else limpar(); });
for (const c of [$('#idPeca'), $('#idResp')]) c.addEventListener('change', () => api('/api/ident', { peca: $('#idPeca').value, responsavel: $('#idResp').value }).catch(() => {}));
for (const c of [$('#opMargem'), $('#opAlcance'), $('#opSoltos')]) c.addEventListener('change', () => { if (S.r) desenharTudo(); });
document.addEventListener('click', (ev) => { if (!ev.target.closest('.menu')) fecharMenus(); });
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  fecharMenus(); for (const f of $$('.fundo')) f.hidden = true;
  if (S.ferr === 'manual') escolherFerramenta('selecionar');
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
$('#opMalha').addEventListener('input', (ev) => { if (visor) { visor.opSolido = Number(ev.target.value) / 100; if (S.fase === 'solido') visor.opacidadeMalha(visor.opSolido); } });

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
    if (S.fase === 'antes' && p.marca >= 2) selecionar(p.marca - 2, false);
    else if (S.fase !== 'antes') {
      // depois/sólido: o alvo mais próximo do ponto clicado, se o clique foi perto de um remendo
      let melhor = null, dm = 30;
      for (const a of S.r.alvos) { const d = Math.hypot(a.centro[0] - p.ponto[0], a.centro[1] - p.ponto[1], a.centro[2] - p.ponto[2]); if (d < dm) { dm = d; melhor = a.i; } }
      if (melhor !== null && S.fase === 'depois') selecionar(melhor, false);
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
    if (!visor) toast('O modelo 3D não pôde ser iniciado neste computador (aceleração gráfica indisponível). A lista de alvos e os arquivos funcionam normalmente.', true, 0);
    if (e.nome) mostrarArquivo(e.nome);
    if (e.ocupado) {
      S.tarefa = /analisando/.test(e.ocupado) ? 'analise' : /retirando/.test(e.ocupado) ? 'limpeza' : /reconhecendo/.test(e.ocupado) ? 'solido' : null;
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
window.cleanmold = { S, visor, selecionar, marcar, trocarFase, escolherFerramenta, limpar, reconhecer, abrirExportar,
  abrirCaminho: async (caminho) => { const r = await api('/api/abrir', { caminho }); mostrarArquivo(r.nome, r.tamanho); await iniciar('analise', '/api/analisar', {}); } };
