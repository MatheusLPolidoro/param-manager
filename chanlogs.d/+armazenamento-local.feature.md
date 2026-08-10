Base para o modo de desenvolvimento local: a biblioteca passou a manter
um arquivo próprio, ao lado do cache, para guardar parâmetros criados sem
o servidor. Ele é separado de propósito — a limpeza automática do cache,
que acontece quando a API responde algo ilegível, não alcança o que você
ainda não sincronizou. Ainda sem efeito visível: nenhuma função pública
usa esse arquivo nesta versão.
