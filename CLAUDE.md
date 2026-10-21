# Projeto: Dashboard de Decisão com JEV

Rede varejista **fictícia** com 40 lojas (LOJ001 a LOJ040) em 5 regiões, dados mensais a partir de 2025-10,
armazenados no **Supabase** (novos meses podem ser carregados no banco ao longo do tempo).

Objetivo: um dashboard executivo de **1 tela** onde o usuário escolhe um mês e aperta o botão **"JEV Analysis"**.
O JEV julga a **rede inteira** naquele mês e o Claude Haiku transforma a decisão em texto de ação.

## As 3 perguntas de negócio (tudo no projeto serve a elas)

1. **O que explica o resultado da rede neste mês?** → causa provável (JEV, `choice`)
2. **Qual o Score de certeza dessa causa?** → probabilidade da causa escolhida × 100, exibida de 0 a 100
   - Score ≥ 70 → **Agir** · 40 a 69 → **Confirmar** · < 40 → **Investigar**
   - A etiqueta vale para qualquer causa, inclusive "Sem problema relevante".
3. **O que fazer e por onde começar?** → 3 lojas prioritárias (Python) + texto de ação (Haiku)

## Papéis (nunca misturar)

| Quem | Faz | Não faz |
|---|---|---|
| **Python** | Lê o Supabase, filtra o mês, calcula KPIs, rankings por região/loja, monta o dossiê, escolhe as lojas prioritárias | Não julga causa |
| **JEV** (TypeSafe, via OpenRouter) | Julga a causa, o risco da rede e se os sinais são ambíguos | Não calcula números |
| **Claude Haiku 4.5** (via OpenRouter) | Redige textos a partir da decisão do JEV (mensagem ao gerente, resumo para diretoria, pedidos livres) | **Nunca** muda, reinterpreta ou contradiz a decisão do JEV |
| **Claude Code** (você) | Constrói e roda o projeto, mostra resultados | Não decide sobre as lojas |

## Como rodar

1. **Python 3** (só biblioteca padrão: `urllib`, `http.server`, `json`; nada para instalar com pip). Testado com Python 3.14.
2. Criar o `.env` na raiz (já ignorado pelo `.gitignore`):
   ```
   SUPABASE_URL=
   SUPABASE_KEY=
   OPENROUTER_API_KEY=
   ```
   - `SUPABASE_URL`: Supabase → *Project Settings → Data API* (ou botão **Connect**) → Project URL (`https://xxxx.supabase.co`).
   - `SUPABASE_KEY`: Supabase → *Project Settings → API Keys* → **Publishable key** (`sb_publishable_...`); em projetos antigos, a `anon`/`public` da aba *Legacy API Keys*. **Nunca** usar a `secret`/`service_role`.
   - `OPENROUTER_API_KEY`: openrouter.ai → *Settings → Keys* → **Create Key** (`sk-or-v1-...`).
3. Rodar `python server.py` e abrir **http://localhost:8000**.
4. Teste rápido do JEV sem o dashboard: `python jev_core.py 2026-10` (imprime a resposta e grava em `runs/`).

## Arquivos

```
CLAUDE.md             este guia
.env                  chaves (não versionar)
.gitignore            ignora o .env
jev_core.py           leitura do Supabase, dossiê, perguntas do JEV, chamadas ao JEV e ao Haiku
server.py             servidor local: serve o HTML e a API; faz todos os cálculos do dashboard
dashboard/index.html  a tela (CSS e JS embutidos; só exibe o que o Python calculou)
runs/                 registro de cada chamada ao JEV e ao Haiku (criado automaticamente)
```

## Dados (Supabase)

A base fica no Supabase, não em arquivos locais. Tabelas no schema `public` (colunas em minúsculas).
Frações estão em escala 0–1 (ex.: `0.0541` = 5,41%).

