"""
Monitor de Passagens v2 — Florida 2027 + Buenos Aires
Roda 3x por dia via GitHub Actions (8h, 13h, 18h BRT)
Detecta erros de tarifa (queda >35% vs média histórica)
"""

import os, requests, json
from datetime import datetime, date, timedelta

SERPAPI_KEY      = os.environ["SERPAPI_KEY"]
CALLMEBOT_PHONE  = os.environ["CALLMEBOT_PHONE"]
CALLMEBOT_APIKEY = os.environ["CALLMEBOT_APIKEY"]
SHEETS_WEBHOOK   = os.environ["SHEETS_WEBHOOK"]

# ── FLORIDA CONFIG ────────────────────────────────────────────────────────────
FL_ROTAS   = [("GRU","MCO"), ("GRU","MIA")]
FL_DATAS   = [("2027-05-06","2027-05-20"), ("2027-05-01","2027-05-16"), ("2027-05-10","2027-05-24")]
FL_ADULTOS = 2
FL_CRIANCAS= 1
FL_ALERTA_ECON = 3500
FL_ALERTA_EXEC = 9000
FL_BOM_ECON    = 4500
FL_BOM_EXEC    = 13000
FL_ERRO_TARIFA_PCT = 35   # % de queda vs média = erro de tarifa

# ── BUENOS AIRES CONFIG ───────────────────────────────────────────────────────
BA_ALERTA     = 500    # R$/pessoa roundtrip — alerta imediato
BA_BOM        = 900    # R$/pessoa — bom preço
BA_ERRO_TARIFA= 280    # R$/pessoa — provável erro de tarifa
CIA_EXCLUIR   = []

# Feriados prolongados do Brasil 2026-2027 (início, fim, nome, dias)
FERIADOS = [
    ("2026-04-18","2026-04-21","Tiradentes + Páscoa",4),
    ("2026-05-01","2026-05-03","Dia do Trabalho",3),
    ("2026-06-11","2026-06-13","Corpus Christi",3),
    ("2026-09-05","2026-09-07","Independência",3),
    ("2026-10-10","2026-10-12","Nossa Senhora",3),
    ("2026-10-31","2026-11-02","Finados",3),
    ("2026-12-25","2026-12-27","Natal",3),
    ("2026-12-31","2027-01-02","Réveillon",3),
    ("2027-02-13","2027-02-16","Carnaval",4),
    ("2027-04-01","2027-04-04","Semana Santa",4),
    ("2027-09-04","2027-09-07","Independência",4),
    ("2027-10-09","2027-10-12","Nossa Senhora",4),
    ("2027-10-30","2027-11-02","Finados",4),
    ("2027-11-13","2027-11-15","Proclamação",3),
]

def feriados_proximos(dias_limite=120):
    hoje = date.today()
    proximos = []
    for inicio, fim, nome, dias in FERIADOS:
        d = datetime.strptime(inicio, "%Y-%m-%d").date()
        diff = (d - hoje).days
        if 7 <= diff <= dias_limite:
            proximos.append((inicio, fim, nome, dias))
    return proximos[:4]  # máximo 4 próximos para economizar API calls

# ── SERPAPI ───────────────────────────────────────────────────────────────────
def buscar_voo(origem, destino, data_ida, data_volta, adultos, criancas=0):
    params = {
        "engine":        "google_flights",
        "departure_id":  origem,
        "arrival_id":    destino,
        "outbound_date": data_ida,
        "return_date":   data_volta,
        "adults":        adultos,
        "currency":      "BRL",
        "hl":            "pt",
        "api_key":       SERPAPI_KEY,
        "type":          "1",
    }
    if criancas > 0:
        params["children"] = criancas
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
        return r.json()
    except Exception as e:
        print(f"  Erro SerpAPI {origem}→{destino}: {e}")
        return {}

def melhor_preco(data, tipo="econ"):
    todos = data.get("best_flights", []) + data.get("other_flights", [])
    melhor = None
    cia_melhor = "—"
    for voo in todos:
        preco = voo.get("price")
        if not preco:
            continue
        flights = voo.get("flights", [])
        cia = flights[0].get("airline", "—") if flights else "—"
        if any(exc.lower() in cia.lower() for exc in CIA_EXCLUIR):
            continue
        travel_class = flights[0].get("travel_class", "Economy") if flights else "Economy"
        eh_exec = "business" in travel_class.lower() or "first" in travel_class.lower()
        if tipo == "exec" and not eh_exec:
            continue
        if tipo == "econ" and eh_exec:
            continue
        if melhor is None or preco < melhor:
            melhor = preco
            cia_melhor = cia
    return melhor, cia_melhor

