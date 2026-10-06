"""Arquivos de CAD da peça de revolução reconhecida: STEP (corpo único), perfil em DXF e macro do SolidWorks.

Convenção dos três: o eixo de revolução é o eixo X, com a origem na primeira face da peça; o perfil fica no
plano XY (X = posição ao longo do eixo, Y = raio). É a posição natural de um esboço de revolução no Plano Frontal."""
import math
import os

import numpy as np

from . import __version__, solido


def _meio_do_arco(e):
    a0 = math.atan2(e["p0"][1] - e["c"][1], e["p0"][0] - e["c"][0])
    a1 = math.atan2(e["p1"][1] - e["c"][1], e["p1"][0] - e["c"][0])
    if e["sentido"] > 0 and a1 < a0:
        a1 += 2 * math.pi
    if e["sentido"] < 0 and a1 > a0:
        a1 -= 2 * math.pi
    am = (a0 + a1) / 2
    return np.array([e["c"][0] + e["r"] * math.cos(am), e["c"][1] + e["r"] * math.sin(am)])


def _fio(ents):
    """Arame (OCP) das entidades do perfil no plano XY."""
    import cadquery as cq
    arestas = []
    for e in ents:
        p0 = cq.Vector(float(e["p0"][0]), float(e["p0"][1]), 0)
        p1 = cq.Vector(float(e["p1"][0]), float(e["p1"][1]), 0)
        if e["tipo"] == "linha":
            arestas.append(cq.Edge.makeLine(p0, p1))
        else:
            m = _meio_do_arco(e)
            arestas.append(cq.Edge.makeThreePointArc(p0, cq.Vector(float(m[0]), float(m[1]), 0), p1))
    return cq.Wire.assembleEdges(arestas)


def forma(sol):
    """Sólido (perfil fechado e volta completa) ou superfícies de revolução (perfil aberto ou setor), como
    objeto do CadQuery. Devolve (forma, é_sólido)."""
    import cadquery as cq
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt
    eixo = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0))
    ang = float(sol["setor"] or 2 * math.pi)
    partes = []
    if sol["fechado"]:
        fio = _fio(sol["perfil"])
        face = BRepBuilderAPI_MakeFace(fio.wrapped, True).Face()
        rev = BRepPrimAPI_MakeRevol(face, eixo, ang) if sol["setor"] else BRepPrimAPI_MakeRevol(face, eixo)
        s = cq.Shape.cast(rev.Shape())
        if s.isValid() and len(s.Solids()) == 1:
            return s, True
    for ents in [sol["perfil"]] + list(sol.get("outros") or []):
        ents = [e for e in ents if e.get("forma") != "eixo"]
        if not ents:
            continue
        fio = _fio(ents)
        rev = BRepPrimAPI_MakeRevol(fio.wrapped, eixo, ang) if sol["setor"] else BRepPrimAPI_MakeRevol(fio.wrapped, eixo)
        partes.append(cq.Shape.cast(rev.Shape()))
    if not partes:
        raise RuntimeError("não há perfil para revolucionar")
    return (partes[0] if len(partes) == 1 else cq.Compound.makeCompound(partes)), False


def gravar_step(sol, caminho):
    import cadquery as cq
    s, eh_solido = forma(sol)
    tmp = str(caminho) + ".parcial.step"
    cq.exporters.export(cq.Workplane("XY").add(s), tmp)
    # confere relendo: um corpo só, para o SolidWorks abrir como peça e não como montagem
    lido = cq.importers.importStep(tmp)
    n_sol = sum(len(o.Solids()) for o in lido.objects)
    if eh_solido and n_sol != 1:
        os.remove(tmp)
        raise RuntimeError(f"o STEP saiu com {n_sol} corpos em vez de 1")
    os.replace(tmp, caminho)
    return caminho, eh_solido


