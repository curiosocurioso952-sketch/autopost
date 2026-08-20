# AutoPost V7.5

Autopublicador de vídeos para **YouTube, Instagram e TikTok**, com interface gráfica em português. Usa as **APIs oficiais** de cada plataforma — nada de simular cliques no navegador.

## O que mudou na V7.5

| Recurso novo | Descrição |
| --- | --- |
| 🎨 Paleta suave de verdade | Cores pastel (terracota suave, âmbar suave, bege neutro) e um tema próprio registrado (`theme_create` herda do `clam`) — no Windows o estilo nativo não consegue mais "estourar" as cores. Botões azul-acinzentados, abas discretas e seleção terracota suave. |
| 🖼️ Prévia sem depender da Pillow | A prévia (capa estilo post) agora usa o **ffmpeg embutido** como fallback quando a Pillow não está instalada na máquina — nunca mais aparece "Prévia indisponível". A dica exata de instalação (`py -3 -m pip install Pillow`) aparece na interface quando ajuda. |
| 🛠️ Vídeos não somem mais | Corrigido um bug crítico: a interface fechava a conexão do banco por dentro (`settings.py`), corrompendo a leitura — vídeos desapareciam da lista e os contadores ficavam em zero. A conexão compartilhada agora é protegida, e o agendamento múltiplo (vários vídeos de uma vez) foi validado. |
| 🗂️ Interface organizada em seções | Abas Conteúdo e Fila agora agrupam as ações em blocos numerados (1 · Importar vídeos, 2 · Prévia, 3 · Metadados e preparo, 1 · Calendário, 2 · Agendamento rápido), com mais espaçamento e instruções de contexto ao lado dos botões. |

## O que mudou na V7.4

| Recurso novo | Descrição |
| --- | --- |
| 🖼️ Prévias estilo post | A prévia do vídeo agora é gerada como uma capa de post: frame do vídeo com o título do seu conteúdo sobreposto na faixa inferior — assim você vê exatamente como a publicação vai aparecer. |
| 📅 Agendamento rápido com data/hora exatas | Na aba Fila e Calendário há um seletor manual de **data, hora e minuto** (com IA opcional) para agendar os vídeos selecionados em qualquer horário — sem depender do clique na grade. |
| 📅 Calendário redesenhado e clicável | A grade do mês (dias × horas 6h–23h) redesenha automaticamente ao exibir a aba e marca cada dia com posts agendados (bolinha vermelha). O clique em qualquer célula agenda a seleção naquele dia/hora, com confirmação visual de 400 ms. |
| 🎨 Tema com cores de marca | Paleta clara com vermelho vivo da marca, abas com contraste claro e tema escuro em cinza com camadas separadas; tudo configurável na engrenagem. |
| 🔗 YouTube em qualquer pasta | Ao conectar o YouTube, basta selecionar o `client_secrets.json` baixado do Google Cloud — ele pode estar em Downloads, Desktop ou qualquer pasta. |

## O que mudou na V7.3

| Recurso novo | Descrição |
| --- | --- |
| 🎨 Cores refinadas | Paleta clara mais viva (vermelho da marca, âmbar forte no horário de pico) e tema escuro com mais contraste e camadas bem separadas. |
| 📅 Escolha livre no calendário | As células âmbar são apenas sugestões de horário de pico — você pode agendar em qualquer dia e hora, clicando direto na grade. |
| 🖼️ Miniaturas à prova de falha | A prévia agora tenta várias vias (miniatura salva, extração direta e versão preparada) e mostra o detalhe do erro quando nenhuma funciona. |

## O que mudou na V7.2

| Recurso novo | Descrição |
| --- | --- |
| 📅 Calendário de verdade interativo | Clique em um dia/hora agenda automaticamente os vídeos selecionados na aba Conteúdo (ou as publicações selecionadas na fila). A célula clicada pisca em vermelho como confirmação e o dia agendado ganha o marcador vermelho. Se nada estiver selecionado, o app mostra uma dica rápida que se fecha sozinha. |
| 🌙 Tema escuro reformulado | Paleta em tons de cinza com contraste real: botões, painéis e textos legíveis, com o amarelo dos horários de pico e o vermelho de destaque bem visíveis. |
| 🖼️ Miniaturas mais robustas | A prévia agora é gerada em segundo plano assim que o vídeo entra na lista, com tratamento de caminhos com acentos/caracteres especiais (o vídeo é copiado temporariamente para a extração do frame quando necessário). |
| 📋 Seleção preservada | A seleção da lista de vídeos é mantida ao atualizar a interface — você não perde a seleção entre ações. |

## O que mudou na V7.1

| Recurso novo | Descrição |