| Tabela | Grão | Colunas |
|---|---|---|
| `lojas` | 1 linha por loja (40) | `id_loja` (LOJ001…), `loja` (nome), `cidade`, `uf`, `regiao` (Sul, Sudeste, Centro-Oeste, Nordeste, Norte), `gerente`, `data_abertura` (AAAA-MM-DD) |
| `performance_mensal` | 1 linha por loja e mês | `id_loja`, `mes` (texto `AAAA-MM`), `faturamento` (R$), `meta` (R$), `atingimento_meta` (fração = faturamento/meta), `pedidos`, `visitas`, `conversao` (fração = pedidos/visitas), `ticket_medio` (R$), `nps`, `devolucoes`, `taxa_devolucao` (fração), `variacao_mom` (fração, variação do faturamento vs mês anterior; vazia no primeiro mês) |
| `relatorio_gestores` | 1 linha por loja e mês | `id_relatorio`, `id_loja`, `mes` (`AAAA-MM`), `comentario_gerente` |
| `reviews_clientes` | 1 linha por avaliação | `id_review`, `id_loja`, `data` (AAAA-MM-DD; o mês vem daqui), `nota` (1 a 5), `comentario`, `canal` (App, Google, Pesquisa NPS) |
| `pos_venda` | 1 linha por ocorrência | `id_ocorrencia`, `id_loja`, `data` (AAAA-MM-DD; o mês vem daqui), `tipo_ocorrencia` (Produto, Entrega, Troca, Atendimento, Disponibilidade), `descricao`, `resolvido` (Sim/Não), `canal` (E-mail, Loja, WhatsApp, Telefone) |

Regras de acesso:
- Leitura pela API REST do Supabase, ex.: `GET {SUPABASE_URL}/rest/v1/performance_mensal?select=*&mes=eq.2026-10`,
  com os headers `apikey` e `Authorization: Bearer` usando a **chave publishable** (`SUPABASE_KEY`).
  Tabelas com data filtram o mês por intervalo: `data=gte.2026-10-01&data=lt.2026-11-01`.
  A API devolve no máximo 1000 linhas por chamada; o código pagina com `offset`/`limit`.
- A chave publishable **só lê**: o RLS precisa estar ligado em todas as tabelas, com policy que permita apenas `SELECT`.
  O projeto nunca escreve no banco.
- **A lista de meses do filtro vem do banco** (meses distintos de `performance_mensal`), nunca fixa no código.
  Quando um mês novo é carregado no banco, ele aparece no dashboard ao recarregar a página.
- Nunca guardar cópia local dos dados; sempre consultar o Supabase.
- Atingimento de rede/região é sempre **soma do faturamento ÷ soma da meta** (não a média de `atingimento_meta`).

## Conexão com o OpenRouter

- Só o Python (`jev_core.py`/`server.py`) lê o `.env`. **Nunca exibir as chaves, nunca enviá-las ao navegador.**
- Header em todas as chamadas: `Authorization: Bearer {OPENROUTER_API_KEY}` e `Content-Type: application/json`.

### JEV
- `POST https://openrouter.ai/api/alpha/decisions`
- Body: `{"model": "typesafe/jev-1.13", "state": "<dossiê em texto>", "questions": {nome: pergunta}}`
- Formato de cada pergunta: `{"type": ..., "instructions": "...", "criteria": ...}`
  - `choice`: `criteria` é um objeto `{rótulo: descrição}`
  - `score`: `criteria` é uma lista ordenada de níveis (do menor para o maior)
  - `noul`: `criteria` é `{"true": descrição, "false": descrição}`
- Resposta: `{"model": "typesafe/jev-1.13-<versão>", "answers": {nome: {...}}, "usage": {"input_tokens", "output_tokens", "cost"}, "id", "provider"}`
  - `choice` → `choice`, `confidence`, `probabilities{rótulo: p}`
  - `score` → `score` (média ponderada, ex.: 2.78), `confidence`, `probabilities{"0".."4": p}`, `legend{"0".."4": rótulo}`
  - `noul` → `noul` (probabilidade de SIM, 0 a 1)