def gravar_dxf(sol, caminho):
    """Perfil meridiano em DXF (mm): para Inserir > DXF/DWG num esboço e revolucionar à mão."""
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.units = 4
    msp = doc.modelspace()
    doc.layers.add("PERFIL", color=7)
    doc.layers.add("EIXO", color=1, linetype="CENTER" if "CENTER" in doc.linetypes else "CONTINUOUS")
    doc.layers.add("OUTROS", color=8)
    zmax = max(max(e["p0"][0], e["p1"][0]) for e in sol["perfil"])
    msp.add_line((-5, 0), (zmax + 5, 0), dxfattribs=dict(layer="EIXO"))
    for camada, grupos in (("PERFIL", [sol["perfil"]]), ("OUTROS", list(sol.get("outros") or []))):
        for ents in grupos:
            for e in ents:
                if e.get("forma") == "eixo":
                    continue
                if e["tipo"] == "linha":
                    msp.add_line(tuple(map(float, e["p0"])), tuple(map(float, e["p1"])), dxfattribs=dict(layer=camada))
                else:
                    a0 = math.degrees(math.atan2(e["p0"][1] - e["c"][1], e["p0"][0] - e["c"][0]))
                    a1 = math.degrees(math.atan2(e["p1"][1] - e["c"][1], e["p1"][0] - e["c"][0]))
                    if e["sentido"] < 0:
                        a0, a1 = a1, a0
                    msp.add_arc(tuple(map(float, e["c"])), float(e["r"]), a0, a1, dxfattribs=dict(layer=camada))
    tmp = str(caminho) + ".parcial"
    doc.saveas(tmp)
    os.replace(tmp, caminho)
    return caminho


# ---------------------------------------------------------------------------
# macro do SolidWorks
# ---------------------------------------------------------------------------

def _m(v):
    """mm -> metros, como texto para o VBA (ponto decimal, sem notação científica)."""
    return f"{float(v) / 1000.0:.9f}"


