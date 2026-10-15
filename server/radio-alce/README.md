# Rádio Alce — programação central

R2 → providers Python → programação/cache persistente → Liquidsoap → Icecast → um único sinal `/alce.mp3` MP3 128 kbps. O Android continua somente reproduzindo o stream; nenhuma regra foi reativada no APK.

## Programação

`config.py` centraliza URLs públicas, intervalos, ganhos e retenção. O sincronizador consulta `music_catalog.json` e `programming.json` a cada 60 s, valida e salva snapshots atomicamente. Falhas preservam a última configuração válida. Uma versão nova reconstrói bags na próxima seleção; itens já entregues ao decoder terminam normalmente. Não é necessário rebuild do APK ou restart para atualizar os pools. Quantidades são dinâmicas (na consulta desta implementação: catálogo versão 4, 46 músicas; programação versão 5, oito vinhetas e três jingles).

`ProgrammingEngine` mantém **MUSIC → STATION_ID → MUSIC → STATION_ID → MUSIC → JINGLE → MUSIC**, repetidamente. Bags independentes usam todos os itens antes de reciclar e não repetem o último na fronteira dos bags. O jingle substitui a vinheta. O campo legado `songsBetweenInsertions` não significa três músicas sem inserção; `INSERTION_PATTERN` documenta a regra atual.

Música: janela principal de **6 h**, artista **90 min** quando informado, prioridade para inéditas e depois grupo das menos recentemente tocadas com `SystemRandom`. Somente quando não há opções, a janela musical relaxa para 3 h, 90 min e zero. A última música e reservas futuras ficam excluídas (exceção: catálogo de uma música). Histórico global SQLite WAL em `/data/station.sqlite3`: último horário de cada música, artista, ciclo, bags, última música/notícia e ids recentes de notícias. Retenção musical 48 h/500 ids, notícias 100 ids. Download/preload não conta como execução: o Liquidsoap confirma o início real. Restart completo/reboot restaura o checkpoint, sem persistir uma playlist rígida.

## Preload, áudio e fallback

O planner prepara a próxima música antes de publicar uma inserção. URLs são baixadas sob demanda para arquivos locais completos, validados com `ffprobe` e uma decodificação `ffmpeg -xerror`. A fila pronta mantém pelo menos a cadeia música/inserção/música, alvo seis itens; `request.dynamic(prefetch=4)` resolve antecipadamente arquivos no decoder Liquidsoap. Nenhuma requisição R2 acontece no callback de término. O endpoint interno `/next` não aguarda download.

Cache operacional LRU inicial **512 MiB**, limite por arquivo 150 MiB. Arquivos em reprodução, reservados e pequeno pool de emergência não são removidos; institucionais do catálogo atual/intro de notícias são protegidos. Portanto o limite pode ser temporariamente excedido por itens protegidos. Os 48 anúncios ficam separadamente em `/data/time/`. Não baixa a biblioteca inteira nem oferece download ao usuário.

**Transições atuais:** um getter de ganho no `amplify` calcula a envoltória pelo
relógio da fonte e pela duração PCM medida no cache. Cada callback síncrono de
início de faixa reinicia o estado; não depende do disparo estimado de `fade.out`. Só MUSIC recebe saída de 15 s (limitada à
metade da duração para arquivos muito curtos); peças curtas recebem saída zero.
Não há overlap/crossfade nem encurtamento fixo de vinhetas. Ganhos continuam em
`config.GAINS`. O emergency existente permanece inalterado.

`audio_boundaries.py` mede PCM antes de publicar o request: só remove da timeline
silêncio de borda abaixo de −80 dB, contínuo por pelo menos 250 ms, limitado a
5 s e mantendo margem de 10 ms. Ajusta apenas final de MUSIC e início de
STATION_ID/JINGLE. Fala, pausas internas, final das peças e início da próxima
música permanecem intactos. Os MP3 originais não são regravados; o cache salva
análise versionada `.edges.json` e envia `liq_cue_in/out` ao decoder. A duração
usada no agendamento corresponde ao áudio após os cues. Notícias/hora não são
recortadas. Não se promete eliminar pausas artísticas ou áudio baixo audível.

