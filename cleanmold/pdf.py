"""Relatório em PDF: o HTML do relatório é impresso pelo motor do Edge ou do Chrome, sem abrir janela.

Não precisa de biblioteca extra: todo Windows 10/11 traz o Edge. Se nenhum navegador for encontrado,
a função levanta RuntimeError e quem chamou oferece o relatório em HTML para imprimir como PDF."""
import os, shutil, subprocess, sys, tempfile, pathlib, time



def navegador():
    """Caminho do executável do Edge/Chrome (ou None). CLEANMOLD_NAVEGADOR força um executável."""
    forcar = os.environ.get("CLEANMOLD_NAVEGADOR")
    if forcar and os.path.isfile(forcar):
        return forcar
    cand = []
    if sys.platform.startswith("win"):
        for raiz in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if raiz:
                cand += [os.path.join(raiz, "Microsoft", "Edge", "Application", "msedge.exe"),
                         os.path.join(raiz, "Google", "Chrome", "Application", "chrome.exe")]
    elif sys.platform == "darwin":
        cand += ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        for nome in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
            p = shutil.which(nome)
            if p:
                cand.append(p)
    for c in cand:
        if os.path.isfile(c):
            return c
    return None


def _apagar(pasta):
    """Apaga uma pasta temporária; no Windows o navegador pode segurar arquivos por um instante depois de sair."""
    for _ in range(6):
        shutil.rmtree(pasta, ignore_errors=True)
        if not os.path.exists(pasta):
            return
        time.sleep(0.5)


def html_para_pdf(html, destino, espera=120):
    exe = navegador()
    if not exe:
        raise RuntimeError("não encontrei o Edge nem o Chrome neste computador")
    destino = os.path.abspath(destino)
    html = os.path.abspath(html)
    if not os.path.isfile(html):
        raise RuntimeError("o relatório em HTML não foi gerado")
    perfil = tempfile.mkdtemp(prefix="cleanmold_pdf_")
    saida = os.path.join(perfil, "relatorio.pdf")          # nome simples; depois vai para o destino
    url = pathlib.Path(html).as_uri()                       # escapa espaço, #, %, ?, acento e apóstrofo do caminho
    cmd = [exe, "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
           "--user-data-dir=" + os.path.join(perfil, "perfil"), "--no-pdf-header-footer", "--print-to-pdf-no-header",
           "--print-to-pdf=" + saida, url]
    if os.environ.get("CLEANMOLD_NAVEGADOR_ARGS"):
        cmd[1:1] = os.environ["CLEANMOLD_NAVEGADOR_ARGS"].split()
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=espera, creationflags=flags)
        except subprocess.TimeoutExpired:
            raise RuntimeError("o navegador demorou demais para montar o PDF")
        if not os.path.isfile(saida) or os.path.getsize(saida) < 1000:
            raise RuntimeError("o navegador não gravou o PDF (pode estar bloqueado pela política da empresa); "
                               "gere o relatório em HTML e use Imprimir > Salvar como PDF")
        with open(saida, "rb") as fh:
            if fh.read(5) != b"%PDF-":
                raise RuntimeError("o navegador não devolveu um PDF válido")
        shutil.copyfile(saida, destino)                     # se o PDF antigo estiver aberto num leitor, o erro aparece aqui
    finally:
        _apagar(perfil)
    return destino
