"""
Monitor de Passagens - Florida Maio 2027
Roda todo dia às 8h via GitHub Actions.
Usa SerpAPI (Google Flights) para buscar preços reais.
Salva no Google Sheets via Apps Script Webhook.
Manda WhatsApp via CallMeBot se achar oferta.
"""

import os, requests
from datetime import datetime

# ── SECRETS (configurados no GitHub → Settings → Secrets) ────────────────────
SERPAPI_KEY      = os.environ["SERPAPI_KEY"]
CALLMEBOT_PHONE  = os.environ["CALLMEBOT_PHONE"]   # ex: +5511999999999
CALLMEBOT_APIKEY = os.environ["CALLMEBOT_APIKEY"]
SHEETS_WEBHOOK   = os.environ["SHEETS_WEBHOOK"]     # URL do Apps Script

# ── CONFIGURAÇÃO DA VIAGEM ────────────────────────────────────────────────────
ROTAS = [
    {"dep": "GRU", "arr": "MCO"},  # Guarulhos → Orlando
    {"dep": "GRU", "arr": "MIA"},  # Guarulhos → Miami
]
DATAS_IDA   = ["2027-05-01", "2027-05-06", "2027-05-10"]
DATAS_VOLTA = ["2027-05-16", "2027-05-18", "2027-05-20"]
ADULTOS  = 2
CRIANCAS = 1

# ── LIMITES DE ALERTA ─────────────────────────────────────────────────────────
ALERTA_ECON = 3500   # Abaixo disso → WhatsApp imediato
ALERTA_EXEC = 9000
BOM_ECON    = 4500   # Abaixo disso → registrar como bom
BOM_EXEC    = 13000
CIA_EXCLUIR = ["Azul"]

# ── BUSCA DE PREÇOS VIA SERPAPI ───────────────────────────────────────────────
def buscar_precos():
    melhor_econ = {"preco": None, "cia": None, "rota": None}
    melhor_exec = {"preco": None, "cia": None, "rota": None}

    for rota in ROTAS:
        for data_ida in DATAS_IDA:
            for data_volta in DATAS_VOLTA:
                params = {
                    "engine":        "google_flights",
                    "departure_id":  rota["dep"],
                    "arrival_id":    rota["arr"],
                    "outbound_date": data_ida,
                    "return_date":   data_volta,
                    "adults":        ADULTOS,
                    "children":      CRIANCAS,
                    "currency":      "BRL",
                    "hl":            "pt",
                    "api_key":       SERPAPI_KEY,
                    "type":          "1",  # ida e volta
                }

                try:
                    resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
                    data = resp.json()
                except Exception as e:
                    print(f"Erro SerpAPI ({rota['dep']}→{rota['arr']} {data_ida}): {e}")
                    continue

                # Percorre best_flights e other_flights
                todos = data.get("best_flights", []) + data.get("other_flights", [])

                for voo in todos:
                    preco = voo.get("price")
                    if not preco:
                        continue

                    preco_pp = preco / (ADULTOS + CRIANCAS)

                    # Nome da cia
                    flights = voo.get("flights", [])
                    cia = flights[0].get("airline", "—") if flights else "—"

                    if any(exc.lower() in cia.lower() for exc in CIA_EXCLUIR):
                        continue

                    # Detectar classe
                    travel_class = flights[0].get("travel_class", "Economy") if flights else "Economy"
                    eh_exec = "business" in travel_class.lower() or "first" in travel_class.lower()

                    nome_rota = f"{rota['dep']}→{rota['arr']}"

                    if eh_exec:
                        if melhor_exec["preco"] is None or preco_pp < melhor_exec["preco"]:
                            melhor_exec = {"preco": round(preco_pp), "cia": cia, "rota": nome_rota}
                    else:
                        if melhor_econ["preco"] is None or preco_pp < melhor_econ["preco"]:
                            melhor_econ = {"preco": round(preco_pp), "cia": cia, "rota": nome_rota}

    return melhor_econ, melhor_exec


