Corrigida uma falha rara em que `get_param` podia lançar `KeyError` na
aplicação que a consome, em vez de devolver o valor ou `None`. Acontecia
quando outra thread apagava ou regravava o mesmo parâmetro no exato
instante da leitura — algo que `delete_param` e `upsert_params` fazem
internamente. A leitura do cache passou a ser feita de uma vez só, sem
essa brecha.
