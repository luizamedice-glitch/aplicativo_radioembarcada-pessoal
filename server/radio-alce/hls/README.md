# Saída HLS paralela de teste — sem corte de produção

Estado: implementação preparada para teste; **não implantada na EC2/R2**.
O commit pai é o checkpoint da configuração existente. Nada modifica o Compose
principal, Liquidsoap, planner, APK, web, catálogo ou programação.

```
Liquidsoap → Icecast /alce.mp3 → ouvintes atuais (inalterado)
                         └→ 1 listener FFmpeg → AAC-LC 128k → HLS → R2 dedicado
```

Projeto Compose independente `radio-alce-hls-test`, profile `test` obrigatório.
Sem compartilhamento de volumes, senhas Icecast, rede Compose ou comandos de
controle da produção. Fonte padrão acessa a porta publicada no host Docker.
Não precisa abrir porta pública nova. Preview somente 127.0.0.1:8083.

## Comportamento

- FFmpeg decodifica o MP3 final e codifica AAC-LC 128 kbps, estéreo 44,1 kHz.
  Há uma segunda codificação com perdas; comparar qualidade antes de migrar.
- Segmentos MPEG-TS de aproximadamente 10 s; janela de seis segmentos.
  A latência esperada é de dezenas de segundos; não é LL-HLS.
- Arquivos temporários e rename atômico; nomes únicos por execução, sequência
  baseada em epoch em microssegundos e marcador de descontinuidade no início.
- Falha de fonte reinicia **somente o listener HLS**, backoff 1–30 s.
- Upload síncrono de segmentos completos antes de publicar a playlist. Falha de
  upload preserva a última playlist publicada; não publica referências quebradas.
  Retomada usa a janela atual, sem fila histórica ilimitada. Falhas longas podem
  exigir reconectar o player HLS; nunca afetam a transmissão MP3.
- Limpeza local depois de 10 min (~10 MB de áudio); preserva margem para clientes
  atrasados. R2 exige lifecycle de 1 dia no prefixo, inclusive após desligar teste.
  Não há deleção do catálogo musical, nem acesso ao bucket musical necessário.
- Recursos limitados: encoder 0,5 CPU/192 MiB, preview 0,1 CPU/32 MiB.
  São limites, não medição de consumo/garantia de capacidade; validar RAM livre
  antes de iniciar na t3.micro. Log Docker limitado a 2 × 5 MB por serviço.
- Healthcheck verifica frescor e arquivos; com R2, exige publicação recente.
  Amplitude é validada separadamente: healthcheck não prova áudio audível.

## Testes no ambiente de desenvolvimento

```bash
python3 -m unittest discover -s server/radio-alce/hls/tests -v
python3 server/radio-alce/hls/tests/validate_http.py
python3 -m unittest discover -s server/radio-alce/tests -q
docker build -t alce-hls-test server/radio-alce/hls
```

O teste gera MP3 sintético, passa pelo mesmo comando FFmpeg e decodifica a playlist
HLS; exige média >−40 dB e pico >−25 dB. Testa ordem de upload, falhas/recuperação,
segmento ausente, playlist antiga, retenção e rejeição de caminhos externos.
Nenhum teste depende do stream de produção ou faz upload real.

## Ativação manual de teste na EC2 (ainda não executada)

No EC2 Instance Connect como `ubuntu`, usar clone separado. Não executar setup.sh
nem Compose da pasta principal. Não copiar a .env de produção.

```bash
free -m
df -h /
docker stats --no-stream
RELEASE="$HOME/radio-alce-hls-test"
test ! -e "$RELEASE"
git clone --branch main --single-branch https://github.com/luizamedice-glitch/aplicativo_radioembarcada-pessoal.git "$RELEASE"
cd "$RELEASE/server/radio-alce/hls"
# Para reproduzir a revisão validada: git checkout <commit-da-entrega>
cp .env.example .env
chmod 600 .env
docker compose --profile test config --quiet
docker compose --profile test build
docker compose --profile test up -d
docker compose --profile test ps
curl --fail http://127.0.0.1:8083/live.m3u8
```

Primeiro aguardar pelo menos 30 s e confirmar encoder healthy. Medir com FFmpeg
**se já estiver instalado** (não instalar automaticamente em produção):

```bash
ffmpeg -hide_banner -i http://127.0.0.1:8083/live.m3u8 -t 30 -af volumedetect -f null -
docker stats --no-stream
```