# ── SALVAR NO GOOGLE SHEETS VIA WEBHOOK ──────────────────────────────────────
def salvar_sheets(econ, exec_, eh_oferta, eh_alerta, queda, obs):
    payload = {
        "date":    datetime.now().strftime("%d/%m/%Y"),
        "econ":    f"R$ {econ['preco']:,}".replace(",", ".") if econ["preco"] else "—",
        "exec":    f"R$ {exec_['preco']:,}".replace(",", ".") if exec_["preco"] else "—",
        "cia":     econ["cia"] or exec_["cia"] or "—",
        "best":    f"R$ {min(filter(None,[econ['preco'],exec_['preco']])):,}".replace(",",".") if any([econ["preco"],exec_["preco"]]) else "—",
        "queda":   queda,
        "oferta":  "SIM" if eh_oferta else "NÃO",
        "alerta":  "SIM" if eh_alerta else "NÃO",
        "obs":     obs,
    }
    try:
        r = requests.post(SHEETS_WEBHOOK, json=payload, timeout=15)
        print(f"✅ Sheets: {r.text.strip()}")
    except Exception as e:
        print(f"⚠️ Erro ao salvar no Sheets: {e}")


# ── WHATSAPP VIA CALLMEBOT ────────────────────────────────────────────────────
def enviar_whatsapp(econ, exec_, obs):
    linhas = ["🌴 *ALERTA PASSAGENS FLORIDA 2027*", ""]
    if econ["preco"]:
        linhas.append(f"✈️ Econômica: *R$ {econ['preco']:,.0f}/pessoa*")
        linhas.append(f"   {econ['cia']} | {econ['rota']}")
    if exec_["preco"]:
        linhas.append(f"🛋️ Executiva: *R$ {exec_['preco']:,.0f}/pessoa*")
        linhas.append(f"   {exec_['cia']} | {exec_['rota']}")
    linhas += ["", obs, "", "📊 Veja o histórico no seu portal!"]
    msg = "\n".join(linhas)

    url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={CALLMEBOT_PHONE}"
        f"&text={requests.utils.quote(msg)}"
        f"&apikey={CALLMEBOT_APIKEY}"
    )
    try:
        r = requests.get(url, timeout=15)
        print(f"✅ WhatsApp enviado! Status: {r.status_code}")
    except Exception as e:
        print(f"⚠️ Erro WhatsApp: {e}")


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n🔍 Buscando passagens — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 50)

    econ, exec_ = buscar_precos()

    print(f"✈️  Econômica: R$ {econ['preco']} ({econ['cia']}) [{econ['rota']}]")
    print(f"🛋️  Executiva: R$ {exec_['preco']} ({exec_['cia']}) [{exec_['rota']}]")

    # Avaliar se é oferta
    eh_oferta_econ = econ["preco"] and econ["preco"] <= ALERTA_ECON
    eh_oferta_exec = exec_["preco"] and exec_["preco"] <= ALERTA_EXEC
    eh_oferta      = eh_oferta_econ or eh_oferta_exec
    deve_alertar   = eh_oferta

    queda = ""
    obs   = ""
    if eh_oferta_econ:
        obs = f"🔥 OFERTA! {econ['cia']} econômica R${econ['preco']}/pessoa!"
    elif eh_oferta_exec:
        obs = f"🔥 OFERTA! {exec_['cia']} executiva R${exec_['preco']}/pessoa!"
    elif econ["preco"] and econ["preco"] <= BOM_ECON:
        obs = f"✅ Bom preço econômica: {econ['cia']} R${econ['preco']}"
    elif exec_["preco"] and exec_["preco"] <= BOM_EXEC:
        obs = f"✅ Bom preço executiva: {exec_['cia']} R${exec_['preco']}"

    # Salvar no Sheets
    salvar_sheets(econ, exec_, eh_oferta, deve_alertar, queda, obs)

    # WhatsApp se necessário
    if deve_alertar:
        print("🔔 OFERTA DETECTADA! Enviando WhatsApp...")
        enviar_whatsapp(econ, exec_, obs)
    else:
        print("😴 Sem oferta hoje. Dados salvos no Sheets.")

    print("=" * 50)
    print("✅ Concluído!\n")
