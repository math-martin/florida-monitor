"""
Monitor de Passagens - Florida 2027
Roda todo dia via GitHub Actions às 8h (horário de Brasília)
Busca preços, salva no Google Sheets e avisa no WhatsApp se achar oferta.
"""

import os, requests, json, gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from amadeus import Client, ResponseError

# ── CONFIGURAÇÃO ──────────────────────────────────────────────────────────────
ROTA_IDA    = ("GRU", "MCO")   # Guarulhos → Orlando
ROTA_VOLTA  = ("MIA", "GRU")   # Miami → Guarulhos
MES_VIAGEM  = "2027-05"
ADULTOS     = 2
CRIANCAS    = 1

ALERTA_ECON_MAX = 3500   # R$ — abaixo disso manda WhatsApp imediato
ALERTA_EXEC_MAX = 9000   # R$ — abaixo disso manda WhatsApp imediato
BOM_PRECO_ECON  = 4500   # R$ — abaixo disso registra como bom preço
BOM_PRECO_EXEC  = 13000  # R$ — abaixo disso registra como bom preço
QUEDA_ALERTA    = 20     # % de queda vs média histórica para alertar

CIA_EXCLUIDA    = ["AD"]  # Código IATA da Azul — excluída das buscas

# Secrets (configurados no GitHub → Settings → Secrets)
AMADEUS_KEY    = os.environ["AMADEUS_API_KEY"]
AMADEUS_SECRET = os.environ["AMADEUS_API_SECRET"]
CALLMEBOT_PHONE = os.environ["CALLMEBOT_PHONE"]   # ex: +5511999999999
CALLMEBOT_KEY   = os.environ["CALLMEBOT_APIKEY"]
SHEETS_ID       = os.environ["SHEETS_ID"]          # ID da sua planilha
GOOGLE_CREDS    = json.loads(os.environ["GOOGLE_CREDENTIALS"])

USD_BRL = 5.10  # Taxa de conversão USD → BRL (atualizada manualmente ou via API)

# ── FUNÇÃO: BUSCAR PREÇOS AMADEUS ────────────────────────────────────────────
def buscar_precos():
    amadeus = Client(client_id=AMADEUS_KEY, client_secret=AMADEUS_SECRET)
    
    melhores = {"econ": None, "exec": None, "cia_econ": None, "cia_exec": None}
    
    # Datas para testar (primeiros 20 dias de Maio 2027)
    datas_ida    = ["2027-05-01", "2027-05-03", "2027-05-06", "2027-05-10"]
    datas_volta  = ["2027-05-15", "2027-05-18", "2027-05-20"]

    for data_ida in datas_ida:
        for data_volta in datas_volta:
            try:
                response = amadeus.shopping.flight_offers_search.get(
                    originLocationCode=ROTA_IDA[0],
                    destinationLocationCode=ROTA_IDA[1],
                    departureDate=data_ida,
                    returnDate=data_volta,
                    adults=ADULTOS,
                    children=CRIANCAS,
                    currencyCode="BRL",
                    max=10,
                )

                for oferta in response.data:
                    cia_code = oferta["validatingAirlineCodes"][0] if oferta.get("validatingAirlineCodes") else ""
                    if cia_code in CIA_EXCLUIDA:
                        continue

                    preco_total = float(oferta["price"]["grandTotal"])
                    preco_por_pessoa = preco_total / (ADULTOS + CRIANCAS)

                    # Detectar classe predominante
                    classes = []
                    for itin in oferta.get("itineraries", []):
                        for seg in itin.get("segments", []):
                            for traveler in oferta.get("travelerPricings", []):
                                for detail in traveler.get("fareDetailsBySegment", []):
                                    if detail.get("segmentId") == seg.get("id"):
                                        classes.append(detail.get("cabin", "ECONOMY"))

                    classe_principal = max(set(classes), key=classes.count) if classes else "ECONOMY"
                    eh_exec = classe_principal in ("BUSINESS", "FIRST")
                    
                    # Nome da cia para exibição
                    cias_nomes = {
                        "LA": "LATAM", "JJ": "LATAM", "AA": "American",
                        "CM": "Copa", "TP": "TAP", "UA": "United",
                        "DL": "Delta", "G3": "Gol", "IB": "Iberia",
                    }
                    cia_nome = cias_nomes.get(cia_code, cia_code)

                    if eh_exec:
                        if melhores["exec"] is None or preco_por_pessoa < melhores["exec"]:
                            melhores["exec"]     = preco_por_pessoa
                            melhores["cia_exec"] = cia_nome
                    else:
                        if melhores["econ"] is None or preco_por_pessoa < melhores["econ"]:
                            melhores["econ"]     = preco_por_pessoa
                            melhores["cia_econ"] = cia_nome

            except ResponseError as e:
                print(f"Erro Amadeus ({data_ida}→{data_volta}): {e}")
                continue

    return melhores

# ── FUNÇÃO: LER HISTÓRICO DO SHEETS ─────────────────────────────────────────
def ler_historico(worksheet):
    rows = worksheet.get_all_values()
    precos_econ = []
    # Pular linha de título (1), subtítulo (2), vazia (3), cabeçalho (4) → dados a partir da linha 5
    for row in rows[4:]:
        if len(row) >= 2 and row[1]:
            try:
                val = float(str(row[1]).replace("R$", "").replace(".", "").replace(",", ".").strip())
                if val > 0:
                    precos_econ.append(val)
            except:
                pass
    return precos_econ

