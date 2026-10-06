"""Interface do Cleanmold: um servidor que só atende este computador (127.0.0.1) e a página que o
Edge/Chrome abre como janela de aplicativo. Nada é enviado para fora: malha, análise e arquivos ficam no PC."""
import json, math, os, re, secrets, shutil, subprocess, sys, tempfile, threading, time, traceback, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

import numpy as np

from . import __version__, app, malha, pdf, saidas

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json", ".txt": "text/plain; charset=utf-8"}


class ErroUsuario(Exception):
    """Erro para mostrar ao usuário como está (sem rastro técnico)."""


class Estado:
    def __init__(self):
        self.token = secrets.token_urlsafe(18)
        self.trava = threading.RLock()
        self.arquivo = None                     # malha escolhida
        self.sessao = None                      # app.Sessao da malha analisada
        self.falha = None                       # última análise que falhou: dict(arquivo, erro)
        self.ident = dict(peca="", responsavel="")
        self.log = []
        self.ocupado = None
        self.erro = None
        self.versao = 0                         # muda a cada alteração do resultado
        self.bin = {}                           # fase -> (versão, bytes) da malha para a tela
        self.janelas = {}
        self.export = None
        self.pasta_saida = None
        self.pasta_nova = None
        self.ultimo_ping = None
        self.fechar_em = None
        self.inicio = time.time()
        self.analisado_em = None
        self.tmp = None

    def registrar(self, s):
        with self.trava:
            self.log.append(str(s))

    @property
    def res(self):                              # usado pelo vigia: há peça aberta?
        return self.sessao


E = Estado()


# ---------------------------------------------------------------------------
# diálogos nativos do Windows (abrir, salvar, escolher pasta) num processo à parte
# ---------------------------------------------------------------------------

_DLG = r'''
import sys, json, tkinter as tk
from tkinter import filedialog
a = json.loads(sys.argv[1])
r = tk.Tk(); r.withdraw()
try:
    r.attributes("-topmost", True); r.update()
except Exception:
    pass
op = dict(parent=r, title=a.get("titulo") or "Cleanmold")
if a.get("pasta"):
    op["initialdir"] = a["pasta"]
if a["tipo"] == "pasta":
    p = filedialog.askdirectory(**op)
else:
    op["filetypes"] = [tuple(x) for x in a.get("tipos") or [["Todos", "*.*"]]]
    if a["tipo"] == "salvar":
        if a.get("ext"): op["defaultextension"] = a["ext"]
        if a.get("nome"): op["initialfile"] = a["nome"]
        p = filedialog.asksaveasfilename(**op)
    else:
        p = filedialog.askopenfilename(**op)
sys.stdout.buffer.write((p or "").encode("utf-8"))
'''


