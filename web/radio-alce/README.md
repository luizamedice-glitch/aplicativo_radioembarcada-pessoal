# Rádio Alce — web mobile

Player web independente, sem alterar o APK ou o servidor. O diretório raiz do
projeto Vercel é **web/radio-alce**, nome **radioalce**, endereço desejado
**https://radioalce.vercel.app**. Não executar builds web a partir da raiz Android.

## Correspondência com a tela Android

| Origem Android | Versão web |
| --- | --- |
| `ui/RadioPlayerScreen.kt` — `AlceLogoHeader` | `public/alce-logo.png`, cópia byte a byte de `app/src/main/res/drawable-nodpi/radio_alce_logo.png` |
| `RadioPlayerScreen.kt` — `premiumBackground` | Gradiente e três curvas SVG de baixa opacidade |
| `LiveBadge`, `RadioTagline` | `index.html`, mesmas palavras, cores e espaçamentos |
| `PrimaryPlayPauseButton`, `VolumeButton` | Três botões acessíveis com SVGs equivalentes |
| `ui/WaveformVisualizer.kt` | `src/waveform.js`, 41 barras, senoides, 20 Hz, sem FFT |
| `ui/theme/RadioTheme.kt` | Tokens CSS: #070808, #e0b75f, #8c703b, #f5f3ee, #ccc8be |

`radio_alce_media.png` é a imagem do player **nativo** e não foi reutilizada na tela
web. Nenhum asset original do Android foi modificado.

A hierarquia, pesos verticais (.16 / 1.15 / .28 / .30), largura máxima do logo,
espaços de 20 px e controles de 48/120 px reproduzem o Compose. `100dvh`, safe areas
e modo compacto abaixo de 500 px preservam uma única tela. Há testes de 320×568
até 768×1024 e paisagem 844×390. A animação para em Pause, aba oculta e preferência
por movimento reduzido. Nenhum metadado de música aparece na tela.

## Áudio e HTTPS

A origem única é `http://15.229.83.121:8000/alce.mp3`, centralizada na regra de
`vercel.json`. O navegador usa somente **/radio/stream** no mesmo domínio HTTPS.
A Vercel faz um external rewrite para essa origem HTTP fixa. Não há redirecionamento
para HTTP no navegador, proxy aberto com URL fornecida pelo usuário, cache da
transmissão, alteração de CORS no Icecast ou mudança no APK/servidor.

O proxy é exclusivo desta web. Não decide programação, não armazena músicas e não
introduz Functions com limite de execução para manter uma conexão infinita.
Limites de conexão do CDN/navegador ainda podem encerrar o fluxo; o player tenta
reconectar ao sinal atual, com backoff de 1–30 s. Verificar a transmissão pública
após deploy (HTTP 200 sozinho não comprova áudio).

Play exige um toque inicial e conecta ao sinal atual; Pause encerra o download;
retomar cria uma nova conexão. Badge/waveform só ficam ativos no evento `playing`.
Durante espera ficam discretos, sem mensagens técnicas. Erro/EOF aciona retry;
Pause cancela timers. A sessão web oferece somente Play/Pause/Stop, sem seek/skip.

Volume ajusta `HTMLAudioElement.volume`. Safari/iOS pode reservar esse controle aos
botões físicos; não usamos WebAudio para contornar a política do navegador.
Continuidade em segundo plano depende do navegador/SO, não equivale às garantias
do foreground service Android.

## Desenvolvimento e validação

Node.js 22.12+ ou 24 LTS:

```sh
cd web/radio-alce
npm ci
npm run dev
npm run build
npx playwright install chromium
npm test
```

Vite lê a mesma origem de `vercel.json` para o proxy local. O teste automatizado usa
áudio PCM sintético, decodificado de verdade pelo navegador, e não depende do
servidor estar online. Capturas de sete tamanhos ficam em `test-results/`, ignorado
pelo Git. Não basta esse teste para validar o proxy da Vercel: após deploy, abrir a
URL no celular, tocar Play, confirmar áudio, pausar e retomar; conferir resposta
`audio/mpeg` de `/radio/stream` e acompanhar reprodução por vários minutos.

## Deploy

Importar **luizamedice-glitch/aplicativo_radioembarcada-pessoal** na equipe autorizada
com nome `radioalce`, Root Directory `web/radio-alce`, framework Vite, install
`npm ci`, build `npm run build`, output `dist`. Não alterar o projeto Android.
Produção precisa ser pública para compartilhamento por WhatsApp. Não há secrets
ou variáveis de ambiente necessários. O arquivo `vercel.json` inclui o proxy e
headers de segurança; não hospedar apenas `dist` sem essa configuração.

A disponibilidade do alias `radioalce.vercel.app` e a permissão de criar o projeto
precisam ser confirmadas na conta Vercel. Não anunciar a URL como publicada antes
de concluir e verificar o deployment. Para rollback, promover o deployment anterior
do mesmo projeto; isso não modifica a rádio central.