- Custo de referência: ~US$ 0,0001 por chamada.

### Haiku
- `POST https://openrouter.ai/api/v1/chat/completions`
- Body: `{"model": "anthropic/claude-haiku-4.5", "messages": [system, user], "max_tokens": 800, "temperature": 0.3}`
- Texto em `choices[0].message.content`.

## Perguntas enviadas ao JEV (uma chamada por mês analisado)

Texto exato (em `QUESTIONS`, no `jev_core.py`):

**`causa_principal`** (`choice`)
- Instrução: "Com base no dossiê da rede inteira neste mês, qual é a causa mais provável do resultado? Pequenas oscilações em 1 ou 2 lojas são normais e não definem a causa da rede. Só aponte uma causa quando houver sinais consistentes nos números E nos textos (comentários dos gerentes, reviews e pós-venda)."
- Critérios:
  - `Estoque`: "Ruptura, falta de produto, atraso de reposição limitando vendas"
  - `Equipe`: "Falta de pessoal, rotatividade, desfalque ou treinamento insuficiente"
  - `Atendimento`: "Mau atendimento, demora, reclamações de tratamento ao cliente"
  - `Demanda`: "Menos clientes/visitas por fatores de mercado, sazonalidade ou concorrência"
  - `Preço`: "Preço acima do mercado, promoções da concorrência, sensibilidade a preço"
  - `Sem problema relevante`: "Rede perto da meta, sem região com queda forte, comentários sem queixas"

**`risco_rede`** (`score`, 0 a 4)
- Instrução: "Qual o nível de risco para o resultado da rede, considerando o dossiê deste mês?"
- Níveis: `["Muito baixo", "Baixo", "Moderado", "Alto", "Muito alto"]`

**`revisao_humana`** (`noul`)
- Instrução: "Os sinais deste mês são ambíguos ou contraditórios a ponto de exigir que um analista confirme a causa antes de agir? Avalie apenas a incerteza sobre a causa, não a gravidade do resultado."
- Critérios:
  - `true`: "Números e textos apontam para causas diferentes ou não sustentam uma causa clara"
  - `false`: "Números e textos convergem para a mesma causa, mesmo que o resultado seja grave"
- Mede **incerteza sobre a causa, não gravidade**. Resultado grave com causa clara = não precisa de revisão.

## O dossiê do mês (o que vai ao JEV)

Texto em português, montado em Python (`montar_dossie` no `jev_core.py`), em 7 blocos:
1. Indicadores da rede (faturamento, atingimento, NPS) vs mês anterior.
2. Por região: atingimento, NPS e variação do atingimento em p.p. vs mês anterior, do pior para o melhor.
3. As 5 lojas com pior atingimento da meta: atingimento, conversão (em %) e visitas com variação vs mês anterior, NPS.
4. Pós-venda: total e contagem por tipo, comparando com o mês anterior.
5. Comentários dos gerentes dessas 5 lojas.
6. As 10 avaliações de menor nota dessas 5 lojas.
7. Até 8 ocorrências de pós-venda dessas 5 lojas, com tipo e descrição.

- Os números vão prontos, o JEV não calcula.
- No primeiro mês da base (sem mês anterior), os blocos saem sem as comparações.
- As **3 lojas prioritárias** do card são as 3 primeiras do bloco 3 (pior atingimento), ou seja, as mesmas que o JEV leu,
  exibidas com o atingimento de cada uma.

## O prompt do Haiku

- **System:** redator de comunicação executiva, português do Brasil, tom profissional e direto. "A decisão abaixo foi tomada
  pelo JEV e é um FATO: não altere a causa nem o score, não invente números. Não reinterprete, não questione e não
  contradiga a decisão." Usa só os números fornecidos. Sem emojis. **Texto simples, sem Markdown** (nada de `**`, `#`,
  tabelas ou `---`), pronto para colar em e-mail ou WhatsApp.
