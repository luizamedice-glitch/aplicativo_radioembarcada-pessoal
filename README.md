# Rádio Alce — stream central

Repositório ativo: **luizamedice-glitch/aplicativo_radioembarcada-pessoal**.
`origin` deve apontar para ele. O repositório antigo é somente upstream histórico;
commits, push em main, workflow e APKs são publicados no repositório pessoal.

## Arquitetura ativa

Antes, cada APK escolhia músicas e inserções a partir de music_catalog.json e
programming.json. Agora o modo padrão é **STREAM**:

```text
Cloudflare R2 → servidor de playout → Liquidsoap → Icecast
→ um stream MP3 → ExoPlayer → MediaLibrarySession/MediaLibraryService → UI
```

Stream provisório: **http://15.229.83.121:8000/alce.mp3**.
Todos os celulares recebem o mesmo sinal central, com pequena diferença de buffer.
O IP é provisório; futuramente usar domínio + HTTPS. O servidor em
`server/radio-alce/` agora inclui programação global, histórico persistente,
vinhetas/jingles, notícias de 30 min e hora opcional FreeTTS. Consulte
[deploy e rollback](server/radio-alce/README.md). Sua aplicação na EC2 é manual
via Instance Connect; o Android permanece inalterado.

`RadioService` conecta um único MediaItem da estação. Não instancia MusicProvider,
ProgrammingEngine, notícias, histórico musical, preload de faixas ou transições.
Não existe fallback automático: uma falha sempre tenta novamente o mesmo stream.
`LiveStreamPlayback` coordena intenção de Play/Pause e reconexão no mesmo ExoPlayer.
`StationSessionPlayer` protege a identidade contra títulos/artistas ICY: **Rádio Alce**,
**AO VIVO**, **Sua Rádio em Movimento**, com o logo local já existente.
O layout premium, volume, cores, logo e waveform permanecem iguais.

## Configuração e execução

JDK **17**, SDK **35**, Build Tools **35.0.0**, Wrapper **8.11.1** e Android Studio
Meerkat 2024.3.1 ou superior. Android mínimo API 26; reprodução STREAM exige internet.

```sh
./gradlew test testDebugUnitTest lintDebug assembleDebug -PplaybackMode=STREAM --max-workers=2
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

`app/build.gradle.kts` centraliza a URL padrão e gera `BuildConfig.RADIO_STREAM_URL`.
Para um endpoint futuro HTTPS, use `-PradioStreamUrl=https://radio.exemplo/alce.mp3`
ou a variável `RADIO_STREAM_URL`. URLs com credenciais/fragmentos são rejeitadas.
O único endpoint HTTP permitido na configuração é o provisório; a configuração
Android bloqueia cleartext global e libera somente o IP explicitamente, sem subdomínios.
Network Security Config restringe o host; a validação da URL também limita porta e caminho.
Uma futura configuração por tenant pode alimentar esta mesma composição, sem espalhar URLs.

`PlaybackMode.STREAM` é padrão. Para usar conscientemente a implementação anterior:

```sh
./gradlew assembleDebug -PplaybackMode=LOCAL_FALLBACK
# Biblioteca de assets opcional, só no fallback:
./gradlew assembleDebug -PplaybackMode=LOCAL_FALLBACK -PuseLocalMusic=true
```