# ── FUNÇÃO: SALVAR NO SHEETS ─────────────────────────────────────────────────
def salvar_sheets(precos, media_hist):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scopes)
    gc     = gspread.authorize(creds)
    sh     = gc.open_by_key(SHEETS_ID)
    ws     = sh.worksheet("Histórico")

    econ = precos["econ"] or 0
    exec_ = precos["exec"] or 0
    cia   = precos["cia_econ"] or precos["cia_exec"] or "—"
    best  = min(filter(None, [econ, exec_])) if any([econ, exec_]) else 0

    queda = ""
    if media_hist and econ > 0:
        pct = round((media_hist - econ) / media_hist * 100)
        queda = f"-{pct}%" if pct > 0 else f"+{abs(pct)}%"

    eh_oferta  = (econ > 0 and econ <= ALERTA_ECON_MAX) or (exec_ > 0 and exec_ <= ALERTA_EXEC_MAX)
    queda_ok   = media_hist and econ > 0 and ((media_hist - econ) / media_hist * 100) >= QUEDA_ALERTA
    deve_alertar = eh_oferta or queda_ok

    data_hoje = datetime.now().strftime("%d/%m/%Y")
    obs = ""
    if econ <= ALERTA_ECON_MAX and econ > 0:
        obs = f"🔥 Econômica {cia} abaixo do alerta!"
    elif exec_ <= ALERTA_EXEC_MAX and exec_ > 0:
        obs = f"🔥 Executiva {cia} abaixo do alerta!"

    nova_linha = [
        data_hoje,
        f"R$ {int(econ):,}".replace(",", ".") if econ else "—",
        f"R$ {int(exec_):,}".replace(",", ".") if exec_ else "—",
        cia,
        f"R$ {int(best):,}".replace(",", ".") if best else "—",
        queda,
        "SIM" if eh_oferta else "NÃO",
        "SIM" if deve_alertar else "NÃO",
        obs,
    ]

    ws.append_row(nova_linha, value_input_option="USER_ENTERED")
    print(f"✅ Salvo no Sheets: {nova_linha}")

    # Salvar na aba Ofertas também
    ws_ofertas = sh.worksheet("Ofertas")
    ws_ofertas.append_row([
        datetime.now().strftime("%d/%m %H:%M"),
        cia,
        "GRU→MCO / MIA→GRU",
        "Econômica" if econ else "Executiva",
        f"R$ {int(econ):,}".replace(",", ".") if econ else f"R$ {int(exec_):,}".replace(",", "."),
        "—",
        queda,
        "✅ Inclusa",
        "—",
        "🔥 OFERTA" if eh_oferta else "✅ Registrado",
    ], value_input_option="USER_ENTERED")

    return deve_alertar, econ, exec_, cia, obs

# ── FUNÇÃO: WHATSAPP ─────────────────────────────────────────────────────────
def enviar_whatsapp(econ, exec_, cia, obs):
    msg_parts = [f"🌴 *ALERTA PASSAGENS FLORIDA 2027*\n"]
    if econ > 0:
        msg_parts.append(f"✈️ Econômica: R$ {int(econ):,.0f}/pessoa ({cia})")
    if exec_ > 0:
        msg_parts.append(f"🛋️ Executiva: R$ {int(exec_):,.0f}/pessoa ({cia})")
    msg_parts.append(f"\n{obs}")
    msg_parts.append(f"\n📊 Ver histórico completo no portal!")
    msg = "\n".join(msg_parts)

    url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={CALLMEBOT_PHONE}"
        f"&text={requests.utils.quote(msg)}"
        f"&apikey={CALLMEBOT_KEY}"
    )
    resp = requests.get(url, timeout=10)
    if resp.status_code == 200:
        print(f"✅ WhatsApp enviado para {CALLMEBOT_PHONE}")
    else:
        print(f"⚠️ Erro WhatsApp: {resp.status_code} — {resp.text}")

    # Registrar na aba Alertas
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scopes)
    gc     = gspread.authorize(creds)
    sh     = gc.open_by_key(SHEETS_ID)
    ws_alertas = sh.worksheet("Alertas WhatsApp")
    ws_alertas.append_row([
        datetime.now().strftime("%d/%m/%Y %H:%M"),
        "Econômica 🔥" if econ <= ALERTA_ECON_MAX else "Executiva 🔥",
        msg.replace("\n", " "),
        int(econ or exec_),
        "✅ Enviado",
    ], value_input_option="USER_ENTERED")

# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"🔍 Iniciando busca — {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # 1. Buscar preços
    precos = buscar_precos()
    print(f"💰 Melhor econômica: R$ {precos['econ']} ({precos['cia_econ']})")
    print(f"🛋️  Melhor executiva: R$ {precos['exec']} ({precos['cia_exec']})")

    # 2. Ler histórico para calcular média
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scopes)
    gc     = gspread.authorize(creds)
    sh     = gc.open_by_key(SHEETS_ID)
    hist   = ler_historico(sh.worksheet("Histórico"))
    media  = sum(hist) / len(hist) if hist else None
    print(f"📊 Média histórica econômica: R$ {round(media) if media else '—'}")

    # 3. Salvar no Sheets
    deve_alertar, econ, exec_, cia, obs = salvar_sheets(precos, media)

    # 4. Enviar WhatsApp se necessário
    if deve_alertar:
        print("🔔 OFERTA DETECTADA! Enviando WhatsApp...")
        enviar_whatsapp(econ, exec_, cia, obs)
    else:
        print("😴 Sem ofertas hoje. Tudo salvo no Sheets.")

    print("✅ Concluído!")
