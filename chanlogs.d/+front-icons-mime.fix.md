Corrija o front desktop instalado do pacote 0.5.0, que abria sem ícones, sem
rótulos e sem opções nos seletores: um comentário do código carregava por
coincidência a assinatura de arquivo `tar` num byte que o protocolo interno
do aplicativo usa para adivinhar o tipo de conteúdo, fazendo o navegador
recusar aquele módulo e, em cascata, quase toda a tela.
