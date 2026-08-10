A biblioteca ganhou uma verificação que confronta o esquema publicado
pelo servidor com as rotas, os códigos de sucesso e os campos que ela de
fato consome — de modo que uma mudança incompatível do lado do servidor
apareça como falha de teste, e não como erro em produção. A verificação
se pula sozinha quando não há esquema disponível.
