Execute a inicialização da instância sob o lock do multiton, evitando que duas threads inicializem a mesma instância e substituam o lock interno, os caches e o arquivo do TinyDB.