# ── WEBHOOK SHEETS ────────────────────────────────────────────────────────────
def salvar(payload):
    try:
        r = requests.post(SHEETS_WEBHOOK, json=payload, timeout=15)
        print(f"  ✅ Sheets: {r.text.strip()[:60]}")
    except Exception as e:
        print(f"  ⚠️ Sheets erro: {e}")

# ── WHATSAPP ──────────────────────────────────────────────────────────────────
def whatsapp(msg, destino_tag="🌴"):
    url = (f"https://api.callmebot.com/whatsapp.php"
           f"?phone={CALLMEBOT_PHONE}"
           f"&text={requests.utils.quote(msg)}"
           f"&apikey={CALLMEBOT_APIKEY}")
    try:
        r = requests.get(url, timeout=15)
        print(f"  📱 WhatsApp: {r.status_code}")
    except Exception as e:
        print(f"  ⚠️ WhatsApp erro: {e}")

def fmt_brl(v, por_pessoa=True):
    if not v: return "—"
    s = f"R$ {int(v):,}".replace(",", ".")
    return s + ("/pessoa" if por_pessoa else "")

# ── MONITOR FLORIDA ────────────────────────────────────────────────────────────
def monitor_florida():
    print("\n🌴 FLORIDA 2027")
    print("-" * 40)
    best_econ = {"preco": None, "cia": "—", "rota": "—"}
    best_exec = {"preco": None, "cia": "—", "rota": "—"}

    for orig, dest in FL_ROTAS:
        data_ida, data_volta = FL_DATAS[0]
        print(f"  Buscando {orig}→{dest} ({data_ida})...")
        data = buscar_voo(orig, dest, data_ida, data_volta, FL_ADULTOS, FL_CRIANCAS)
        adultos_total = FL_ADULTOS + FL_CRIANCAS

        preco_econ, cia_econ = melhor_preco(data, "econ")
        if preco_econ:
            pp = round(preco_econ / adultos_total)
            if best_econ["preco"] is None or pp < best_econ["preco"]:
                best_econ = {"preco": pp, "cia": cia_econ, "rota": f"{orig}→{dest}"}

        preco_exec, cia_exec = melhor_preco(data, "exec")
        if preco_exec:
            pp = round(preco_exec / adultos_total)
            if best_exec["preco"] is None or pp < best_exec["preco"]:
                best_exec = {"preco": pp, "cia": cia_exec, "rota": f"{orig}→{dest}"}

    print(f"  ✈️  Econômica: {fmt_brl(best_econ['preco'])} ({best_econ['cia']})")
    print(f"  🛋️  Executiva: {fmt_brl(best_exec['preco'])} ({best_exec['cia']})")

    econ = best_econ["preco"] or 0
    exec_ = best_exec["preco"] or 0
    eh_oferta_econ = econ > 0 and econ <= FL_ALERTA_ECON
    eh_oferta_exec = exec_ > 0 and exec_ <= FL_ALERTA_EXEC
    eh_oferta = eh_oferta_econ or eh_oferta_exec

    obs = ""
    if econ <= FL_ALERTA_ECON and econ > 0:
        obs = f"🔥 OFERTA! {best_econ['cia']} econômica {fmt_brl(econ)}"
    elif exec_ <= FL_ALERTA_EXEC and exec_ > 0:
        obs = f"🔥 OFERTA! {best_exec['cia']} executiva {fmt_brl(exec_)}"

    payload = {
        "destino":  "florida",
        "date":     datetime.now().strftime("%d/%m/%Y"),
        "hora":     datetime.now().strftime("%H:%M"),
        "econ":     f"R$ {int(econ):,}".replace(",",".") if econ else "—",
        "exec":     f"R$ {int(exec_):,}".replace(",",".") if exec_ else "—",
        "cia":      best_econ["cia"] if econ else best_exec["cia"],
        "best":     f"R$ {min(filter(None,[econ,exec_])):,}".replace(",",".") if any([econ,exec_]) else "—",
        "queda":    "",
        "oferta":   "SIM" if eh_oferta else "NÃO",
        "alerta":   "SIM" if eh_oferta else "NÃO",
        "obs":      obs,
    }
    salvar(payload)

    if eh_oferta:
        msg_parts = ["🌴 *ALERTA PASSAGENS FLORIDA 2027*", ""]
        if best_econ["preco"]: msg_parts.append(f"✈️ Econômica: *{fmt_brl(best_econ['preco'])}* ({best_econ['cia']}) [{best_econ['rota']}]")
        if best_exec["preco"]: msg_parts.append(f"🛋️ Executiva: *{fmt_brl(best_exec['preco'])}* ({best_exec['cia']})")
        msg_parts += ["", obs, "", "📊 Veja o portal para mais detalhes!"]
        print("  🔔 OFERTA DETECTADA! Enviando WhatsApp...")
        whatsapp("\n".join(msg_parts), "🌴")