A regressão `ALCE_TEST_TRANSITIONS=1 python3 tests/validate_runtime.py` mede PCM
recebido do Icecast com fixtures que contêm 2 s de silêncio musical terminal e
400 ms de silêncio inicial na vinheta: exige saída musical gradual, peças
completas, restauração do volume e ausência de silêncio >50 ms a −80 dB.


Falha de música: cooldown 10 min e outra seleção; peça institucional: tenta alternativas do mesmo tipo, depois segue música. Falha editorial: cancela o bloco inteiro, sem intro isolada. Um pool persistente de três músicas verificadas sustenta o sinal caso o planner falhe. Esse modo de emergência pode relaxar a antirrepetição. Se nunca houve áudio válido no primeiro boot e todas as fontes estão indisponíveis, `mksafe` mantém a conexão Icecast com silêncio; isso é degradado, não uma programação saudável. Não é possível garantir áudio sem uma fonte válida.

## Notícias e hora certa

Feed oficial preservado: `https://agenciabrasil.ebc.com.br/radioagencia-nacional/rss/ultimasnoticias/feed.xml`. `RemoteNewsProvider` atualiza a cada 15 min; prefere a notícia não reproduzida mais recente nas últimas 24 h, duração 30–240 s. Usa enclosure ou resolve áudio do HTML oficial; URLs e redirects ficam restritos a HTTPS EBC. Notícias não são modificadas, e metadata atribui **Radioagência Nacional**.

Blocos ficam devidos após **4 horas** desde a última notícia (ou início da estação, quando não há histórico), mas só entram após a música terminar, substituindo a inserção normal sem consumir sua posição. Não interrompem conteúdos. A previsão considera a duração dos itens já preparados, corrigida pelo começo real de playback. Sequência indivisível:

**MUSIC → NEWS_INTRO → [TIME_ANNOUNCEMENT] → NEWS_DROP → MUSIC**.

Intro: `Vinheta_Noticias_Masterizada.mp3` no mesmo R2. Não há vinheta/jingle comum no bloco. Quando não há notícia elegível, continua a programação e tenta no próximo ponto seguro.

O checkpoint salva timestamps absolutos, migra os slots antigos de 30 min sem apagar histórico e sobrevive a reinícios. `config.NEWS_INTERVAL = 4 * 60 * 60` é a configuração do servidor; `programming.json` não controla esse intervalo. O refresh do RSS continua a cada 15 min e não dispara blocos.

A hora continua opcional **dentro do bloco de notícias**; não foi criado um anúncio independente a cada meia hora.

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

Após deploy, ouvir `http://15.229.83.121:8000/alce.mp3` em dois aparelhos simultaneamente: música/vinheta/música/vinheta/música/jingle/música, peças completas, cortes limpos, mesma sequência e diferença pequena de buffer. Ouvir também um bloco de notícias após 4 horas; se terminou fora da tolerância, **não haverá hora**. Testar restart completo com `docker compose restart` e conferir histórico/ciclo persistentes. Para substituir apenas o serviço catalog em manutenção, reiniciar também liquidsoap para descartar reservas de decoder da sessão anterior.

O Codex não possui SSH/SSM da EC2; validações isoladas não comprovam que a nova versão já foi aplicada na produção. Não foi feito cutover remoto.

## Fallback emergency: áudio mesmo sem planner

`emergency.m3u` contém somente `#EXTM3U` e caminhos absolutos de até três
MP3 musicais já preparados no cache. A publicação é atômica, os caminhos são
validados, e um snapshot antigo é migrado ao iniciar mesmo sem acesso ao R2.
Não há `annotate:`, URLs ou tokens nesse arquivo. O Liquidsoap usa explicitamente
o parser M3U (`audio/x-mpegurl`) e antecipa dois arquivos do fallback.

O ganho/fade editorial foi reativado com relógio da fonte e reinicialização por faixa; consulte a seção de transições atuais.
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

## Histórico do isolamento de amplitude — Liquidsoap 2.4.6

Pipeline da recuperação anterior: `request.dynamic → fallback → mksafe → output.icecast`
(MP3 128 kbps, mesmo `/alce.mp3`). Callbacks, planner, emergency, histórico e
programação continuam intactos. Os campos `liq_gain`/`liq_fade_out`/`liq_fade_in`
continuam chegando, mas o principal não os aplica nesta recuperação.

