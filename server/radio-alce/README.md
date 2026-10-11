# Rádio Alce — programação central

R2 → providers Python → programação/cache persistente → Liquidsoap → Icecast → um único sinal `/alce.mp3` MP3 128 kbps. O Android continua somente reproduzindo o stream; nenhuma regra foi reativada no APK.

## Programação

`config.py` centraliza URLs públicas, intervalos, ganhos e retenção. O sincronizador consulta `music_catalog.json` e `programming.json` a cada 60 s, valida e salva snapshots atomicamente. Falhas preservam a última configuração válida. Uma versão nova reconstrói bags na próxima seleção; itens já entregues ao decoder terminam normalmente. Não é necessário rebuild do APK ou restart para atualizar os pools. Quantidades são dinâmicas (na consulta desta implementação: catálogo versão 3, 74 músicas; programação versão 5, oito vinhetas e três jingles).

`ProgrammingEngine` mantém **MUSIC → STATION_ID → MUSIC → STATION_ID → MUSIC → JINGLE → MUSIC**, repetidamente. Bags independentes usam todos os itens antes de reciclar e não repetem o último na fronteira dos bags. O jingle substitui a vinheta. O campo legado `songsBetweenInsertions` não significa três músicas sem inserção; `INSERTION_PATTERN` documenta a regra atual.

Música: janela principal de **6 h**, artista **90 min** quando informado, prioridade para inéditas e depois grupo das menos recentemente tocadas com `SystemRandom`. Somente quando não há opções, a janela musical relaxa para 3 h, 90 min e zero. A última música e reservas futuras ficam excluídas (exceção: catálogo de uma música). Histórico global SQLite WAL em `/data/station.sqlite3`: último horário de cada música, artista, ciclo, bags, última música/notícia e ids recentes de notícias. Retenção musical 48 h/500 ids, notícias 100 ids. Download/preload não conta como execução: o Liquidsoap confirma o início real. Restart completo/reboot restaura o checkpoint, sem persistir uma playlist rígida.

## Preload, áudio e fallback

O planner prepara a próxima música antes de publicar uma inserção. URLs são baixadas sob demanda para arquivos locais completos, validados com `ffprobe` e uma decodificação `ffmpeg -xerror`. A fila pronta mantém pelo menos a cadeia música/inserção/música, alvo seis itens; `request.dynamic(prefetch=4)` resolve antecipadamente arquivos no decoder Liquidsoap. Nenhuma requisição R2 acontece no callback de término. O endpoint interno `/next` não aguarda download.

Cache operacional LRU inicial **512 MiB**, limite por arquivo 150 MiB. Arquivos em reprodução, reservados e pequeno pool de emergência não são removidos; institucionais do catálogo atual/intro de notícias são protegidos. Portanto o limite pode ser temporariamente excedido por itens protegidos. Os 48 anúncios ficam separadamente em `/data/time/`. Não baixa a biblioteca inteira nem oferece download ao usuário.

Fade de saída **15 s somente para MUSIC**, seno contínuo até o fim real, sem overlap/crossfade/seek/clipping. Entrada de peça curta 150 ms; de música 100 ms. `STATION_ID`, `JINGLE`, intro, hora e notícia têm fade-out zero e tocam integralmente. Ganhos: música/notícia 0,9; demais peças 0,8. Não há normalização agressiva nem soma de dois áudios. Silêncio já gravado nos arquivos não é removido; audibilidade final deve ser validada na EC2 com as peças reais.

Falha de música: cooldown 10 min e outra seleção; peça institucional: tenta alternativas do mesmo tipo, depois segue música. Falha editorial: cancela o bloco inteiro, sem intro isolada. Um pool persistente de três músicas verificadas sustenta o sinal caso o planner falhe. Esse modo de emergência pode relaxar a antirrepetição. Se nunca houve áudio válido no primeiro boot e todas as fontes estão indisponíveis, `mksafe` mantém a conexão Icecast com silêncio; isso é degradado, não uma programação saudável. Não é possível garantir áudio sem uma fonte válida.

## Notícias e hora certa

Feed oficial preservado: `https://agenciabrasil.ebc.com.br/radioagencia-nacional/rss/ultimasnoticias/feed.xml`. `RemoteNewsProvider` atualiza a cada 15 min; prefere a notícia não reproduzida mais recente nas últimas 24 h, duração 30–240 s. Usa enclosure ou resolve áudio do HTML oficial; URLs e redirects ficam restritos a HTTPS EBC. Notícias não são modificadas, e metadata atribui **Radioagência Nacional**.

Blocos ficam devidos nos slots de **30 min**, mas só entram após a música terminar, substituindo a inserção normal sem consumir sua posição. Não interrompem conteúdos. A previsão considera a duração dos itens já preparados, corrigida pelo começo real de playback. Sequência indivisível:

**MUSIC → NEWS_INTRO → [TIME_ANNOUNCEMENT] → NEWS_DROP → MUSIC**.

Intro: `Vinheta_Noticias_Masterizada.mp3` no mesmo R2. Não há vinheta/jingle comum no bloco. Quando não há notícia elegível, continua a programação e tenta no próximo ponto seguro.

