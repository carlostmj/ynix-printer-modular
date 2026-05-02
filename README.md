# Ynix Printer Modular

Aplicativo Tkinter para ajustar, pré-visualizar e imprimir com fluxo modular para térmicas e CUPS.

## Créditos

- Autor: CarlosTMJ
- GitHub: https://github.com/carlostmj
- Versão: 1.2.0
- Atualizado em: 2026-05-01 19:49:53 -03
- Ícone: `assets/icone.png`

## Rodar

```bash
.venv/bin/python run.py
```

Com arquivo inicial:

```bash
.venv/bin/python run.py caminho/etiquetas.pdf
```

## Observações

- O perfil `10x15` usa `100 x 150 mm` em `203 DPI`, que é o padrão mais comum em impressoras térmicas de etiqueta.
- A barra superior concentra as escolhas globais: perfil, impressora, tipo de impressão e qualidade.
- A aba `Perfis` abre uma janela para criar medidas personalizadas salvas em `~/.config/ynix-printer-modular/profiles.json`.
- A aba `Ajustes` fica dedicada ao posicionamento, escala, rotação, corte e opções do conteúdo.
- O menu `Camadas` e os botões do topo permitem adicionar texto/imagem por cima da página atual e mover a camada no preview.
- Texto e numeração podem ser editados com duplo clique na camada ou pelo botão `Editar camada`.
- A camada `Numeração` gera comandas sequenciais, por exemplo de `1` a `1500`, e a aba `Impressão` envia a sequência inteira.
- Se sua impressora for realmente 300 DPI, selecione ou ajuste o campo DPI para `300`.
- O preview atualiza sozinho quando tamanho, DPI, margem, offset, ajuste, rotação, inversão ou perfil mudam.
- Ajustes de conteúdo como escala, offset, ajuste e rotação ficam salvos por página.
- O conteúdo pode ser cortado por bordas usando `Corte esq./dir./topo/baixo`.
- A impressão é enviada em modo raw com comando TSPL (`lp -o raw`).
- Também existe modo `Impressora normal`, que envia PNG ao CUPS sem TSPL/raw.
- Arrastar e soltar arquivos usa `tkinterdnd2`, instalado na `.venv` do projeto.
- A lista de impressoras vem do CUPS (`lpstat`).
- A aba `Fila` permite acompanhar trabalhos, cancelar pendentes, reimprimir e ver erros.
- O menu `Ferramentas > Driver Tomate / CUPS...` diagnostica a Tomate no CUPS e pode recriar a fila em modo raw com `lpadmin`.
- A instalação segue o contrato do modelo selecionado e permite escolher manualmente fila CUPS e porta/URI quando a detecção automática não bastar.
- Impressoras seguem contratos em `thermal_label_app/printers/contracts/` e modelos em `thermal_label_app/printers/models/`. Exemplo: `printers/models/mdk_007.py`.

## Atalhos

- `Ctrl+O`: abrir arquivos
- `Ctrl+P`: imprimir página atual
- `Ctrl+Shift+P`: imprimir todas as páginas
- `Ctrl+Z`: desfazer ajuste
- `Ctrl+Y` / `Ctrl+Shift+Z`: refazer ajuste
- `Ctrl+←` / `Ctrl+→`: navegar páginas
- `Ctrl+R`: alternar redimensionar/rotacionar
- `Ctrl+0`: redefinir escala e rotação
- `Ctrl+Shift+0`: limpar corte
- `Esc`: cancelar ação no preview