O Manifest usa um placeholder e declara **um único serviço**: RadioService no STREAM
ou LocalFallbackRadioService no fallback. O MediaController conecta ao mesmo modo;
RadioApplication bloqueia inicialização dos providers locais no STREAM. Assets
music/** permanecem excluídos do APK padrão e não são apagados do workspace.

## Rádio ao vivo, buffer e recuperação

Play abre uma conexão nova no sinal atual; Pause pausa e encerra o carregamento,
descartando o buffer antigo. Retomar ou reabrir nunca restaura posição de podcast.
Player e sessão não são recriados a cada comando. Não existe cache de disco do
stream: reutilizar bytes de uma sessão anterior atrasaria a transmissão.

`LiveStreamConfiguration` centraliza buffer mínimo **10 s**, máximo **20 s**, início
**1,5 s** e rebuffer **5 s**; não usa o buffer de 90 s do fallback musical. A fonte
progressiva é ao vivo, sem duração falsa, seek ou navegação. Falhas transitórias são
recuperadas dentro do carregador Media3 com backoff limitado, sem encerrar a fonte
a cada três erros: isso mantém BUFFERING, foreground e wake locks durante a
recuperação. O Media3 consome primeiro o áudio em buffer antes de reabrir o sinal
ao vivo. Erros permanentes/fim do sinal abrem uma nova conexão com
backoff **1, 2, 4, 8, 16, 32 s**, limitado a 32 s. O contador só reinicia após reprodução
real. Sem rede, não há loops de requests; buffer audível continua até acabar. A volta
da rede recupera o sinal parado sem recriar o player; troca saudável não o reinicia.
Pause encerra o carregador e os retries; perda de foco é respeitada. Não há
healthcheck/polling extra. A verificação de carregamento usa blocos de 16 KiB
(aproximadamente 1 s a 128 kbit/s), menores que o buffer de início, e timeout de
leitura de 30 s para tolerar variações de rede sem desconectar prematuramente.
A quantidade real de áudio disponível depende também do envio do servidor.

MediaSession e o callback compartilhado mantêm somente Play/Pause e consultas,
sem Next/Previous/Seek/shuffle. Android Auto navega por uma única estação; Bluetooth,
headset, notificação e lock screen usam a mesma restrição. Audio Focus, noisy,
wake lock de rede e foreground de MediaLibraryService permanecem. O wrapper de
identidade repassa explicitamente todos os callbacks de estado: delegação Kotlin
`by listener` não encaminha métodos padrão Java de Player.Listener. Sem esse
repasse, o controlador da notificação podia permanecer com Play/Pause desatualizado
e deixar de promover o serviço a foreground durante a reprodução. A sessão é
registrada no serviço desde onCreate. Logs técnicos
somente DEBUG; a UI mostra apenas a identidade e animação conforme o estado.

## Validação e APK

O workflow existente **Android debug** usa Ubuntu/JDK 17/SDK 35, testa, executa lint,
assembleDebug e valida a assinatura e ausência de MP3. Gera somente STREAM.
No repositório pessoal: **Actions → Android debug → Run workflow → main**;
abra a execução e baixe **Artifacts → radio-embarcada-debug-apk**, que contém
**app-debug.apk**, retido por sete dias. APK: `app/build/outputs/apk/debug/app-debug.apk`.
MP3, RAR, APK e credenciais locais não são versionados.

Teste manual com **dois dispositivos**:

1. Instale o mesmo APK em A e B, abra Rádio Alce e pressione Play em ambos.
2. Compare áudio, música atual, passagem à próxima e blocos: devem vir do mesmo
   sinal. Alguns segundos de diferença de buffer são aceitáveis.
3. Pause A por alguns minutos enquanto B toca; retome A. A deve voltar ao sinal
   atual de B, não à posição em que pausou. Force Stop e reabertura têm o mesmo resultado.
4. Teste Wi-Fi → 4G/5G → Wi-Fi, perda de internet e retorno, servidor indisponível,
   segundo plano, tela apagada, chamadas, Bluetooth e Android Auto. Nenhuma falha
   pode iniciar a programação independente do fallback.
5. Confira somente Play/Pause e identidade fixa nos controles nativos, sem faixa/ICY.

Testes usam fontes/players simulados e Robolectric, sem depender do stream real.
A validação automática não substitui ouvir dois aparelhos ou testar o veículo.
Para regressão em segundo plano, teste 15–30 minutos com outro aplicativo aberto
e depois com tela apagada, tanto em Wi-Fi como em dados móveis. Confira que a
notificação permanece e que Pause interrompe o áudio. Se o problema persistir,
registre `adb logcat -s RadioDiagnostics ExoPlayerImpl` durante o travamento;
os logs DEBUG incluem estado, buffer e exigência de foreground, sem URLs ou secrets.

## Regras a migrar para o servidor

O radio.liq versionado atualmente transmite o catálogo aleatório; a implementação
completa de vinhetas, jingles, notícias e antirrepetição **não é realizada nesta tarefa**.
Próxima etapa central: pools remotos (hoje oito vinhetas/três jingles), uma inserção
por troca no padrão STATION_ID/STATION_ID/JINGLE, notícias a cada **30 minutos** com
intro, seis horas musicais/least-recently-played, preload e transições com peças
integrais. Os componentes/testes antigos abaixo permanecem como referência/fallback.
O fallback preserva seu intervalo anterior de notícias de 60 minutos; não executa
nenhuma dessas decisões no modo STREAM. Não há garantia de regras ausentes no servidor.

---

As seções seguintes descrevem **exclusivamente a arquitetura anterior preservada**;
não devem ser interpretadas como comportamento do build STREAM.

# Implementação anterior preservada — somente LOCAL_FALLBACK

Rádio Alce reproduz faixas individuais da programação, sem emissora externa. **RemoteMusicProvider é a fonte do fallback explícito**, não do build padrão STREAM. O APK padrão não contém MP3 e não usa `MUSIC_ARCHIVE_URL`, credenciais R2, Jamendo ou URLs assinadas.

Catálogo público do MVP: [music_catalog.json](https://pub-e38948fd737d4d969bb4e65eebed0249.r2.dev/music_catalog.json). O catálogo atual possui versão 1 e 77 itens MUSIC; esses números não são fixados no código. A configuração fica em `network/catalog/RemoteCatalogConfiguration.kt`.

Regras e peças da estação: [programming.json](https://pub-e38948fd737d4d969bb4e65eebed0249.r2.dev/programming.json), carregado pelo **RemoteProgrammingProvider**, separado do MusicProvider. A configuração publicada da estação `alce`, versão 4, possui **sete vinhetas e três jingles**. A regra corrigida desta fase é **uma peça por troca**, no ciclo **STATION_ID → STATION_ID → JINGLE**. O runtime usa o JSON remoto; fixtures existem somente em testes.

## Abrir e executar

- Android Studio Meerkat 2024.3.1 ou superior, compatível com AGP 8.9.2.
- JDK 17, SDK Platform 35, Build Tools 35.0.0; Gradle Wrapper 8.11.1.
- Android 8.0/API 26 ou superior. Internet necessária para a primeira obtenção do catálogo e áudio.

Abra a raiz no Android Studio, sincronize e execute `app` em debug. Configure `JAVA_HOME`/`ANDROID_HOME` ou `sdk.dir` no `local.properties` ignorado. No Windows, use `gradlew.bat`.

```sh
./gradlew test testDebugUnitTest lintDebug assembleDebug --warning-mode all --max-workers=2
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

A tela mantém Rádio Alce, empresa, AO VIVO, faixa atual, artista quando preenchido, Play/Pause e estado. O tenant continua em `app/src/main/assets/tenant.json`, separado do catálogo. Nenhum backend, autenticação, escolha de gênero, publicidade ou interface de gerenciamento foi acrescentado.

## Arquitetura

```text
RemoteMusicProvider + RemoteProgrammingProvider
→ AutomaticProgramming / QueueBuilder / ProgrammingSequencer
→ ProgramItem → ProgramPlayer → MediaSession → UI
```

| Parte | Responsabilidade |
| --- | --- |
| `network/catalog` | Configuração, HTTP limitado e parsing do JSON público para modelos internos. |
| `data/music/MusicProvider` | Contrato do catálogo, incluindo catálogo completo, revisão e suporte a versão salva. |
| `storage/FileMusicCatalog` | Último JSON válido, salvo atomicamente no `filesDir` privado. |
| `network/programming` / `data/programming` | Provider independente, validação das regras e conversão de vinhetas/jingles para modelos internos. |
| `storage/FileProgrammingConfiguration` | Último programming.json válido em arquivo privado separado, reutilizando a gravação atômica de JSON. |
| `model` | Track, ProgramItem, NowPlaying e estados; não dependem do JSON externo. |
| `programming` | Ciclos pseudoaleatórios completos, lotes de 20 e reposição com até três próximas faixas. |
| `player/ProgramPlayer` | Uma instância ExoPlayer, fontes progressivas, preload, buffer, cache e metadados. |
| `player/RadioService` | MediaLibraryService/MediaLibrarySession, coordenação da fila e controles externos. |
| `ui` | MediaController/ViewModel/Compose; não consulta API ou arquivos musicais. |

ProgramItem mantém MUSIC, STATION_ID, JINGLE, ADVERTISEMENT e ANNOUNCEMENT. Apenas MUSIC é aceito pelo catálogo musical; STATION_ID/JINGLE vêm do provider de programação. Publicidade continua fora desta etapa. Conforme a correção da regra, não há crossfade/overlap: os 15 segundos são somente a saída da música antes da peça.

## Catálogo e fila

O parser valida station/version/items, aceita MUSIC com ID/título/URL HTTPS válidos, ignora itens inválidos e deduplica IDs. Catálogo vazio ou malformado é recusado e não substitui a versão salva. Artista vazio permanece vazio na sessão e é omitido na UI; cada artista desconhecido recebe identidade própria para a fila continuar.

A primeira consulta ocorre ao iniciar a programação. O provider mantém o catálogo em memória e atualiza após **6 horas**; uma nova instância tenta obter a versão atual. Falhas de atualização respeitam intervalo mínimo de **30 segundos**, retornando a última versão válida em memória/disco. Timeouts de conexão/leitura: **10 segundos** cada; resposta limitada a **2 MiB**. Não há consulta a cada frame nem download de MP3 pelo provider.

O último catálogo válido fica em `filesDir/music_catalog.json`, fora do cache de áudio. A gravação usa arquivo temporário e troca atômica; respostas inválidas não apagam dados válidos. Sem catálogo salvo e com falha de rede, a UI mostra **Programação indisponível** e o serviço agenda novas tentativas controladas. URLs e erros internos não aparecem na UI.

A biblioteca completa prioriza faixas inéditas, com histórico persistido e janela de seis horas antes de repetir. A exceção por esgotamento utiliza o grupo de músicas mais antigo; detalhes na seção de repetição musical abaixo. Itens ainda pendentes não são duplicados, e a fronteira entre lotes/ciclos evita repetição imediata. Artistas conhecidos têm janela de 90 minutos, com exceção apenas quando os demais artistas elegíveis se esgotam. Versão/itens alterados atualizam a biblioteca lógica na próxima reposição; a faixa atual e sua sessão permanecem.

O ExoPlayer avança naturalmente entre fontes. A fila é reabastecida durante a reprodução; quando termina, a programação continua no mesmo player. O início offline com catálogo salvo prioriza itens que possuem trecho inicial no cache. Isso permite consumir conteúdo preparado, mas não garante reprodução completa de um trecho parcialmente armazenado.

## Vinhetas e jingles da programação remota

`network/programming/RemoteProgrammingConfiguration.kt` centraliza a URL e os limites. O parser valida `stationId`, `version` e regras, aceitando `alternateInsertionTypes` (versão 3) e o campo legado `alternateStationIdAndJingle`. `songsBetweenInsertions` é preservado para compatibilidade do JSON, mas **não significa esperar três músicas** nesta fase. O provider aceita somente a estação do tenant ativo. Itens inválidos, sem URL HTTPS ou com tipo incorreto são ignorados; listas ausentes/vazias são permitidas. O player recebe somente ProgramItem e não conhece JSON, regras ou URLs específicas das peças.

Em **toda troca**, a sequência é **MUSIC → STATION_ID → MUSIC → STATION_ID → MUSIC → JINGLE → MUSIC**, repetindo. O jingle **substitui** a vinheta na terceira troca; jamais há duas peças no mesmo intervalo. `ProgrammingRules.DEFAULT_INSERTION_PATTERN` centraliza `[STATION_ID, STATION_ID, JINGLE]`. Um `rules.insertionPattern` explícito no JSON pode substituir o padrão, com tipos validados. O contador avança por inserções, persiste entre lotes/ciclos e não muda no Pause.

Vinhetas e jingles possuem **shuffle-bags independentes**, alimentados exclusivamente pelos itens do JSON remoto: todas as sete vinhetas e todos os três jingles são utilizados uma vez em seus respectivos bags antes de reembaralhar. A fronteira evita repetir a mesma peça quando existem alternativas. Mudanças no conjunto de IDs atualizam o bag. Toda nova `version` invalida imediatamente os dois bags pendentes no próximo agendamento, sem esperar terminar o bag antigo; preserva a última seleção de cada tipo para proteger a fronteira e mantém a posição do ciclo. Metadados atualizados na mesma versão não reiniciam o bag. Não existe limite de sete: oito, dez ou doze itens são aceitos automaticamente. Não há URLs de peças hardcoded no player. Se faltar um tipo, o disponível mantém uma única peça por troca; ambos ausentes ou programação indisponível sem cache deixam somente músicas.
Cada inserção recebe ID de ocorrência único na fila. `contentId` identifica o áudio original, compartilhando cache entre repetições da mesma vinheta/jingle; a URL continua participando da chave para invalidar áudio alterado. As peças usam a mesma fonte progressiva, cache LRU, preload, retry e sessão das músicas. Não são baixadas em bloco nem empacotadas no APK. O fim natural da peça inicia a próxima música sem recriar ExoPlayer ou MediaSession.

O último JSON válido fica em `filesDir/programming.json`. Falhas HTTP/parsing/gravação não interrompem músicas nem descartam uma configuração válida; sem versão salva, a rádio toca somente músicas. As consultas acontecem ao montar novos lotes, com refresh mínimo de **15 minutos** e nova tentativa após falha elegível a partir de **30 segundos**, na próxima montagem. Conexão/leitura têm timeout de **5 segundos** cada e a resposta é limitada a **256 KiB**. Atualizações valem para lotes futuros; itens já preparados não são reordenados e a música atual não é interrompida. Mudança no padrão explícito inicia um novo ciclo no próximo lote; o campo legado de intervalo não altera a frequência corrigida.

DEBUG registra versão, contagens reais dos pools, resumo de IDs (até 12), `StationIdBag remaining`/`JingleBag remaining`, seleção e `Fila: troca 1/3`, `2/3`, `3/3`, inserção selecionada e falhas sanitizadas, além do próximo ProgramItem nas transições. Esses contadores indicam itens agendados, não posição de áudio; logs não aparecem em release. O modo opt-in de assets continua exclusivamente local e não consulta programming.json.

Pause preserva fila, bags, posição do áudio e ciclo. Ao recriar o serviço após liberar a fila, uma nova sessão começa na posição 1 (STATION_ID).

## Política de transições

`TransitionPolicy` decide a passagem por tipo; `AudioTransitionController` aplica apenas envelopes de volume ao **mesmo ExoPlayer**, sem seek, stop, players auxiliares ou timers que avancem faixas. O ProgrammingEngine continua decidindo o conteúdo.

| Passagem | Comportamento |
| --- | --- |
| MUSIC → STATION_ID/JINGLE/peça curta | Saída smoothstep nos **últimos 15.000 ms** da música; ela termina naturalmente. A peça entra com rampa de **150 ms**, partindo de 25% de seu ganho, sem herdar o volume reduzido da música. |
| Peça curta → MUSIC | Peça toca integralmente; avanço natural do Media3, sem atraso programado/overlap; música entra com rampa de **100 ms**. |
| MUSIC → MUSIC, se peças indisponíveis | Avanço natural sem overlap. |
| Peça curta → peça curta | Proibido pela fila e pela validação do player. |

`player/TransitionPolicy.kt` centraliza tempos e ganhos: MUSIC **0,90**; STATION_ID, JINGLE, ADVERTISEMENT e ANNOUNCEMENT **0,80**. A saída musical mantém piso de **10% do ganho musical** (0,09), inclusive nos últimos milissegundos, evitando um trecho artificialmente mudo antes do fim. Não há soma de áudios nem crossfade de 15 segundos sobre peças. Essas peças não recebem fade-out antecipado: uma peça de 8, 12 ou 20 segundos toca até o fim. Ganhos fixos não substituem normalização/masterização do catálogo.

O envelope segue **a posição real de reprodução**, congelando em Pause/rebuffer e retomando na mesma posição. Duração desconhecida não provoca corte nem avanço antecipado. DEBUG registra tipo, conteúdo, duração real conhecida, fade de 15 s, conclusão por avanço natural, callback real de preload e esperas de buffering observadas. Logs não afirmam gap acústico zero apenas por um evento de timeline.

Sem silêncio perceptível depende do áudio original, codec, dispositivo e dados efetivamente preparados; o código não acrescenta intervalo e não aguarda um download deliberadamente após a peça. Validar auditivamente o APK em aparelho continua necessário.

## Controles externos da rádio

`player/RadioSessionCallback.kt`, usado pelo callback da MediaLibrarySession em RadioService,
restringe `availablePlayerCommands` para todos os controladores, incluindo o controlador da
notificação. A sessão oferece Play/Pause e consultas de estado/metadados, sem anterior/próxima,
seek, avanço/retrocesso, alteração da fila, shuffle, repeat ou velocidade. A preparação e a
seleção da estação pela biblioteca permanecem disponíveis; RadioService aceita somente o ID
da estação e conserva a programação e posição existentes.

No Media3 1.6.1, os comandos do controlador da notificação também definem as ações da sessão
nativa do Android. Isso limita notificação, tela bloqueada, Quick Settings, Bluetooth e Android
Auto. Comandos de salto recebidos são ignorados pelo Media3. Nenhum callback depreciado é usado
para autorizar comandos. O ExoPlayer interno permanece com seus comandos completos: fim natural,
recuperação de uma faixa e futuras inserções de ProgramItem continuam na mesma sessão.

## Buffer, preload e cache

Configurações centralizadas em `player/PlaybackConfiguration.kt`:

| Configuração remota | Valor |
| --- | --- |
| Mínimo do DefaultLoadControl | 30 s |
| Histerese do buffer estável | 45–60 s |
| Teto do DefaultLoadControl | 90 s |
| Início de reprodução | 1,5 s |
| Retomada após rebuffer | 3 s |
| Preload da próxima faixa | 45 s |
| Preload da segunda próxima | 45 s quando sucede peça curta; 15 s no fallback só musical |
| Cache LRU | **300 MiB / 314.572.800 bytes** |
| Descarte por idade na próxima inicialização | 24 h |

RadioLoadControl preserva os métodos encaminhados explicitamente ao DefaultLoadControl, incluindo back buffer e lifecycle, evitando o crash corrigido anteriormente. A histerese constrói o buffer progressivamente sem esperar dezenas de segundos para iniciar.

O preload usa a API oficial de **playlist do ExoPlayer 1.6.1**, `ExoPlayer.PreloadConfiguration`, na mesma instância/timeline. O DefaultPreloadManager independente ignora fontes já usadas pela timeline, portanto não era prova de que as peças estivessem pré-carregadas. Não se espera STATE_ENDED para selecionar, registrar ou preparar uma inserção: os ProgramItems do lote inteiro entram antes do início.

RadioLoadControl prioriza o início da música e permite preload antecipado após **5 s de buffer real atual**, ou quando o período já está completamente carregado. Limita os alvos aos dois próximos itens e preserva os tempos de buffer remoto existentes. A configuração permanece habilitada durante Pause/perda de rede, conservando o conteúdo preparado. O Media3 prepara o próximo período da playlist além do período em carregamento; assim a peça e, quando o carregamento permite, a música subsequente ficam preparadas antecipadamente. Não há player auxiliar, download de biblioteca nem prepare/stop/seek no handoff natural.

`PlaybackReadiness` observa MediaPeriods reais: início de preparação, callback onPrepared, seleção de trilha e posição de áudio em buffer. A posição de buffer só é consultada **depois de onPrepared**: durante a descoberta inicial de trilhas, ProgressiveMediaPeriod ainda não permite essa consulta. Antes disso, o observador mantém buffer não comprovado e `ready=false`, sem interromper o carregamento. Testes com extração progressiva real cobrem esse ciclo, pausa e avanço automático, sem internet ou biblioteca privada. `ready` requer **período preparado + trilha selecionada + ao menos 1,5 s de áudio disponível (ou fim já totalmente carregado)**. URL, MediaItem, entrada na timeline e formato conhecido, isoladamente, não valem como ready. Ao liberar o período, esse estado é removido. DEBUG mostra a presença na timeline, estados reais, buffer, 15 s/500 ms restantes e estimativa de atraso do evento do player. Essa estimativa não mede o silêncio acústico existente dentro de um MP3. Falhas do player registram código e classes das causas em DEBUG, sem URLs; ao recuperar a reprodução, a mensagem de erro é limpa.

A extração MP3 padrão e o AudioSink do Media3 continuam processando encoder delay/padding Xing/LAME. A remoção **autorizada** do silêncio digital inicial é feita por `InsertSilenceProcessor`, depois desse trimming padrão, na cadeia PCM do mesmo AudioSink. Ele descarta somente frames 16-bit cujos canais sejam todos exatamente zero antes da primeira amostra não zero de STATION_ID/JINGLE. A primeira amostra audível, pausas internas e final são preservados; MUSIC e outros tipos não são alterados. Não usa limiar de volume, nomes de arquivos, durações fixas, análise pesada, download adicional ou alteração no R2. Formatos não suportados são preservados.

`RadioRenderersFactory` identifica o tipo pela timeline no thread de reprodução e ativa a política na mudança real do stream de saída; não depende de um callback tardio da UI. `InsertAudioProcessorChain` informa os frames removidos ao relógio oficial do sink, evitando acrescentar uma espera equivalente no final da peça. A rampa de entrada usa a posição descontando o prefixo removido. Pause não reinicia o detector; recuperação no meio de uma peça não remove pausas internas. DEBUG registra a duração realmente removida por ocorrência. Nenhum conteúdo audível é encurtado e não há micro-sobreposição ou early-handoff fixo (0 ms). O total de reprodução fica menor apenas pelo silêncio inicial descartado. A duração exibida continua sendo a duração original da fonte.

SimpleCache + LeastRecentlyUsedCacheEvictor usam o `cacheDir` privado e StandaloneDatabaseProvider. Player/preload compartilham dados e removem os mais antigos por LRU. Chaves incluem ID e hash da URL, evitando reutilizar áudio antigo quando a URL muda com o mesmo ID. O Android pode limpar o cache; após 24 h, uma nova inicialização descarta o cache anterior. Não existe downloader, biblioteca permanente ou opção de download offline.

Queda/troca de rede não limpa timeline/buffer e não recria o player. Áudio disponível continua tocando. Carregamento transitório usa backoff **1, 2, 4, 8, 16, até 32 s**; erros definitivos de URL/formato têm recuperação limitada. A sessão e a posição permanecem durante Wi-Fi/dados móveis. Retomada imperceptível depende do conteúdo realmente preparado e do tempo do retry.

Estados distinguem **Carregando programação**, **Conectando**, **Ao vivo**, **Pausado**, **Reconectando**, **Programação indisponível** e o estado existente **Sem conexão**, quando o áudio preparado esgota. Uma falha de reposição do catálogo não substitui Ao vivo enquanto há reprodução.

## Providers preservados

LocalAssetMusicProvider permanece como fallback **opt-in de desenvolvimento**:

```sh
./gradlew assembleDebug -PplaybackMode=LOCAL_FALLBACK -PuseLocalMusic=true
```

Coloque MP3 em `app/src/main/assets/music/` ou qualquer subpasta, como MPB/rock80/pop. O catálogo local lê título/artista/duração/capa embutida segura, usa nomes como fallback, pula áudio defeituoso e funciona sem rede. Buffer local: mínimo 1 s, máximo 5 s, início 250 ms, rebuffer 500 ms; preload de 3 s / 1 s. UI não acessa arquivos.

O build padrão usa uma tarefa Sync para copiar somente assets não musicais ao diretório gerado; `music/**` fica excluído. **Os MP3 originais não são apagados, movidos ou alterados.** MP3/RAR/APK continuam ignorados pelo Git. Um build opt-in local contém a biblioteca e serve apenas a testes autorizados.

JamendoMusicProvider permanece implementado e inativo. Para uso futuro, mude a composição em RadioApplication e configure `jamendo.clientId` no local.properties ou `JAMENDO_CLIENT_ID` no ambiente; não versione valores. A fila e o player continuam usando os mesmos contratos. Nenhuma licença do MVP é presumida válida para uso comercial futuro.

## Blocos automáticos de notícias

`RemoteNewsProvider` usa exclusivamente o RSS **Radioagência Nacional / Últimas Notícias**:
`https://agenciabrasil.ebc.com.br/radioagencia-nacional/rss/ultimasnoticias/feed.xml`.
O parser converte título, GUID, data, categoria, duração (inclusive `hms` do feed real) e enclosure para `NewsItem`. Sem enclosure, o resolver lê a página oficial e identifica MP3 em `audio/source`, links de download e `data-source`, em ordem de documento. Links relacionados não têm prioridade sobre o áudio principal. Somente HTTPS em `ebc.com.br`/subdomínios é aceito; disponibilidade é verificada por HEAD (ou um byte via Range quando HEAD não é permitido). Links quebrados são ignorados em favor do próximo item. Redirecionamentos são revalidados também no DataSource de notícias antes de ler/cachear áudio. Não há serviço intermediário nem download permanente.

`NewsConfiguration` centraliza **60 minutos ativos**, idade máxima **24 horas**, duração preferida **30 s–4 min**, refresh do RSS **15 min** e nova tentativa **5 min**. Duração desconhecida é permitida; Media3 determina duração real na reprodução. `NewsScheduler` usa tempo monotônico e conta apenas `isPlaying`: pausa, perda de foco e buffering não avançam o relógio. O primeiro boundary cuja projeção alcança o intervalo é reservado antecipadamente, quando há um candidato elegível. A música/peça atual sempre termina normalmente; não há seek, stop ou prepare nesse handoff.

O bloco é **NEWS_INTRO → NEWS_DROP → MUSIC**. A intro fixa vem de `https://pub-e38948fd737d4d969bb4e65eebed0249.r2.dev/Vinheta_Noticias_Masterizada.mp3`. `NewsQueuePlanner` ocupa um único intervalo e adia a vinheta/jingle normal já reservado, mantendo sua ordem e o ciclo **STATION_ID → STATION_ID → JINGLE**, inclusive entre lotes. Nenhuma peça normal entra dentro do bloco. Se o intervalo ficar due durante uma peça institucional, ela termina e o bloco pode ocupar a fronteira seguinte.

O Media3 usa a mesma instância de player/cache LRU: preload oficial de **45 s da intro**, **45 s da notícia** e, quando a timeline permitir, **15 s da música seguinte**; durante a intro a preparação da próxima música cresce pelo pipeline normal. `ready` continua exigindo MediaPeriod preparado, trilha selecionada e áudio em buffer, sem flags artificiais. Até 2 s antes da fronteira, se intro/drop não estiverem realmente prontos ou a notícia tiver envelhecido, a fila normal é restaurada e o bloco é adiado. Falha do RSS nunca agenda intro sozinha. Falhas posteriores de áudio editorial têm retry limitado; a rádio retorna à música seguinte em caso de erro. A disponibilidade na rede não garante ausência de buffering posterior.

MUSIC mantém saída de 15 s; intro/notícia tocam integralmente, sem crossfade ou trimming de silêncio sobre NEWS_DROP. NEWS_INTRO → NEWS_DROP é a exceção explícita de conteúdos consecutivos na política de transição; vinhetas/jingles normais continuam separados por música. Ganhos de notícias ficam em `TransitionConfiguration`. Metadados da matéria usam seu título e **Radioagência Nacional** como artista/fonte; Play/Pause, bloqueio de seek/next/previous e integração MediaSession/Android Auto permanecem.

`filesDir/news_history.json` guarda atomicamente `lastNewsPlayedAt`, os últimos **100 IDs** e tempo ativo acumulado. A notícia é registrada ao começar efetivamente a tocar; reservar/preparar não consome o histórico. Reinício não dispara repetição imediata. O catálogo de notícias é consultado antes do vencimento do relógio; todos os candidatos são ordenados por publicação e filtrados pelo histórico/idade/duração. Falhas mantêm a rádio musical e tentam novamente sem polling agressivo.

**Teste acelerado somente DEBUG:** `./gradlew assembleDebug -PplaybackMode=LOCAL_FALLBACK -PnewsIntervalDebugMinutes=3` (também aceita `5`; `0` usa 60 minutos). O workflow padrão gera somente STREAM e não executa notícias locais. `BuildConfig.NEWS_INTERVAL_DEBUG` é zero em release; o intervalo de produção nunca muda. O bloco aguarda a faixa terminar, portanto o teste pode ultrapassar esses minutos. Não há botão de pular. Pause durante a intro e o drop, retome, confira crédito/metadados, fim integral e próxima música; depois confirme que a inserção normal adiada ainda é a próxima. Teste feed/áudio indisponível e confira continuidade musical. Logs DEBUG mostram refresh, elegibilidade, seleção, relógio e readiness real. O gap registrado é estimativa do scheduler, não medição acústica de zero samples; continuidade audível, Android Auto e Bluetooth precisam de validação em aparelho.

## GitHub Actions e APK

O workflow existente **Android debug**, `.github/workflows/android-debug.yml`, é o ambiente oficial de validação. Usa Ubuntu, Temurin **JDK 17**, SDK 35, validação do Wrapper e cache de Gradle. Executa **test/testDebugUnitTest → lintDebug → assembleDebug → verificação da assinatura/tamanho/ausência de MP3 → upload**. Não baixa RAR, não extrai músicas e não lê `MUSIC_ARCHIVE_URL`. O secret pode permanecer no repositório, sem ser utilizado.

A cada push em main ou **GitHub → Actions → Android debug → Run workflow → main**, o APK fica em **Artifacts → radio-embarcada-debug-apk**, contendo **app-debug.apk**, por sete dias. Caminho: `app/build/outputs/apk/debug/app-debug.apk`. O workflow falha se houver testes/lint/build com erro ou qualquer MP3 empacotado.

A versão anterior com biblioteca tinha **771.352.284 bytes / 735,6 MiB**. O tamanho atual é registrado no resumo/log de cada execução. APK, músicas e arquivos locais não são versionados.

## Teste manual e validação

1. Instale o APK remoto, abra Rádio Alce conectado e pressione Play. Confira música e avanço automático; artista vazio não deve aparecer.
   A cada troca deve haver uma peça: nas duas primeiras, vinheta; na terceira, somente jingle; repetir. Confira saída suave nos últimos 15 s da música, entrada curta, peça integral e próxima música imediata. Escute quatorze vinhetas e seis jingles: cada bag deve percorrer respectivamente sete/três conteúdos sem repetição imediata. Nenhuma peça pode ser cortada nem seguida de outra peça.
2. Deixe tocar por 30–60 s para abastecer buffer/preload. Desligue Wi-Fi e dados móveis: o áudio preparado deve continuar até esgotar.
3. Recupere rede antes de esgotar e confira continuidade de posição, música e sessão. Repita Wi-Fi → dados móveis e retorno.
4. Após ouvir faixas e salvar catálogo, reabra temporariamente offline. Trechos já armazenados podem tocar; conteúdo não armazenado exige rede. Instalação nova offline mostra Programação indisponível sem crash.
5. Coloque o app em segundo plano e confira que notificação/player do sistema oferecem somente Play/Pause, sem anterior/próxima ou seek. Bloqueie a tela e repita. Via Bluetooth/Android Auto, confira Play/Pause e metadados; comandos NEXT/PREVIOUS não devem mudar a faixa. Aguarde o fim natural de uma música e confira o avanço automático. Teste também tela apagada, chamadas e Audio Focus. A apresentação exata depende do Android/veículo e precisa de validação em dispositivo.
6. Confira logs de debug com `adb logcat -s RadioDiagnostics`; diagnósticos não aparecem em release/UI.

Os testes JVM não dependem de internet nem dos 77 MP3 reais. Cobrem parsing/validação, catálogo de 77 itens simulado, cache de JSON, fallback offline, refresh/versionamento/backoff, ciclos aleatórios, ProgramItem, estados, buffer e chaves do cache. Também preservam os testes de assets/Jamendo e lifecycle do LoadControl. Testes da sessão usam Robolectric e as ferramentas oficiais de teste do Media3 (somente em testImplementation), com ExoPlayer real e fontes/clock simulados: permissões de controladores comuns e da notificação, Play/Pause, bloqueio de navegação, metadados, avanço interno, padrão 1-2-3, bags independentes, preload real de playlist, buffer/seleção de áudio antes do fim da música e após Pause, preload da música após a peça, envelopes de ganho, Pause/Play e fim natural integral de peças de 8/12/20 s através do ExoPlayer real simulado. Os scripts antigos de preparação da biblioteca ficam preservados, fora do workflow atual; seus testes podem ser executados com `python3 -m unittest discover -s scripts -p 'test_*.py' -v`.

Lint mantém visíveis os avisos de dependências, serviço exportado para controladores, HTTP herdado e target SDK 35. Manifest, permissões de mídia, MediaSession/MediaLibraryService, Audio Focus e estrutura Android Auto permanecem; a validação automática não substitui teste audível em aparelho. Nenhuma dependência de produção nova foi adicionada.

### Tela premium da Rádio Alce

A tela principal usa o logo oficial transparente, fundo preto, detalhes dourados,
badge AO VIVO, “Sua Rádio em Movimento”, Play/Pause e volume lateral. Metadados continuam
na MediaSession, mas não são apresentados nesta tela. A UI não altera programação,
notícias, providers, cache, transições ou controles externos.

`ui/RadioPlayerScreen.kt` separa logo, badge, tagline e botão;
`ui/theme/RadioTheme.kt` centraliza a paleta. `WaveformVisualizer.kt` desenha 41
barras procedurais a 20 Hz apenas durante reprodução e com a tela em primeiro
plano, sem analisar áudio ou solicitar permissões. Quando pausada, fica estática.
O layout adapta logo, espaços e botão à área disponível, respeitando os insets.

Os testes Compose/Robolectric verificam acessibilidade de Play/Pause, conteúdo
visível, ausência de controles de navegação/metadados/cards, waveform e limites
em telas de 320 × 568 e 480 × 960 dp. Capturas de conferência ficam em
`app/build/reports/ui/`. Execute `./gradlew test testDebugUnitTest lintDebug assembleDebug`.
O workflow **Android debug** existente disponibiliza **app-debug.apk** no Artifact
**radio-embarcada-debug-apk**. Para validação no aparelho, confira o logo e o botão
sem rolagem, pause/retome, coloque em segundo plano e confirme que o áudio e os
controles de mídia continuam funcionando.

### Volume, identidade e repetição musical

O aplicativo aparece como **Rádio Alce**, com ícone adaptativo usando o logo oficial.
Os dois botões laterais diminuem/aumentam o volume de mídia do Android em um passo,
inclusive na saída Bluetooth quando suportado pelo aparelho. Não alteram o ganho
interno dos fades, nem adicionam Next/Previous/Seek aos controles da sessão.

O player nativo, notificação e tela bloqueada recebem o título fixo **Rádio Alce - AO VIVO**
e a arte quadrada `drawable-nodpi/radio_alce_media.png` (1254 × 1254),
com o logo central ocupando aproximadamente 38% da altura e 42% da largura.
O respiro vertical de aproximadamente 31% por lado preserva o desenho completo
em uma simulação de recorte central horizontal até 2,4:1. O ícone adaptativo continua usando
`radio_alce_brand.jpg`; a imagem e o layout principal permanecem separados.
A arte é um recurso local carregável pelo Media3 sem internet; o Android decide como
renderizá-la no fundo/cartão do sistema. Capas fornecidas pelo catálogo ou embutidas
nos MP3 não são encaminhadas à sessão. Títulos/artistas continuam nos ProgramItems
internos para a programação e anti-repetição; o crédito da fonte das notícias permanece.
O extractor Media3 desabilita metadados ID3 de apresentação, preservando a leitura
de delay/padding gapless e os créditos da fonte das notícias.

Não existe dimensão universal em pixels para o cartão horizontal nativo. A
[documentação Android](https://developer.android.com/media/implement/surfaces/mobile)
define a entrega da arte via metadados, enquanto o SystemUI/fabricante determina
o tamanho, escala, sobreposição de controles e recorte do painel. A dimensão
1254 × 1254 é uma escolha deste asset, não uma exigência do Android. A margem
reduz cortes, mas precisa ser conferida no aparelho, especialmente em cartões
mais largos que 2,4:1. A imagem ficará menor em superfícies quadradas, como Auto.
O teste `nativeArtworkKeepsWholeLogoInsideHorizontalNotificationCrop` verifica
a área visível e gera `app/build/reports/ui/native-artwork-2.4-to-1.png`.

A janela de repetição é `ProgrammingConfiguration.MUSIC_REPEAT_BLOCK_WINDOW` (**6 h**).
`PlaybackHistoryRepository` grava um checkpoint JSON privado por tenant em
`filesDir/music_history_<clientId>.json`: timestamps por faixa e artista, última
faixa iniciada e os primeiros cinco IDs da abertura anterior. Não salva a fila.
A gravação sincroniza o arquivo e substitui o checkpoint atomicamente, durante a
reprodução, sem depender de `onDestroy()`. O formato anterior é migrado preservando
seus timestamps. Apenas MUSIC realmente iniciada pelo player é registrada;
preload e agendamento são reservas em memória, nunca execuções persistidas.

Ao iniciar uma sessão, o histórico é recarregado e reconciliado com o catálogo
completo: IDs removidos são descartados, músicas novas ficam elegíveis. Retenção
centralizada de **48 h**, até **500 entradas** por mapa; a última faixa permanece
como proteção de fronteira enquanto existir no catálogo. Pause não apaga histórico
nem prolonga o timestamp de uma mesma execução.

A seleção tenta primeiro a janela de 6 h. Somente se não houver elegíveis, relaxa
para **3 h**, **90 min** e finalmente **0**, priorizando o grupo menos recentemente
usado. Nunca preenche um lote com faixas bloqueadas apenas para alcançar 20 itens.
Faixas inéditas têm prioridade; depois são embaralhadas as opções mais antigas,
respeitando também a restrição de artista. `Random.Default` gera uma nova ordem,
sem seed fixa em produção. A primeira faixa não pode ser a última da sessão
anterior (exceto catálogo com uma única música). A abertura anterior é evitada
no primeiro ponto em que houver alternativas elegíveis, sem restaurar uma playlist.

Para conferir no aparelho DEBUG, acompanhe `adb logcat -s RadioDiagnostics`: aparecem
histórico carregado, última faixa, elegíveis/bloqueadas, relaxamentos e primeiros IDs.
Deixe algumas músicas começarem, execute `adb shell am force-stop br.com.radioembarcada`,
reabra pelo ícone e pressione Play; compare os IDs com a sessão anterior. Repita
após fechar pelo gesto e reiniciar o dispositivo. Não desinstale nem limpe os dados:
essas ações apagam intencionalmente o armazenamento privado do Android. Os testes
simulam descarte/reinstanciação sem callback de encerramento; Force Stop, reboot e
renderização da arte em diferentes aparelhos ainda requerem conferência manual.

O padrão STATION_ID/STATION_ID/JINGLE, seus shuffle-bags, fades, preload e blocos de
notícias permanecem. Nenhuma notícia, vinheta ou jingle consome o histórico musical.

A janela por artista é `ProgrammingConfiguration.ARTIST_REPEAT_INTERVAL_MS` (**90 min**).
A seleção considera o histórico persistido e as reservas de cada música da fila,
inclusive dentro do mesmo lote. A restrição de seis horas por faixa continua tendo
prioridade: entre suas opções elegíveis, são escolhidos artistas fora dos 90 minutos.
Se nenhum restar, a exceção prioriza o artista há mais tempo sem seleção. Nomes são
normalizados sem diferenciar maiúsculas/minúsculas e espaços nas bordas; arquivos
sem artista identificável não são agrupados como um artista fictício. O catálogo
precisa fornecer artistas corretos para que essa proteção possa ser aplicada.
Vinhetas, jingles e notícias não consomem o histórico de artistas.

### Atualização visual e biblioteca — outubro de 2026

O player usa duas apresentações do logo Rádio Alce: `radio_alce_logo.png`,
transparente e com enquadramento próximo para ficar maior na tela principal,
e `radio_alce_media.png`, com amplo respiro para o player nativo horizontal.
A tela usa `ContentScale.Fit`, dimensões adaptativas e limite de largura de 420 dp.
O ícone do aplicativo permanece separado. A reprodução e os controles não foram alterados.

O workflow existente `Sincronizar catálogo R2` foi executado após a limpeza da
biblioteca: `music_catalog.json` passou para a versão 4, com 46 músicas (28 entradas
removidas). Ele usa a listagem real de objetos `music/`, preserva IDs/metadados e
incrementa a versão. Após novas exclusões no bucket, executar esse mesmo workflow.
O servidor consulta o catálogo a cada 60 segundos; itens já preparados podem
terminar antes de a nova seleção refletir a biblioteca atual. Atualizar o catálogo
não exige novo APK ou alterações em `programming.json`.

### Inclusão das vinhetas Nova 3, 4 e 5

No workflow existente **Sincronizar catálogo R2**, selecionar `operation=programming`
para mesclar `scripts/station-id-additions.json` no `programming.json` atual do bucket.
O job verifica os três objetos MP3, preserva regras/jingles/campos desconhecidos,
recusa conflitos de ID/URL, incrementa a versão somente quando necessário e salva
um Artifact `programming-backup` por 30 dias antes da publicação. Reexecutar não
insere duplicatas. O modo padrão `music` continua sincronizando somente músicas.
As três inclusões expandem a configuração atual de 8 para 11 STATION_ID; as 3 JINGLE
permanecem. O servidor já faz refresh da programação sem novo APK.
A fixture histórica v4 permanece com sete vinhetas; a expansão publicada é testada
separadamente por `programming-v6.json`.

A arte nativa agora usa PNG sem perdas e logo cerca de 34% maior na altura, mantendo
margem compatível com o cartão de aproximadamente 2,4:1 mostrado no aparelho.
O sistema pode reduzir a resolução e aplicar escurecimento; validar a nitidez no
celular após instalar o novo APK. Não há mudança de layout interno ou playback.

### Inclusão dos spots como jingles

Os spots Bifão e Salão Flack foram autorizados como `JINGLE` e estão declarados em
`scripts/jingle-additions.json`. No workflow **Sincronizar catálogo R2**, usar
`operation=jingles`: valida a existência dos MP3, guarda backup da configuração
remota e acrescenta os itens ao pool `jingles`, preservando vinhetas e regras.
O merge é idempotente e incrementa `version` somente quando há alteração.
Os spots participam do shuffle-bag de jingles já existente; não criam um novo
intervalo publicitário nem alteram o ciclo STATION_ID / STATION_ID / JINGLE.

Para substituições autorizadas, o manifesto pode declarar `replacesUrl` com a URL
anterior exata. O merge troca somente a URL do mesmo ID/tipo/título, falha se a
referência remota divergir e não publica esse campo auxiliar. O Spot Bifão passou
para `Spot_Bifao-Certo.mp3`; a URL nova também renova a chave do cache de áudio.
