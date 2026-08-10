No modo local, a biblioteca passou a avisar quando um valor provavelmente
será recusado pelo servidor — comprimento acima do limite, número fora
da faixa ou tipo desconhecido. O aviso não impede a gravação: quem
valida de verdade continua sendo o servidor, na sincronização. Serve
para o erro aparecer na hora, e não no fim de uma sessão inteira de
trabalho offline.

A nova função `refresh_type_catalog()` busca no servidor a lista de tipos
aceitos e os limites padrão, guardando-a para uso offline. Sem ela, vale
uma cópia embarcada, que pode ficar desatualizada.
