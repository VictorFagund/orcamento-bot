#!/usr/bin/env bash
# Backup diário: banco + PDFs/logos, enviado para fora do servidor com o rclone. Guarda 30 dias.
# Agendar (como usuário orcamento):  crontab -e  ->  0 3 * * * /opt/orcamento-bot/deploy/backup.sh
set -euo pipefail
APP=/opt/orcamento-bot
DESTINO_LOCAL=/var/backups/orcamento
REMOTO="${REMOTO_BACKUP:-backup:orcamento-bot}"   # nome do remoto configurado com "rclone config"
DATA=$(date +%F)

mkdir -p "$DESTINO_LOCAL"
sqlite3 "$APP/dados/orcamentos.db" ".backup '$DESTINO_LOCAL/orcamentos-$DATA.db'"   # cópia segura com o bot rodando
tar -czf "$DESTINO_LOCAL/arquivos-$DATA.tar.gz" -C "$APP/dados" arquivos
rclone copy "$DESTINO_LOCAL" "$REMOTO" --include "*-$DATA.*"
find "$DESTINO_LOCAL" -type f -mtime +30 -delete
rclone delete "$REMOTO" --min-age 30d
