# Ynix Printer Modular

![Release](https://img.shields.io/badge/release-v1.0.0.0-blue)

Editor gráfico leve para montar, ajustar, salvar e imprimir etiquetas térmicas. O fluxo principal é: abrir PDF/imagem, editar no canvas, organizar camadas, salvar projeto `.ynix` e enviar para CUPS em modo TSPL/raw ou PNG normal.

## Recursos

- Editor Tkinter com preview interativo, movimentação, redimensionamento e rotação de camadas.
- Toolbar lateral estilo Corel com seleção, mover, texto e inserir imagem.
- Camadas por página com z-index, duplicação, excluir, trazer para frente, enviar para trás e mover acima/abaixo.
- Texto avançado com fonte do sistema, tamanho, negrito, itálico, cor preparada para render P&B e alinhamento.
- Menu de contexto com editar, duplicar, ordenar e deletar.
- Projetos `.ynix` em JSON com canvas, fontes, textos, imagens, camadas, posições, rotação, ajustes de página e configuração de impressão.
- Impressão modular via CUPS, TSPL e fila com retry automático e logs em `~/.config/ynix-printer-modular/logs/app.log`.
- Persistência de preferências em `~/.config/ynix-printer-modular/settings.json`.

## Metadados

- Autor: CarlosTMJ
- GitHub: https://github.com/carlostmj
- Versão: 1.0.0.0
- Ícone: `assets/icone.png`

## Rodar

```bash
.venv/bin/python run.py
```

Com arquivo inicial:

```bash
.venv/bin/python run.py caminho/etiquetas.pdf
```

## Como usar o editor

- `Abrir arquivos` carrega PDF ou imagem.
- A toolbar esquerda troca a ferramenta ativa: seleção, mover, texto e imagem.
- Com a ferramenta texto, clique no canvas para criar uma camada editável.
- Clique em uma camada para selecionar e arraste para mover.
- Use o canto inferior direito da seleção para redimensionar.
- Use o handle circular acima da seleção para rotacionar.
- O painel `Camadas` controla ordem, duplicação, exclusão e propriedades numéricas.
- Ative `Snap à grade` para alinhar posições ao grid.

## Projetos

- `Arquivo > Salvar projeto` grava `.ynix`.
- `Arquivo > Abrir projeto` restaura fontes, textos, imagens, posições, camadas, ajustes e impressão.
- O formato é JSON estruturado para facilitar auditoria e integração futura.

## Impressão

- `Térmica TSPL` gera comando raw com `SIZE`, `GAP`, `DENSITY`, `BITMAP` e `PRINT`.
- `Impressora normal` envia PNG ao CUPS.
- A aba `Fila` mostra status, permite cancelar pendentes, reimprimir e abrir erro detalhado.
- Qualidade controla velocidade e densidade TSPL.

## Atalhos

- `Ctrl+O`: abrir arquivos
- `Ctrl+Shift+O`: abrir projeto
- `Ctrl+S`: salvar projeto
- `Ctrl+Shift+S`: salvar projeto como
- `Ctrl+P`: imprimir página atual
- `Ctrl+Shift+P`: imprimir todas as páginas
- `Ctrl+Z`: desfazer ajuste
- `Ctrl+Y` / `Ctrl+Shift+Z`: refazer ajuste
- `Ctrl+←` / `Ctrl+→`: navegar páginas
- `Delete`: remover camada selecionada
- `Esc`: cancelar ação no preview

## Troubleshooting

- Se `lp` não existir, instale/configure CUPS.
- Se impressora TSPL imprimir caracteres, confirme que a fila está em modo raw.
- Se PDF não abrir, instale `pdftoppm`/Poppler.
- Se arrastar arquivos não funcionar, instale `tkinterdnd2`.
- Consulte logs em `~/.config/ynix-printer-modular/logs/app.log`.

## Arquitetura

- `domain/`: modelos de canvas, projeto e camadas.
- `core/`: documento, estado do canvas, transformações, overlays, print service e fila.
- `ui/`: componentes de janela, canvas, toolbar, painel direito e menu de contexto.
- `infrastructure/`: adapters CUPS e TSPL.
- `storage/`: serialização `.ynix`.
- `config/`: settings persistentes.
- `utils/`: logger.