```bash
docker build -t alce-catalog-validation -f server/radio-alce/Dockerfile.catalog server/radio-alce
python3 server/radio-alce/tests/validate_audio_pipeline.py
```

A/B usa a mesma configuração de produção e apenas insere operadores no ramo
principal de containers isolados. Mede o MP3 de entrada e o áudio recebido de
`/alce.mp3` usando **FFmpeg volumedetect**, incluindo a captura após os primeiros
10 segundos. Casos: sem processamento, amplify, fade-out isolado, fade-in isolado,
combinação antiga e overrides explícitos com `track_sensitive=true`.
`override_duration` padrão já é `liq_fade_out`/`liq_fade_in`: valores numéricos válidos
substituem `duration=0.`. Entretanto `track_sensitive` padrão é **false**, portanto
a envoltória não é reiniciada a cada faixa. O teste identifica se o sinal permanece
zerado após o primeiro fade-out. O caso explícito é apenas diagnóstico; não está
habilitado no stream de produção.

O teste de recuperação exige média > −40 dB e pico > −20 dB, bem acima de −80/−91 dB.
Tons sintéticos pequenos são gerados temporariamente; nenhuma música/licença ou
internet é necessária. Metadata, decoder válido e HTTP 200 sozinhos não aprovam o
teste. O workflow existente executa essa regressão antes do build Android.

Resultado de isolamento no Liquidsoap fixado (volume do Icecast após 10 s):

| Ramo principal | Média | Pico |
|---|---:|---:|
| Sem processamento — produção atual | −19,0 dB | −15,8 dB |
| Apenas amplify | −20,1 dB | −16,8 dB |
| Amplify + fade.out padrão | −91,0 dB | −91,0 dB |
| Amplify + fade.in padrão | −20,1 dB | −16,8 dB |
| Cadeia antiga de fades | −91,0 dB | −91,0 dB |
| Fades com overrides explícitos e track_sensitive=true | −23,0 dB | −16,9 dB |

Entrada sintética: média −15,5 dB, pico −12,5 dB. A conversão mono/estéreo e
re-encoding afetam os níveis absolutos, mas todas as comparações usam o mesmo MP3.
A média da captura inteira podia esconder o problema, pois inclui áudio inicial:
por isso a regressão também mede o período após a primeira faixa terminar.
O responsável isolado foi `fade.out` sem reinicialização por faixa. `duration=0.`
não neutraliza o operador quando o request possui `liq_fade_out=15.0`.

Para este hotfix, não é necessário reiniciar catalog ou Icecast. Faça backup do
`liquidsoap/radio.liq` da instalação ativa, clone o repositório pessoal em um
novo diretório e fixe o commit validado. No diretório Compose ativo, valide a
candidata com `docker compose run --rm --no-deps -v /caminho/candidata.liq:/candidate.liq:ro liquidsoap liquidsoap --check /candidate.liq`.
Somente após aprovação copie a candidata sobre `liquidsoap/radio.liq` e execute
`docker compose up -d --no-deps --force-recreate liquidsoap`. Para rollback,
restaure esse único arquivo do backup e repita o último comando. Credenciais,
volumes, imagem fixada, planner e emergency não são alterados. O encoder será
reconectado uma vez; valide a amplitude do stream após a troca.

### Nome do JSON de programação no R2

O endpoint consumido pelo servidor é `programming.json` na raiz do bucket.
`server/radio-alce/programming.json` registra a configuração completa recuperada
em 14/10/2026 (versão 10), validada pelo parser do servidor e publicada no R2.
Ela contém `stationId`, `version`, `rules`, `stationIds` e `jingles`.

`scripts/station-id-additions.json` é somente uma lista de adições para merge.
Não deve substituir nem ser publicada como configuração completa, mesmo que
renomeada para `station-id-additions-atualizado.json`. Para futuras adições, use
o workflow existente de publicação de vinhetas, que preserva a configuração remota.
O snapshot versionado não é carregado automaticamente pelo servidor.

A operação manual `restore_programming` do workflow de sincronização recupera
um backup histórico, valida os áudios e cria o objeto somente se estiver ausente
(`If-None-Match: *`). Referências confirmadas como 404 são descartadas; erros de
acesso interrompem a publicação. Não usar essa recuperação histórica para uma
atualização rotineira. O relatório e os JSONs ficam no Artifact
`programming-restoration` por 30 dias.

