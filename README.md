# 🌴 Monitor de Passagens — Flórida 2027

Roda automaticamente todo dia às 8h (BRT) via GitHub Actions.
Busca preços, salva no Google Sheets e avisa no WhatsApp se achar oferta.

## Secrets necessários no GitHub

Vá em: Seu repositório → Settings → Secrets and variables → Actions → New repository secret

| Secret | O que é |
|--------|---------|
| `AMADEUS_API_KEY` | Chave da API Amadeus (developers.amadeus.com) |
| `AMADEUS_API_SECRET` | Segredo da API Amadeus |
| `CALLMEBOT_PHONE` | Seu número com DDI: +5511999999999 |
| `CALLMEBOT_APIKEY` | API Key recebida do CallMeBot |
| `SHEETS_ID` | ID da sua planilha (parte da URL do Google Sheets) |
| `GOOGLE_CREDENTIALS` | JSON completo da conta de serviço do Google |

## Como pegar o SHEETS_ID

Na URL da sua planilha:
https://docs.google.com/spreadsheets/d/AQUI_É_O_ID/edit
Copie a parte entre /d/ e /edit

## Como criar o GOOGLE_CREDENTIALS

1. Acesse console.cloud.google.com
2. Crie um projeto → Ative a API Google Sheets
3. Crie uma Conta de Serviço → Gere chave JSON
4. Copie o JSON inteiro como valor do secret
5. Compartilhe sua planilha com o e-mail da conta de serviço (como editor)

## Como cadastrar na Amadeus

1. Acesse developers.amadeus.com
2. Crie conta gratuita
3. Crie um app → copie API Key e API Secret
4. Solicite acesso de produção (Production) para Flight Offers Search
