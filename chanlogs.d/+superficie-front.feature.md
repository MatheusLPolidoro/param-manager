Novo módulo `param_manager.api`, pensado para aplicações com interface
gráfica. Ele expõe as mesmas operações em funções que sempre devolvem um
dicionário simples com `ok` indicando sucesso ou falha, em vez de lançar
exceções — o que evita que um erro atravesse a ponte entre a interface e
o Python como um rastreamento de pilha.

Os dados devolvidos são cópias independentes, então alterá-los na
interface não afeta o estado interno da biblioteca.

As funções são bloqueantes: chame-as fora do laço de eventos da
interface, sob pena de a janela travar durante uma requisição ou a
leitura de um parâmetro protegido.