## Deploy da correção MUSIC → INSERT (2026-10-15)

Atualize **catalog e liquidsoap** juntos. O `catalog` mede as bordas e fornece
`radio_duration`/cues; o encoder aplica o ganho usando o relógio da fonte.
Não basta copiar apenas `radio.liq`, nem atualizar somente o JSON.

No EC2 Instance Connect, usuário `ubuntu`, use um novo clone do repositório pessoal:

```bash
RELEASE="$HOME/radio-alce-transitions-$(date -u +%Y%m%dT%H%M%SZ)"
git clone --branch main --single-branch https://github.com/luizamedice-glitch/aplicativo_radioembarcada-pessoal.git "$RELEASE"
cd "$RELEASE/server/radio-alce"
bash deploy-transitions.sh
```

O script identifica automaticamente instalação/projeto ativos; guarda backup
privado incluindo `.env`; reutiliza o mesmo volume e as credenciais existentes;
compila, testa e valida sintaxe antes de trocar containers. Não altera Icecast,
R2, APK, programação, hora ou notícias. Pode ocorrer uma reconexão breve na troca
do encoder. No final compara SHA256 dos arquivos dentro dos containers com os
do checkout e imprime o comando exato de rollback. Não apaga o volume.

Confirmação na EC2: logs `AUDIO pipeline=clock-envelope-v1`, `AUDIO edges` com
silêncios medidos, `AUDIO envelope type=MUSIC ... fade_out=15.0s` (músicas >30 s)
e `type=STATION_ID/JINGLE ... fade_out=0.0s`. Duração zero significa que o planner
antigo ainda está entregando requests sem duração, não que o fade está validado.
A confirmação final é auditiva em várias trocas e pela medição do stream; logs
sozinhos não comprovam áudio contínuo. Arquivos com pausas/caudas acima de −80 dB
não são cortados automaticamente. O teste sintético mede também jingles e dois
ouvintes recebendo os mesmos bytes de um único encoder.

### Evidência de validação da transição

Teste local isolado com a imagem Liquidsoap 2.4.6 fixada no Compose, mesmo
`radio.liq` de produção e MP3 recebido de `/alce.mp3` (2026-10-15):

- 3 transições PCM verificadas: duas STATION_ID e um JINGLE, todos completos.
- Queda medida entre 16 s e 1 s antes das peças: 17,87 / 18,03 / 17,83 dB.
- Maior janela abaixo de −80 dB: 50 ms (resolução de medição 10 ms), contra
  2 s de cauda musical + 400 ms de início vazio adicionados às fixtures.
- Volume do stream: média −21,1 dB / pico −16,7 dB; ganho da MUSIC seguinte restaurado.
- Dois ouvintes receberam o mesmo sinal codificado; nenhuma fila por cliente.
- Emergency com planner suspenso: zero janelas silenciosas de 100 ms,
  retomada da programação confirmada, nenhum erro de parsing M3U.
- 54 testes do servidor, inclusive dentro da imagem catalog, e 34 testes dos
  scripts aprovados; imagem catalog compilada e Liquidsoap `--check` aprovado.

A/B também reproduziu o defeito histórico de `fade.out` sem reset: −91 dB.
O envelope atual permanece audível após várias faixas. O teste de amplitude
isolado dos operadores não mede sozinho a progressão do fade; a nova regressão
PCM faz essa distinção. Timestamps HTTP de `/played` são apenas diagnósticos e
não são tratados como prova de ausência de gaps ou duração integral.

Estas são medições locais, não uma declaração de deploy/escuta na EC2. A validação
final deve ouvir várias trocas do catálogo real após conferir os hashes dos
containers implantados. MP3 com silêncio artístico acima do limite conservador
não são recortados por esta política.

A integração com as alterações concorrentes `b28cb12`/`79c39cc` preserva a
seleção de fonte **antes** do processamento de volume, evitando que um operador
de fade leve o fallback a escolher emergency numa transição normal. A análise
persistente de bordas substitui o scanner anterior de cauda; não são aplicados
dois recortes/fades. O teste de cue-out e a asserção de que produção não ativa
emergency durante transições normais permanecem na regressão.