def macro_solidworks(sol, nome_peca="peca"):
    """Texto de uma macro VBA que reconstrói a peça no SolidWorks passo a passo: esboço do perfil com relações e
    cotas, e a revolução. Sem nomes de planos ou de esboços (que mudam com o idioma do SolidWorks)."""
    fechado = bool(sol["fechado"])
    # perfil fechado: a linha sobre o eixo entra como reta comum, para o contorno fechar; aberto: fica de fora
    ents = [e for e in sol["perfil"] if fechado or e.get("forma") != "eixo"]
    solido_ = bool(sol["solido"])
    ang = float(sol["setor"] or 2 * math.pi)
    zmax = max(max(e["p0"][0], e["p1"][0]) for e in ents)
    rmax = max(max(e["p0"][1], e["p1"][1]) for e in ents)
    L = []
    w = L.append
    w("' ---------------------------------------------------------------------------")
    w(f"' Cleanmold {__version__} - reconstrucao da peca no SolidWorks")
    w(f"' Peca: {nome_peca}")
    w("' Como usar: no SolidWorks, Ferramentas > Macro > Executar... e escolha este arquivo (.swb).")
    w("' A macro cria uma peca nova com: Esboco do perfil (retas, arcos, relacoes e cotas) e a Revolucao.")
    w("' Para mudar uma medida depois: de dois cliques na revolucao ou no esboco e edite a cota.")
    w("' Medidas em mm no SolidWorks; aqui dentro a API trabalha em metros.")
    w("' ---------------------------------------------------------------------------")
    w("Option Explicit")
    w("")
    w("Dim swApp As Object")
    w("Dim Part As Object")
    w("Dim skm As Object")
    w("Dim seg() As Object")
    w("Dim eixo As Object")
    w("Dim falhas As String")
    w("")
    w("Sub main()")
    w("    Dim modelo As String, pedir As Boolean, k As Long, n As Long")
    w("    Dim feat As Object, sd As Object, ok As Boolean, d As Object")
    w("    Set swApp = Application.SldWorks")
    w("    modelo = swApp.GetUserPreferenceStringValue(8)            ' modelo padrao de peca")
    w("    Set Part = swApp.NewDocument(modelo, 0, 0, 0)")
    w("    If Part Is Nothing Then")
    w('        MsgBox "Nao consegui criar uma peca nova. Confira o modelo padrao de peca em Opcoes > Modelos padrao.", vbExclamation, "Cleanmold"')
    w("        Exit Sub")
    w("    End If")
    w("    Set skm = Part.SketchManager")
    w("    pedir = swApp.GetUserPreferenceToggle(10)                 ' pedir o valor da cota ao criar")
    w("    swApp.SetUserPreferenceToggle 10, False")
    w("")
    w("    ' ---- 1. esboco do perfil no primeiro plano de referencia (Plano Frontal)")
    w("    Set feat = PlanoDeReferencia(1)")
    w("    If feat Is Nothing Then")
    w('        MsgBox "Nao encontrei o Plano Frontal desta peca.", vbExclamation, "Cleanmold"')
    w("        GoTo fim")
    w("    End If")
    w("    feat.Select2 False, 0")
    w("    skm.InsertSketch True")
    w("    skm.AddToDB = True                                        ' sem encaixe automatico: as coordenadas entram exatas")
    w("    skm.DisplayWhenAdded = False")
    w(f"    Set eixo = skm.CreateCenterLine({_m(-5)}, 0, 0, {_m(zmax + 5)}, 0, 0)")
    w(f"    n = {len(ents)}")
    w("    ReDim seg(1 To n)")
    for k, e in enumerate(ents, 1):
        if e["tipo"] == "linha":
            w(f"    Set seg({k}) = skm.CreateLine({_m(e['p0'][0])}, {_m(e['p0'][1])}, 0, {_m(e['p1'][0])}, {_m(e['p1'][1])}, 0)")
        else:
            w(f"    Set seg({k}) = skm.CreateArc({_m(e['c'][0])}, {_m(e['c'][1])}, 0, {_m(e['p0'][0])}, {_m(e['p0'][1])}, 0, "
              f"{_m(e['p1'][0])}, {_m(e['p1'][1])}, 0, {1 if e['sentido'] > 0 else -1})")
    w("    skm.DisplayWhenAdded = True")
    w("    skm.AddToDB = False")
    w("    For k = 1 To n")
    w("        If seg(k) Is Nothing Then")
    w('            MsgBox "O SolidWorks recusou o trecho " & k & " do perfil. A macro parou com o esboco aberto.", vbExclamation, "Cleanmold"')
    w("            GoTo fim")
    w("        End If")
    w("    Next k")
    w("")
    w("    ' ---- 2. relacoes: pontas unidas, eixo fixo, cilindros paralelos ao eixo, faces perpendiculares")
    w("    On Error Resume Next")
    w("    For k = 1 To n - 1")
    w("        Unir seg(k), seg(k + 1)")
    w("    Next k")
    if fechado:
        w("    Unir seg(n), seg(1)")
    w("    Part.ClearSelection2 True")
    w('    eixo.Select4 False, Nothing: Part.SketchAddConstraints "sgFIXED"')
    for k, e in enumerate(ents, 1):
        f = e.get("forma")
        if f in ("cilindro", "eixo"):
            w(f'    Part.ClearSelection2 True: seg({k}).Select4 False, Nothing: Part.SketchAddConstraints "sgHORIZONTAL2D"')
        elif f == "face":
            w(f'    Part.ClearSelection2 True: seg({k}).Select4 False, Nothing: Part.SketchAddConstraints "sgVERTICAL2D"')
    w("")
    w("    ' ---- 3. cotas (diametros, posicoes das faces, cones e raios)")
    prim_face = next((k for k, e in enumerate(ents, 1) if e.get("forma") == "face"), None)
    desloc = 0
    for k, e in enumerate(ents, 1):
        f = e.get("forma")
        zm = (e["p0"][0] + e["p1"][0]) / 2
        rm = (e["p0"][1] + e["p1"][1]) / 2
        if f == "cilindro" and rm > 1e-6:
            desloc += 1
            # texto do outro lado do eixo: o SolidWorks faz a cota de diametro
            w(f"    Cotar2 seg({k}), eixo, {_m(zm)}, {_m(-(rmax * 0.25 + 4 * desloc))}        ' diametro {2 * rm:.3f} mm")
        elif f == "face" and prim_face is not None and k != prim_face:
            w(f"    Cotar2 seg({prim_face}), seg({k}), {_m(zm / 2)}, {_m(rmax * 1.15 + 3 * k)}        ' posicao {zm:.3f} mm")
        elif f == "cone":
            w(f"    CotarH seg({k}), {_m(zm)}, {_m(rm + rmax * 0.12 + 2)}        ' comprimento do cone {abs(e['p1'][0] - e['p0'][0]):.3f} mm")
            w(f"    CotarV seg({k}), {_m(max(e['p0'][0], e['p1'][0]) + 3)}, {_m(rm)}        ' altura do cone {abs(e['p1'][1] - e['p0'][1]):.3f} mm")
        elif e["tipo"] == "arco":
            w(f"    Cotar1 seg({k}), {_m(e['c'][0])}, {_m(e['c'][1])}        ' raio {e['r']:.3f} mm")
    if prim_face is not None:
        w(f'    Part.ClearSelection2 True: seg({prim_face}).Select4 False, Nothing: Part.SketchAddConstraints "sgFIXED"')
    w("    On Error GoTo 0")
    w("    Part.ClearSelection2 True")
    w("    skm.InsertSketch True                                     ' fecha o esboco")
    w("    Set feat = Part.FeatureByPositionReverse(0)")
    w('    If Not feat Is Nothing Then feat.Name = "Perfil (Cleanmold)"')
    w("")
    w("    ' ---- 4. revolucao")
    w("    Part.ClearSelection2 True")
    w("    If Not feat Is Nothing Then feat.Select2 False, 0")
    w("    Set sd = Part.SelectionManager.CreateSelectData")
    w("    sd.Mark = 16                                              ' 16 = eixo da revolucao")
    w("    eixo.Select4 True, sd")
    w("    Set d = Nothing")
    w("    On Error Resume Next")
    if solido_:
        w(f"    Set d = Part.FeatureManager.FeatureRevolve2(True, True, False, False, False, False, 0, 0, {ang:.9f}, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)")
    else:
        w(f"    Set d = Part.InsertRevolvedRefSurface({ang:.9f}, False, 0, 0)")
        w(f"    If d Is Nothing Then Set d = Part.FeatureManager.FeatureRevolve2(True, False, False, False, False, False, 0, 0, {ang:.9f}, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)")
    w("    On Error GoTo 0")
    w("    Set feat = Part.FeatureByPositionReverse(0)")
    w("    If d Is Nothing And InStr(1, feat.GetTypeName2, \"Rev\", vbTextCompare) = 0 Then")
    if solido_:
        w('        MsgBox "O esboco do perfil foi criado, mas a revolucao nao saiu sozinha." & vbCrLf & _')
        w('               "Selecione o esboco Perfil (Cleanmold) e use Inserir > Ressalto/Base > Revolucao.", vbExclamation, "Cleanmold"')
    else:
        w('        MsgBox "O esboco do perfil foi criado, mas a superficie de revolucao nao saiu sozinha." & vbCrLf & _')
        w('               "Selecione o esboco Perfil (Cleanmold) e use Inserir > Superficie > Revolucao.", vbExclamation, "Cleanmold"')
    w("    Else")
    w('        feat.Name = "Revolucao (Cleanmold)"')
    w("    End If")
    w("    Part.ClearSelection2 True")
    w("    Part.ViewZoomtofit2")
    w('    If Len(falhas) > 0 Then MsgBox "Peca criada. Algumas cotas ou relacoes nao entraram:" & vbCrLf & falhas & vbCrLf & _')
    w('        "A geometria esta certa; complete as cotas pelo comando Totalmente definir esboco.", vbInformation, "Cleanmold"')
    w("fim:")
    w("    swApp.SetUserPreferenceToggle 10, pedir")
    w("End Sub")
    w("")
    w("' n-esimo plano de referencia da peca (1 = Frontal, 2 = Superior, 3 = Direito), sem depender do idioma")
    w("Function PlanoDeReferencia(n As Long) As Object")
    w("    Dim f As Object, k As Long")
    w("    Set f = Part.FirstFeature")
    w("    Do While Not f Is Nothing")
    w('        If f.GetTypeName2 = "RefPlane" Then')
    w("            k = k + 1")
    w("            If k = n Then")
    w("                Set PlanoDeReferencia = f")
    w("                Exit Function")
    w("            End If")
    w("        End If")
    w("        Set f = f.GetNextFeature")
    w("    Loop")
    w("End Function")
    w("")
    w("' une a ponta final de um trecho ao comeco do seguinte (se o SolidWorks ja uniu, nao faz nada)")
    w("Sub Unir(a As Object, b As Object)")
    w("    Dim p As Object, q As Object")
    w("    On Error Resume Next")
    w("    Set p = a.GetEndPoint2")
    w("    Set q = b.GetStartPoint2")
    w("    If p Is Nothing Or q Is Nothing Then Exit Sub")
    w("    If p Is q Then Exit Sub")
    w("    Part.ClearSelection2 True")
    w("    p.Select4 False, Nothing")
    w("    q.Select4 True, Nothing")
    w('    Part.SketchAddConstraints "sgMERGEPOINTS"')
    w("    Part.ClearSelection2 True")
    w("End Sub")
    w("")
    w("Sub Anotar(o As Object, oque As String)")
    w("    If o Is Nothing Then falhas = falhas & \"  - \" & oque & vbCrLf")
    w("End Sub")
    w("")
    w("' cota de um trecho sozinho (raio de arco)")
    w("Sub Cotar1(a As Object, x As Double, y As Double)")
    w("    Dim d As Object")
    w("    On Error Resume Next")
    w("    Part.ClearSelection2 True")
    w("    a.Select4 False, Nothing")
    w("    Set d = Part.AddDimension2(x, y, 0)")
    w('    Anotar d, "raio"')
    w("End Sub")
    w("")
    w("' cota entre dois trechos (cilindro e eixo = diametro; face e face = distancia)")
    w("Sub Cotar2(a As Object, b As Object, x As Double, y As Double)")
    w("    Dim d As Object")
    w("    On Error Resume Next")
    w("    Part.ClearSelection2 True")
    w("    a.Select4 False, Nothing")
    w("    b.Select4 True, Nothing")
    w("    Set d = Part.AddDimension2(x, y, 0)")
    w('    Anotar d, "diametro ou posicao"')
    w("End Sub")
    w("")
    w("Sub CotarH(a As Object, x As Double, y As Double)")
    w("    Dim d As Object")
    w("    On Error Resume Next")
    w("    Part.ClearSelection2 True")
    w("    a.Select4 False, Nothing")
    w("    Set d = Part.AddHorizontalDimension2(x, y, 0)")
    w('    Anotar d, "comprimento de cone"')
    w("End Sub")
    w("")
    w("Sub CotarV(a As Object, x As Double, y As Double)")
    w("    Dim d As Object")
    w("    On Error Resume Next")
    w("    Part.ClearSelection2 True")
    w("    a.Select4 False, Nothing")
    w("    Set d = Part.AddVerticalDimension2(x, y, 0)")
    w('    Anotar d, "altura de cone"')
    w("End Sub")
    return "\r\n".join(L) + "\r\n"


def gravar_macro(sol, caminho, nome_peca="peca"):
    txt = macro_solidworks(sol, nome_peca)
    tmp = str(caminho) + ".parcial"
    with open(tmp, "w", encoding="cp1252", errors="replace", newline="") as fh:
        fh.write(txt)
    os.replace(tmp, caminho)
    return caminho
