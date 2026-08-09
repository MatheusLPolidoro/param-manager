Limpe também o cache em memória do parâmetro ao atualizá-lo por `upsert_params`: o valor anterior continuava sendo devolvido por `get_param` até o fim da janela de cache.
