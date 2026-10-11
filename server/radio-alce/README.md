# Rádio Alce — servidor de streaming

Primeira versão funcional do playout central da Rádio Alce.

## Arquitetura

Cloudflare R2 → sincronizador de catálogo → Liquidsoap → Icecast → clientes Android.

O servidor consulta o `music_catalog.json` público do R2, gera `music.m3u` em volume Docker compartilhado e o Liquidsoap transmite um único stream MP3 pelo Icecast.

## Requisitos

- Ubuntu Linux
- Docker
- Docker Compose v2
- porta TCP 8000 liberada no firewall/security group

## Deploy

```bash
cd server/radio-alce
chmod +x setup.sh
./setup.sh
```

O script gera senhas aleatórias locais em `.env`, cria `icecast/icecast.xml` a partir do template e sobe os containers.

## Stream

```text
http://SEU_IP_PUBLICO:8000/alce.mp3
```

## Serviços

- `radio-alce-icecast`
- `radio-alce-catalog`
- `radio-alce-liquidsoap`

## Diagnóstico

```bash
docker compose ps
docker compose logs catalog --tail=50
docker compose logs liquidsoap --tail=50
docker compose logs icecast --tail=50
```

## Segurança

Não versionar `.env` nem `icecast/icecast.xml`, pois contêm credenciais. Para produção, colocar HTTPS/reverse proxy na frente do Icecast e restringir SSH.

## Próximas etapas

Migrar para o servidor as regras de programação atualmente validadas no app: vinhetas, jingles, notícias, janela antirrepetição e transições/preload.
