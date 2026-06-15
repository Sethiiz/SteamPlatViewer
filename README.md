# SteamPlatViewer

Varre sua biblioteca Steam e gera um Excel com status de conquistas de cada jogo, cruzando com o tempo estimado do HowLongToBeat.

## Setup

```
pip install -r requirements.txt
```

Crie um `.env` na raiz com sua chave da [Steam Web API](https://steamcommunity.com/dev/apikey):

```
STEAM_API_KEY=sua_chave_aqui
```

## Uso

```
python main.py
```

Na primeira execução pede o perfil Steam (URL ou SteamID64). O progresso fica salvo em `progress.json` — pode interromper e continuar quando quiser.
