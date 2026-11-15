# Diagnostika Pylontech Force H2

Sběr běží pořád a dívá se **jen do sítě `192.168.99.0/24`**. Jinou adresu nepřijme ani z `config.yaml`. Dashboard staré hodnoty neukazuje jako aktuální stav: když baterie neodpoví, je na obrazovce výpadek.

Program je jen na čtení. Do BMS nic nezapisuje. OpenVPN je cesta k téhle stránce, ne k baterii.

## Spuštění

Na počítači, který má cestu do `192.168.99.0/24`:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python run.py
```

Stránka je na [http://localhost:8080](http://localhost:8080). Historie je v `data/diag.db`.

PostgreSQL je volitelný. Obraz pro domácí server ho má v sobě. Když ho chcete i mimo Docker, do prostředí s běžným CPythonem přidejte `psycopg[binary]` a nastavte `DATABASE_URL`.

Při prvním startu Windows může chtít povolit Python v soukromých sítích. Bez toho discovery na UDP 48899 neuvidí odpověď. Procházení TCP 8899 v `192.168.99.1`–`192.168.99.254` běží i tak.

Když logger na discovery neodpovídá, dopište ho do `config.yaml`. IP musí být `192.168.99.x`, sériové číslo je číslo Wi-Fi loggeru:

```yaml
devices:
  - ip: 192.168.99.20
    serial: 3912345678
    name: Dům
```

## Co se čte

Solarman V5 na TCP 8899, Modbus funkce 0x03, mapa registrů Force H2. Z BMS jdou napětí článků, teploty modulů, SOC, SOH, proud, ochrany a poruchy. Vlastní prahy napětí program nestanovuje.

Teplota u článku v téhle mapě není samostatné čidlo. Ukazuje se teplota modulu.

## Domácí server

Na Linuxu v domě může PostgreSQL držet historii a samotný sběr musí vidět solární síť, proto běží v hostitelské síti, ne v dockerovém mostu:

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

Port 8080 nepouštějte na internet. K dashboardu se chodí přes OpenVPN na adresu serveru v domě. Port 8899 baterie zůstává jen v `192.168.99.0/24`.

Jednotka pro automatický start po rebootu je v `deploy/solar-diag.service`.
