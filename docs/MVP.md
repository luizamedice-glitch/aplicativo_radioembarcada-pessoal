# MVP — Rádio Embarcada

## Arquitetura ativa — stream central autorizado

O build padrão agora usa PlaybackMode.STREAM: R2 → Liquidsoap → Icecast →
stream único → APK/ExoPlayer/MediaLibraryService. URL provisória centralizada via
BuildConfig.RADIO_STREAM_URL; HTTP restrito ao IP autorizado, migrar para domínio HTTPS.
RadioService não acessa providers, programação, notícias ou histórico locais.
Play/reconexão reabre o sinal atual; Pause fecha a fonte sem recriar player/sessão.
Sem cache de disco de stream; buffer 10–20 s, início 1,5 s, rebuffer 5 s, retry/backoff até 32 s.
Falhas transitórias permanecem no carregador Media3 (BUFFERING/foreground/wake
locks), sem término forçado após três falhas. Verificações a cada 16 KiB e timeout
de leitura de 30 s; Pause encerra a fonte. Diagnóstico técnico somente DEBUG.
Controles externos somente Play/Pause, metadados fixos e layout existente preservados.
O wrapper de identidade encaminha explicitamente callbacks de Player.Listener,
incluindo playWhenReady/playbackState, para manter o controlador da notificação
e o foreground sincronizados. Delegação Kotlin de métodos padrão Java é evitada.

A implementação anterior integral está em LocalFallbackRadioService, disponível
somente por build LOCAL_FALLBACK explícito, sem troca automática. Manifest/Controller
selecionam um único serviço e RadioApplication impede programação local no STREAM.
Os tópicos históricos abaixo descrevem este fallback. O servidor agora implementa
pools dinâmicos de vinhetas/jingles, vinheta institucional em toda fronteira normal e jingle por relógio no máximo uma vez por hora, notícias de
4 h, histórico SQLite de 6 h, cache/preload local e fade exclusivo de MUSIC.
Hora FreeTTS opcional usa São Paulo e é omitida se o boundary atrasar mais de 60 s.
Deploy/rollback pela EC2 Instance Connect: server/radio-alce/README.md. O fallback mantém
as regras antigas, incluindo notícias de 60 min.

Origin/workflows/Artifacts/push são exclusivamente do repositório pessoal
luizamedice-glitch/aplicativo_radioembarcada-pessoal; antigo somente upstream histórico.


## Atualização autorizada — catálogo remoto R2

A fonte ativa nesta fase é RemoteMusicProvider: catálogo público JSON versionado e faixas MP3 individuais do R2. A programação de testes é montada no app, em ciclos aleatórios completos, substituindo nesta etapa as referências históricas abaixo à programação exclusiva no servidor. Não há emissora de rádio contínua por trás.

O último catálogo válido é salvo privadamente, com fallback em falhas/offline e refresh controlado. Media3 mantém streaming progressivo, buffer/preload e cache operacional LRU de 300 MiB, sem download da biblioteca. MusicProvider → Programming → ProgramItem → Player → MediaSession permanece separado; MediaLibraryService, segundo plano e estrutura Android Auto são preservados.