Hora: timezone **America/Sao_Paulo**, slots HH:00/HH:30. Conforme regra aprovada, **se o ponto seguro atrasar mais de 60 s, omite somente a hora**. Não corta música para acertar relógio. O Liquidsoap revalida o deadline no início real, além da previsão do planner, e descarta uma hora vencida por atraso de decoder/rede. A notícia continua. A latência do stream/player acrescenta alguns segundos.

`TtsProvider` é substituível; adapter `FreeTtsProvider` usa POST oficial `https://freetts.org/api/v1/tts`, header `x-api-key`, `file_id`, download oficial `/api/audio/{file_id}`. Voz padrão `pt-BR-AntonioNeural`, configurável em `FREETTS_VOICE`. Gera antecipadamente **48 arquivos** `/data/time/0000.mp3` … `2330.mp3`, começando pelo slot atual, com no máximo uma geração a cada 8 s. Arquivos válidos não são gerados novamente. Não chama API durante playback. Sem chave/arquivo/API, pula apenas a hora e tenta gerar depois.

Adicionar a chave **somente na `.env` da EC2**, usando editor. Nunca no APK, Git, linha de comando ou logs. `.env.example` contém apenas placeholder. Conferir termos/plano FreeTTS: o plano grátis anunciado tem limite e watermark, e não presume licença comercial. O adapter é configurável e não define o provedor definitivo.

## Instalação e atualização pela EC2 Instance Connect

Ubuntu, Docker + Compose v2, Python 3, OpenSSL, relógio sincronizado, saída HTTPS e porta TCP 8000 já liberada. Não exige SSH nem chave no ambiente Codex. O script usa volumes persistentes e não apaga dados.

Para atualizar uma instalação existente sem sobrescrever seu checkout, execute como `ubuntu`:

```bash
set -euo pipefail
CURRENT=$(docker inspect radio-alce-liquidsoap --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}')
PROJECT=$(docker inspect radio-alce-liquidsoap --format '{{ index .Config.Labels "com.docker.compose.project" }}')
test -d "$CURRENT"
test -n "$PROJECT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$HOME/radio-alce-backups/$STAMP"
mkdir -p "$BACKUP"
chmod 700 "$HOME/radio-alce-backups" "$BACKUP"
cp -a "$CURRENT/." "$BACKUP/"
RELEASE="$HOME/radio-alce-release-$STAMP"
git clone --branch main --single-branch https://github.com/luizamedice-glitch/aplicativo_radioembarcada-pessoal.git "$RELEASE"
# Para deploy reproduzível, faça git -C "$RELEASE" checkout <commit-validado>.
cp "$CURRENT/.env" "$RELEASE/server/radio-alce/.env"
chmod 600 "$RELEASE/server/radio-alce/.env"
cd "$RELEASE/server/radio-alce"
export COMPOSE_PROJECT_NAME="$PROJECT"
printf 'COMPOSE_PROJECT_NAME=%s\n' "$PROJECT" >> .env
grep -q '^FREETTS_API_KEY=' .env || printf '\nFREETTS_API_KEY=\n' >> .env
grep -q '^FREETTS_VOICE=' .env || printf '\nFREETTS_VOICE=pt-BR-AntonioNeural\n' >> .env
nano .env
# Preencha FREETTS_API_KEY no editor; não cole a chave em comandos/logs.
sudo timedatectl set-timezone America/Sao_Paulo
# Habilite o daemon NTP já instalado; Ubuntu pode usar chrony ou timesyncd:
if systemctl list-unit-files chrony.service --no-legend | grep -q '^chrony.service'; then
  sudo systemctl enable --now chrony
else
  sudo timedatectl set-ntp true
fi
timedatectl status
chmod +x setup.sh
./setup.sh --check
./setup.sh --deploy
docker compose ps
docker compose logs --tail=80 catalog liquidsoap
printf 'Backup: %s\nRelease: %s\nProjeto: %s\n' "$BACKUP" "$RELEASE" "$PROJECT"
```

`--check` gera XML local e imagens e valida a **mesma versão fixada do Liquidsoap**, sem reiniciar serviços existentes. `--deploy` aquece catálogo/cache, faz backup online SQLite e só então troca encoder. Backup lógico anterior no Git: `7c049243c51f36423571e2ef0937ee08eaf4b766`. Backups de arquivos/credenciais ficam locais ignorados, com acesso restrito. Uma troca planejada do encoder pode causar breve reconexão de ouvintes.

**Não execute `docker compose down -v`**. `COMPOSE_PROJECT_NAME` preserva o mesmo volume da instalação anterior. Healthchecks: Icecast responde, planner tem catálogo + áudio preparado e worker vivo, Liquidsoap atualiza heartbeat. `docker compose ps` deve indicar healthy. O heartbeat comprova processo vivo, não qualidade audível; também conferir o mount e ouvir.

Rollback, mantendo o volume (use as variáveis anteriores ou os caminhos mostrados no deploy):

