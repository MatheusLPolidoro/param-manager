A exceção de parâmetro não encontrado passou a se chamar
`ParamNotFoundError`, acompanhando o restante da biblioteca, que agora
usa nomes em inglês. **Nada precisa ser alterado em código já escrito**:
`ParamNaoEncontradoError` continua exportado e é a mesma classe, então
um `except` existente segue capturando normalmente.