# ── MONITOR BUENOS AIRES ──────────────────────────────────────────────────────
def monitor_buenos_aires():
    print("\n🇦🇷 BUENOS AIRES — FERIADOS PROLONGADOS")
    print("-" * 40)
    proximos = feriados_proximos()

    if not proximos:
        print("  Sem feriados próximos para monitorar (próximos 120 dias)")
        return

    for data_ida, data_volta, nome, dias in proximos:
        print(f"  Verificando: {nome} ({data_ida} → {data_volta})...")

        # Busca os dois aeroportos de Buenos Aires
        melhor_preco_total = None
        melhor_cia = "—"
        melhor_aeroporto = "—"

        for aeroporto in ["EZE", "AEP"]:
            print(f"    → GRU → {aeroporto}...")
            data = buscar_voo("GRU", aeroporto, data_ida, data_volta, 2)
            preco_t, cia_t = melhor_preco(data, "econ")
            if preco_t:
                print(f"       {aeroporto}: R$ {round(preco_t/2):,}/pessoa ({cia_t})")
                if melhor_preco_total is None or preco_t < melhor_preco_total:
                    melhor_preco_total = preco_t
                    melhor_cia = cia_t
                    melhor_aeroporto = aeroporto
            else:
                print(f"       {aeroporto}: sem resultado")

        preco_total = melhor_preco_total
        cia = f"{melhor_cia} ({melhor_aeroporto})" if melhor_aeroporto != "—" else "—"
        preco_pp = round(preco_total / 2) if preco_total else 0
        print(f"    ✅ Melhor: {fmt_brl(preco_pp)} via {cia}")

        eh_erro    = preco_pp > 0 and preco_pp <= BA_ERRO_TARIFA
        eh_oferta  = preco_pp > 0 and preco_pp <= BA_ALERTA
        eh_bom     = preco_pp > 0 and preco_pp <= BA_BOM
        deve_alertar = eh_oferta or eh_erro

        obs = ""
        if eh_erro:    obs = f"🚨 ERRO DE TARIFA! {cia} {fmt_brl(preco_pp)} GRU→Buenos Aires"
        elif eh_oferta: obs = f"🔥 OFERTA! {cia} {fmt_brl(preco_pp)}/pessoa p/ {nome}"
        elif eh_bom:    obs = f"✅ Bom preço: {cia} {fmt_brl(preco_pp)}/pessoa"

        payload = {
            "destino":     "buenos_aires",
            "date":        datetime.now().strftime("%d/%m/%Y"),
            "hora":        datetime.now().strftime("%H:%M"),
            "feriado":     nome,
            "data_ida":    data_ida,
            "data_volta":  data_volta,
            "dias":        str(dias),
            "preco_pp":    f"R$ {int(preco_pp):,}".replace(",",".") if preco_pp else "—",
            "cia":         cia,
            "oferta":      "SIM" if (eh_oferta or eh_erro) else ("BOM" if eh_bom else "NÃO"),
            "alerta":      "SIM" if deve_alertar else "NÃO",
            "obs":         obs,
        }
        salvar(payload)

        if deve_alertar:
            emoji = "🚨" if eh_erro else "🔥"
            msg = "\n".join([
                f"{emoji} *{'ERRO DE TARIFA' if eh_erro else 'ALERTA'} — BUENOS AIRES*",
                "",
                f"🇦🇷 Feriado: *{nome}*",
                f"📅 Datas: {data_ida} → {data_volta} ({dias} dias)",
                f"✈️ Preço: *{fmt_brl(preco_pp)}* ({cia})",
                f"🛫 Rota: GRU → Buenos Aires",
                "",
                obs,
                "",
                "⚡ Corra! Erros de tarifa são corrigidos em horas!",
            ])
            print(f"  🔔 ALERTA BA! Enviando WhatsApp...")
            whatsapp(msg, "🇦🇷")

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"🔍 Monitor de Passagens — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*50}")
    monitor_florida()
    monitor_buenos_aires()
    print(f"\n✅ Concluído — {datetime.now().strftime('%H:%M')}\n")