| Recurso novo | Descrição |
| --- | --- |
| 🖱️ Abas com rolagem | Todo o conteúdo das abas agora rola verticalmente — nada fica cortado na tela. |
| 📅 Calendário interativo | O calendário da fila ficou maior e agora você clica diretamente em um dia/hora para agendar as publicações selecionadas naquele horário exato. |
| 🕐 Horários de pico dinâmicos | O app escolhe sozinho os melhores horários conforme o dia da semana (manhã, almoço, fim de tarde e noite) — acabou o intervalo fixo e a edição manual. |
| 🌙 Tema escuro | Alterne entre tema claro e escuro na janela de Configurações; a escolha fica salva. |
| ⚙️ Configurações do app | Tudo em um lugar só (engrenagem no canto superior direito): tema, idioma, chave da IA, privacidade (TikTok) e preparo de vídeos. |
| 🛠️ ffmpeg embutido | `ffmpeg.exe` e `ffprobe.exe` vêm na pasta `tools/` do ZIP — não precisa baixar nada. |
| 🖼️ Miniaturas automáticas | A prévia de cada vídeo é gerada sozinha em segundo plano (ffmpeg embutido) e aparece ao selecionar o vídeo. |
| 📤 Exportar relatórios | Botão para baixar a fila em CSV e para limpar o log de execução. |

## Como usar

| Recurso | Descrição |
| --- | --- |
| 🔗 Gerenciamento de Contas | Conecte uma conta de cada plataforma, com status 🟢/🟡/🔴. |
| 🖼️ Miniaturas | Veja a prévia de cada vídeo na lista de conteúdo. |
| 🤖 IA automática | Gere título, hashtags e legendas analisando o conteúdo do vídeo (frames). Use sua chave da Manus API — ou o app sugere metadados automaticamente. |
| 🎬 Preparar vídeo | Converta automaticamente para o formato exigido por cada plataforma (vertical 9:16, duração máxima) e grave legendas embutidas no vídeo. |
| ⚙️ Configuração de Postagem | Para cada vídeo, escolha as plataformas e (no TikTok) a privacidade: Público, Amigos mútuos ou Privado. |
| 📅 Fila e Calendário | Veja suas publicações em um calendário mensal com os **horários de pico** marcados (9h, 12h, 15h e 18h). |
| ▶️ Execução | Selecione os itens na fila, clique em **Iniciar** e o app publica sozinho, com painel de progresso e contadores em tempo real. Pode pausar e parar a qualquer momento. |
| 💾 Banco SQLite | `autopost.db` fica junto ao programa; se o PC reiniciar no meio da madrugada, a fila continua de onde parou. |

## Como rodar no Windows

1. Instale o Python 3.11+ em [python.org](https://www.python.org/downloads/) (marque *Add Python to PATH*).
2. Descompacte o `AutoPost_V7.zip`.
3. Dê dois cliques em `run_autopost.bat` (ou rode `python main.py` no Prompt). Recomenda-se sempre descompactar em uma pasta nova e vazia, para evitar arquivos de versões antigas.

Nenhuma dependência é obrigatória para usar a fila e o agendamento — tudo roda com a biblioteca padrão do Python. O conector do TikTok usa apenas o `requests`, que já está na lista de opcionais.

## Conversão de vídeo

A conversão e as legendas usam o **ffmpeg**, que já vem embutido na pasta `tools/` deste ZIP — não precisa baixar nada. O app detecta automaticamente e os botões de "Preparar vídeo" ficam ativos.

## Chave da IA (opcional)

Para a geração de título/hashtags por IA com visão de vídeo:

1. Obtenha sua chave da Manus API em [manus.im](https://manus.im) (menu de configurações → API).
2. Cole a chave no campo **Chave da Manus API** na janela de Configurações (engrenagem no canto superior direito) e clique em **Testar chave**.
3. Sem chave, o app ainda preenche metadados automaticamente a partir do nome do vídeo.

## Conectores — plataformas

O TikTok usa a **Content Posting API v2** com upload direto de arquivo local (`FILE_UPLOAD`). Enquanto o app não passar na auditoria oficial do TikTok, as publicações saem **privadas** (visíveis só para você) — isso é regra da própria plataforma, não um limite do AutoPost.

O Instagram exige conta **Empresarial/Creator** vinculada a uma Página do Facebook (Graph API). O YouTube usa a Data API v3 com OAuth e exige adicionar seu e-mail como testador no console do Google (modo teste).

## Virar `AutoPost.exe` (opcional)

```bat
pip install pyinstaller
pyinstaller --onefile --noconsole --name AutoPost main.py
```

O executável aparecerá em `dist/AutoPost.exe` — mantenha-o na mesma pasta do projeto (o banco `autopost.db` é criado ao lado do executável).
