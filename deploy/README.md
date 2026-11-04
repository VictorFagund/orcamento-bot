# Colocar no ar (VPS Ubuntu 24.04)

São dois programas: o **bot** (`bot_telegram.py`) e o **site** (`web.py`), usando o mesmo banco.
O Caddy fica na frente do site e cuida do HTTPS.

## 0. Antes
- Um domínio apontando para o IP da VPS (registro **A** no painel do domínio).
- O `.env` preenchido (veja `.env.example`), com `BASE_URL=https://seudominio.com.br` e `ADMIN_CHAT_ID`.
- Conta paga da IA com **teto de gasto** definido no painel do provedor.

## 1. Pacotes e usuário
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip sqlite3 rclone caddy git
sudo adduser --system --group --home /opt/orcamento-bot orcamento
```

## 2. Código
```bash
sudo -u orcamento git clone <seu-repositorio> /opt/orcamento-bot
cd /opt/orcamento-bot
sudo -u orcamento python3 -m venv .venv
sudo -u orcamento .venv/bin/pip install -r requirements.txt
sudo -u orcamento cp .env.example .env   # e preencha com: sudo -u orcamento nano .env
```

## 3. Serviços (religam sozinhos se cair ou se o servidor reiniciar)
```bash
sudo cp deploy/bot.service /etc/systemd/system/orcamento-bot.service
sudo cp deploy/web.service /etc/systemd/system/orcamento-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now orcamento-bot orcamento-web
sudo systemctl status orcamento-bot orcamento-web     # os dois "active (running)"
```
Logs: `journalctl -u orcamento-bot -f` e `journalctl -u orcamento-web -f`.

**Importante:** desligue o bot do seu PC antes. O mesmo token rodando em dois lugares faz um roubar as
mensagens do outro.

## 4. HTTPS
```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile        # troque seudominio.com.br pelo seu
sudo systemctl reload caddy
```
Teste: `https://seudominio.com.br/saude` deve mostrar `{"ok":true}`.

## 5. Backup diário
```bash
sudo -u orcamento rclone config        # crie um remoto chamado "backup" (Google Drive, Backblaze B2...)
sudo mkdir -p /var/backups/orcamento && sudo chown orcamento /var/backups/orcamento
sudo -u orcamento crontab -e           # adicione: 0 3 * * * /opt/orcamento-bot/deploy/backup.sh
sudo -u orcamento /opt/orcamento-bot/deploy/backup.sh   # rode uma vez e confira no remoto
```

### Restaurar um backup
```bash
sudo systemctl stop orcamento-bot orcamento-web
sudo -u orcamento rclone copy backup:orcamento-bot/orcamentos-AAAA-MM-DD.db /tmp/
sudo -u orcamento cp /tmp/orcamentos-AAAA-MM-DD.db /opt/orcamento-bot/dados/orcamentos.db
sudo -u orcamento rclone copy backup:orcamento-bot/arquivos-AAAA-MM-DD.tar.gz /tmp/
sudo -u orcamento tar -xzf /tmp/arquivos-AAAA-MM-DD.tar.gz -C /opt/orcamento-bot/dados
sudo systemctl start orcamento-bot orcamento-web
```

## 6. Atualizar
```bash
cd /opt/orcamento-bot && sudo -u orcamento git pull
sudo -u orcamento .venv/bin/pip install -r requirements.txt
sudo systemctl restart orcamento-bot orcamento-web
```

## 7. Piloto
```bash
sudo -u orcamento .venv/bin/python admin.py listar
sudo -u orcamento .venv/bin/python admin.py plano telegram:ID_DO_PRESTADOR piloto
sudo -u orcamento .venv/bin/python metricas.py --dias 21
```