LocalAssetMusicProvider permanece opt-in para desenvolvimento, Jamendo preservado e inativo. O APK padrão exclui music/** sem apagar músicas locais. O workflow existente não usa MUSIC_ARCHIVE_URL nem baixa MPB.rar; valida testes, lint, build e zero MP3 no APK antes do Artifact. Configuração e roteiro de validação estão no README.

Nenhuma licença do MVP é presumida suficiente para operação comercial. Publicidade, autenticação musical, backend definitivo e Android Auto completo continuam fora desta etapa.

## Atualização autorizada — programação remota da estação

RemoteProgrammingProvider carrega programming.json do R2, separado do MusicProvider. A programação publicada versão 4 contém sete STATION_ID e três JINGLE. A regra ativa é **uma peça em toda mudança de música**: normalmente STATION_ID; quando completar 1 hora desde o último JINGLE realmente reproduzido, o próximo boundary elegível usa JINGLE no lugar da vinheta. Se o jingle ainda não estiver devido ou estiver indisponível, a vinheta continua sendo reproduzida — nunca se cria um slot vazio entre músicas. ProgrammingRules centraliza o padrão, ProgrammingSequencer mantém posição entre lotes e bags independentes sem repetição imediata. Os pools incluem todos os itens remotos, sem limite fixo; nova versão reconstrói os bags no agendamento seguinte preservando ciclo, último item selecionado e áudio já em reprodução. O campo legado songsBetweenInsertions não espaça músicas nesta fase.

TransitionPolicy/AudioTransitionController aplicam saída de MUSIC nos últimos 15 s, entrada curta de peça (150 ms) e de música (100 ms). Peças tocam integralmente, sem crossfade/overlap; avanço natural na mesma instância ExoPlayer. Ganhos centralizados (saída musical com piso de 10%) e preload oficial de playlist da peça/próxima música usam o pipeline/cache existente. Readiness exige MediaPeriod preparado, trilha selecionada e áudio efetivamente em buffer; a presença na timeline não basta. A remoção autorizada de silêncio inicial utiliza um AudioProcessor PCM: somente frames exatamente zero no início de STATION_ID/JINGLE, depois do trimming do encoder, com contagem no relógio oficial do sink. Fala, pausas internas e cauda são preservadas; não há clipping fixo nem early-handoff. Pause preserva posição e programação.

A última configuração válida é salva privadamente; falhas usam a versão salva ou deixam a rádio tocando somente músicas, com refresh/retry controlados. IDs de ocorrência distintos permitem repetir peças na fila com cache compartilhado por conteúdo. Media3, sessão contínua e controles externos somente Play/Pause permanecem. O APK padrão não contém MP3 e o workflow existente continua gerando o Artifact. Não há novas telas nem regras comerciais de anúncios.


## Atualização autorizada — notícias editoriais

RemoteNewsProvider é separado dos provedores musicais/institucionais: RSS Radioagência Nacional → NewsItem → NEWS_INTRO/NEWS_DROP → programação → mesmo Media3/cache/sessão. Intervalo de 60 minutos ativos (pausa/foco/buffering não contam), candidato resolvido antecipadamente, notícias das últimas 24 h com histórico de 100 IDs e crédito da fonte. A página oficial é consultada quando não há enclosure; MP3/redirects devem permanecer em domínios EBC e links indisponíveis são ignorados.

Uma reserva editorial substitui a inserção normal de uma fronteira futura, adiando-a sem consumir seu ciclo/bag. Intro → notícia → música é indivisível; cada item termina integralmente, com preload oficial e readiness comprovada. Se o áudio não estiver preparado antes do boundary, a fila normal é restaurada; falhas editoriais não encerram a rádio. Histórico, último horário e relógio ativo são persistidos privadamente. DEBUG aceita intervalo de 3/5 minutos para teste, release mantém 60 minutos. Não há nova tela, backend ou áudio empacotado. Workflow existente valida testes/lint/APK e disponibiliza o Artifact.

## Atualização autorizada — histórico musical entre sessões

PlaybackHistoryRepository mantém um checkpoint JSON privado por tenant com timestamps
musicais/artistas, última MUSIC iniciada e cinco IDs da abertura anterior; a fila não
é persistida. Gravação sincronizada e substituição atômica ocorrem na execução real,
sem depender do encerramento do app; o formato antigo é migrado. Retenção de 48 h
com limite de 500 entradas, reconciliação de IDs removidos e prioridade para inéditas.
Janela musical de 6 h relaxada somente quando esgotadas as opções para 3 h, 90 min e
0, escolhendo as menos recentes. Nova ordem usa Random.Default e evita a última
faixa e a abertura anterior quando há alternativas; artista mantém 90 min.

Preload, Pause, inserts e notícias não consomem histórico musical. Ciclo institucional,
notícias de hora em hora, transições e controles da sessão permanecem. A arte nativa
passa a usar imagem quadrada com margens, separada do ícone e layout existentes.

## Visão
Aplicativo Android multi-tenant para rádios 24/7 voltadas a plataformas locais de mobilidade.

Cada empresa usa a mesma base do app, mas com identidade visual e stream próprios.

## Objetivo do MVP
Validar:
1. streaming estável no Android;
2. reprodução em segundo plano;
3. configuração por cliente;
4. arquitetura compatível com Android Auto.

## Incluído
- Android
- Kotlin
- Jetpack Compose
- Media3 / ExoPlayer
- MediaSession
- MediaLibraryService
- stream HTTP/HTTPS
- play/pause
- status da transmissão
- notificação de mídia
- Audio Focus
- reconexão básica
- configuração mockada de tenant
- identidade visual por configuração
- persistência local básica
- estrutura para Android Auto

## Fora do MVP
- painel web
- programador automático definitivo
- servidor de streaming definitivo
- publicidade
- relatórios
- cobrança
- iOS
- Android Automotive OS

## Fluxo do motorista
1. Abrir o app.
2. Informar código da empresa.
3. App identifica o tenant.
4. Configuração é salva.
5. Tela da rádio é exibida.
6. Motorista toca Play.

## Tela principal
- logo do cliente
- nome da rádio
- AO VIVO
- play/pause
- conteúdo atual quando houver
- status de conexão

## Tenant de exemplo

```json
{
  "clientId": "alce",
  "activationCode": "ALCE2026",
  "companyName": "Alce App Transporte",
  "radioName": "Rádio Alce",
  "logoUrl": "https://exemplo.com/logo.png",
  "primaryColor": "#000000",
  "streamUrl": "https://radio.exemplo.com/alce",
  "enabled": true
}
```

## Programação
O app não cria playlists.

Arquitetura futura:

```text
Biblioteca musical
→ Motor de programação
→ Músicas + vinhetas + jingles
→ Encoder / servidor de streaming
→ URL da estação
→ App Android
→ Bluetooth / Android Auto / som do veículo
```

## Curadoria musical futura
Priorizar:
- músicas ambientes e democráticas
- sem baixo calão
- sem conteúdo sexual explícito
- sem agressividade excessiva
- sem graves exagerados
- sem som estridente
- sem grandes variações de volume

## Conteúdo comercial futuro
O motor poderá inserir:
- vinhetas
- jingles
- publicidade
- avisos
- campanhas por horário

## Requisitos do player
- tocar stream contínuo
- funcionar com tela apagada
- manter MediaSession
- mostrar notificação
- respeitar Audio Focus
- responder a controles externos
- reconectar automaticamente
- evitar consumo excessivo
- impedir múltiplas instâncias do player

## Android Auto
Preparar:
- MediaSession
- MediaLibraryService
- metadados compatíveis
- controles de mídia

Experiência desejada:

```text
Rádio do cliente
AO VIVO
[ Play / Pause ]
```

## Rede
Considerar:
- Wi-Fi
- 4G
- 5G
- troca de rede
- perda temporária de sinal

Usar retry com backoff.

## Persistência local
Salvar:
- tenant ativo
- configuração visual
- streamUrl
- preferências básicas

## Critérios de aceite
A primeira etapa está pronta quando:
1. projeto compila;
2. app abre;
3. stream de teste toca;
4. play/pause funciona;
5. áudio continua em segundo plano;
6. notificação funciona;
7. MediaSession funciona;
8. MediaLibraryService está configurado;
9. arquitetura permite Android Auto;
10. existe tenant mockado;
11. não existem credenciais hardcoded;
12. README explica como executar.

## Próximas fases
1. API real de tenants
2. servidor de programação
3. streaming 24/7
4. painel administrativo
5. Android Auto completo
6. campanhas e jingles
7. métricas e relatórios
8. licenciamento por cliente
