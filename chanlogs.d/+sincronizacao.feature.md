Os parâmetros criados no modo local agora podem ser enviados ao servidor.
A sincronização acontece em duas etapas: `sync_plan()` mostra o que seria
feito — o que será criado, o que será atualizado e o que está em conflito
— sem tocar em nada; `sync_apply()` executa apenas o que foi apresentado
no plano.

Conflito nunca é resolvido sozinho. Quando o mesmo parâmetro mudou dos
dois lados, ele fica de fora e é apresentado com os dois valores, para
que a decisão seja de quem está operando.

Um parâmetro recusado pelo servidor permanece guardado localmente, com a
mensagem exata que o servidor devolveu, e os demais continuam sendo
enviados normalmente. Falta de permissão é tratada de forma distinta de
valor inválido: o parâmetro segue pendente e volta a ser tentado quando a
credencial for corrigida.