- **User:** os fatos (causa, Score, etiqueta, risco, revisão humana, 3 lojas prioritárias com região, gerente e
  atingimento, e os big numbers da rede no mês) + a tarefa + o lembrete "não altere a causa nem o score, não invente números".
- A revisão humana chega ao Haiku já interpretada pelo Python: **RECOMENDADA** se `noul` ≥ 0,5, **NÃO necessária** se < 0,5.
- Tarefas:
  - `gerente`: mensagem ao gerente da loja prioritária nº 1, com a causa, o número que a coloca como prioridade, 2 a 3 ações e prazo de retorno. Até 150 palavras.
  - `diretoria`: título de 1 linha e até 5 tópicos (resultado, causa com Score e etiqueta, risco, lojas prioritárias, próximo passo coerente com a etiqueta). Até 160 palavras.
  - `livre`: o pedido digitado pelo usuário (máx. 1000 caracteres).
- O Haiku lê a decisão do **arquivo do JEV em `runs/`**, nunca de dados enviados pelo navegador.

## Arquitetura do dashboard

`server.py` (`http.server`, porta 8000, só em `127.0.0.1`) serve o HTML e expõe:
- `GET /api/meses` → lista de meses disponíveis no banco
- `GET /api/filtros` → meses (valor + rótulo "Outubro/2026"), regiões e lojas (para os filtros)
- `GET /api/dados?mes=AAAA-MM&regiao=&loja=` → big numbers, gráficos e títulos já calculados em Python para o filtro
- `POST /api/jev` `{mes}` → monta o dossiê, chama o JEV, grava em `runs/`, devolve a decisão (causa, score, etiqueta, probabilidades, risco, revisão humana, prioridades, arquivo)
- `POST /api/acao` `{mes, tipo, pedido, arquivo}` → `tipo` = `gerente` | `diretoria` | `livre`; `arquivo` = o `runs/jev_...json` devolvido pelo `/api/jev` do mesmo mês; chama o Haiku e grava em `runs/`
- Erros de entrada devolvem 400 com mensagem clara; falha do JEV/Haiku devolve 502. Nunca inventar resultado.

`dashboard/index.html`: 1 tela, visual executivo e limpo
- Topo: filtros de **Mês**, **Região** e **Loja** (a lista de lojas acompanha a região escolhida)
- Etiquetas dos filtros ativos (com "×") + botão **"Limpar filtros"** + texto "Exibindo: …"
- Big numbers: Faturamento, % da Meta, NPS médio, Ocorrências de pós-venda
- 3 gráficos: Atingimento da meta por região · Evolução mensal de faturamento vs meta · Lojas com pior atingimento da meta (até 10)
- **Cross-filter:** clicar numa barra de região filtra por ela; clicar numa loja filtra por ela; clicar de novo desfaz. Tudo é recalculado em Python.
- **Card JEV (protagonista)**: botão "JEV Analysis" → causa, **Score de certeza** (medidor 0–100), etiqueta, barras de probabilidade, 3 lojas prioritárias clicáveis, risco e revisão humana
- **O JEV sempre analisa a rede inteira do mês**; os filtros de região/loja servem para investigar e comparar com o que ele apontou.
- **Transformar em ação** (aparece só depois do JEV). Pode ser escondida para gravações mudando `ACAO_ATIVA` para `false` no `index.html`.

## Diretrizes do dashboard (UX/UI e análise de dados)

O dashboard é o ponto alto do projeto. Siga estas regras sempre, para o resultado sair consistente.

### Princípio
A tela responde às 3 perguntas, nessa ordem de leitura: **contexto (números) → decisão (JEV) → ação (Haiku)**.
O **card do JEV é o protagonista**: é o maior elemento da tela e o único com cor de destaque. O resto é neutro e serve de contexto.