```bash
cd "$BACKUP"
export COMPOSE_PROJECT_NAME="$PROJECT"
docker compose up -d --build --remove-orphans
curl --fail --silent --max-time 10 http://127.0.0.1:8000/alce.mp3 --output /tmp/alce-rollback-check.mp3 || test -s /tmp/alce-rollback-check.mp3
```

O backup inclui o antigo compose e código/XML, restaurando a arquitetura musical anterior sem apagar o volume. O novo sincronizador continua gerando `music.m3u` para compatibilidade; `liquidsoap/radio-legacy.liq` conserva o código original. Não basta selecionar somente o arquivo legacy e interpretar o healthcheck novo como válido: o encoder antigo não emite heartbeat. Para rollback completo use o compose antigo do backup.

## Validação

```bash
python3 -m unittest discover -s server/radio-alce/tests -v
bash -n server/radio-alce/setup.sh
# Teste offline opcional com tons sintéticos, decoder real, Icecast e dois ouvintes:
docker build -t alce-catalog-validation -f server/radio-alce/Dockerfile.catalog server/radio-alce
python3 server/radio-alce/tests/validate_runtime.py
ALCE_TEST_NEWS=1 python3 server/radio-alce/tests/validate_runtime.py
```

O workflow **existente** `Android debug` executa testes Python e valida sintaxe Liquidsoap, além de testes Android/lint/build. Artifact APK continua `radio-embarcada-debug-apk`; não contém música, chave TTS ou alteração de player nesta tarefa.

Após deploy, ouvir `http://15.229.83.121:8000/alce.mp3` em dois aparelhos simultaneamente: música/vinheta/música/vinheta/música/jingle/música, peças completas, fades suaves, mesma sequência e diferença pequena de buffer. Ouvir também um bloco de 30 min; se terminou fora da tolerância, **não haverá hora**. Testar restart completo com `docker compose restart` e conferir histórico/ciclo persistentes. Para substituir apenas o serviço catalog em manutenção, reiniciar também liquidsoap para descartar reservas de decoder da sessão anterior.

O Codex não possui SSH/SSM da EC2; validações isoladas não comprovam que a nova versão já foi aplicada na produção. Não foi feito cutover remoto.

## Fallback emergency: áudio mesmo sem planner

`emergency.m3u` contém somente `#EXTM3U` e caminhos absolutos de até três
MP3 musicais já preparados no cache. A publicação é atômica, os caminhos são
validados, e um snapshot antigo é migrado ao iniciar mesmo sem acesso ao R2.
Não há `annotate:`, URLs ou tokens nesse arquivo. O Liquidsoap usa explicitamente
o parser M3U (`audio/x-mpegurl`) e antecipa dois arquivos do fallback.

O ganho/fade editorial é aplicado somente ao ramo principal, antes do `fallback`.
O emergency usa ganho fixo moderado (0,9), sem envoltória editorial nem dependência
de metadados/duração. `metadata.map` fornece metadados genéricos até quando o MP3
não possui tags e limpa explicitamente tokens/ids. Assim, o fallback não herda
estado da música anterior. Esses metadados não contêm identificação editorial: o fallback **não**
altera o histórico oficial nem o ciclo. Apenas acknowledgements de deliveries
válidos do fluxo principal atualizam o estado. O token antigo `emergency` é ignorado.

`request.dynamic` continua antecipando quatro requests; blocos já preparados
são publicados atomicamente e `/next` pula arquivos que desapareceram. Respostas
HTTP de erro não viram requests. O fallback respeita o fim da faixa para retornar
ao planner, mantendo uma única saída Icecast. `mksafe` permanece como última
proteção, inclusive no cold boot sem nenhum áudio válido cacheado.

Logs de estado: `EMERGENCY playlist updated: N tracks`, `EMERGENCY fallback ready`,
`EMERGENCY active`, `EMERGENCY ended / planner resumed`. Os três últimos são emitidos
por mudança de estado/disponibilidade, não por polling repetitivo.

Teste integrado isolado (FFmpeg e Docker necessários; apenas tons sintéticos):

```bash
docker build -t alce-catalog-validation -f server/radio-alce/Dockerfile.catalog server/radio-alce
ALCE_TEST_EMERGENCY=1 python3 server/radio-alce/tests/validate_runtime.py
```

Ele confirma o ciclo principal, pausa o container do planner, drena o prefetch,
mede áudio PCM recebido do Icecast durante o fallback e verifica a recuperação.
Exige áudio em todas as janelas de 100 ms amostradas e ausência dos erros XML/SCPLS.
Dois ouvintes recebem o mesmo sinal. O workflow existente também executa esse teste.
Não é uma medição da disponibilidade da EC2 nem uma garantia de todo tipo de rede.

Para aplicar apenas esta correção no EC2 Instance Connect, use os comandos de
backup/release acima, **sem editar `.env`, voz, timezone ou NTP**. Fixe o checkout
no commit validado, copie o `.env` existente e preserve `COMPOSE_PROJECT_NAME`.
Rode `./setup.sh --check` antes de `./setup.sh --deploy`. O rollback continua sendo
`docker compose up -d --build --remove-orphans` no diretório de backup com o mesmo
nome de projeto; nunca remova o volume com `down -v`.
