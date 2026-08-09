A garantia de que a biblioteca não pode entrar em deadlock deixou de
depender de revisão e passou a ser verificada automaticamente a cada
build, em duas frentes: a execução real dos métodos públicos, inclusive
sob concorrência, e uma varredura do código que reprova qualquer
gravação de cache feita por fora do caminho seguro.