### Layout (desktop 1440px, 1 tela sem rolagem até o card do JEV)
```
┌ Cabeçalho: "Decisão do Mês" · nome da rede · mês de referência │ filtros MÊS · REGIÃO · LOJA ┐
├ Etiquetas dos filtros ativos · Limpar filtros · Exibindo: …                                  ┤
├ 4 big numbers em linha ──────────────────────────────────────────────────────────────────────┤
├ Gráfico 1: regiões (esq., ~40%)    │ CARD JEV (dir., ~60%, mais alto)                         │
├ Gráfico 2: evolução (esq., ~40%)   │   botão JEV Analysis / resultado                         │
├ Transformar em ação (largura total, aparece só após o JEV) ──────────────────────────────────┤
├ Gráfico de lojas com pior atingimento (largura total) ───────────────────────────────────────┤
```
- Grid de 12 colunas, espaçamento em múltiplos de 8px, cards com cantos de 12px e sombra muito leve.
- Abaixo de 900px, empilhar tudo em 1 coluna (o card JEV logo depois dos big numbers).

### Visual
- Fundo cinza muito claro (`#F6F7F9`), cards brancos, texto principal `#1A1F29`, secundário `#6B7280`, bordas `#E5E7EB`.
- **Uma** cor de destaque para o JEV: verde-água `#0EA5A4`. Status: Agir `#16A34A` · Confirmar `#D97706` · Investigar `#DC2626`.
- Gráficos de contexto em tons de cinza-azulado; só a categoria em foco (a região/loja filtrada ou, sem filtro, a pior) ganha cor.
- Fonte Inter (Google Fonts) com fallback `system-ui`. Números com `font-variant-numeric: tabular-nums`.
- Hierarquia: título 20px · valor do big number 32px semibold · rótulos 12px maiúsculos em cinza.
- Sem gradientes, sem 3D, sem sombras pesadas, sem ícones decorativos em excesso, sem emojis.

### Big numbers
- Faturamento · % da Meta · NPS médio · Ocorrências de pós-venda.
- Cada um mostra: valor do mês + variação contra o mês anterior (▲/▼ com cor: verde se melhorou, vermelho se piorou; atenção que **mais ocorrências é pior**) + uma linha de contexto (meta, referência 100%, NPS da rede quando filtrado).
- Formato brasileiro: `R$ 7,8 mi` (ou `R$ 189 mil` numa loja), `94,5%`, `1.234`. Nunca casas decimais desnecessárias.

### Gráficos (Chart.js 4.4.1 via cdnjs)
- **Gráfico 1, Atingimento da meta por região:** sempre as 5 regiões, barras horizontais da pior para a melhor, linha de referência em 100%, rótulo de valor na ponta da barra.
- **Gráfico 2, Evolução mensal:** faturamento (linha) vs meta (linha tracejada) em todos os meses do banco, no escopo do filtro, com o mês selecionado destacado.
- **Gráfico de lojas:** até 10 lojas com pior atingimento no escopo da região (a loja filtrada sempre aparece), mesmas regras do gráfico 1.
- Regras: título do gráfico em forma de frase que diz o que olhar (ex.: "Nordeste ficou 11,6 p.p. abaixo da meta"); eixo começando em zero em barras; sem legenda quando o rótulo direto resolve; tooltips em formato BR; poucas linhas de grade.

### Card do JEV (estados)
1. **Antes:** título "O que explica <Mês/Ano>?" + texto curto ("Pergunte ao JEV o que explica o resultado da rede em *Outubro*") + botão grande **JEV Analysis**.
2. **Carregando:** botão desabilitado + etapas visíveis: "Montando dossiê… → Consultando o JEV… → Pronto". Nunca tela travada sem feedback.
3. **Resultado:**
   - Causa provável em destaque (texto grande).
   - **Score de certeza** em medidor semicircular 0–100 colorido pela etiqueta + etiqueta Agir / Confirmar / Investigar.
   - Barras horizontais com a probabilidade de cada causa (a principal colorida, as demais em cinza).
   - 3 lojas prioritárias (vindas do Python) com região, gerente e atingimento; clicar filtra o dashboard pela loja.
   - Linha discreta: risco da rede (rótulo + score 0–4) e revisão humana (% de chance de os sinais serem ambíguos).
   - Rodapé pequeno: "Decisão: JEV (TypeSafe) via OpenRouter · <modelo> · gravado em runs/…".