O volume depende do trecho musical; comparar com MP3 contemporâneo e ouvir.
Nunca considerar HTTP 200 suficiente. Manter amostra por 30–60 minutos para avaliar
memória, CPU, reconexão e estabilidade; não é teste de carga.

## Publicação opcional no R2 — fase seguinte

1. Criar bucket **dedicado** `radio-alce-hls-test`. Não usar bucket musical.
2. Criar lifecycle para excluir objetos sob `alce-test/` após **1 dia**. Obrigatório
   antes de habilitar upload; ~1,4 GB/dia além de overhead, não arquivo eterno.
3. Vincular domínio próprio HTTPS ao bucket. Não usar r2.dev para produção.
4. Credencial somente Object Read/Write nesse bucket; inserir pelo editor na .env.
   Não enviar chave no chat, nem executar `docker compose config` sem `--quiet`.
5. Configurar CORS GET/HEAD para a origem do player de teste; expor Content-Length,
   Content-Range e Accept-Ranges quando necessário. Sem cookies/credenciais no player.
6. Cache de `.ts`: respeitar `max-age=86400, immutable`. Playlist `.m3u8`:
   respeitar `max-age=2, must-revalidate`, **não forçar Edge TTL longo nem servir
   playlist antiga por stale caching**. Não cachear erros/404. Publicação é a cada
   segmento; cache da playlist precisa vencer rapidamente.
7. Editar `.env`: R2_ENABLED=true, endpoint oficial, bucket/prefixo e credenciais.
   Recriar exclusivamente o encoder de teste:

```bash
nano .env
docker compose --profile test up -d --no-deps --force-recreate encoder
```

URL resultante: `https://<dominio-hls>/alce-test/live.m3u8`.
Testar em VLC ou Safari com HLS nativo. Chrome/Android web exige player HLS/MSE;
o APK atual também requer módulo/fonte HLS em tarefa posterior. Não alterar URLs
dos players existentes nesta etapa. Confirmar áudio, cronologia e recuperação.
A integração R2 real fica pendente de domínio, bucket/lifecycle e credencial restrita.
Não criamos esses recursos automaticamente nesta preparação.

## Rollback / encerramento

Na pasta `server/radio-alce/hls` desse clone:

```bash
docker compose --profile test down
```

Para somente suspender: `docker compose --profile test stop`.
Isso encerra apenas o projeto HLS. Não remove volume nem altera /alce.mp3.
Objetos R2 expiram por lifecycle; remover/desabilitar domínio de teste quando
encerrar a avaliação. Não manter a URL publicada como se estivesse ao vivo após
parar o encoder: a última playlist permanecerá até expirar/remover.

## Resultado da preparação (18/10/2026)

- 7 testes HLS passaram no host; fixture MP3 → HLS: média −24,5 dB, pico −21,5 dB.
- Build Docker e validação Compose passaram; compilação Python e diff sem erros.
- Suíte principal: 67 testes, 63 passaram e 4 falharam em código preexistente,
  intocado por esta pasta: pareamento de vinheta por gênero, persistência do slot
  de hora e duas expectativas de vinheta/jingle após notícia. Essas falhas não
  foram corrigidas aqui para não alterar a programação em uma tarefa HLS.
- R2 e EC2 não foram alterados; validação de longa duração e reprodução em
  dispositivos reais continuam pendentes da ativação manual de teste.
- Teste HTTP local em tempo real: playlist avançou com segmentos completos;
  média −24,6 dB e pico −21,2 dB. Fonte sintética, sem acesso à EC2.
- Os mesmos 7 testes passaram dentro da imagem Docker como usuário sem privilégios.

### Correção da primeira ativação

O regex Nginx precisa estar entre aspas por conter `{32}`; sem aspas, a imagem
interpretava parte do regex como diretiva e reiniciava. `nginx -t` passou após a
correção. A inicialização do volume também agora é explícita: `init-output` ajusta
somente o diretório raiz do volume HLS para UID/GID 65534 antes do encoder; o
preview usa `nocopy` e inicia depois. Evita a corrida de população do volume pela
imagem Nginx. O encoder verifica escrita antes de conectar, exibindo erro de
permissão diretamente em vez de repetir conexões sem diagnóstico.

Validação adicional: Compose completo isolado com MP3 sintético, servidor Nginx,
playlist HTTP e healthcheck passaram. Áudio decodificado do preview: média −24,6 dB,
pico −21,3 dB. Sete testes Python passaram novamente; build passou. Não foi teste
na EC2 nem publicação R2. O teste anterior de fonte HTTP contínua permanece válido.