def dialogo(**a):
    saida = {"abrir": "Arraste o arquivo para dentro da janela do Cleanmold.",
             "pasta": "Digite o caminho completo da pasta no campo \"Gravar em\".",
             "salvar": "Tente de novo ou reinicie o Cleanmold."}.get(a.get("tipo"), "")
    # Aberto pelo atalho, o Cleanmold roda no pythonw (sem console). A janela de arquivos devolve o caminho pela saída
    # padrão, então roda no python.exe vizinho, sem janela preta (CREATE_NO_WINDOW).
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        vizinho = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(vizinho):
            exe = vizinho
    try:
        # -I: só o Python do Cleanmold, sem variáveis PYTHON* nem pacotes de outro Python do usuário
        r = subprocess.run([exe, "-I", "-c", _DLG, json.dumps(a)], capture_output=True, timeout=900,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return ""                                   # janela esquecida aberta: trata como cancelada
    except Exception as e:
        raise ErroUsuario(f"Não consegui abrir a janela de arquivos do Windows ({type(e).__name__}). {saida}")
    if r.returncode != 0:
        raise ErroUsuario(f"Não consegui abrir a janela de arquivos do Windows. {saida}")
    return r.stdout.decode("utf-8", "replace").strip()



def _limpo(o):
    if isinstance(o, dict):
        return {str(k): _limpo(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_limpo(v) for v in o]
    if isinstance(o, np.ndarray):
        return _limpo(o.tolist())
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        o = float(o)
        return o if math.isfinite(o) else None
    return o


def resultado():
    s = E.sessao
    r = s.resumo()
    r.update(versao=E.versao, ident=E.ident, analisado_em=E.analisado_em,
             pasta=E.pasta_saida or os.path.dirname(s.caminho), solido=saidas.resumo_solido(s))
    return _limpo(r)


# ---------------------------------------------------------------------------
# tarefas demoradas
# ---------------------------------------------------------------------------

def _tarefa(nome, fn):
    with E.trava:
        if E.ocupado:
            raise ErroUsuario("Ainda estou trabalhando: " + E.ocupado)
        E.ocupado, E.erro = nome, None

    def rodar():
        try:
            fn()
        except (RuntimeError, ErroUsuario, ValueError) as e:
            E.erro = str(e)
            E.registrar("ERRO: " + str(e))
        except MemoryError:
            E.erro = "Faltou memória. Feche outros programas ou exporte a malha com menos triângulos."
            E.registrar("ERRO: " + E.erro)
        except Exception as e:
            E.erro = f"Erro inesperado: {e}"
            E.registrar("ERRO inesperado: " + traceback.format_exc(limit=-5))
        finally:
            E.ocupado = None
    threading.Thread(target=rodar, daemon=True).start()


def _tela(fase):
    """Malha reduzida para a tela, de antes ou de depois da limpeza (guardada até o resultado mudar)."""
    s = E.sessao
    g = E.bin.get(fase)
    if g and g[0] == E.versao:
        return g[1]
    focos, raio = s.focos()
    if fase == "antes":
        b = app.malha_para_tela(s.m, s.marcas_antes(), focos, raio)
    else:
        if s.limpa is None:
            raise ErroUsuario("A malha ainda não foi limpa.")
        b = app.malha_para_tela(s.limpa["malha"], s.limpa["remendo"].astype(np.uint16), focos, raio)
    E.bin[fase] = (E.versao, b)
    return b


def analisar():
    caminho = E.arquivo
    if not caminho or not os.path.isfile(caminho):
        raise ErroUsuario("Abra uma malha primeiro.")

    def fn():
        E.log.clear()
        E.falha = None
        try:
            s = app.Sessao(caminho, log=E.registrar)
            s.analisar()
            E.registrar("Preparando a vista 3D")
            antes = app.malha_para_tela(s.m, s.marcas_antes(), *s.focos())
        except MemoryError:
            E.falha = dict(arquivo=os.path.basename(caminho), erro="Faltou memória para esta malha. Feche outros programas ou "
                           "exporte a malha com menos triângulos.")
            raise ErroUsuario(E.falha["erro"])
        except Exception as e:
            E.falha = dict(arquivo=os.path.basename(caminho), erro=str(e) or type(e).__name__)
            raise
        with E.trava:
            nova = E.sessao is None or E.sessao.caminho != caminho
            E.sessao = s
            E.versao += 1
            E.bin = {"antes": (E.versao, antes)}
            E.analisado_em = time.strftime("%d/%m/%Y %H:%M")
            if E.pasta_nova:
                E.pasta_saida = E.pasta_nova
            if nova:
                E.ident = dict(peca="", responsavel=E.ident.get("responsavel", ""))
            E.export = None
        E.registrar("Análise concluída.")
    _tarefa("analisando a malha", fn)


def limpar(d):
    s = E.sessao
    if s is None:
        raise ErroUsuario("Abra uma malha primeiro.")
    escolha = d.get("escolha")
    if not isinstance(escolha, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in escolha):
        raise ErroUsuario("Pedido inválido.")
    op = d.get("opcoes") or {}
    if not isinstance(op, dict):
        raise ErroUsuario("Pedido inválido.")
    opcoes = dict(margem=_numero(op.get("margem"), "Margem"), alcance=_numero(op.get("alcance"), "Alcance"))
    if opcoes["margem"] is not None and not (0.0 <= opcoes["margem"] <= 10.0):
        raise ErroUsuario("A margem precisa ficar entre 0 e 10 mm.")
    if opcoes["alcance"] is not None and not (2.0 <= opcoes["alcance"] <= 30.0):
        raise ErroUsuario("O alcance precisa ficar entre 2 e 30 mm.")
    if any(not (0 <= i < len(s.det["alvos"])) for i in escolha):
        raise ErroUsuario("Pedido inválido.")
    if "remover_soltos" in op:
        opcoes["remover_soltos"] = bool(op["remover_soltos"])

    def fn():
        E.registrar("Retirando os alvos…")
        s.limpar(escolha, opcoes)
        E.registrar("Preparando a vista 3D")
        with E.trava:
            E.versao += 1
            E.bin.pop("depois", None)
            E.export = None
        _tela("antes"), _tela("depois")
        E.registrar("Limpeza concluída.")
    _tarefa("retirando os alvos", fn)


def exportar(itens, pasta, ident):
    s = E.sessao
    if s is None:
        raise ErroUsuario("Abra uma malha antes de gerar arquivos.")
    if not isinstance(itens, (list, tuple)) or not isinstance(ident, dict):
        raise ErroUsuario("Pedido inválido.")
    itens = [k for k in itens if isinstance(k, str) and k in app.ITENS]
    if not itens:
        raise ErroUsuario("Marque pelo menos um arquivo para gerar.")
    if s.limpa is None:
        raise ErroUsuario("Retire os alvos antes de gerar os arquivos.")
    if not isinstance(pasta, str):
        raise ErroUsuario("Pedido inválido.")
    pasta = pasta.strip().strip('"')
    if not pasta:
        raise ErroUsuario("Escolha a pasta onde os arquivos serão gravados.")
    if not os.path.isabs(os.path.expanduser(pasta)):
        raise ErroUsuario("Informe o caminho completo da pasta (por exemplo C:\\Users\\seu_nome\\Documents\\Cleanmold), "
                          "ou use o botão Escolher.")
    pasta = os.path.normpath(os.path.expanduser(pasta))
    E.ident = dict(peca=str(ident.get("peca") or "").strip(), responsavel=str(ident.get("responsavel") or "").strip())
    base = os.path.splitext(os.path.basename(s.caminho))[0]

    def fn():
        E.export = None
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError as e:
            raise ErroUsuario(f"Não consegui usar a pasta {pasta} ({app.erro_de_arquivo(e)}). Escolha outra.")
        E.pasta_saida = pasta
        out = saidas.salvar(s, pasta, base, itens, ident=E.ident, log=E.registrar)
        falhas = out.pop("falhas", {})
        E.export = dict(pasta=pasta, arquivos=out, falhas=falhas)
    _tarefa("gerando os arquivos", fn)


def _numero(v, nome):
    """Número digitado na página (aceita vírgula decimal). Texto que não é número vira erro em português."""
    if v in (None, ""):
        return None
    if isinstance(v, bool):
        raise ErroUsuario(f"{nome}: valor inválido.")
    try:
        x = float(str(v).strip().replace(" ", "").replace("\u2212", "-").replace(",", "."))
    except ValueError:
        raise ErroUsuario(f"{nome}: \"{v}\" não é um número.")
    if not math.isfinite(x):
        raise ErroUsuario(f"{nome}: valor inválido.")
    return x


def _caminho(d, chave="caminho"):
    v = d.get(chave)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise ErroUsuario("Pedido inválido.")
    return v


def _parado():
    if E.ocupado:
        raise ErroUsuario("Espere terminar: " + E.ocupado + ".")


def abrir_no_sistema(caminho):
    if sys.platform.startswith("win"):
        os.startfile(caminho)                                    # noqa: só existe no Windows
    elif sys.platform == "darwin":
        subprocess.Popen(["open", caminho])
    else:
        subprocess.Popen(["xdg-open", caminho], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Pedido(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Cleanmold"

    def log_message(self, *a):
        pass

    def _enviar(self, corpo, tipo="application/json", codigo=200):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, o, codigo=200):
        self._enviar(json.dumps(o, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", codigo)

    def _erro(self, msg, codigo=400):
        if codigo == 403:
            self.close_connection = True
        self._json(dict(erro=msg), codigo)

    def _autorizado(self, q):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        t = self.headers.get("X-Cleanmold") or (q.get("t") or [""])[0]
        return secrets.compare_digest(str(t).encode("utf-8", "replace"), E.token.encode("utf-8"))

    def _tamanho(self):
        try:
            return max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            return 0

    def _corpo_json(self):
        n = self._tamanho()
        if n <= 0:
            return {}
        if n > 4_000_000:
            self.close_connection = True
            raise ErroUsuario("Pedido grande demais.")
        try:
            d = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ErroUsuario("Pedido inválido.")
        if not isinstance(d, dict):
            raise ErroUsuario("Pedido inválido.")
        return d

    # ---- GET
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path.startswith("/api/"):
                if not self._autorizado(q):
                    return self._erro("não autorizado", 403)
                E.fechar_em = None
                return self._api_get(u.path, q)
            return self._estatico(u.path)
        except ErroUsuario as e:
            self._erro(str(e))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            E.registrar("ERRO interno: " + traceback.format_exc(limit=-5))
            self._erro("Erro interno do Cleanmold. Veja Análise > Ver registro.", 500)

    def _estatico(self, caminho):
        rel = "index.html" if caminho in ("/", "") else unquote(caminho).lstrip("/")
        alvo = os.path.normpath(os.path.join(WEB, rel))
        try:
            dentro = os.path.commonpath([alvo, WEB]) == WEB
        except ValueError:
            dentro = False
        if not dentro or not os.path.isfile(alvo):
            return self._enviar(b"nao encontrado", "text/plain", 404)
        with open(alvo, "rb") as fh:
            dados = fh.read()
        self._enviar(dados, TIPOS.get(os.path.splitext(alvo)[1].lower(), "application/octet-stream"))

    def _api_get(self, p, q):
        def inteiro(nome):
            try:
                return int((q.get(nome) or ["0"])[0])
            except ValueError:
                raise ErroUsuario("Pedido inválido.")
        if p == "/api/estado":
            desde = max(0, inteiro("desde"))
            with E.trava:
                self._json(dict(versao_app=__version__, ocupado=E.ocupado, erro=E.erro, n_log=len(E.log), log=E.log[desde:],
                                versao=E.versao, tem_resultado=E.sessao is not None, falha=E.falha,
                                limpo=bool(E.sessao and E.sessao.limpa is not None),
                                arquivo=E.arquivo, nome=os.path.basename(E.arquivo) if E.arquivo else None,
                                analisado=os.path.basename(E.sessao.caminho) if E.sessao else None,
                                export=E.export, pdf_disponivel=pdf.navegador() is not None))
        elif p == "/api/resultado":
            if E.sessao is None:
                return self._erro("sem resultado", 404)
            with E.trava:
                self._json(resultado())
        elif p == "/api/malha.bin":
            if E.sessao is None:
                return self._erro("sem malha", 404)
            fase = (q.get("fase") or ["antes"])[0]
            if fase not in ("antes", "depois"):
                return self._erro("fase desconhecida", 404)
            if fase == "depois" and E.sessao.limpa is None:
                return self._erro("a malha ainda não foi limpa", 404)
            with E.trava:
                b = _tela(fase)
            self._enviar(b, "application/octet-stream")
        elif p == "/api/solido.bin":
            if E.sessao is None:
                return self._erro("sem malha", 404)
            with E.trava:
                b = saidas.solido_para_tela(E.sessao)
            if b is None:
                return self._erro("sem sólido", 404)
            self._enviar(b, "application/octet-stream")
        else:
            self._erro("rota desconhecida", 404)

    # ---- POST
    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if not u.path.startswith("/api/") or not self._autorizado(q):
                return self._erro("não autorizado", 403)
            self._api_post(u.path, q)
        except ErroUsuario as e:
            self._erro(str(e))
        except ValueError as e:
            self._erro(str(e) or "Pedido inválido.")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError as e:
            E.registrar("ERRO de arquivo: " + traceback.format_exc(limit=-5))
            self._erro(f"Não consegui ler ou gravar o arquivo ({app.erro_de_arquivo(e)}).", 400)
        except Exception:
            E.registrar("ERRO inesperado: " + traceback.format_exc(limit=-5))
            self._erro("Erro inesperado do Cleanmold. Veja Análise > Ver registro.", 500)

    def _api_post(self, p, q):
        janela = str((q.get("j") or [""])[0])[:40]
        if p == "/api/ping":
            n = self._tamanho()
            if n:
                self.rfile.read(min(n, 65536))
            agora = time.time()
            E.janelas[janela] = agora
            E.ultimo_ping, E.fechar_em = agora, None
            return self._json(dict(ok=True))
        if p == "/api/fechar":
            n = self._tamanho()
            if n:
                self.rfile.read(min(n, 65536))
            agora = time.time()
            E.janelas.pop(janela, None)
            prazo = 1800 if E.sessao is not None else 240
            if not any(agora - t < prazo for t in E.janelas.values()):
                E.fechar_em = agora + 12
            return self._json(dict(ok=True))
        if p == "/api/enviar":
            nome = re.sub(r"[^\w.\- ]", "_", os.path.basename((q.get("nome") or ["malha.stl"])[0])).strip(". ") or "malha.stl"
            if os.path.splitext(nome)[1].lower() not in malha.FORMATOS:
                self.close_connection = True
                raise ErroUsuario("Use um arquivo de malha: STL, PLY, OBJ ou OFF.")
            if E.ocupado:
                self.close_connection = True
                raise ErroUsuario("Espere terminar: " + E.ocupado + ".")
            n = self._tamanho()
            destino = os.path.join(_tmp(), nome)
            with open(destino, "wb") as fh:
                resto = n
                while resto > 0:
                    b = self.rfile.read(min(1 << 20, resto))
                    if not b:
                        break
                    fh.write(b); resto -= len(b)
            E.arquivo = destino
            E.pasta_nova = E.pasta_saida or os.path.join(os.path.expanduser("~"), "Documents", "Cleanmold")
            return self._json(dict(caminho=destino, nome=nome, tamanho=n))
        d = self._corpo_json()
        if p == "/api/abrir":
            _parado()
            cam = _caminho(d) or dialogo(tipo="abrir", titulo="Malha escaneada",
                                         tipos=[["Malhas", "*.stl *.ply *.obj *.off"], ["Todos", "*.*"]],
                                         pasta=os.path.dirname(E.arquivo) if E.arquivo else None)
            if not cam:
                return self._json(dict(cancelado=True))
            if not os.path.isfile(cam):
                raise ErroUsuario("Arquivo não encontrado: " + cam)
            E.arquivo = cam
            E.pasta_nova = os.path.dirname(cam)
            self._json(dict(caminho=cam, nome=os.path.basename(cam), tamanho=os.path.getsize(cam)))
        elif p == "/api/analisar":
            analisar()
            self._json(dict(ok=True))
        elif p == "/api/limpar":
            limpar(d)
            self._json(dict(ok=True))
        elif p == "/api/manual":
            _parado()
            if E.sessao is None:
                raise ErroUsuario("Abra uma malha primeiro.")
            pt = d.get("ponto")
            if not (isinstance(pt, list) and len(pt) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in pt)):
                raise ErroUsuario("Pedido inválido.")
            with E.trava:
                i = E.sessao.alvo_manual(pt, _numero(d.get("diametro"), "Diâmetro"))
                E.versao += 1
                E.bin = {}
                E.export = None
                r = resultado()
            r["novo"] = i
            self._json(r)
        elif p == "/api/esquecer":
            _parado()
            if E.sessao is None:
                raise ErroUsuario("Abra uma malha primeiro.")
            i = d.get("i")
            alvos_ = E.sessao.det["alvos"]
            if not isinstance(i, int) or isinstance(i, bool) or not (0 <= i < len(alvos_)) or not alvos_[i].get("manual"):
                raise ErroUsuario("Só dá para apagar da lista um alvo indicado à mão.")
            with E.trava:
                alvos_.pop(i)
                E.sessao.escolha = [k if k < i else k - 1 for k in E.sessao.escolha if k != i]
                E.sessao.limpa = None
                E.versao += 1
                E.bin = {}
                E.export = None
                self._json(resultado())
        elif p == "/api/ident":
            with E.trava:
                E.ident = dict(peca=str(d.get("peca") or "").strip()[:120], responsavel=str(d.get("responsavel") or "").strip()[:120])
            self._json(dict(ok=True))
        elif p == "/api/solido":
            _parado()
            if E.sessao is None:
                raise ErroUsuario("Abra uma malha primeiro.")

            def fn():
                saidas.reconhecer(E.sessao, d, log=E.registrar)
                with E.trava:
                    E.versao += 1
            _tarefa("reconhecendo as formas da peça", fn)
            self._json(dict(ok=True))
        elif p == "/api/pasta":
            cam = dialogo(tipo="pasta", titulo="Pasta para gravar os arquivos", pasta=_caminho(d, "pasta") or E.pasta_saida)
            self._json(dict(pasta=cam) if cam else dict(cancelado=True))
        elif p == "/api/exportar":
            exportar(d.get("itens") or [], d.get("pasta") or "", d)
            self._json(dict(ok=True))
        elif p == "/api/mostrar":
            alvo = _caminho(d) or ""
            ex = E.export or {}
            permitidos = set(ex.get("arquivos", {}).values()) | {ex.get("pasta")}
            if alvo not in permitidos or not os.path.exists(alvo):
                raise ErroUsuario("Arquivo não encontrado.")
            abrir_no_sistema(alvo)
            self._json(dict(ok=True))
        else:
            self._erro("rota desconhecida", 404)


def _janela(url):
    if os.environ.get("CLEANMOLD_SEM_NAVEGADOR"):
        return
    exe = pdf.navegador()
    if exe:
        try:
            subprocess.Popen([exe, "--app=" + url, "--window-size=1500,940"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)


def _tmp():
    """Pasta temporária desta execução (malhas arrastadas para a janela)."""
    if E.tmp is None or not os.path.isdir(E.tmp):
        E.tmp = tempfile.mkdtemp(prefix="cleanmold_")
    return E.tmp


def _limpar_temporarios():
    """Apaga pastas temporárias de execuções antigas que não fecharam direito (janela preta fechada no X)."""
    raiz = tempfile.gettempdir()
    agora = time.time()
    try:
        nomes = os.listdir(raiz)
    except OSError:
        return
    for nome in nomes:
        if not nome.startswith(("cleanmold_", "cleanmold_pdf_")):
            continue
        cam = os.path.join(raiz, nome)
        try:
            if os.path.isdir(cam) and agora - os.path.getmtime(cam) > 86400:
                shutil.rmtree(cam, ignore_errors=True)
        except OSError:
            pass


class _Servidor(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # a janela fechou ou recarregou no meio de uma resposta: não é erro do programa
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def main(porta=0):
    httpd = _Servidor(("127.0.0.1", int(os.environ.get("CLEANMOLD_PORTA") or porta)), Pedido)
    httpd.daemon_threads = True
    if os.environ.get("CLEANMOLD_TOKEN"):
        E.token = os.environ["CLEANMOLD_TOKEN"]
    _limpar_temporarios()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={E.token}"
    try:
        print(f"Cleanmold {__version__}")
        print("A janela do programa abre no Edge ou no Chrome. Se nao abrir, copie este endereco para o navegador:")
        print("   " + url)
        print("Tudo roda neste computador; nada e enviado pela internet.")
        print("Para encerrar, feche a janela do Cleanmold. Esta janela preta fecha sozinha em seguida.")
        sys.stdout.flush()
    except Exception:
        pass                                   # sem console (pythonw): segue sem as mensagens

    def avisar_sem_janela():
        """A janela do programa não deu sinal: sem console não há onde ler o endereço, então mostra numa caixa."""
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "A janela do Cleanmold não abriu sozinha.\n\nAbra o Edge ou o Chrome e cole este endereço:\n\n" + url +
                "\n\n(Ctrl+C copia o texto desta caixa.)\nSe a janela do Cleanmold já abriu, é só fechar este aviso.",
                "Cleanmold", 0x40 | 0x10000 | 0x40000)
        except Exception:
            pass

    def vigia():
        ultimo = time.time()
        avisado = False
        while True:
            time.sleep(1.0)
            agora = time.time()
            if not avisado and E.ultimo_ping is None and agora - E.inicio > 40 and not os.environ.get("CLEANMOLD_SEM_NAVEGADOR"):
                avisado = True
                threading.Thread(target=avisar_sem_janela, daemon=True).start()
            if agora - ultimo > 30:              # o computador dormiu: não conta esse tempo como janela fechada
                if E.ultimo_ping is not None:
                    E.ultimo_ping = agora
                E.inicio = agora
            ultimo = agora
            if E.ocupado:
                continue
            if E.fechar_em and agora > E.fechar_em:
                break
            if E.ultimo_ping is None:
                if agora - E.inicio > 300:
                    break
            elif agora - E.ultimo_ping > (1800 if E.res is not None else 240):
                # com uma peça analisada espera mais: o Edge congela janelas em segundo plano e os sinais param
                break
        httpd.shutdown()
    threading.Thread(target=vigia, daemon=True).start()
    threading.Timer(0.4, _janela, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if E.tmp:
            shutil.rmtree(E.tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