4. **Erro:** mensagem clara do que falhou + botão "Tentar de novo". Nunca inventar resultado.
- Ao trocar o mês, o card **volta ao estado "Antes"** e a seção "Transformar em ação" some (a decisão é sempre de um mês específico).

### Transformar em ação (Haiku)
- Só aparece depois de uma decisão do JEV; título "Com base na decisão do JEV de *Outubro/2026*" + resumo (causa, Score, etiqueta, risco).
- Botões "Mensagem para o gerente" e "Resumo para a diretoria" + campo livre com botão "Gerar" (Ctrl+Enter também gera).
- Resposta em caixa de texto com botão "Copiar" e o rótulo discreto "Texto redigido por Claude Haiku. A decisão é do JEV."

### Boas práticas de análise na tela
- Todo número tem contexto (meta, mês anterior ou média da rede). Número solto não entra.
- Cálculos e textos dos títulos vêm prontos do Python (`/api/dados`); o JavaScript só exibe.
- Mesma métrica, mesmo formato e mesma cor em toda a tela.
- Mostrar no cabeçalho o mês de referência; dados sintéticos sinalizados no rodapé.

### Qualidade
- Um único `dashboard/index.html` (CSS e JS embutidos), sem frameworks pesados.
- Contraste AA, botões com estado de foco e hover, áreas clicáveis ≥ 40px.
- Antes de dizer que terminou: abrir no navegador, trocar de mês, filtrar por região e loja (pelos selects e pelos cliques), rodar o JEV Analysis e o Haiku, e conferir que nada quebra.

## Registro em runs/

- JEV: `runs/jev_<AAAA-MM>_<AAAAMMDD_HHMMSS>.json` com `mes`, `enviado` (body completo, incluindo o dossiê), `recebido` e `prioridades`.
- Haiku: `runs/haiku_<AAAA-MM>_<tipo>_<AAAAMMDD_HHMMSS_micro>.json` com `mes`, `tipo`, `decisao_jev` (arquivo do JEV usado), `enviado` e `recebido`.

## Resultados de referência (para conferir se está tudo certo)

Com a base distribuída e o dossiê acima, o JEV tem dado:

| Mês | Causa | Score | Etiqueta | Lojas prioritárias |
|---|---|---|---|---|
| Jul/2026 | Estoque | 100 | Agir | LOJ003, LOJ007, LOJ004 (Sul) |
| Ago/2026 | Equipe | 99–100 | Agir | LOJ013, LOJ016, LOJ015 (Sudeste) |
| Out/2026 | Atendimento | 76–77 | Agir | LOJ032, LOJ031, LOJ033 (Nordeste) |

O JEV pode variar um pouco entre execuções com o mesmo dossiê (ex.: risco 3.09 vs 3.11). Meses de out/2025 a jun/2026 são
estáveis (rede perto da meta) e tendem a "Sem problema relevante" ou causas divididas.

## Regras

- Cálculos sempre em Python. O JEV só julga.
- O Haiku recebe a decisão do JEV como fato. No prompt dele: "não altere a causa nem o score, não invente números".
- Toda chamada ao JEV e ao Haiku é gravada em `runs/` (o que foi enviado e o que voltou).
- Nunca inventar números. Se uma chamada falhar, mostrar o erro.
- Ao mostrar uma decisão do JEV no chat, copie os valores exatos, sem arredondar nem reescrever.
- Nunca exibir as chaves do `.env` no chat, no terminal ou no navegador.
